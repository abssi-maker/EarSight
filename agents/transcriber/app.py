"""
Transcriber Cloud Run service.

Consumes earsight.jobs → downloads video from GCS → transcribes with Gemini
→ uploads transcript JSON to GCS → publishes to earsight.transcript.
"""

import json
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from agents.shared.gcs import download_to_file, upload_json, make_uri
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.transcriber.transcriber import transcribe

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

    # Publish to earsight.transcript
    producer = get_producer()
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "transcript_uri": transcript_uri,
        "word_count": len(transcript.words),
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
