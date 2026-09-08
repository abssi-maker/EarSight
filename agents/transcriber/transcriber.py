"""
Transcriber agent — ADK LlmAgent pattern.

Uses google.adk LlmAgent + Runner for the audio-understanding call,
consistent with the describer's ADK pattern. The audio file is uploaded
via the Files API and passed as a Part.from_uri to the agent.

Exposes the same public signature: transcribe(video_path) -> Transcript.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from dotenv import load_dotenv

load_dotenv()

from agents.shared.models import Transcript, Word

# Ordered preference — falls back if earlier model is overloaded
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

# ── Safety settings ────────────────────────────────────────────────────────────
# Transcription of real speech content: harassment and hate-speech filters can
# trigger on actual dialogue. Set explicit thresholds for predictable behaviour.
_SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_NONE,
    ),
]


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


def extract_audio(video_path: str, out_path: str) -> str:
    """Extract mono 16kHz WAV from video using ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", out_path],
        check=True, capture_output=True,
    )
    return out_path


import asyncio


def _run_transcriber_agent(client: genai.Client, audio_uri: str) -> str:
    """
    Run the transcription via ADK LlmAgent.
    Returns the raw text from the agent's final response.
    """
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

    model_name = GEMINI_MODELS[0]

    agent = LlmAgent(
        name="transcriber",
        model=model_name,
        instruction=prompt,
        generate_content_config=types.GenerateContentConfig(
            safety_settings=_SAFETY_SETTINGS,
        ),
    )

    session_service = InMemorySessionService()
    runner = Runner(
        app_name="earsight_transcriber",
        agent=agent,
        session_service=session_service,
    )

    async def _run():
        session = await session_service.create_session(
            app_name="earsight_transcriber",
            user_id="system",
        )
        events = []
        async for event in runner.run_async(
            user_id="system",
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[
                    types.Part.from_uri(file_uri=audio_uri, mime_type="audio/wav"),
                    types.Part.from_text(text="Transcribe the audio above."),
                ],
            ),
        ):
            events.append(event)
        for event in reversed(events):
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        return part.text
        return None

    try:
        return asyncio.run(_run())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()


def transcribe(video_path: str) -> Transcript:
    """
    Transcribe a video file using Gemini audio understanding via ADK LlmAgent.
    Returns a Transcript with word-level timestamps.
    Falls back to direct generate_content if the ADK runner fails.
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

        print("[transcriber] Requesting transcription via ADK agent...")
        raw = None

        # ADK path
        try:
            raw = _run_transcriber_agent(client, uploaded.uri)
        except Exception as exc:
            print(f"[transcriber] ADK path failed: {exc} — falling back to direct generate")

        # Fallback: direct model ladder
        if raw is None:
            last_err = None
            response = None
            prompt = """Transcribe this audio with precise word-level timestamps.

Return ONLY valid JSON — no markdown, no explanation:
{"language": "en", "words": [{"word": "Hello", "start": 0.12, "end": 0.45}], "full_text": "Hello world"}

Rules:
- Include every word with start/end time in seconds
- If no speech: {"language": "en", "words": [], "full_text": ""}
- Do not include non-speech sounds
"""
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
                        config=types.GenerateContentConfig(
                            safety_settings=_SAFETY_SETTINGS,
                        ),
                    )
                    raw = response.text
                    break
                except Exception as e:
                    print(f"[transcriber] {model} failed: {str(e)[:80]}")
                    last_err = e
            if raw is None:
                raise RuntimeError(f"All models failed. Last error: {last_err}")

        if raw is None:
            raise RuntimeError("Transcription returned no text")

        raw = raw.strip()
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
