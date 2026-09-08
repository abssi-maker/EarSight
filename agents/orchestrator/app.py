"""
Orchestrator service.

- POST /upload      — accept multipart video, save to GCS, return {gcs_uri, upload_id}
- POST /jobs        — accept a job (GCS URI), publish to earsight.jobs, return job_id
- GET  /jobs/{id}   — return current job status
- GET  /health      — liveness probe
- GET  /            — service info

Job state: in-process dict (sufficient for hackathon; GCS persistence is Step 5).
Pipeline:
  earsight.jobs  → transcriber, framer (parallel)
  earsight.transcript + earsight.frames → both must arrive before earsight.gaps publish
"""

import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

load_dotenv()

from agents.shared.kafka_client import (
    consume_loop,
    get_consumer,
    get_producer,
    publish,
)
import agents.shared.gcs as gcs

# ── in-memory job store ────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

TOPIC_JOBS = "earsight.jobs"
TOPIC_TRANSCRIPT = "earsight.transcript"
TOPIC_FRAMES = "earsight.frames"
TOPIC_GAPS = "earsight.gaps"
TOPIC_CUES = "earsight.cues"
TOPIC_AUDIO_SEGMENTS = "earsight.audio-segments"
TOPIC_RESULTS = "earsight.results"

# Pattern to extract upload_id from a GCS URI produced by /upload
_UPLOAD_URI_RE = re.compile(r"gs://[^/]+/jobs/([^/]+)/video\.mp4$")


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


def _handle_cues(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    cues_uri = msg.get("cues_uri")
    with _jobs_lock:
        if job_id in _jobs:
            if cues_uri:
                try:
                    cue_list = gcs.download_json(cues_uri)
                    _jobs[job_id]["cues"] = cue_list
                except Exception as exc:
                    print(f"[orchestrator] could not fetch cues for {job_id}: {exc}")
            _jobs[job_id]["status"] = "synthesising"
            print(f"[orchestrator] cues arrived for job {job_id}")


def _handle_audio_segments(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "mixing"
            print(f"[orchestrator] audio segments arrived for job {job_id}")


def _handle_result(msg: dict) -> None:
    job_id = msg.get("job_id")
    if not job_id:
        return
    with _jobs_lock:
        if job_id in _jobs:
            raw_video = msg.get("result_video_url")
            raw_vtt = msg.get("vtt_url")
            # Convert gs:// URIs to signed HTTPS URLs so browsers can load them
            try:
                video_url = gcs.signed_url(raw_video) if raw_video and raw_video.startswith("gs://") else raw_video
            except Exception:
                video_url = raw_video
            try:
                vtt_url_val = gcs.signed_url(raw_vtt) if raw_vtt and raw_vtt.startswith("gs://") else raw_vtt
            except Exception:
                vtt_url_val = raw_vtt
            _jobs[job_id].update({
                "status": msg.get("status", "done"),
                "result_video_url": video_url,
                "vtt_url": vtt_url_val,
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

        def cues_thread():
            consumer = get_consumer("orchestrator-cues", [TOPIC_CUES])
            consume_loop(consumer, _handle_cues, producer, TOPIC_CUES)

        def audio_segments_thread():
            consumer = get_consumer("orchestrator-audio-segments", [TOPIC_AUDIO_SEGMENTS])
            consume_loop(consumer, _handle_audio_segments, producer, TOPIC_AUDIO_SEGMENTS)

        def results_thread():
            consumer = get_consumer("orchestrator-results", [TOPIC_RESULTS])
            consume_loop(consumer, _handle_result, producer, TOPIC_RESULTS)

        threading.Thread(target=transcript_thread, daemon=True).start()
        threading.Thread(target=frames_thread, daemon=True).start()
        threading.Thread(target=cues_thread, daemon=True).start()
        threading.Thread(target=audio_segments_thread, daemon=True).start()
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
    return {"service": "orchestrator", "version": "0.3.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Accept a multipart video upload, validate it, save to GCS.
    Returns {gcs_uri, upload_id}.
    Rejects non-mp4 or videos longer than 90 seconds.
    """
    if file.content_type not in ("video/mp4", "video/mpeg"):
        raise HTTPException(status_code=400, detail="Only MP4 video is accepted")

    upload_id = str(uuid.uuid4())
    bucket = os.environ.get("GCS_BUCKET", "")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name
        content = await file.read()
        tmp.write(content)

    # Validate duration with ffprobe
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
            capture_output=True, text=True, check=True,
        )
        duration = float(result.stdout.strip())
        if duration > 90:
            os.unlink(tmp_path)
            raise HTTPException(status_code=400, detail=f"Video is {duration:.1f}s; maximum is 90s")
    except HTTPException:
        raise
    except Exception as exc:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail=f"Could not read video duration: {exc}")

    gcs_uri = f"gs://{bucket}/jobs/{upload_id}/video.mp4"
    try:
        gcs.upload_from_file(tmp_path, gcs_uri, content_type="video/mp4")
    finally:
        os.unlink(tmp_path)

    return {"gcs_uri": gcs_uri, "upload_id": upload_id}


@app.post("/jobs", response_model=JobResponse, status_code=201)
def create_job(req: JobRequest):
    # If this URI was produced by /upload, reuse the embedded upload_id as job_id
    m = _UPLOAD_URI_RE.match(req.video_uri)
    job_id = m.group(1) if m else str(uuid.uuid4())
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
            # cue data (populated when earsight.cues arrives):
            "cues": None,
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
