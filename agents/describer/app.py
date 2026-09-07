"""
Describer Cloud Run service.

Consumes earsight.gaps → loads transcript + frames manifest from GCS →
runs two-pass describer (salience + copy) → asserts constraints →
uploads cues JSON to GCS → publishes to earsight.cues.
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

from agents.shared.gcs import download_json, download_to_file, make_uri, upload_json
from agents.shared.kafka_client import consume_loop, get_consumer, get_producer, publish
from agents.shared.models import Gap, Transcript, Word
from agents.shared.budget import assert_fits
from agents.shared.collision import assert_no_collision, CollisionError
from agents.describer.describer import describe_gaps
from agents.describer import memory as facts_memory

TOPIC_IN = "earsight.gaps"
TOPIC_OUT = "earsight.cues"


def _handle(msg: dict) -> None:
    job_id = msg.get("job_id", "?")
    transcript_uri = msg.get("transcript_uri", "")
    frames_manifest_uri = msg.get("frames_manifest_uri", "")

    print(f"[describer] job {job_id} — transcript: {transcript_uri}, frames: {frames_manifest_uri}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # ── Load transcript ────────────────────────────────────────────────────
        transcript_data = download_json(transcript_uri)
        words = [Word(**w) for w in transcript_data.get("words", [])]
        transcript = Transcript(
            words=words,
            language=transcript_data.get("language", "en"),
            full_text=transcript_data.get("full_text", ""),
        )
        print(f"[describer] transcript loaded ({len(words)} words)")

        # ── Load frames manifest → gaps ────────────────────────────────────────
        frames_data = download_json(frames_manifest_uri)
        gaps_raw = frames_data.get("gaps", [])

        # Download frame images locally for the copy-writing pass
        gaps: list[Gap] = []
        for g in gaps_raw:
            frame_path = None
            frame_uri = g.get("frame_uri")
            if frame_uri:
                local = os.path.join(tmpdir, f"{g['gap_id']}.jpg")
                try:
                    download_to_file(frame_uri, local)
                    frame_path = local
                except Exception as e:
                    print(f"[describer] could not download frame for {g['gap_id']}: {e}")

            gaps.append(Gap(
                gap_id=g["gap_id"],
                start=g["start"],
                end=g["end"],
                duration=g["duration"],
                frame_path=frame_path,
                preceding_context=g.get("preceding_context", ""),
                following_context=g.get("following_context", ""),
            ))

        print(f"[describer] {len(gaps)} gaps loaded")

        # ── Load established facts (GCS-backed) ────────────────────────────────
        established_facts = facts_memory.load(job_id)

        # ── Run two-pass describer ─────────────────────────────────────────────
        cues = describe_gaps(transcript, gaps, established_facts)

        # ── Hard-assert all constraints before publishing ─────────────────────
        active_cues = [c for c in cues if c.text is not None]
        for cue in active_cues:
            # Budget assertion
            gap = next((g for g in gaps if g.gap_id == cue.gap_id), None)
            if gap:
                assert_fits(cue.text, gap.duration, cue.gap_id)

        # Collision assertion — raises CollisionError if any cue overlaps dialogue
        cue_dicts = [{"start": c.start, "end": c.end, "text": c.text} for c in active_cues]
        assert_no_collision(cue_dicts, transcript.dialogue_spans())

        # ── Persist updated established facts ─────────────────────────────────
        new_facts = [c.text for c in active_cues]
        if new_facts:
            facts_memory.save(job_id, established_facts + new_facts)

    # ── Serialise cues to GCS ──────────────────────────────────────────────────
    cues_data = [
        {
            "cue_id": c.cue_id,
            "start": c.start,
            "end": c.end,
            "text": c.text,
            "word_count": c.word_count,
            "gap_id": c.gap_id,
            "skip_reason": c.skip_reason,
        }
        for c in cues
    ]
    cues_uri = make_uri(job_id, "cues.json")
    upload_json({"job_id": job_id, "cues": cues_data}, cues_uri)
    print(f"[describer] cues uploaded → {cues_uri} "
          f"({len(active_cues)} active / {len(cues)} total)")

    # ── Publish to earsight.cues ───────────────────────────────────────────────
    producer = get_producer()
    publish(producer, TOPIC_OUT, {
        "job_id": job_id,
        "cues_uri": cues_uri,
        "cue_count": len(active_cues),
        "total_gaps": len(cues),
    }, key=job_id)
    print(f"[describer] published to {TOPIC_OUT}")


def _start_consumer() -> None:
    try:
        consumer = get_consumer("describer", [TOPIC_IN])
        producer = get_producer()
        consume_loop(consumer, _handle, producer, TOPIC_IN)
    except Exception as exc:
        print(f"[describer] consumer error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_start_consumer, daemon=True)
    t.start()
    yield


app = FastAPI(title="EarSight Describer", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "describer", "version": "0.4.0"}


@app.get("/health")
def health():
    return {"status": "ok"}
