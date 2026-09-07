"""
Synthesiser agent.

Converts cue text to speech using Google Cloud Text-to-Speech (Chirp HD / Neural2).
Produces one audio clip per cue, trimmed to fit the gap duration.

Input:  list of Cue objects
Output: Cue objects with audio_path set
"""

import io
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from google.cloud import texttospeech
from dotenv import load_dotenv

load_dotenv()

from agents.shared.models import Cue


# Voice configuration — Neural2 gives high-quality narration voice
VOICE_NAME = "en-US-Neural2-J"   # warm, authoritative male voice
VOICE_LANGUAGE = "en-US"
SPEAKING_RATE = 0.95              # slightly slower than default for clarity


def synthesise_cue(
    cue: Cue,
    output_dir: str,
    client: Optional[texttospeech.TextToSpeechClient] = None,
) -> Optional[str]:
    """
    Synthesise a single cue to an audio file.
    Returns the path to the output WAV file, or None if cue is skipped.
    """
    if cue.text is None:
        return None

    if client is None:
        client = texttospeech.TextToSpeechClient()

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(output_dir) / f"{cue.cue_id}.wav")

    synthesis_input = texttospeech.SynthesisInput(text=cue.text)
    voice = texttospeech.VoiceSelectionParams(
        language_code=VOICE_LANGUAGE,
        name=VOICE_NAME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        speaking_rate=SPEAKING_RATE,
        sample_rate_hertz=44100,
    )

    print(f"[synthesiser] {cue.cue_id}: synthesising '{cue.text}'")
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    # Write raw TTS output
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(response.audio_content)

    # Trim/pad to exactly fit the gap duration using ffmpeg
    gap_duration = cue.end - cue.start
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", tmp_path,
            "-t", str(gap_duration),
            "-af", "afade=t=out:st=0:d=0.1",  # brief fade-out to avoid hard cut
            out_path,
        ],
        check=True,
        capture_output=True,
    )
    os.unlink(tmp_path)

    print(f"[synthesiser] {cue.cue_id}: ✓ saved to {out_path}")
    return out_path


def synthesise_cues(
    cues: list[Cue],
    output_dir: str,
) -> list[Cue]:
    """
    Synthesise all non-skipped cues.
    Mutates cues in place, setting cue.audio_path.
    Returns the updated cue list.
    """
    client = texttospeech.TextToSpeechClient()

    for cue in cues:
        if cue.text is None:
            continue
        audio_path = synthesise_cue(cue, output_dir, client)
        cue.audio_path = audio_path

    return cues


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Synthesise cue audio clips")
    parser.add_argument("--cues", "-c", required=True, help="Cues JSON path")
    parser.add_argument("--output-dir", "-o", required=True, help="Output directory for audio clips")
    args = parser.parse_args()

    from agents.shared.models import Cue

    cues_data = json.loads(Path(args.cues).read_text())
    cue_objs = [Cue(**c) for c in cues_data]
    synthesise_cues(cue_objs, args.output_dir)
    print(f"[synthesiser] Done. {sum(1 for c in cue_objs if c.audio_path)} clips synthesised.")
