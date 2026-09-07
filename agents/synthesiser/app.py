"""Synthesiser service stub — consumes earsight.cues, logs, produces to earsight.audio-segments."""
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
load_dotenv()

from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish

TOPIC_IN  = "earsight.cues"
TOPIC_OUT = "earsight.audio-segments"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    print(f"[synthesiser] received cues for job {job_id} — stub, no-op")
    producer = get_producer()
    publish(producer, TOPIC_OUT, {"job_id": job_id, "segments": [], "status": "stub"}, key=job_id)


def _start_consumer() -> None:
    try:
        consumer = get_consumer("synthesiser", [TOPIC_IN])
        producer = get_producer()
        consume_loop(consumer, _handle, producer, TOPIC_IN)
    except Exception as exc:
        print(f"[synthesiser] consumer error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_start_consumer, daemon=True)
    t.start()
    yield


app = FastAPI(title="EarSight Synthesiser", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "synthesiser", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
