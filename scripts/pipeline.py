"""
scripts/pipeline.py — Local sequential pipeline for EarSight Step 1.

Usage:
    python -m scripts.pipeline --input demo/sample.mp4 [--output-dir demo/output]

Runs the full pipeline:
  1. Transcription (Gemini audio)
  2. Gap detection + frame extraction
  3. Description (Gemini multimodal, two-pass)
  4. Synthesis (Google Cloud TTS)
  5. Mix (ffmpeg)
  6. Collision validation (assert, fail hard on violation)

Output: demo/output/described.mp4 + demo/output/described.vtt
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Allow running from project root as `python -m scripts.pipeline`
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.transcriber.transcriber import transcribe
from agents.framer.framer import find_gaps, extract_frames, get_video_duration
from agents.describer.describer import describe_gaps
from agents.synthesiser.synthesiser import synthesise_cues
from agents.mixer.mixer import mix
from agents.shared.collision import assert_no_collision
from agents.shared.models import Transcript, Word


def main():
    parser = argparse.ArgumentParser(description="EarSight local pipeline")
    parser.add_argument("--input", "-i", default="demo/sample.mp4", help="Input video path")
    parser.add_argument("--output-dir", "-o", default="demo/output", help="Output directory")
    parser.add_argument("--skip-transcription", action="store_true",
                        help="Use cached transcript if available")
    args = parser.parse_args()

    video_path = args.input
    output_dir = args.output_dir
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    frames_dir = str(Path(output_dir) / "frames")
    audio_dir = str(Path(output_dir) / "audio")
    transcript_path = str(Path(output_dir) / "transcript.json")
    gaps_path = str(Path(output_dir) / "gaps.json")
    cues_path = str(Path(output_dir) / "cues.json")
    output_video = str(Path(output_dir) / "described.mp4")
    output_vtt = str(Path(output_dir) / "described.vtt")

    # ── Step 1: Transcription ─────────────────────────────────────────────────
    if args.skip_transcription and Path(transcript_path).exists():
        print("[pipeline] Loading cached transcript...")
        transcript_data = json.loads(Path(transcript_path).read_text())
        words = [Word(**w) for w in transcript_data["words"]]
        transcript = Transcript(
            words=words,
            language=transcript_data["language"],
            full_text=transcript_data["full_text"],
        )
    else:
        print("[pipeline] ── Step 1: Transcription ──────────────────────────")
        transcript = transcribe(video_path)
        # Save transcript
        Path(transcript_path).write_text(json.dumps({
            "language": transcript.language,
            "full_text": transcript.full_text,
            "words": [{"word": w.word, "start": w.start, "end": w.end} for w in transcript.words],
        }, indent=2))
        print(f"[pipeline] Transcript: {len(transcript.words)} words, text: {transcript.full_text[:100]!r}")

    # ── Step 2: Gap detection + frame extraction ──────────────────────────────
    print("[pipeline] ── Step 2: Gap detection + frame extraction ──────────")
    duration = get_video_duration(video_path)
    gaps = find_gaps(transcript, duration)
    print(f"[pipeline] Found {len(gaps)} silence gaps in {duration:.1f}s video")

    gaps = extract_frames(video_path, gaps, frames_dir)

    # Save gaps
    Path(gaps_path).write_text(json.dumps([
        {
            "gap_id": g.gap_id,
            "start": g.start,
            "end": g.end,
            "duration": g.duration,
            "frame_path": g.frame_path,
            "preceding_context": g.preceding_context,
            "following_context": g.following_context,
        }
        for g in gaps
    ], indent=2))

    for g in gaps:
        from agents.shared.budget import word_budget
        budget = word_budget(g.duration)
        print(f"  {g.gap_id}: [{g.start:.2f}–{g.end:.2f}s] duration={g.duration:.2f}s budget={budget}w")

    # ── Step 3: Description ───────────────────────────────────────────────────
    print("[pipeline] ── Step 3: Description (two-pass Gemini) ─────────────")
    cues = describe_gaps(transcript, gaps)

    # Final collision guard — belt-and-suspenders check before writing output
    active_cues = [c for c in cues if c.text is not None]
    assert_no_collision(
        [{"start": c.start, "end": c.end, "text": c.text} for c in active_cues],
        transcript.dialogue_spans(),
    )
    print(f"[pipeline] Collision guard: PASSED ({len(active_cues)} active cues)")

    # Save cues
    Path(cues_path).write_text(json.dumps([
        {
            "cue_id": c.cue_id,
            "start": c.start,
            "end": c.end,
            "text": c.text,
            "word_count": c.word_count,
            "gap_id": c.gap_id,
            "skip_reason": c.skip_reason,
            "audio_path": c.audio_path,
        }
        for c in cues
    ], indent=2))

    print(f"[pipeline] Cues: {len(active_cues)} active, {len(cues) - len(active_cues)} skipped")
    for c in cues:
        status = f"'{c.text}' ({c.word_count}w)" if c.text else f"SKIP ({c.skip_reason})"
        print(f"  {c.cue_id}: [{c.start:.2f}–{c.end:.2f}s] {status}")

    # ── Step 4: Synthesis ─────────────────────────────────────────────────────
    print("[pipeline] ── Step 4: TTS synthesis ────────────────────────────")
    cues = synthesise_cues(cues, audio_dir)

    # Update cues JSON with audio paths
    Path(cues_path).write_text(json.dumps([
        {
            "cue_id": c.cue_id,
            "start": c.start,
            "end": c.end,
            "text": c.text,
            "word_count": c.word_count,
            "gap_id": c.gap_id,
            "skip_reason": c.skip_reason,
            "audio_path": c.audio_path,
        }
        for c in cues
    ], indent=2))

    # ── Step 5: Mix ───────────────────────────────────────────────────────────
    print("[pipeline] ── Step 5: ffmpeg mix ───────────────────────────────")
    mix(video_path, cues, output_video, output_vtt)

    # ── Done ──────────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("EARSIGHT PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Video:   {output_video}")
    print(f"  VTT:     {output_vtt}")
    print(f"  Cues:    {len(active_cues)} descriptions placed")
    print(f"  Skipped: {len(cues) - len(active_cues)} gaps (budget/salience/redundant)")
    print()

    # Print the VTT for inspection
    print("[VTT output]")
    print(Path(output_vtt).read_text())


if __name__ == "__main__":
    main()
