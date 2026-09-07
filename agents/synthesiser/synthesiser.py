"""
Synthesiser agent.

Converts cue text to speech using Gemini Flash TTS (gemini-2.5-flash-preview-tts)
via the google-genai SDK — the same SDK used throughout the pipeline.
Produces one WAV audio clip per cue, trimmed to fit the gap duration.

Input:  list of Cue objects
Output: Cue objects with audio_path set
"""

import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from agents.shared.models import Cue


# Gemini Flash TTS model
TTS_MODEL = "gemini-2.5-flash-preview-tts"

# Voice: Puck is a clear, neutral narration voice available in Flash TTS
TTS_VOICE = "Puck"


def _client() -> genai.Client:
    """
    Use Vertex AI (ADC / service account) when running on Cloud Run
    (GOOGLE_CLOUD_PROJECT is set).  Fall back to API key for local dev.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        return genai.Client(vertexai=True, project=project, location=location)
    return genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"])


def synthesise_cue(
    cue: Cue,
    output_dir: str,
    client: Optional[genai.Client] = None,
) -> Optional[str]:
    """
    Synthesise a single cue to a WAV file using Gemini Flash TTS.
    Returns the path to the output WAV file, or None if cue is skipped.
    """
    if cue.text is None:
        return None

    if client is None:
        client = _client()

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = str(Path(output_dir) / f"{cue.cue_id}.wav")

    print(f"[synthesiser] {cue.cue_id}: synthesising '{cue.text}'")

    response = client.models.generate_content(
        model=TTS_MODEL,
        contents=cue.text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=TTS_VOICE,
                    )
                )
            ),
        ),
    )

    # Extract raw PCM bytes from response
    audio_data = response.candidates[0].content.parts[0].inline_data.data

    # Write as WAV (Gemini Flash TTS returns 24 kHz, 16-bit, mono PCM)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
        with wave.open(tmp_path, "wb") as wav_file:
            wav_file.setnchannels(1)       # mono
            wav_file.setsampwidth(2)       # 16-bit
            wav_file.setframerate(24000)   # 24 kHz
            wav_file.writeframes(audio_data)

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
    client = _client()

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

    cues_data = json.loads(Path(args.cues).read_text())
    cue_objs = [Cue(**c) for c in cues_data]
    synthesise_cues(cue_objs, args.output_dir)
    print(f"[synthesiser] Done. {sum(1 for c in cue_objs if c.audio_path)} clips synthesised.")
