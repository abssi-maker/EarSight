"""
Describer agent — salience scoring + word-budget copy writing.  (gemini-3.8-flash)

Two-pass approach:
1. Context pass: Gemini sees the full transcript, all gaps, and established facts.
   Returns a priority-ranked list of gaps with rationale.
2. Copy pass: For each prioritised gap, Gemini writes copy fitting the word budget,
   given the frame image and established-facts memory.

No cue that would exceed its budget or collide with dialogue is ever written.
"""

import json
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from agents.shared.budget import word_budget, fits_budget, count_words
from agents.shared.collision import assert_no_collision
from agents.shared.models import Transcript, Gap, Cue

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
]
GEMINI_MODEL = GEMINI_MODELS[0]


import time as _time

def _get_client() -> genai.Client:
    """
    Use Vertex AI (ADC / service account) when running on Cloud Run
    (GOOGLE_CLOUD_PROJECT is set).  Fall back to API key for local dev.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        return genai.Client(vertexai=True, project=project, location=location)
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def _generate(client: genai.Client, contents) -> object:
    """Try each model in GEMINI_MODELS until one responds."""
    last_err = None
    for attempt, model in enumerate(GEMINI_MODELS):
        try:
            if attempt > 0:
                _time.sleep(2)
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            print(f"[describer] {model} failed: {str(e)[:80]}")
            last_err = e
    raise RuntimeError(f"All models failed: {last_err}")


def describe_gaps(
    transcript: Transcript,
    gaps: list[Gap],
    established_facts: Optional[list[str]] = None,
) -> list[Cue]:
    """
    Run the two-pass describer on a list of gaps.
    Returns a list of Cue objects (some with text=None for skipped gaps).
    """
    client = _get_client()

    if established_facts is None:
        established_facts = []

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
    response1 = _generate(client, pass1_prompt)
    raw1 = response1.text.strip()
    if raw1.startswith("```"):
        lines = raw1.split("\n")
        raw1 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    ranking_data = json.loads(raw1)

    # Build lookup: gap_id → ranking decision
    ranking = {r["gap_id"]: r for r in ranking_data.get("ranked_gaps", [])}

    # ── PASS 2: Copy writing ───────────────────────────────────────────────────
    cues: list[Cue] = []

    # Sort by timeline order, not priority (cues must be in time order)
    gap_map = {g.gap_id: g for g in gaps}

    for gap in sorted(gaps, key=lambda g: g.start):
        decision = ranking.get(gap.gap_id, {})
        budget = word_budget(gap.duration)

        if budget < 3:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start,
                end=gap.end,
                text=None,
                gap_id=gap.gap_id,
                skip_reason="budget",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (budget={budget} < 3)")
            continue

        if not decision.get("include", False):
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start,
                end=gap.end,
                text=None,
                gap_id=gap.gap_id,
                skip_reason="salience",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (salience — {decision.get('rationale', '')})")
            continue

        # Build copy-writing prompt with frame image if available
        content_parts: list[types.Part] = []

        if gap.frame_path and Path(gap.frame_path).exists():
            try:
                content_parts.append(
                    types.Part.from_bytes(
                        data=Path(gap.frame_path).read_bytes(),
                        mime_type="image/jpeg",
                    )
                )
            except Exception:
                pass

        facts_str = json.dumps(established_facts) if established_facts else "[]"
        copy_prompt = f"""You are writing one audio description cue for a short video.

Silence gap: {gap.start:.2f}s to {gap.end:.2f}s ({gap.duration:.2f}s)
Hard word budget: {budget} words MAXIMUM
Dialogue before: "{gap.preceding_context}"
Dialogue after:  "{gap.following_context}"
Facts already established: {facts_str}

{"[Frame from video at the midpoint of this gap is attached above]" if content_parts else "[No frame available]"}

Write ONE description cue. Rules:
- MUST be {budget} words or fewer — this is a hard limit, not a guide
- Present tense, active voice, specific and visual
- Do not describe what the audio already conveys
- Do not repeat established facts
- Do not mention camera angles or filmmaking
- If there is genuinely nothing worth describing, return null

Return ONLY valid JSON — no markdown:
{{"text": "A woman in a red coat crosses the empty platform." }}
or if nothing worth describing:
{{"text": null, "reason": "brief explanation"}}
"""

        content_parts.append(types.Part.from_text(text=copy_prompt))

        print(f"[describer] {gap.gap_id}: writing copy (budget={budget} words)...")
        response2 = _generate(client, content_parts)
        raw2 = response2.text.strip()
        if raw2.startswith("```"):
            lines = raw2.split("\n")
            raw2 = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        copy_data = json.loads(raw2)
        text = copy_data.get("text")

        if text is None:
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start,
                end=gap.end,
                text=None,
                gap_id=gap.gap_id,
                skip_reason="redundant",
            ))
            print(f"[describer] {gap.gap_id}: SKIP (redundant — {copy_data.get('reason', '')})")
            continue

        # Word budget check — drop if over budget
        wc = count_words(text)
        if wc > budget:
            print(f"[describer] {gap.gap_id}: SKIP (copy exceeded budget: {wc} > {budget})")
            cues.append(Cue(
                cue_id=f"cue_{gap.gap_id}",
                start=gap.start,
                end=gap.end,
                text=None,
                gap_id=gap.gap_id,
                skip_reason="budget",
            ))
            continue

        # Collision guard — verify cue doesn't overlap any dialogue
        candidate_cue = {"start": gap.start, "end": gap.end, "text": text}
        assert_no_collision([candidate_cue], transcript.dialogue_spans())

        # Add to established facts
        established_facts.append(text)

        cue = Cue(
            cue_id=f"cue_{gap.gap_id}",
            start=gap.start,
            end=gap.end,
            text=text,
            word_count=wc,
            gap_id=gap.gap_id,
        )
        cues.append(cue)
        print(f"[describer] {gap.gap_id}: ✓ '{text}' ({wc}/{budget} words)")

    return cues


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate description cues for a video")
    parser.add_argument("--transcript", "-t", required=True, help="Transcript JSON path")
    parser.add_argument("--gaps", "-g", required=True, help="Gaps JSON path")
    parser.add_argument("--output", "-o", help="Output cues JSON path (default: stdout)")
    args = parser.parse_args()

    from agents.shared.models import Word

    transcript_data = json.loads(Path(args.transcript).read_text())
    words = [Word(**w) for w in transcript_data["words"]]
    transcript_obj = Transcript(words=words, language=transcript_data["language"], full_text=transcript_data["full_text"])

    gaps_data = json.loads(Path(args.gaps).read_text())
    gap_objs = [Gap(**g) for g in gaps_data]

    cues = describe_gaps(transcript_obj, gap_objs)
    result = [
        {
            "cue_id": c.cue_id,
            "start": c.start,
            "end": c.end,
            "text": c.text,
            "word_count": c.word_count,
            "gap_id": c.gap_id,
            "skip_reason": c.skip_reason,
        }
        for c in cues
    ]
    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out)
        print(f"[describer] Written to {args.output}")
    else:
        print(out)
