"""
Describer agent — ADK LlmAgent with forced budget/collision guards.

Architecture:
- describe_gaps() is the public entry point; agents/describer/app.py calls it.
- Single ADK LlmAgent invocation: the whole video is attached once, all gaps are
  described in one prompt, the model calls check_budget / check_collision per candidate
  cue inside that one invocation (tool_config mode=ANY is kept — forced function calling
  is deliberate).
- Still-frame fallback (per-gap _cached_generate) when video_gcs_uri is None.
- Post-generation asserts in app.py remain the hard guarantee. Belt and braces.
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


def _run_adk_all_gaps(
    prompt: str,
    dialogue_spans_json: str,
    video_part: Optional[types.Part],
) -> Optional[str]:
    """
    Single ADK LlmAgent invocation that describes all gaps at once.

    The video (if provided) is attached once. The model calls check_budget and
    check_collision per candidate cue inside this one invocation (tool_config
    mode=ANY — forced function calling is kept intentionally).

    Returns the raw text from the agent's final message, or None on failure.
    """
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
        # Attach video once at the top of the user message if available
        user_parts = []
        if video_part is not None:
            user_parts.append(video_part)
        user_parts.append(types.Part.from_text(text="Write description cues for all gaps now."))

        events = []
        async for event in runner.run_async(
            user_id="system",
            session_id=session.id,
            new_message=types.Content(role="user", parts=user_parts),
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
    Describe all gaps in a single ADK agent invocation.
    Returns a list of Cue objects (some with text=None for skipped gaps).

    video_gcs_uri: if provided the whole video is attached once via
    types.Part.from_uri (no VideoMetadata offsets — the model sees the entire
    clip and is instructed to focus on each gap's time window). Still-frame
    fallback (one _cached_generate per gap) is used when video_gcs_uri is None.
    """
    import re

    client = _get_client()

    if established_facts is None:
        established_facts = []

    dialogue_spans = transcript.dialogue_spans()
    dialogue_spans_json = json.dumps(dialogue_spans)
    facts_str = json.dumps(established_facts) if established_facts else "[]"

    # Build the gap table for the prompt
    gaps_sorted = sorted(gaps, key=lambda g: g.start)
    gaps_table = []
    for g in gaps_sorted:
        budget = word_budget(g.duration)
        gaps_table.append({
            "gap_id": g.gap_id,
            "start": round(g.start, 2),
            "end": round(g.end, 2),
            "duration_seconds": round(g.duration, 2),
            "word_budget": budget,
            "preceding_dialogue": g.preceding_context,
            "following_dialogue": g.following_context,
        })

    # ── VIDEO PATH (single ADK call) ───────────────────────────────────────────
    if video_gcs_uri:
        try:
            video_part: Optional[types.Part] = types.Part.from_uri(
                file_uri=video_gcs_uri,
                mime_type="video/mp4",
            )
        except Exception as exc:
            print(f"[describer] video part failed: {exc} — falling back to still frames")
            video_part = None
    else:
        video_part = None

    if video_part is not None:
        all_gaps_prompt = f"""You are writing audio descriptions for a short video —
narration spoken in the silences between dialogue for blind and low-vision viewers.
The video is attached. Do NOT add VideoMetadata offsets; you see the full clip.

Full transcript:
{transcript.full_text or "(no dialogue)"}

Facts already established (do not repeat):
{facts_str}

Silence gaps to describe:
{json.dumps(gaps_table, indent=2)}

For EACH gap:
1. Call check_budget(text, gap_seconds) before finalising any cue text.
2. Optionally call check_collision(start, end) to verify no overlap with dialogue.
3. Focus only on what is visible in that gap's time window [start, end].
4. Skip a gap (text=null) if: budget < 3 words, dialogue already conveys the scene,
   the audio makes it clear, or it would repeat an established fact.

After all guard-tool calls, return ONLY a JSON array — no markdown, no explanation:
[
  {{"gap_id": "gap_000", "text": "A woman in a red coat crosses the platform.", "skip_reason": null}},
  {{"gap_id": "gap_001", "text": null, "skip_reason": "dialogue conveys scene"}}
]

Rules per cue:
- text MUST fit within word_budget — hard limit, not a guide
- Present tense, active voice, specific and visual
- Never mention camera angles or filmmaking
- Never repeat an established fact
"""

        print(f"[describer] single ADK call — {len(gaps_sorted)} gaps, video attached once")
        _t0 = _time.time()
        raw = None
        try:
            raw = _run_adk_all_gaps(all_gaps_prompt, dialogue_spans_json, video_part)
        except Exception as exc:
            print(f"[describer] ADK call failed: {exc} — falling back to still frames")
            video_part = None  # trigger still-frame fallback below

        if raw is not None:
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            try:
                results = json.loads(raw)
            except json.JSONDecodeError:
                m = re.search(r'\[.*\]', raw, re.DOTALL)
                if m:
                    try:
                        results = json.loads(m.group())
                    except json.JSONDecodeError:
                        results = None
                else:
                    results = None

            if results is not None:
                result_map = {r["gap_id"]: r for r in results}
                cues: list[Cue] = []
                for gap in gaps_sorted:
                    budget = word_budget(gap.duration)
                    r = result_map.get(gap.gap_id, {})
                    text = r.get("text")
                    skip_reason = r.get("skip_reason")

                    if text is None:
                        reason = skip_reason or "salience"
                        cues.append(Cue(
                            cue_id=f"cue_{gap.gap_id}",
                            start=gap.start, end=gap.end,
                            text=None, gap_id=gap.gap_id, skip_reason=reason,
                        ))
                        print(f"[describer] {gap.gap_id}: SKIP ({reason})")
                        continue

                    # Hard budget check in Python
                    wc = count_words(text)
                    if wc > budget:
                        print(f"[describer] {gap.gap_id}: SKIP (copy exceeded budget: {wc} > {budget})")
                        cues.append(Cue(
                            cue_id=f"cue_{gap.gap_id}",
                            start=gap.start, end=gap.end,
                            text=None, gap_id=gap.gap_id, skip_reason="budget",
                        ))
                        continue

                    # Collision guard
                    candidate_cue = {"start": gap.start, "end": gap.end, "text": text}
                    assert_no_collision([candidate_cue], dialogue_spans)

                    established_facts.append(text)
                    cue = Cue(
                        cue_id=f"cue_{gap.gap_id}",
                        start=gap.start, end=gap.end,
                        text=text, word_count=wc, gap_id=gap.gap_id,
                    )
                    cues.append(cue)
                    print(f"[describer] {gap.gap_id}: ✓ '{text}' ({wc}/{budget} words)")

                print(f"[describer] single-call pass done in {_time.time()-_t0:.1f}s")
                return cues

            # JSON parse failed — fall through to still-frame path
            print("[describer] could not parse single-call response — falling back to still frames")
            video_part = None

    # ── STILL-FRAME FALLBACK (video_gcs_uri is None or video_part failed) ──────
    print(f"[describer] still-frame path — {len(gaps_sorted)} gaps")
    cues = []
    for gap in gaps_sorted:
        budget = word_budget(gap.duration)

        if budget < 3:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="budget",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (budget={budget} < 3)")
            continue

        media_bytes: Optional[bytes] = None
        media_mime: Optional[str] = None
        if gap.frame_path and Path(gap.frame_path).exists():
            try:
                media_bytes = Path(gap.frame_path).read_bytes()
                media_mime = "image/jpeg"
            except Exception:
                pass

        media_sha256 = hashlib.sha256(media_bytes).hexdigest() if media_bytes else ""
        facts_str_cur = json.dumps(established_facts) if established_facts else "[]"
        media_label = (
            "[Frame from video at the midpoint of this gap is attached above]" if media_bytes
            else "[No visual context available]"
        )

        copy_prompt = f"""You are writing one audio description cue for a short video.
IMPORTANT: You are a text-only agent here (no tool calls). Return ONLY valid JSON.

Silence gap: {gap.start:.2f}s to {gap.end:.2f}s ({gap.duration:.2f}s)
Hard word budget: {budget} words MAXIMUM
Dialogue before: "{gap.preceding_context}"
Dialogue after:  "{gap.following_context}"
Facts already established: {facts_str_cur}
{media_label}

Return ONLY valid JSON — no markdown:
{{"text": "A woman in a red coat crosses the empty platform."}}
or if nothing worth describing:
{{"text": null, "reason": "brief explanation"}}

Rules:
- MUST be {budget} words or fewer — hard limit
- Present tense, active voice, specific and visual
- Do not describe what the audio already conveys
- Do not repeat established facts
- Do not mention camera angles or filmmaking
"""

        _t0 = _time.time()
        print(f"[describer] {gap.gap_id}: writing copy via fallback (budget={budget} words)...")

        raw2 = _cached_generate(client, copy_prompt, media_sha256, media_bytes, media_mime)
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

        wc = count_words(text)
        if wc > budget:
            print(f"[describer] {gap.gap_id}: SKIP (copy exceeded budget: {wc} > {budget})")
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start, end=gap.end,
                text=None, gap_id=gap.gap_id, skip_reason="budget",
            ))
            continue

        candidate_cue = {"start": gap.start, "end": gap.end, "text": text}
        assert_no_collision([candidate_cue], dialogue_spans)

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
