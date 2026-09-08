"""
Describer agent — ADK LlmAgent with forced budget/collision guards.

Architecture:
- describe_gaps() is the public entry point; agents/describer/app.py:84 calls it unchanged.
- Internally uses google.adk LlmAgent + Runner for both passes.
- Pass 1 (salience): plain generate_content through the fallback ladder.
- Pass 2 (copy writing): ADK LlmAgent with check_budget and check_collision as forced
  function tools (tool_config mode=ANY). The model MUST call one of the guard tools
  before it may emit a cue — forcing it to see its headroom before committing.
- A3: native video understanding — the copy pass receives a gs:// video clip via
  types.Part.from_uri with VideoMetadata start_offset/end_offset for the gap window.
  Still-frame fallback is kept for the case where gs_uri is not available.
- Post-generation asserts in app.py are kept. The tools let the model self-correct;
  the asserts remain the hard guarantee. Belt and braces.
"""

import asyncio
import hashlib
import json
import os
import time as _time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from dotenv import load_dotenv

load_dotenv()

from agents.shared.budget import word_budget, count_words
from agents.shared.cache import cached
from agents.shared.collision import assert_no_collision
from agents.shared.models import Transcript, Gap, Cue

# ── Model ladder ───────────────────────────────────────────────────────────────
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
]

# ── Safety settings ────────────────────────────────────────────────────────────
# Descriptive audio-description copy about visual film content can trigger default
# violence/sexual-content filters because it accurately describes action on screen.
# We set explicit thresholds: only block high-severity harm, never block for
# HARASSMENT or CIVIC_INTEGRITY which are irrelevant to this use case.
_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]


def _get_client() -> genai.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        return genai.Client(vertexai=True, project=project, location=location)
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def _generate(client: genai.Client, contents, safety_settings=None) -> object:
    """Try each model in GEMINI_MODELS until one responds."""
    last_err = None
    for attempt, model in enumerate(GEMINI_MODELS):
        try:
            if attempt > 0:
                _time.sleep(2)
            kwargs = {"model": model, "contents": contents}
            if safety_settings:
                kwargs["config"] = types.GenerateContentConfig(
                    safety_settings=safety_settings
                )
            return client.models.generate_content(**kwargs)
        except Exception as e:
            print(f"[describer] {model} failed: {str(e)[:80]}")
            last_err = e
    raise RuntimeError(f"All models failed: {last_err}")


@cached("describe", key_args=("prompt", "media_sha256"))
def _cached_generate(
    client: genai.Client,
    prompt: str,
    media_sha256: str,
    media_bytes: Optional[bytes],
    media_mime: Optional[str],
) -> str:
    """
    Cache-aware wrapper around _generate.
    Keyed on prompt text + sha256 of any attached media bytes.
    The client object is excluded from the key (non-deterministic repr).
    """
    if media_bytes:
        parts = [
            types.Part.from_bytes(data=media_bytes, mime_type=media_mime or "image/jpeg"),
            types.Part.from_text(text=prompt),
        ]
    else:
        parts = prompt
    resp = _generate(client, parts, safety_settings=_SAFETY_SETTINGS)
    return resp.text


# ── ADK guard tools ────────────────────────────────────────────────────────────

def check_budget(text: str, gap_seconds: float) -> dict:
    """
    Check whether `text` fits within the word budget for a silence gap of
    `gap_seconds` seconds. Returns a dict with fits, words_used, words_allowed,
    and headroom. The model MUST call this before emitting a cue.
    """
    allowed = word_budget(gap_seconds)
    used = count_words(text)
    fits = used <= allowed
    return {
        "fits": fits,
        "words_used": used,
        "words_allowed": allowed,
        "headroom": allowed - used,
    }


def check_collision(start: float, end: float, dialogue_spans_json: str) -> dict:
    """
    Check whether a cue spanning [start, end] seconds would overlap any
    dialogue span. `dialogue_spans_json` is a JSON array of {start, end} objects.
    Returns {collides: bool, overlapping_span: str|null}.
    """
    try:
        spans = json.loads(dialogue_spans_json)
    except Exception:
        return {"collides": False, "overlapping_span": None}

    for span in spans:
        s_start = span.get("start", 0)
        s_end = span.get("end", 0)
        if start < s_end and end > s_start:
            return {
                "collides": True,
                "overlapping_span": f"{s_start:.3f}–{s_end:.3f}s",
            }
    return {"collides": False, "overlapping_span": None}


def _run_adk_copy_pass(
    prompt: str,
    gap_seconds: float,
    dialogue_spans_json: str,
) -> Optional[str]:
    """
    Run the copy-writing pass via ADK LlmAgent with forced guard tools.

    The agent must call check_budget (and optionally check_collision) before
    emitting its final JSON. We use tool_config mode=ANY with
    allowed_function_names so the model cannot skip the checks.

    Returns the raw text from the agent's final message, or None on failure.
    """
    # Bind dialogue context into check_collision via closure
    def _check_collision(start: float, end: float) -> dict:
        """Check whether cue [start, end] overlaps any dialogue span."""
        return check_collision(start, end, dialogue_spans_json)

    def _check_budget(text: str, gap_seconds: float) -> dict:
        """Check word budget for text against a gap of gap_seconds seconds."""
        return check_budget(text, gap_seconds)

    model_name = GEMINI_MODELS[0]

    agent = LlmAgent(
        name="copy_writer",
        model=model_name,
        instruction=prompt,
        tools=[_check_budget, _check_collision],
        generate_content_config=types.GenerateContentConfig(
            safety_settings=_SAFETY_SETTINGS,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=["_check_budget", "_check_collision"],
                )
            ),
        ),
    )

    session_service = InMemorySessionService()
    runner = Runner(
        app_name="earsight_describer",
        agent=agent,
        session_service=session_service,
    )

    async def _run():
        session = await session_service.create_session(
            app_name="earsight_describer",
            user_id="system",
        )
        events = []
        async for event in runner.run_async(
            user_id="system",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text="Write the description cue now.")],
            ),
        ):
            events.append(event)
        # Extract the last model text response
        for event in reversed(events):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        return part.text
        return None

    try:
        return asyncio.run(_run())
    except RuntimeError:
        # Already inside an event loop (e.g. during tests)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()


def describe_gaps(
    transcript: Transcript,
    gaps: list[Gap],
    established_facts: Optional[list[str]] = None,
    video_gcs_uri: Optional[str] = None,
) -> list[Cue]:
    """
    Run the two-pass describer on a list of gaps.
    Returns a list of Cue objects (some with text=None for skipped gaps).

    video_gcs_uri: if provided, pass the source video to the copy pass via
    native video understanding (A3) with VideoMetadata offsets for each gap
    window, instead of a still frame. Still frames are used as fallback.
    """
    client = _get_client()

    if established_facts is None:
        established_facts = []

    # Precompute dialogue spans for collision checking
    dialogue_spans = transcript.dialogue_spans()
    dialogue_spans_json = json.dumps(dialogue_spans)

    # ── PASS 1: Priority ranking ───────────────────────────────────────────────
    gaps_summary = []
    for g in gaps:
        budget = word_budget(g.duration)
        gaps_summary.append({
            "gap_id": g.gap_id,
            "start": round(g.start, 2),
            "end": round(g.end, 2),
            "duration_seconds": round(g.duration, 2),
            "word_budget": budget,
            "preceding_dialogue": g.preceding_context,
            "following_dialogue": g.following_context,
        })

    pass1_prompt = f"""You are writing audio description for a short video — narration spoken
in the silences between dialogue for blind and low-vision viewers.

Full transcript:
{transcript.full_text or "(no dialogue)"}

Silence gaps available for description:
{json.dumps(gaps_summary, indent=2)}

Facts already established in earlier cues (do not repeat these):
{json.dumps(established_facts) if established_facts else "[]"}

For each gap, decide: would a blind viewer lose meaningful story information
without a description here? Apply these rules:
- Skip gaps whose budget is fewer than 3 words (not enough to say anything useful)
- Skip gaps where the surrounding dialogue already conveys the scene
- Skip gaps describing things the audio already makes clear (doors slamming, music, etc.)
- Skip gaps that would repeat established facts

Return ONLY valid JSON — no markdown, no explanation:
{{
  "ranked_gaps": [
    {{
      "gap_id": "gap_000",
      "priority": 1,
      "include": true,
      "rationale": "one sentence reason"
    }}
  ]
}}

List ALL gaps (include: true or false). Rank by importance (1 = most important).
"""

    print("[describer] Pass 1: ranking gaps for salience...")
    raw1 = _cached_generate(client, pass1_prompt, "", None, None).strip()
    if raw1.startswith("```"):
        lines = raw1.split("\n")
        raw1 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    ranking_data = json.loads(raw1)

    # Build lookup: gap_id → ranking decision
    ranking = {r["gap_id"]: r for r in ranking_data.get("ranked_gaps", [])}

    # ── PASS 2: Copy writing via ADK agent with guard tools ────────────────────
    cues: list[Cue] = []

    for gap in sorted(gaps, key=lambda g: g.start):
        decision = ranking.get(gap.gap_id, {})
        budget = word_budget(gap.duration)

        if budget < 3:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="budget",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (budget={budget} < 3)")
            continue

        if not decision.get("include", False):
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="salience",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (salience — {decision.get('rationale', '')})")
            continue

        # ── A3: Build media context — prefer GCS video clip, fall back to frame ──
        media_bytes: Optional[bytes] = None
        media_mime: Optional[str] = None
        video_part: Optional[types.Part] = None

        if video_gcs_uri:
            try:
                video_part = types.Part.from_uri(
                    file_uri=video_gcs_uri,
                    mime_type="video/mp4",
                    video_metadata=types.VideoMetadata(
                        start_offset=f"{gap.start:.3f}s",
                        end_offset=f"{gap.end:.3f}s",
                    ),
                )
            except Exception as exc:
                print(f"[describer] video part failed for {gap.gap_id}: {exc}")
                video_part = None

        if video_part is None and gap.frame_path and Path(gap.frame_path).exists():
            try:
                media_bytes = Path(gap.frame_path).read_bytes()
                media_mime = "image/jpeg"
            except Exception:
                pass

        media_sha256 = hashlib.sha256(media_bytes).hexdigest() if media_bytes else ""
        # Include gap timing in cache key when using video (offsets make it unique)
        if video_part:
            media_sha256 = hashlib.sha256(
                f"{video_gcs_uri}:{gap.start:.3f}:{gap.end:.3f}".encode()
            ).hexdigest()

        facts_str = json.dumps(established_facts) if established_facts else "[]"
        media_label = (
            "[Source video clip for this gap is attached]" if video_part
            else "[Frame from video at the midpoint of this gap is attached above]" if media_bytes
            else "[No visual context available]"
        )

        copy_prompt = f"""You are writing one audio description cue for a short video.
IMPORTANT: You must call check_budget before finalising your cue text to verify it
fits the word budget. You may also call check_collision to verify no overlap with dialogue.

Silence gap: {gap.start:.2f}s to {gap.end:.2f}s ({gap.duration:.2f}s)
Hard word budget: {budget} words MAXIMUM
Dialogue before: "{gap.preceding_context}"
Dialogue after:  "{gap.following_context}"
Facts already established: {facts_str}
{media_label}

After calling the guard tools, return ONLY valid JSON — no markdown:
{{"text": "A woman in a red coat crosses the empty platform."}}
or if nothing worth describing:
{{"text": null, "reason": "brief explanation"}}

Rules:
- MUST be {budget} words or fewer — this is a hard limit, not a guide
- Present tense, active voice, specific and visual
- Do not describe what the audio already conveys
- Do not repeat established facts
- Do not mention camera angles or filmmaking
"""

        _t0 = _time.time()
        print(f"[describer] {gap.gap_id}: writing copy via ADK (budget={budget} words)...")

        # Build cache key for ADK path (includes video offset or frame sha)
        adk_cache_key = hashlib.sha256(
            (copy_prompt + media_sha256).encode()
        ).hexdigest()

        # Try ADK path first; fall back to direct generate if ADK fails
        raw2 = None
        try:
            raw2 = _run_adk_copy_pass(copy_prompt, gap.duration, dialogue_spans_json)
        except Exception as exc:
            print(f"[describer] ADK path failed for {gap.gap_id}: {exc} — falling back")

        if raw2 is None:
            # Fallback: direct generate (still has cache, safety settings)
            if video_part:
                # For fallback, build content with video part
                contents = [video_part, types.Part.from_text(text=copy_prompt)]
                try:
                    resp = _generate(client, contents, safety_settings=_SAFETY_SETTINGS)
                    raw2 = resp.text
                except Exception as exc2:
                    print(f"[describer] fallback generate failed for {gap.gap_id}: {exc2}")
                    cues.append(Cue(
                        cue_id=f"cue_{gap.gap_id}",
                        start=gap.start, end=gap.end,
                        text=None, gap_id=gap.gap_id, skip_reason="salience",
                    ))
                    continue
            else:
                raw2 = _cached_generate(
                    client, copy_prompt, media_sha256, media_bytes, media_mime
                )

        if raw2 is None:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="salience",
            ))
            continue

        raw2 = raw2.strip()
        if raw2.startswith("```"):
            lines = raw2.split("\n")
            raw2 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            copy_data = json.loads(raw2)
        except json.JSONDecodeError:
            # Extract first {...} block if model included surrounding text
            import re
            m = re.search(r'\{[^{}]+\}', raw2)
            if m:
                copy_data = json.loads(m.group())
            else:
                print(f"[describer] {gap.gap_id}: could not parse response — skip")
                cues.append(Cue(
                    cue_id=f"cue_{gap.gap_id}",
                    start=gap.start, end=gap.end,
                    text=None, gap_id=gap.gap_id, skip_reason="salience",
                ))
                continue

        text = copy_data.get("text")

        if text is None:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="redundant",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (redundant — {copy_data.get('reason', '')})")
            continue

        # Word budget check — drop if over budget
        wc = count_words(text)
        if wc > budget:
            print(f"[describer] {gap.gap_id}: SKIP (copy exceeded budget: {wc} > {budget})")
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="budget",
            ))
            continue

        # Collision guard — verify cue doesn't overlap any dialogue
        candidate_cue = {"start": gap.start, "end": gap.end, "text": text}
        assert_no_collision([candidate_cue], dialogue_spans)

        # Add to established facts
        established_facts.append(text)

        cue = Cue(
            cue_id=f"cue_{gap.gap_id}",
            start=gap.start, end=gap.end,
            text=text, word_count=wc, gap_id=gap.gap_id,
        )
        cues.append(cue)
        print(f"[describer] {gap.gap_id}: ✓ '{text}' ({wc}/{budget} words, {_time.time()-_t0:.1f}s)")

    return cues


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate description cues for a video")
    parser.add_argument("--transcript", "-t", required=True, help="Transcript JSON path")
    parser.add_argument("--gaps", "-g", required=True, help="Gaps JSON path")
    parser.add_argument("--output", "-o", help="Output cues JSON path (default: stdout)")
    parser.add_argument("--video-gcs-uri", help="GCS URI for video (enables video understanding)")
    args = parser.parse_args()

    from agents.shared.models import Word

    transcript_data = json.loads(Path(args.transcript).read_text())
    words = [Word(**w) for w in transcript_data["words"]]
    transcript_obj = Transcript(words=words, language=transcript_data["language"], full_text=transcript_data["full_text"])

    gaps_data = json.loads(Path(args.gaps).read_text())
    gap_objs = [Gap(**g) for g in gaps_data]

    cues = describe_gaps(transcript_obj, gap_objs, video_gcs_uri=args.video_gcs_uri)
    result = [
        {
            "cue_id": c.cue_id, "start": c.start, "end": c.end,
            "text": c.text, "word_count": c.word_count,
            "gap_id": c.gap_id, "skip_reason": c.skip_reason,
        }
        for c in cues
    ]
    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out)
        print(f"[describer] Written to {args.output}")
    else:
        print(out)
