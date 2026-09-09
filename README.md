# EarSight

**Drop a video. Hear everything.**

EarSight is a distributed AI agent crew that produces an audio description track for
short videos. It finds silences between dialogue, decides what is worth narrating in
each gap, synthesises speech, and mixes it into the original audio — returning a
described `.mp4` and a WebVTT cue sheet.

---

## Built with IBM Bob

This project was built step-by-step using **[IBM Bob](https://www.ibm.com/products/bob)**
as the sole AI engineering assistant. Every architectural decision, every file, every
commit was authored in a Bob session following the §6 stop-and-wait workflow: plan
first in Plan mode, implement one step per session, stop and wait for approval, commit
only after approval.

### Verifiable evidence

| Artefact | Count | Location |
|---|---|---|
| Commits with `Built-with: IBM-Bob` trailer | 11 of 12 | `git log` |
| Commits with `Co-authored-by: IBM Bob` trailer | 10 of 12 | `git log` |
| Bob sessions logged (with timestamps + session IDs) | 21 | [`docs/bob/session-log.md`](docs/bob/session-log.md) |
| Step monologues | 6 | [`internal-monologue/`](internal-monologue/) |
| Workflow rules in `.bob/rules/` | 5 | [`.bob/rules/`](.bob/rules/) |
| Build plan (authored in Plan mode, pre-code) | 1 | [`plans/00-build-plan.md`](plans/00-build-plan.md) |

The only commit with neither trailer is `2146a91` "Initial commit" — the empty repo
scaffold created before Bob was engaged. `d69def3` carries `Built-with` but not
`Co-authored-by`; it was deliberately not rewritten after push.

Run these yourself:

```bash
# Total commits
git log --format='%H %s' | wc -l

# Commits carrying the IBM Bob trailer
git log --format='%(trailers:key=Built-with)' | grep -c IBM-Bob
```

### .bob/rules/ — the §6 workflow encoded

| Rule file | Purpose |
|---|---|
| `01-report-format.md` | Every step ends with the 5-line STEP N report |
| `02-stop-and-wait.md` | One step per session, stop and wait for approval |
| `03-commit-discipline.md` | One commit per approved step, push immediately |
| `04-runtime-dependency-ban.md` | Google Cloud AI only — grep verified in CI |
| `05-screenshot-requirement.md` | Every UI step captures a Playwright screenshot |

---

## Architecture

6 services, 7 Confluent Kafka topics.

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

### Kafka topics (7)

| Topic | Producer | Consumer |
|---|---|---|
| `earsight.jobs` | orchestrator | transcriber, framer |
| `earsight.transcript` | transcriber | describer |
| `earsight.frames` | framer | describer |
| `earsight.gaps` | describer (gap analysis) | describer (copy writer) |
| `earsight.cues` | describer (copy writer) | synthesiser |
| `earsight.audio-segments` | synthesiser | mixer |
| `earsight.results` | mixer | orchestrator |

Dead-letter topic: `earsight.dead-letter` — unroutable or poison-pill messages land here.

---

## Confluent Kafka

Confluent Cloud is used as the managed Kafka backbone. All seven topics are provisioned
on a Confluent Cloud cluster; producer/consumer code ships in every agent service — this
is not mocked.

**Producer config (all agents):**
```python
{'acks': 'all', 'enable.idempotence': True}
```

**Consumer pattern:**
Each agent service runs a background thread consuming its input topic, auto-commits
offsets only after successful processing. Unrecoverable errors are re-published to
`earsight.dead-letter`.

Agent-shared code: [`agents/shared/kafka_client.py`](agents/shared/kafka_client.py)

---

## Gemini + Google ADK

| Component | Model / API |
|---|---|
| Transcription | `gemini-2.0-flash` audio understanding via `google-generativeai` upload |
| Salience scoring | `gemini-2.0-flash` — `google-adk` `LlmAgent` with `Runner` |
| Copy writing | `gemini-2.0-flash` — native ADK `LlmAgent`; `check_budget` and `check_collision` as forced function tools (`tool_config` mode=ANY) |
| Video understanding | VideoMetadata offsets in the copy pass for gap-aligned frame context |
| Speech synthesis | `gemini-2.5-flash-preview-tts` — audio-tag steering, SynthID watermarking |

The describer is the intellectual centre of the system. Two-pass design: a **context
pass** ranks gaps by salience (what would a viewer lose?), then a **copy pass** writes
word-budget-constrained narration for each prioritised gap. Both passes run as native
ADK `LlmAgent`s.

---

## Hard constraints

- **No cue overlaps dialogue** — `CollisionError` raised in [`agents/shared/collision.py`](agents/shared/collision.py) before any cue is published
- **Word budget** — `floor(gap_seconds × 2.75)`, hard ceiling; cues that exceed budget are dropped, not truncated
- **Input cap** — 90 seconds maximum, enforced in upload handler and pipeline entry point
- **Google Cloud AI only** — no OpenAI / Anthropic / AWS / Microsoft AI anywhere in the dependency tree; verified on every push by CI

---

## Local setup

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
python scripts/validate_cues.py --vtt output/described.vtt --transcript output/transcript.json
```

---

## Running services locally

Each Python service is a FastAPI app:

```bash
uvicorn agents.orchestrator.app:app --port 8000 --reload
uvicorn agents.transcriber.app:app  --port 8001 --reload
uvicorn agents.framer.app:app       --port 8002 --reload
uvicorn agents.describer.app:app    --port 8003 --reload
uvicorn agents.synthesiser.app:app  --port 8004 --reload
uvicorn agents.mixer.app:app        --port 8005 --reload
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

## Live deployment

Seven Cloud Run services are deployed and running in project **earsight-prod-2026**,
region **us-central1**. No end-to-end pipeline run has been verified yet.

| Service | URL |
|---|---|
| orchestrator | https://earsight-orchestrator-131214399019.us-central1.run.app |
| transcriber  | https://earsight-transcriber-131214399019.us-central1.run.app |
| framer       | https://earsight-framer-131214399019.us-central1.run.app |
| describer    | https://earsight-describer-131214399019.us-central1.run.app |
| synthesiser  | https://earsight-synthesiser-131214399019.us-central1.run.app |
| mixer        | https://earsight-mixer-131214399019.us-central1.run.app |
| frontend     | https://earsight-frontend-131214399019.us-central1.run.app |

---

## Deploy to Google Cloud Run

`deploy/cloudbuild.yaml` uses a `_TAG` substitution (defaults to `latest`) so manual
`gcloud builds submit` calls work without `$COMMIT_SHA`. A push trigger can override
with `--substitutions _TAG=$COMMIT_SHA`.

```bash
gcloud config set project YOUR_PROJECT_ID

# Store secrets (one-time)
echo -n "your-confluent-bootstrap" | gcloud secrets create CONFLUENT_BOOTSTRAP_SERVERS --data-file=-
echo -n "your-api-key"             | gcloud secrets create CONFLUENT_API_KEY --data-file=-
echo -n "your-api-secret"          | gcloud secrets create CONFLUENT_API_SECRET --data-file=-
echo -n "your-gemini-key"          | gcloud secrets create GOOGLE_API_KEY --data-file=-
echo -n "earsight-media"           | gcloud secrets create GCS_BUCKET --data-file=-

# Build and deploy all services (manual — tags images :latest)
gcloud builds submit --config deploy/cloudbuild.yaml

# From a trigger — tags images with the commit SHA
# --substitutions _TAG=$COMMIT_SHA
```

---

## Known limitations

- **Orchestrator job store is in-memory and single-instance** — jobs are lost if the
  orchestrator container restarts. A persistent store (Firestore, Cloud SQL) was not
  adopted within the hackathon window.
- **Vertex AI Agent Engine deployment was not adopted** — agents run as standard Cloud
  Run services rather than managed Agent Engine instances. The ADK `LlmAgent` pattern
  is in place; migrating to Agent Engine is a deploy-target change, not a code change.
- **Step 7 resilience work was descoped** — partial-failure handling (mixer accepting
  incomplete cue sets, per-agent deadline timeouts) was planned in Step 7 of the build
  plan but deliberately skipped to focus budget on the evidence trail (Step 8). The
  system is not fault-tolerant at the agent level; a failed agent will stall the job.

---

## Credits

Demo footage: *Elephants Dream* (2006), directed by Bassam Kurdali,
Blender Foundation. Source: https://archive.org/details/ElephantsDream
Licensed under [CC BY 3.0 US](https://creativecommons.org/licenses/by/3.0/us/).
Modified: EarSight mixes audio description narration into the original
soundtrack. The picture is unaltered.

EarSight's own source code is MIT licensed — see LICENSE.
