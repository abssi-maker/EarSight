"""
Synthesiser Cloud Run service.

Consumes earsight.cues → downloads cues JSON from GCS →
synthesises each active cue with Gemini Flash TTS →
uploads audio clips to GCS → batch-publishes to earsight.audio-segments.
"""

import os
import tempfile
import threading
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from agents.shared.gcs import download_json, make_uri, upload_from_file
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.shared.models import Cue
from agents.synthesiser.synthesiser import synthesise_cue, _client as _tts_client

TOPIC_IN  = "earsight.cues"
TOPIC_OUT = "earsight.audio-segments"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    cues_uri = msg.get("cues_uri", "")
    print(f"[synthesiser] job {job_id} — cues: {cues_uri}")

    # ── Load cues from GCS ────────────────────────────────────────────────────
    cues_data = download_json(cues_uri)
    cues_raw = cues_data.get("cues", [])
    cues = [Cue(**{k: v for k, v in c.items() if k in Cue.__dataclass_fields__})
            for c in cues_raw]

    active_cues = [c for c in cues if c.text is not None]
    print(f"[synthesiser] {len(active_cues)} active cues to synthesise")

    if not active_cues:
        # No narration — pass through immediately
        _publish_segments(job_id, [], get_producer())
        return

    # ── Synthesise each cue, upload clip to GCS ───────────────────────────────
    client = _tts_client()
    segments = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for cue in active_cues:
            audio_path = synthesise_cue(cue, tmpdir, client)
            if audio_path is None:
                continue
            # Upload to GCS: jobs/{job_id}/audio/{cue_id}.wav
            gcs_audio_uri = make_uri(job_id, f"audio/{cue.cue_id}.wav")
            upload_from_file(audio_path, gcs_audio_uri, content_type="audio/wav")
            cue.audio_path = gcs_audio_uri
            segments.append({
                "cue_id": cue.cue_id,
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                "audio_uri": gcs_audio_uri,
            })
            print(f"[synthesiser] {cue.cue_id} → {gcs_audio_uri}")

    _publish_segments(job_id, segments, get_producer())


def _publish_segments(job_id: str, segments: list, producer) -> None:
    """Batch-publish all segments for a job to earsight.audio-segments."""
    cues_uri = make_uri(job_id, "cues.json")  # reference back so mixer can load full cue list
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "segments": segments,
        "cues_uri": cues_uri,
        "segment_count": len(segments),
    }, key=job_id)
    print(f"[synthesiser] published {len(segments)} segments → {TOPIC_OUT}")


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
    return {"service": "synthesiser", "version": "0.5.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
