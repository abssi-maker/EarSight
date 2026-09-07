# EarSight

**Drop a video. Hear everything.**

EarSight is a distributed AI agent crew that produces an audio description track for
short videos. It finds silences between dialogue, decides what is worth narrating in
each gap, synthesises speech, and mixes it into the original audio — returning a
described `.mp4` and a WebVTT cue sheet.

> Built with [IBM Bob](https://www.ibm.com/products/bob) — see [§ Built with IBM Bob](#built-with-ibm-bob)

---

## Architecture

```
[frontend]  →  upload  →  [orchestrator]
                               │
                    ┌──────────┼──────────┐
                    ▼          ▼          ▼
             [transcriber] [framer]  [describer]
                    │          │          │
                    └──────────┴──────────┘
                               │
                          [synthesiser]
                               │
                           [mixer]
                               │
                          result → frontend
```

Every inter-service handoff crosses a **Confluent Kafka** topic.
Six services on **Google Cloud Run**; media artefacts in **Google Cloud Storage**.

### Kafka topics

| Topic | Producer | Consumer |
|---|---|---|
| `earsight.jobs` | orchestrator | transcriber, framer |
| `earsight.transcript` | transcriber | describer |
| `earsight.frames` | framer | describer |
| `earsight.gaps` | describer (gap analysis) | describer (copy writer) |
| `earsight.cues` | describer (copy writer) | synthesiser |
| `earsight.audio-segments` | synthesiser | mixer |
| `earsight.results` | mixer | orchestrator |

---

## Local setup (one-command)

```bash
# 1. Clone and enter
git clone https://github.com/<your-org>/EarSight.git
cd EarSight

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in GOOGLE_API_KEY, CONFLUENT_*, GCS_BUCKET

# 3. Install Python deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Run the local monolithic pipeline on the demo clip
python scripts/pipeline.py --input demo/sample.mp4 --output output/

# 5. Validate — must exit 0
python scripts/validate_cues.py output/described.vtt demo/sample.mp4
```

---

## Running services locally

Each Python service is a FastAPI app. Start them individually:

```bash
# Orchestrator (port 8000)
uvicorn agents.orchestrator.app:app --port 8000 --reload

# Transcriber (port 8001)
uvicorn agents.transcriber.app:app --port 8001 --reload

# Framer (port 8002)
uvicorn agents.framer.app:app --port 8002 --reload

# Describer (port 8003)
uvicorn agents.describer.app:app --port 8003 --reload

# Synthesiser (port 8004)
uvicorn agents.synthesiser.app:app --port 8004 --reload

# Mixer (port 8005)
uvicorn agents.mixer.app:app --port 8005 --reload
```

Frontend:
```bash
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Submit a test job:
```bash
curl -X POST http://localhost:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"video_uri": "gs://your-bucket/sample.mp4"}'
```

---

## Deploy to Google Cloud Run

```bash
# Set your GCP project
gcloud config set project YOUR_PROJECT_ID

# Store secrets in Secret Manager (one-time setup)
echo -n "your-confluent-bootstrap" | gcloud secrets create CONFLUENT_BOOTSTRAP_SERVERS --data-file=-
echo -n "your-api-key"             | gcloud secrets create CONFLUENT_API_KEY --data-file=-
echo -n "your-api-secret"          | gcloud secrets create CONFLUENT_API_SECRET --data-file=-
echo -n "your-gemini-key"          | gcloud secrets create GOOGLE_API_KEY --data-file=-
echo -n "earsight-media"           | gcloud secrets create GCS_BUCKET --data-file=-

# Trigger Cloud Build (builds all images, deploys all services)
gcloud builds submit --config deploy/cloudbuild.yaml \
  --substitutions _ORCHESTRATOR_URL=$(gcloud run services describe earsight-orchestrator \
    --region us-central1 --format 'value(status.url)')
```

---

## Hard constraints

- **No cue overlaps dialogue** — `CollisionError` raised before any cue is published
- **Word budget** — `floor(gap_seconds × 2.75)`, hard ceiling
- **Input cap** — 90 seconds maximum
- **Google Cloud AI only** — no OpenAI / Anthropic / AWS / Microsoft AI

---

## Built with IBM Bob

This project was built step-by-step using **IBM Bob** as the sole AI engineering
assistant, following the §6 workflow: plan first, implement one step per session,
stop-and-wait for approval, commit only after approval.

Evidence trail:
- [`plans/00-build-plan.md`](plans/00-build-plan.md) — full build plan in Plan mode
- [`internal-monologue/`](internal-monologue/) — one entry per approved step
- [`docs/steps/`](docs/steps/) — screenshot per step
- [`docs/bob/session-log.md`](docs/bob/session-log.md) — session log

Every commit carries `Built-with: IBM-Bob` in its trailer.
