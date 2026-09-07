"""
Orchestrator service.

- POST /jobs        — accept a job (GCS URI), publish to earsight.jobs, return job_id
- GET  /jobs/{id}   — return current job status
- GET  /health      — liveness probe
- GET  /            — service info

Job state is kept in-process (dict) for the skeleton. Step 3 replaces with GCS persistence.
"""

import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

from agents.shared.kafka_client import (
    consume_loop,
    get_consumer,
    get_producer,
    publish,
)

# ── in-memory job store (replaced by GCS in Step 3) ──────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

TOPIC_JOBS = "earsight.jobs"
TOPIC_RESULTS = "earsight.results"


# ── background result consumer ────────────────────────────────────────────────
def _handle_result(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update({
                "status": msg.get("status", "done"),
                "result_video_url": msg.get("result_video_url"),
                "vtt_url": msg.get("vtt_url"),
                "error": msg.get("error"),
                "finished_at": time.time(),
            })
            print(f"[orchestrator] job {job_id} → {_jobs[job_id]['status']}")


def _start_result_consumer() -> None:
    try:
        consumer = get_consumer("orchestrator-results", [TOPIC_RESULTS])
        producer = get_producer()
        consume_loop(consumer, _handle_result, producer, TOPIC_RESULTS)
    except Exception as exc:
        print(f"[orchestrator] result consumer error: {exc}")


# ── FastAPI lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_start_result_consumer, daemon=True)
    t.start()
    yield


app = FastAPI(title="EarSight Orchestrator", lifespan=lifespan)


# ── Request / Response models ─────────────────────────────────────────────────
class JobRequest(BaseModel):
    video_uri: str          # GCS URI: gs://bucket/path/to/video.mp4
    label: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: str


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "orchestrator", "version": "0.1.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(req: JobRequest):
    job_id = str(uuid.uuid4())
    now = time.time()
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "video_uri": req.video_uri,
            "label": req.label,
            "status": "queued",
            "created_at": now,
            "result_video_url": None,
            "vtt_url": None,
            "error": None,
        }

    producer = get_producer()
    publish(producer, TOPIC_JOBS, {
        "job_id": job_id,
        "video_uri": req.video_uri,
    }, key=job_id)
    print(f"[orchestrator] published job {job_id} → {TOPIC_JOBS}")

    with _jobs_lock:
        _jobs[job_id]["status"] = "transcribing"

    return JobResponse(job_id=job_id, status="transcribing")


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
