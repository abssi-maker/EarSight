"""
scripts/test_step3.py — Integration test for Step 3.

Tests transcriber + framer agent logic end-to-end using the demo clip.
Does NOT require Kafka or a running GCS bucket — tests the core processing
logic that the Cloud Run services wrap.

Usage:
    python scripts/test_step3.py [--use-cached]
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.transcriber.transcriber import transcribe
from agents.framer.framer import find_gaps, extract_frames, get_video_duration
from agents.shared.models import Transcript, Word
from agents.shared.budget import word_budget


DEMO_VIDEO = "demo/sample.mp4"
CACHED_TRANSCRIPT = "demo/output/transcript.json"


def test_transcriber(video_path: str, use_cached: bool) -> Transcript:
    """Test real transcription or load cached transcript."""
    if use_cached and Path(CACHED_TRANSCRIPT).exists():
        print(f"[test] Loading cached transcript from {CACHED_TRANSCRIPT}")
        data = json.loads(Path(CACHED_TRANSCRIPT).read_text())
        words = [Word(**w) for w in data["words"]]
        transcript = Transcript(
            words=words,
            language=data.get("language", "en"),
            full_text=data.get("full_text", ""),
        )
    else:
        print(f"[test] Transcribing {video_path} via Gemini...")
        transcript = transcribe(video_path)

    assert isinstance(transcript.words, list), "transcript.words must be a list"
    assert all(hasattr(w, "word") and hasattr(w, "start") and hasattr(w, "end")
               for w in transcript.words), "each word must have word/start/end"
    print(f"[test] ✓ transcript: {len(transcript.words)} words")
    print(f"[test]   full_text: {transcript.full_text[:80]!r}...")
    for w in transcript.words[:3]:
        print(f"[test]   [{w.start:.2f}–{w.end:.2f}s] {w.word!r}")
    print()
    return transcript


def test_framer(video_path: str, transcript: Transcript) -> list:
    """Test gap detection + frame extraction."""
    import tempfile

    duration = get_video_duration(video_path)
    print(f"[test] Video duration: {duration:.2f}s")

    gaps = find_gaps(transcript, duration)
    print(f"[test] ✓ {len(gaps)} silence gaps detected")

    # Validate gap structure
    for gap in gaps:
        assert gap.gap_id, "gap must have an ID"
        assert gap.start >= 0, f"gap start must be ≥ 0: {gap.start}"
        assert gap.end > gap.start, f"gap end must be > start: {gap}"
        assert gap.duration > 0, f"gap duration must be > 0: {gap.duration}"
        # No gap should overlap any word
        for w in transcript.words:
            overlap = min(gap.end, w.end) - max(gap.start, w.start)
            assert overlap <= 0, (
                f"GAP {gap.gap_id} [{gap.start:.2f}–{gap.end:.2f}] overlaps "
                f"word '{w.word}' [{w.start:.2f}–{w.end:.2f}]"
            )

    # Print gap summary
    for gap in gaps:
        budget = word_budget(gap.duration)
        print(f"[test]   {gap.gap_id}: [{gap.start:.2f}–{gap.end:.2f}s] "
              f"duration={gap.duration:.2f}s budget={budget}w")

    print()

    # Extract frames to a temp dir
    with tempfile.TemporaryDirectory() as tmpdir:
        frames_dir = os.path.join(tmpdir, "frames")
        gaps = extract_frames(video_path, gaps, frames_dir)
        frames_found = sum(1 for g in gaps if g.frame_path and Path(g.frame_path).exists())
        print(f"[test] ✓ {frames_found}/{len(gaps)} frames extracted")
        assert frames_found > 0, "At least one frame must be extracted"

    return gaps


def test_manifest_shape(gaps: list) -> None:
    """Validate the structure of the frames manifest that would be uploaded."""
    manifest = {
        "job_id": "test-step3",
        "gap_count": len(gaps),
        "gaps": [
            {
                "gap_id": g.gap_id,
                "start": g.start,
                "end": g.end,
                "duration": g.duration,
                "frame_uri": f"gs://earsight-media/jobs/test-step3/frames/{g.gap_id}.jpg",
                "preceding_context": g.preceding_context,
                "following_context": g.following_context,
            }
            for g in gaps
        ],
    }
    # Round-trip through JSON
    serialised = json.dumps(manifest)
    parsed = json.loads(serialised)
    assert parsed["gap_count"] == len(gaps)
    assert len(parsed["gaps"]) == len(gaps)
    print(f"[test] ✓ manifest shape valid ({len(gaps)} gaps)")


def main():
    parser = argparse.ArgumentParser(description="Step 3 integration test")
    parser.add_argument("--use-cached", action="store_true",
                        help="Use cached transcript (skip Gemini call)")
    args = parser.parse_args()

    video_path = DEMO_VIDEO
    assert Path(video_path).exists(), f"Demo video not found: {video_path}"

    print("=" * 60)
    print("STEP 3 INTEGRATION TEST")
    print("=" * 60)
    print()

    # 1. Transcription
    transcript = test_transcriber(video_path, use_cached=args.use_cached)

    # 2. Framer
    gaps = test_framer(video_path, transcript)

    # 3. Manifest shape
    test_manifest_shape(gaps)

    print()
    print("=" * 60)
    print("ALL CHECKS PASSED ✓")
    print(f"  Words transcribed: {len(transcript.words)}")
    print(f"  Gaps detected:     {len(gaps)}")
    print(f"  Max word budget:   {max(word_budget(g.duration) for g in gaps) if gaps else 0}w")
    print("=" * 60)


if __name__ == "__main__":
    main()
