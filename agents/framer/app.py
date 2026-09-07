"""
Framer Cloud Run service.

Consumes earsight.jobs → downloads video + transcript from GCS
→ finds silence gaps → extracts frames → uploads to GCS
→ publishes gap+frame manifest to earsight.frames.
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

from agents.shared.gcs import download_to_file, download_json, upload_from_file, upload_json, make_uri
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.framer.framer import find_gaps, extract_frames, get_video_duration
from agents.shared.models import Transcript, Word

TOPIC_IN = "earsight.jobs"
TOPIC_TRANSCRIPT = "earsight.transcript"
TOPIC_OUT = "earsight.frames"

# Buffer transcript messages so we can process when a job arrives.
# Framer listens to earsight.jobs (for the video URI) and earsight.transcript
# (for the word-level timing). We process whichever arrives second.
_pending_jobs: dict[str, dict] = {}       # job_id → {"video_uri": ...}
_pending_transcripts: dict[str, dict] = {}  # job_id → {"transcript_uri": ...}
_lock = threading.Lock()


def _maybe_process(job_id: str) -> None:
    """If we have both the job and the transcript, run the framer."""
    with _lock:
        job = _pending_jobs.get(job_id)
        transcript_msg = _pending_transcripts.get(job_id)
        if not job or not transcript_msg:
            return
        # Consume both — don't process twice
        del _pending_jobs[job_id]
        del _pending_transcripts[job_id]

    video_uri = job["video_uri"]
    transcript_uri = transcript_msg["transcript_uri"]
    print(f"[framer] job {job_id} — processing")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Download video and transcript
        video_path = os.path.join(tmpdir, "input.mp4")
        download_to_file(video_uri, video_path)
        transcript_data = download_json(transcript_uri)

        # Reconstruct transcript object
        words = [Word(**w) for w in transcript_data["words"]]
        transcript = Transcript(
            words=words,
            language=transcript_data.get("language", "en"),
            full_text=transcript_data.get("full_text", ""),
        )

        # Find gaps and extract frames
        duration = get_video_duration(video_path)
        gaps = find_gaps(transcript, duration)
        frames_dir = os.path.join(tmpdir, "frames")
        gaps = extract_frames(video_path, gaps, frames_dir)

        print(f"[framer] found {len(gaps)} gaps")

        # Upload each frame to GCS and build manifest
        frames_manifest = []
        for gap in gaps:
            frame_gcs_uri = None
            if gap.frame_path and Path(gap.frame_path).exists():
                frame_gcs_uri = make_uri(job_id, f"frames/{gap.gap_id}.jpg")
                upload_from_file(gap.frame_path, frame_gcs_uri, content_type="image/jpeg")

            frames_manifest.append({
                "gap_id": gap.gap_id,
                "start": gap.start,
                "end": gap.end,
                "duration": gap.duration,
                "frame_uri": frame_gcs_uri,
                "preceding_context": gap.preceding_context,
                "following_context": gap.following_context,
            })

        # Upload manifest to GCS
        manifest_data = {
            "job_id": job_id,
            "video_duration": duration,
            "gap_count": len(gaps),
            "gaps": frames_manifest,
        }
        manifest_uri = make_uri(job_id, "frames_manifest.json")
        upload_json(manifest_data, manifest_uri)
        print(f"[framer] manifest uploaded → {manifest_uri}")

    # Publish to earsight.frames
    producer = get_producer()
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "frames_manifest_uri": manifest_uri,
        "gap_count": len(gaps),
    }, key=job_id)
    print(f"[framer] published to {TOPIC_OUT}")


def _handle_job(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    with _lock:
        _pending_jobs[job_id] = {"video_uri": msg.get("video_uri", "")}
    print(f"[framer] received job {job_id} — waiting for transcript")
    _maybe_process(job_id)


def _handle_transcript(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    with _lock:
        _pending_transcripts[job_id] = {"transcript_uri": msg.get("transcript_uri", "")}
    print(f"[framer] received transcript for job {job_id}")
    _maybe_process(job_id)


def _start_consumers() -> None:
    try:
        producer = get_producer()
        # Consumer for jobs
        def jobs_thread():
            consumer = get_consumer("framer-jobs", [TOPIC_IN])
            consume_loop(consumer, _handle_job, producer, TOPIC_IN)

        # Consumer for transcripts
        def transcripts_thread():
            consumer = get_consumer("framer-transcripts", [TOPIC_TRANSCRIPT])
            consume_loop(consumer, _handle_transcript, producer, TOPIC_TRANSCRIPT)

        threading.Thread(target=jobs_thread, daemon=True).start()
        threading.Thread(target=transcripts_thread, daemon=True).start()
    except Exception as exc:
        print(f"[framer] consumer startup error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_consumers()
    yield


app = FastAPI(title="EarSight Framer", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "framer", "version": "0.2.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
