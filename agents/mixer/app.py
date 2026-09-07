"""Mixer service stub — consumes earsight.audio-segments, logs, produces to earsight.results."""
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
load_dotenv()

from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish

TOPIC_IN  = "earsight.audio-segments"
TOPIC_OUT = "earsight.results"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    print(f"[mixer] received audio-segments for job {job_id} — stub, no-op")
    producer = get_producer()
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "status": "done",
        "result_video_url": None,
        "vtt_url": None,
    }, key=job_id)


def _start_consumer() -> None:
    try:
        consumer = get_consumer("mixer", [TOPIC_IN])
        producer = get_producer()
        consume_loop(consumer, _handle, producer, TOPIC_IN)
    except Exception as exc:
        print(f"[mixer] consumer error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_start_consumer, daemon=True)
    t.start()
    yield


app = FastAPI(title="EarSight Mixer", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "mixer", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
