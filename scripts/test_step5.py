#!/usr/bin/env python3
"""
Step 5 local integration test.

Exercises synthesiser + mixer end-to-end using the Step 4 demo output:
  demo/output/cues_step4.json  →  synthesiser  →  mixer  →  demo/output/described_step5.mp4
                                                         →  demo/output/described_step5.vtt

Run:
    python scripts/test_step5.py

Requires: GOOGLE_API_KEY set in .env (or environment).
Use EARSIGHT_USE_CACHE=1 to replay cached TTS responses.
"""

import json
import sys
from pathlib import Path

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from agents.shared.models import Cue
from agents.synthesiser.synthesiser import synthesise_cues
from agents.mixer.mixer import mix

CUES_PATH      = "demo/output/cues_step4.json"
VIDEO_PATH     = "demo/sample.mp4"
OUTPUT_VIDEO   = "demo/output/described_step5.mp4"
OUTPUT_VTT     = "demo/output/described_step5.vtt"
AUDIO_OUT_DIR  = "demo/output/audio_step5"


def main():
    print("=" * 60)
    print("Step 5 — local synthesiser + mixer test")
    print("=" * 60)

    # Load cues
    cues_raw = json.loads(Path(CUES_PATH).read_text())
    cues = [Cue(**c) for c in cues_raw]
    active = [c for c in cues if c.text is not None]
    print(f"\nLoaded {len(cues)} cues ({len(active)} active)")

    # Synthesise
    print("\n── Synthesiser ──────────────────────────────────────────")
    cues = synthesise_cues(cues, AUDIO_OUT_DIR)
    synthesised = [c for c in cues if c.audio_path is not None]
    print(f"✓ {len(synthesised)} clips synthesised → {AUDIO_OUT_DIR}/")

    # Mix
    print("\n── Mixer ────────────────────────────────────────────────")
    mix(VIDEO_PATH, cues, OUTPUT_VIDEO, OUTPUT_VTT)

    print("\n── Results ──────────────────────────────────────────────")
    print(f"✓ Video: {OUTPUT_VIDEO}  ({Path(OUTPUT_VIDEO).stat().st_size // 1024} KB)")
    print(f"✓ VTT:   {OUTPUT_VTT}")
    print(Path(OUTPUT_VTT).read_text())
    print("=" * 60)
    print("Step 5 local test PASS")


if __name__ == "__main__":
    main()
