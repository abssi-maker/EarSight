"""
scripts/validate_cues.py — VTT collision validator.

Parses a WebVTT file and a transcript JSON, then asserts that no cue
overlaps any dialogue span.

Exit code 1 on any collision — this is meant to fail CI.

Usage:
    python -m scripts.validate_cues --vtt output/described.vtt --transcript output/transcript.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def parse_vtt_time(time_str: str) -> float:
    """Parse HH:MM:SS.mmm or MM:SS.mmm to seconds."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    raise ValueError(f"Invalid VTT time: {time_str!r}")


def parse_vtt(vtt_path: str) -> list[dict]:
    """Parse a WebVTT file into a list of cue dicts with start, end, text."""
    content = Path(vtt_path).read_text(encoding="utf-8")
    cues = []
    current_cue: dict | None = None

    for line in content.splitlines():
        line = line.strip()
        if "-->" in line:
            parts = re.split(r"\s+-->\s+", line)
            current_cue = {
                "start": parse_vtt_time(parts[0].split()[0]),
                "end": parse_vtt_time(parts[1].split()[0]),
                "text": "",
            }
        elif current_cue is not None:
            if line == "":
                if current_cue["text"]:
                    cues.append(current_cue)
                current_cue = None
            else:
                current_cue["text"] = (current_cue["text"] + " " + line).strip()

    if current_cue and current_cue["text"]:
        cues.append(current_cue)

    return cues


def validate(vtt_path: str, transcript_path: str) -> int:
    """
    Validate that no cue in the VTT file overlaps any dialogue span.
    Returns 0 on success, 1 on collision.
    """
    cues = parse_vtt(vtt_path)
    transcript_data = json.loads(Path(transcript_path).read_text())
    dialogue_spans = transcript_data.get("words", [])

    collisions = 0
    for cue in cues:
        for word in dialogue_spans:
            # Collision: cue starts before word ends AND cue ends after word starts
            if cue["start"] < word["end"] and cue["end"] > word["start"]:
                print(
                    f"COLLISION: cue [{cue['start']:.3f}–{cue['end']:.3f}s] "
                    f"overlaps word '{word['word']}' [{word['start']:.3f}–{word['end']:.3f}s]",
                    file=sys.stderr,
                )
                collisions += 1

    if collisions == 0:
        print(f"OK: {len(cues)} cues, no collisions with {len(dialogue_spans)} dialogue words")
        return 0
    else:
        print(f"FAILED: {collisions} collision(s) found in {len(cues)} cues", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Validate that no VTT cue overlaps dialogue"
    )
    parser.add_argument("--vtt", required=True, help="WebVTT file path")
    parser.add_argument("--transcript", required=True, help="Transcript JSON path")
    args = parser.parse_args()

    sys.exit(validate(args.vtt, args.transcript))


if __name__ == "__main__":
    main()
