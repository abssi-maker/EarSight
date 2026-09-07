"""
Orchestrator service.

- POST /jobs        — accept a job (GCS URI), publish to earsight.jobs, return job_id
- GET  /jobs/{id}   — return current job status
- GET  /health      — liveness probe
- GET  /            — service info

Job state: in-process dict (sufficient for hackathon; GCS persistence is Step 5).
Pipeline:
  earsight.jobs  → transcriber, framer (parallel)
  earsight.transcript + earsight.frames → both must arrive before earsight.gaps publish
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

# ── in-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

TOPIC_JOBS = "earsight.jobs"
TOPIC_TRANSCRIPT = "earsight.transcript"
TOPIC_FRAMES = "earsight.frames"
TOPIC_GAPS = "earsight.gaps"
TOPIC_RESULTS = "earsight.results"


def _try_publish_gaps(job_id: str) -> None:
    """Publish to earsight.gaps if both transcript and frames have arrived."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        transcript_uri = job.get("transcript_uri")
        frames_manifest_uri = job.get("frames_manifest_uri")
        gaps_published = job.get("gaps_published", False)
        if not transcript_uri or not frames_manifest_uri or gaps_published:
            return
        # Mark before releasing lock to avoid double-publish
        job["gaps_published"] = True
        job["status"] = "describing"

    producer = get_producer()
    publish(producer, TOPIC_GAPS, {
        "job_id": job_id,
        "transcript_uri": transcript_uri,
        "frames_manifest_uri": frames_manifest_uri,
    }, key=job_id)
    print(f"[orchestrator] job {job_id} → {TOPIC_GAPS} (both transcript+frames ready)")


# ── background consumers ──────────────────────────────────────────────────────
def _handle_transcript(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["transcript_uri"] = msg.get("transcript_uri")
            _jobs[job_id]["transcript_word_count"] = msg.get("word_count", 0)
            if _jobs[job_id]["status"] == "transcribing":
                _jobs[job_id]["status"] = "framing"
            print(f"[orchestrator] transcript arrived for job {job_id}")
    _try_publish_gaps(job_id)


def _handle_frames(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["frames_manifest_uri"] = msg.get("frames_manifest_uri")
            _jobs[job_id]["gap_count"] = msg.get("gap_count", 0)
            print(f"[orchestrator] frames arrived for job {job_id} ({msg.get('gap_count')} gaps)")
    _try_publish_gaps(job_id)


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


def _start_consumers() -> None:
    try:
        producer = get_producer()

        def transcript_thread():
            consumer = get_consumer("orchestrator-transcripts", [TOPIC_TRANSCRIPT])
            consume_loop(consumer, _handle_transcript, producer, TOPIC_TRANSCRIPT)

        def frames_thread():
            consumer = get_consumer("orchestrator-frames", [TOPIC_FRAMES])
            consume_loop(consumer, _handle_frames, producer, TOPIC_FRAMES)

        def results_thread():
            consumer = get_consumer("orchestrator-results", [TOPIC_RESULTS])
            consume_loop(consumer, _handle_result, producer, TOPIC_RESULTS)

        threading.Thread(target=transcript_thread, daemon=True).start()
        threading.Thread(target=frames_thread, daemon=True).start()
        threading.Thread(target=results_thread, daemon=True).start()
    except Exception as exc:
        print(f"[orchestrator] consumer startup error: {exc}")


# ── FastAPI lifespan ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_consumers()
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
    return {"service": "orchestrator", "version": "0.2.0"}


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
            "status": "transcribing",
            "created_at": now,
            # filled in as completions arrive:
            "transcript_uri": None,
            "frames_manifest_uri": None,
            "transcript_word_count": None,
            "gap_count": None,
            "gaps_published": False,
            # final outputs:
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

    return JobResponse(job_id=job_id, status="transcribing")


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
