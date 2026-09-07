"""
Transcriber agent.

Extracts audio from a video file and produces a word-level transcript
using Gemini's audio understanding capability (gemini-3.8-flash).

Falls back through available models if the primary is overloaded.

Input:  path to .mp4 video
Output: Transcript dataclass with word-level timestamps
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

from agents.shared.models import Transcript, Word

# Ordered preference — falls back if earlier model is overloaded
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
]


def _get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def extract_audio(video_path: str, out_path: str) -> str:
    """Extract mono 16kHz WAV from video using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", out_path],
        check=True, capture_output=True,
    )
    return out_path


def transcribe(video_path: str) -> Transcript:
    """
    Transcribe a video file using Gemini audio understanding.
    Returns a Transcript with word-level timestamps.
    """
    client = _get_client()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    uploaded = None
    try:
        extract_audio(video_path, audio_path)
        size_kb = Path(audio_path).stat().st_size // 1024
        print(f"[transcriber] Uploading audio ({size_kb}KB)...")

        uploaded = client.files.upload(
            file=audio_path,
            config=types.UploadFileConfig(mime_type="audio/wav"),
        )

        prompt = """Transcribe this audio with precise word-level timestamps.

Return ONLY valid JSON in this exact format — no markdown, no explanation:
{
  "language": "en",
  "words": [
    {"word": "Hello", "start": 0.12, "end": 0.45},
    {"word": "world", "start": 0.50, "end": 0.82}
  ],
  "full_text": "Hello world"
}

Rules:
- Include every spoken word with its start and end time in seconds
- If there is no speech, return {"language": "en", "words": [], "full_text": ""}
- Timestamps must be accurate to within 0.1 seconds
- Do not include non-speech sounds as words
"""

        print("[transcriber] Requesting transcription from Gemini...")
        response = None
        last_err = None
        for attempt, model in enumerate(GEMINI_MODELS):
            try:
                if attempt > 0:
                    time.sleep(2)
                print(f"[transcriber] Trying model: {model}")
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_uri(file_uri=uploaded.uri, mime_type="audio/wav"),
                        types.Part.from_text(text=prompt),
                    ],
                )
                break
            except Exception as e:
                print(f"[transcriber] {model} failed: {str(e)[:80]}")
                last_err = e
        if response is None:
            raise RuntimeError(f"All models failed. Last error: {last_err}")
        raw = response.text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(raw)
        words = [Word(word=w["word"], start=w["start"], end=w["end"])
                 for w in data.get("words", [])]
        return Transcript(
            words=words,
            language=data.get("language", "en"),
            full_text=data.get("full_text", ""),
        )

    finally:
        os.unlink(audio_path)
        if uploaded:
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Transcribe a video file")
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o", help="Output JSON path (default: stdout)")
    args = parser.parse_args()

    transcript = transcribe(args.input)
    result = {
        "language": transcript.language,
        "full_text": transcript.full_text,
        "words": [{"word": w.word, "start": w.start, "end": w.end}
                  for w in transcript.words],
    }
    out = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(out)
        print(f"[transcriber] Written to {args.output}")
    else:
        print(out)
