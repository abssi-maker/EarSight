"""
Mixer agent.

Mixes narration audio clips into the original video:
- Ducks original audio under narration (−12dB) during description
- Places each narration clip at its gap start time
- Produces described.mp4 and described.vtt

Input:  original video path + list of Cue objects with audio_path set
Output: described.mp4, described.vtt
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from agents.shared.models import Cue


DUCK_VOLUME = 0.25  # 25% volume (≈ -12dB) under narration


def build_vtt(cues: list[Cue], output_path: str) -> str:
    """Write a WebVTT cue sheet from the cue list."""
    lines = ["WEBVTT", ""]
    for cue in cues:
        if cue.text is None:
            continue
        start_str = _format_vtt_time(cue.start)
        end_str = _format_vtt_time(cue.end)
        lines.append(f"{cue.cue_id}")
        lines.append(f"{start_str} --> {end_str}")
        lines.append(cue.text)
        lines.append("")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm for WebVTT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def mix(
    video_path: str,
    cues: list[Cue],
    output_video_path: str,
    output_vtt_path: str,
) -> tuple[str, str]:
    """
    Mix narration audio clips into the video.

    Strategy:
    - Build a complex ffmpeg filter graph that:
      1. Takes the original audio
      2. At each narration window, ducks the original to DUCK_VOLUME
      3. Overlays the narration clip at the correct offset
    - Mux with the original video stream

    Returns (output_video_path, output_vtt_path).
    """
    active_cues = [c for c in cues if c.text is not None and c.audio_path is not None]

    if not active_cues:
        print("[mixer] No active cues — copying original video unchanged")
        Path(output_video_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_video_path],
            check=True, capture_output=True,
        )
        build_vtt(cues, output_vtt_path)
        return output_video_path, output_vtt_path

    # Build ffmpeg command with amix/adelay approach
    # Input 0: original video
    # Input 1..N: narration clips
    inputs = ["-i", video_path]
    for i, cue in enumerate(active_cues):
        inputs += ["-i", cue.audio_path]

    n = len(active_cues)

    # Filter graph:
    # 1. For each narration clip, delay it to its start position
    # 2. Mix all narration clips together
    # 3. Use sidechaincompress to duck original under narration
    # 4. Mix ducked original with narration

    filter_parts = []
    narration_labels = []

    for i, cue in enumerate(active_cues):
        delay_ms = int(cue.start * 1000)
        label = f"nar{i}"
        filter_parts.append(f"[{i + 1}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        narration_labels.append(f"[{label}]")

    # Mix all narration clips together
    if n == 1:
        filter_parts.append(f"{narration_labels[0]}anull[narration]")
    else:
        mix_inputs = "".join(narration_labels)
        filter_parts.append(f"{mix_inputs}amix=inputs={n}:normalize=0[narration]")

    # Build duck filter: volume envelope that drops to DUCK_VOLUME during narration windows
    # Use volume= with enable expressions for each cue window
    duck_conditions = "+".join(
        f"between(t,{c.start:.3f},{c.end:.3f})" for c in active_cues
    )
    duck_expr = f"if(gt({duck_conditions},0),{DUCK_VOLUME},1)"
    filter_parts.append(f"[0:a]volume='{duck_expr}'[ducked]")

    # Mix ducked original with narration
    filter_parts.append("[ducked][narration]amix=inputs=2:normalize=0[mixed]")

    filter_graph = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", filter_graph,
            "-map", "0:v",
            "-map", "[mixed]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_video_path,
        ]
    )

    Path(output_video_path).parent.mkdir(parents=True, exist_ok=True)
    print(f"[mixer] Mixing {n} narration clips into {output_video_path}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[mixer] ffmpeg stderr:\n{result.stderr[-2000:]}")
        raise RuntimeError(f"ffmpeg mix failed: {result.returncode}")

    build_vtt(cues, output_vtt_path)
    print(f"[mixer] ✓ {output_video_path}")
    print(f"[mixer] ✓ {output_vtt_path}")
    return output_video_path, output_vtt_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mix narration into a video")
    parser.add_argument("--video", "-v", required=True, help="Original video path")
    parser.add_argument("--cues", "-c", required=True, help="Cues JSON path (with audio_path set)")
    parser.add_argument("--output-video", required=True, help="Output video path")
    parser.add_argument("--output-vtt", required=True, help="Output VTT path")
    args = parser.parse_args()

    from agents.shared.models import Cue

    cues_data = json.loads(Path(args.cues).read_text())
    cue_objs = [Cue(**c) for c in cues_data]
    mix(args.video, cue_objs, args.output_video, args.output_vtt)
