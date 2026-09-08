"""
Transcriber Cloud Run service.

Consumes earsight.jobs → downloads video from GCS → transcribes with Gemini
→ uploads transcript JSON + peaks.json to GCS → publishes to earsight.transcript.

peaks.json carries waveform peak data for the frontend Waveform component:
  {duration: float, peaks: float[1000]}  (normalised 0.0–1.0)
Generated with ffmpeg + stdlib wave — no new dependencies.
"""

import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import wave
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from agents.shared.gcs import download_to_file, upload_json, make_uri
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.transcriber.transcriber import transcribe

PEAKS_COUNT = 1000  # number of buckets in the waveform


def _generate_peaks(video_path: str, tmpdir: str) -> tuple[float, list[float]]:
    """
    Decode audio to 8-bit mono PCM at 1kHz, bucket into PEAKS_COUNT normalised
    peaks using the stdlib wave module (no extra dependencies).
    Returns (duration_seconds, peaks) where peaks values are 0.0–1.0.
    """
    pcm_path = os.path.join(tmpdir, "peaks.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path,
         "-vn", "-ac", "1", "-ar", "1000", "-sample_fmt", "u8", "-f", "wav", pcm_path],
        check=True, capture_output=True,
    )

    with wave.open(pcm_path, "rb") as wf:
        n_frames = wf.getnframes()
        framerate = wf.getframerate()
        raw = wf.readframes(n_frames)

    if n_frames == 0:
        return 0.0, [0.0] * PEAKS_COUNT

    duration = n_frames / framerate
    # 8-bit unsigned: values 0–255, centre at 128
    samples = [abs(b - 128) for b in raw]  # 0–128 range

    bucket_size = max(1, len(samples) // PEAKS_COUNT)
    peaks = []
    for i in range(PEAKS_COUNT):
        chunk = samples[i * bucket_size: (i + 1) * bucket_size]
        peaks.append(max(chunk) / 128.0 if chunk else 0.0)

    return duration, peaks

TOPIC_IN = "earsight.jobs"
TOPIC_OUT = "earsight.transcript"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    video_uri = msg.get("video_uri", "")
    print(f"[transcriber] job {job_id} — video: {video_uri}")

    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "input.mp4")

        # Download video from GCS
        print(f"[transcriber] downloading {video_uri}...")
        download_to_file(video_uri, video_path)

        # Transcribe
        print(f"[transcriber] transcribing...")
        transcript = transcribe(video_path)

        # Serialise to GCS
        transcript_data = {
            "language": transcript.language,
            "full_text": transcript.full_text,
            "words": [{"word": w.word, "start": w.start, "end": w.end}
                      for w in transcript.words],
        }
        transcript_uri = make_uri(job_id, "transcript.json")
        upload_json(transcript_data, transcript_uri)
        print(f"[transcriber] transcript uploaded → {transcript_uri} "
              f"({len(transcript.words)} words)")

        # Generate waveform peaks
        peaks_uri = None
        try:
            duration, peaks = _generate_peaks(video_path, tmpdir)
            peaks_uri = make_uri(job_id, "peaks.json")
            upload_json({"duration": duration, "peaks": peaks}, peaks_uri)
            print(f"[transcriber] peaks uploaded → {peaks_uri} ({duration:.1f}s, {PEAKS_COUNT} buckets)")
        except Exception as exc:
            print(f"[transcriber] peaks generation failed (non-fatal): {exc}")

    # Publish to earsight.transcript
    producer = get_producer()
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "transcript_uri": transcript_uri,
        "word_count": len(transcript.words),
        "peaks_uri": peaks_uri,
    }, key=job_id)
    print(f"[transcriber] published to {TOPIC_OUT}")


def _start_consumer() -> None:
    try:
        consumer = get_consumer("transcriber", [TOPIC_IN])
        producer = get_producer()
        consume_loop(consumer, _handle, producer, TOPIC_IN)
    except Exception as exc:
        print(f"[transcriber] consumer error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_start_consumer, daemon=True)
    t.start()
    yield


app = FastAPI(title="EarSight Transcriber", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "transcriber", "version": "0.2.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
