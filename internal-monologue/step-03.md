# Step 03 — Real transcription + gap map over Kafka

**Date:** 2025-09-07  
**Status:** Implemented, integration test passing

---

## What was built

Replaced the transcriber and framer service stubs with real implementations
that run the Step 1 processing logic as Cloud Run services communicating over Kafka.

### `agents/shared/gcs.py` (new)
Thin wrapper around `google-cloud-storage`:
- `download_to_file(uri, dest)` — stream GCS object to local temp file
- `upload_from_file(local, uri)` — upload local file to GCS
- `upload_json(data, uri)` / `download_json(uri)` — JSON convenience methods
- `make_uri(job_id, filename)` — canonical `gs://BUCKET/jobs/{job_id}/{filename}`

### `agents/transcriber/app.py` (rewritten from stub)
Consumer of `earsight.jobs`:
1. Downloads video from GCS to a temp directory
2. Calls `transcribe()` from `transcriber.py` (Gemini audio → word timestamps)
3. Uploads `transcript.json` to `gs://BUCKET/jobs/{job_id}/transcript.json`
4. Publishes `{job_id, transcript_uri, word_count}` to `earsight.transcript`

### `agents/framer/app.py` (rewritten from stub)
Dual consumer of `earsight.jobs` (video URI) and `earsight.transcript` (word timing):
- Buffers whichever arrives first; processes when both are in hand
- Calls `find_gaps()` → `extract_frames()` from `framer.py`
- Uploads frame JPEGs and `frames_manifest.json` to GCS
- Publishes `{job_id, frames_manifest_uri, gap_count}` to `earsight.frames`

### `agents/orchestrator/app.py` (updated)
Added three background consumers (transcript, frames, results) — previously only results.
Implemented `_try_publish_gaps()`:
- Called whenever transcript or frames arrive
- Publishes to `earsight.gaps` **only** when both have arrived (barrier pattern)
- Uses a `gaps_published` flag in the job dict (guarded by lock) to prevent double-publish
- Sets job status → `"describing"` on publish

`GET /jobs/{id}` now returns rich status with `transcript_uri`, `frames_manifest_uri`,
`transcript_word_count`, `gap_count`, `gaps_published`, and `result_video_url` / `vtt_url`.

---

## Design decisions

**Framer waits for transcript**: The framer needs word timings to calculate silence
gaps. It can't run on the video alone. It subscribes to both `earsight.jobs` and
`earsight.transcript`, buffering whichever arrives first in an in-memory dict,
processing immediately when both are present. This is correct for the current
in-process service model; a persistent store would be needed for multi-instance
deployments.

**Orchestrator barrier**: The describer needs both the transcript (for context) and
the frames (for visual input). The orchestrator acts as a fan-in barrier — it waits
for both `earsight.transcript` and `earsight.frames` before publishing to
`earsight.gaps`. This is preferable to having the describer buffer both streams
because the orchestrator already tracks job state.

**GCS bucket**: `gs://earsight-media` uses ADC (Application Default Credentials)
in Cloud Run; locally, uses `GOOGLE_APPLICATION_CREDENTIALS` or `gcloud auth`.
The bucket name is injected via `GCS_BUCKET` env var / Secret Manager secret.

---

## Integration test

`scripts/test_step3.py --use-cached` runs the transcriber + framer logic end-to-end
against `demo/sample.mp4` using the Step 1 cached transcript.

Output:
```
STEP 3 INTEGRATION TEST
60.00s video, 29 words, 10 silence gaps detected
10/10 frames extracted
Manifest shape valid (10 gaps)
ALL CHECKS PASSED ✓
  Words transcribed: 29
  Gaps detected:     10
  Max word budget:   46w
```

All collision assertions pass (no gap overlaps any dialogue word).

---

## What's next (Step 4)

Implement the describer service consuming `earsight.gaps`:
- Two-pass Gemini call (context + copy writing)
- Word-budget assertion before publish
- Collision guard before publish
- Established-facts memory per job (GCS-backed)
