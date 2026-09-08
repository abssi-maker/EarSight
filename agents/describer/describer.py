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
from google.adk.runners import Runner, RunConfig
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


# ── Per-gap ADK invocation ─────────────────────────────────────────────────────
_MAX_LLM_CALLS = 8  # hard ceiling per gap — prevents infinite tool-call loops


def _run_adk_gap(
    gap_id: str,
    gap_prompt: str,
    dialogue_spans_json: str,
    video_part: Optional[types.Part],
) -> tuple[Optional[str], Optional[str]]:
    """
    Single ADK LlmAgent invocation for one gap.

    tool_config mode=ANY is kept (forced function calling). The model must call
    _check_budget and _check_collision before calling submit_cue, which is the
    only terminal tool. max_llm_calls=8 caps the loop so a bad gap can never hang.

    Returns (text, skip_reason): text=None means skip this gap.
    """
    def _check_collision(start: float, end: float) -> dict:
        """Check whether cue [start, end] overlaps any dialogue span."""
        print(f"[describer] {gap_id}: tool _check_collision({start}, {end})")
        return check_collision(start, end, dialogue_spans_json)

    def _check_budget(text: str, gap_seconds: float) -> dict:
        """Check word budget for text against a gap of gap_seconds seconds."""
        print(f"[describer] {gap_id}: tool _check_budget(words={count_words(text)}, secs={gap_seconds})")
        return check_budget(text, gap_seconds)

    def submit_cue(gap_id: str, text: str, skip_reason: str = "") -> dict:
        """Submit the final description for a gap. Call this last, exactly once,
        after check_budget and check_collision have passed. Pass text=\"\" and a
        skip_reason to skip the gap."""
        print(f"[describer] {gap_id}: tool submit_cue(text={repr(text)[:60]}, skip={repr(skip_reason)})")
        return {"accepted": True, "gap_id": gap_id}

    model_name = GEMINI_MODELS[0]

    agent = LlmAgent(
        name="copy_writer",
        model=model_name,
        instruction=gap_prompt,
        tools=[_check_budget, _check_collision, submit_cue],
        generate_content_config=types.GenerateContentConfig(
            safety_settings=_SAFETY_SETTINGS,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=["_check_budget", "_check_collision", "submit_cue"],
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

    async def _run() -> tuple[Optional[str], Optional[str]]:
        session = await session_service.create_session(
            app_name="earsight_describer",
            user_id="system",
        )
        user_parts = []
        if video_part is not None:
            user_parts.append(video_part)
        user_parts.append(types.Part.from_text(text="Write the description cue for this gap now."))

        # Scan events for a submit_cue function call — that carries the result
        submit_args: Optional[dict] = None
        async for event in runner.run_async(
            user_id="system",
            session_id=session.id,
            new_message=types.Content(role="user", parts=user_parts),
            run_config=RunConfig(max_llm_calls=_MAX_LLM_CALLS),
        ):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        if fc.name == "submit_cue":
                            submit_args = dict(fc.args) if fc.args else {}

        if submit_args is None:
            return None, "no_submit"

        text = submit_args.get("text") or None
        skip_reason = submit_args.get("skip_reason") or None
        # Treat empty string as skip
        if text == "":
            text = None
        return text, skip_reason

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

    # ── VIDEO PATH (per-gap ADK calls with submit_cue terminal tool) ───────────
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
        print(f"[describer] ADK per-gap path — {len(gaps_sorted)} gaps, video attached each call")
        cues: list[Cue] = []
        _t0 = _time.time()

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

            facts_str = json.dumps(established_facts) if established_facts else "[]"
            gap_prompt = f"""You are writing one audio description cue for a short video —
narration spoken in a silence gap for blind and low-vision viewers.
The video is attached. Do NOT add VideoMetadata offsets; you see the full clip.

Full transcript:
{transcript.full_text or "(no dialogue)"}

Facts already established (do not repeat):
{facts_str}

This gap: {gap.gap_id}
  start={round(gap.start, 2)}s  end={round(gap.end, 2)}s  duration={round(gap.duration, 2)}s
  word_budget={budget}
  dialogue_before="{gap.preceding_context}"
  dialogue_after="{gap.following_context}"

Steps (MUST follow in order):
1. Call _check_budget(text, gap_seconds) with your candidate cue text.
2. Call _check_collision(start={round(gap.start, 2)}, end={round(gap.end, 2)}) to verify no overlap.
3. Call submit_cue(gap_id="{gap.gap_id}", text="<your cue>") to submit — OR
   call submit_cue(gap_id="{gap.gap_id}", text="", skip_reason="<reason>") to skip.

Rules:
- text MUST be {budget} words or fewer — hard limit
- Present tense, active voice, specific and visual
- Never mention camera angles or filmmaking
- Never repeat an established fact
- Skip if: budget < 3, dialogue conveys the scene, or nothing visual is worth describing
"""

            print(f"[describer] {gap.gap_id}: writing copy via ADK (budget={budget} words)...")
            try:
                text, skip_reason = _run_adk_gap(gap.gap_id, gap_prompt, dialogue_spans_json, video_part)
            except Exception as exc:
                print(f"[describer] {gap.gap_id}: ADK error: {exc} — skipping gap")
                cues.append(Cue(
                    cue_id=f"cue_{gap.gap_id}",
                    start=gap.start, end=gap.end,
                    text=None, gap_id=gap.gap_id, skip_reason="error",
                ))
                continue

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

        print(f"[describer] ADK per-gap pass done in {_time.time()-_t0:.1f}s")
        return cues

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
