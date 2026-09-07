"""
Mixer Cloud Run service.

Consumes earsight.audio-segments → downloads original video and audio clips from GCS →
runs ffmpeg mix with audio ducking → uploads described.mp4 + described.vtt to GCS →
publishes completion to earsight.results.
"""

import os
import tempfile
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from agents.shared.gcs import download_json, download_to_file, make_uri, upload_from_file
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.shared.models import Cue
from agents.mixer.mixer import mix

TOPIC_IN  = "earsight.audio-segments"
TOPIC_OUT = "earsight.results"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    segments = msg.get("segments", [])
    cues_uri = msg.get("cues_uri", "")
    print(f"[mixer] job {job_id} — {len(segments)} segments, cues: {cues_uri}")

    producer = get_producer()

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── Download original video from GCS ──────────────────────────────────
        video_gcs_uri = make_uri(job_id, "video.mp4")
        local_video = os.path.join(tmpdir, "video.mp4")
        try:
            download_to_file(video_gcs_uri, local_video)
        except Exception as e:
            print(f"[mixer] could not download video for job {job_id}: {e}")
            publish(producer, TOPIC_OUT, {
                "job_id": job_id,
                "status": "failed",
                "error": f"video download failed: {e}",
            }, key=job_id)
            return

        # ── Load full cue list from GCS (includes skip_reason etc.) ───────────
        cues_data = download_json(cues_uri)
        cues_raw = cues_data.get("cues", [])
        cues = [Cue(**{k: v for k, v in c.items() if k in Cue.__dataclass_fields__})
                for c in cues_raw]

        # ── Download each audio segment and attach path to its Cue ────────────
        # segments list is the "active" subset; match by cue_id
        seg_by_id = {s["cue_id"]: s for s in segments}
        for cue in cues:
            seg = seg_by_id.get(cue.cue_id)
            if seg and seg.get("audio_uri"):
                local_audio = os.path.join(tmpdir, f"{cue.cue_id}.wav")
                download_to_file(seg["audio_uri"], local_audio)
                cue.audio_path = local_audio

        # ── Mix ───────────────────────────────────────────────────────────────
        local_output_video = os.path.join(tmpdir, "described.mp4")
        local_output_vtt   = os.path.join(tmpdir, "described.vtt")

        mix(local_video, cues, local_output_video, local_output_vtt)

        # ── Upload outputs to GCS ─────────────────────────────────────────────
        video_out_uri = make_uri(job_id, "described.mp4")
        vtt_out_uri   = make_uri(job_id, "described.vtt")
        upload_from_file(local_output_video, video_out_uri, content_type="video/mp4")
        upload_from_file(local_output_vtt,   vtt_out_uri,   content_type="text/vtt")
        print(f"[mixer] ✓ uploaded {video_out_uri}")
        print(f"[mixer] ✓ uploaded {vtt_out_uri}")

    # ── Publish completion ────────────────────────────────────────────────────
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "status": "done",
        "result_video_url": video_out_uri,
        "vtt_url": vtt_out_uri,
    }, key=job_id)
    print(f"[mixer] job {job_id} → done, published to {TOPIC_OUT}")


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
    return {"service": "mixer", "version": "0.5.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
