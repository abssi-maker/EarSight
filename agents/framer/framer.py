"""
Framer agent.

Detects silence gaps in the transcript and extracts one representative
frame from the video for each gap (at the midpoint of the gap).

Input:  video path + Transcript
Output: list of Gap objects with frame_path set
"""

import os
import subprocess
from pathlib import Path

from agents.shared.models import Transcript, Gap


MIN_GAP_SECONDS = 0.5  # ignore gaps shorter than this


def find_gaps(transcript: Transcript, video_duration: float) -> list[Gap]:
    """
    Find silence gaps in a transcript.

    A gap is any span ≥ MIN_GAP_SECONDS with no transcript word overlapping it.
    We also check the gap before the first word and after the last word.
    """
    gaps: list[Gap] = []
    gap_index = 0

    words = sorted(transcript.words, key=lambda w: w.start)

    # Gap before first word
    if words and words[0].start >= MIN_GAP_SECONDS:
        gaps.append(Gap(
            gap_id=f"gap_{gap_index:03d}",
            start=0.0,
            end=words[0].start,
            duration=words[0].start,
            preceding_context="",
            following_context=words[0].word if words else "",
        ))
        gap_index += 1

    # Gaps between words
    for i in range(len(words) - 1):
        gap_start = words[i].end
        gap_end = words[i + 1].start
        duration = gap_end - gap_start
        if duration >= MIN_GAP_SECONDS:
            # Context: up to 10 words before and after
            preceding = " ".join(w.word for w in words[max(0, i - 9):i + 1])
            following = " ".join(w.word for w in words[i + 1:i + 11])
            gaps.append(Gap(
                gap_id=f"gap_{gap_index:03d}",
                start=gap_start,
                end=gap_end,
                duration=duration,
                preceding_context=preceding,
                following_context=following,
            ))
            gap_index += 1

    # Gap after last word
    if words and (video_duration - words[-1].end) >= MIN_GAP_SECONDS:
        gaps.append(Gap(
            gap_id=f"gap_{gap_index:03d}",
            start=words[-1].end,
            end=video_duration,
            duration=video_duration - words[-1].end,
            preceding_context=words[-1].word,
            following_context="",
        ))
        gap_index += 1

    # No words at all — the whole video is a gap
    if not words and video_duration >= MIN_GAP_SECONDS:
        gaps.append(Gap(
            gap_id="gap_000",
            start=0.0,
            end=video_duration,
            duration=video_duration,
        ))

    return gaps


def extract_frame(video_path: str, timestamp: float, out_path: str) -> str:
    """Extract a single frame from the video at the given timestamp."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
    return out_path


def extract_frames(video_path: str, gaps: list[Gap], frames_dir: str) -> list[Gap]:
    """
    Extract a representative frame for each gap (at the midpoint).
    Mutates gaps in place, setting gap.frame_path.
    Returns the updated gap list.
    """
    Path(frames_dir).mkdir(parents=True, exist_ok=True)

    for gap in gaps:
        midpoint = gap.start + gap.duration / 2
        frame_path = str(Path(frames_dir) / f"{gap.gap_id}.jpg")
        try:
            extract_frame(video_path, midpoint, frame_path)
            gap.frame_path = frame_path
            print(f"[framer] {gap.gap_id}: {gap.duration:.2f}s gap → frame at {midpoint:.2f}s")
        except subprocess.CalledProcessError as e:
            print(f"[framer] WARNING: failed to extract frame for {gap.gap_id}: {e}")
            gap.frame_path = None

    return gaps


def get_video_duration(video_path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Find gaps and extract frames from a video")
    parser.add_argument("--input", "-i", required=True, help="Path to input video")
    parser.add_argument("--transcript", "-t", required=True, help="Path to transcript JSON")
    parser.add_argument("--frames-dir", "-f", default="frames", help="Directory for frame images")
    args = parser.parse_args()

    from agents.shared.models import Word, Transcript as T
    transcript_data = json.loads(Path(args.transcript).read_text())
    words = [Word(**w) for w in transcript_data["words"]]
    transcript = T(words=words, language=transcript_data["language"], full_text=transcript_data["full_text"])

    duration = get_video_duration(args.input)
    gaps = find_gaps(transcript, duration)
    gaps = extract_frames(args.input, gaps, args.frames_dir)

    for g in gaps:
        print(f"  {g.gap_id}: [{g.start:.2f}s – {g.end:.2f}s] ({g.duration:.2f}s) frame={g.frame_path}")
