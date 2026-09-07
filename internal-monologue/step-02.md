# Step 02 — Deployment skeleton + Confluent wiring

**Date:** 2025-09-07  
**Session:** step-02  
**Status:** complete

---

## What I built

Six FastAPI services plus a Next.js 14 frontend skeleton, all wired to Confluent Kafka
stubs. The orchestrator is the only real logic — it accepts `POST /jobs`, publishes
to `earsight.jobs`, and listens on `earsight.results` to update job state. Every other
Python service is a stub: consume input topic, log, produce to output topic.

The Dockerfiles mirror the service boundary exactly. `cloudbuild.yaml` builds all
seven images and deploys to Cloud Run in sequence, pulling secrets from Google Secret
Manager — never environment variables in the build config.

## Decisions made

**`kafka_client.py` is a thin wrapper, not an abstraction.** It exposes `get_producer()`,
`get_consumer()`, `publish()`, `consume_loop()`, and `dead_letter()`. Services call these
directly. There is no "framework" here — confluent-kafka objects are returned as-is.
This makes Step 3 easy: swap handler implementations without touching infrastructure.

**Orchestrator keeps job state in-process dict for the skeleton.** The plan says
"replace with GCS persistence in Step 3" — so I didn't build that now. Minimal change
that makes the step pass.

**No `npm install` yet.** The frontend `package.json` exists; `node_modules/` is
gitignored. The frontend builds in Docker using `npm ci`. Local dev requires a
`cd frontend && npm install` which is in the README. This is correct — `node_modules`
should never be committed.

**`consume_loop()` runs in a daemon thread.** FastAPI's lifespan context starts the
consumer thread on startup. If the Kafka connection isn't configured (local dev without
`.env`), the thread catches the exception and logs it — the HTTP service still starts
and answers `/health`.

## What I'm uncertain about

- **Confluent topic provisioning** — the plan mentions provisioning via Confluent MCP or
  manually. I haven't created the topics yet (no Confluent credentials in this context).
  The `cloudbuild.yaml` assumes topics already exist. Alami will need to provision them
  before Step 3 wires real traffic.
- **Cloud Run service URLs** — the `cloudbuild.yaml` deploy step for the frontend passes
  `_ORCHESTRATOR_URL` as a substitution that defaults to empty. After first deploy,
  Alami will need to re-deploy frontend with the actual orchestrator URL, or set it
  via `gcloud run services update`.

## What the smoke test would look like (when Confluent creds are set)

```bash
# Start orchestrator locally
uvicorn agents.orchestrator.app:app --port 8000

# Post a job
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"video_uri": "gs://earsight-media/sample.mp4"}'
# → {"job_id": "...", "status": "transcribing"}

# Each downstream service stub should log "received job <id>"
# Mixer stub publishes to earsight.results → orchestrator updates status to "done"
curl http://localhost:8000/jobs/<job_id>
# → {..., "status": "done"}
```

## Next step

Step 3 — replace transcriber and framer stubs with the real implementations from
Step 1, upload `demo/sample.mp4` to GCS, and wire `GET /jobs/{id}` with GCS persistence.
