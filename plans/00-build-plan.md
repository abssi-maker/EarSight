# EARSIGHT — Build Plan `00`

**Generated:** 2025-09-06 (Plan mode, pre-implementation)  
**Author:** IBM Bob  
**Status:** AWAITING APPROVAL

---

## Overview

EARSIGHT is a distributed agent crew that produces an audio description track for
a short video. A user drops in a video; the system finds the silences between
dialogue, decides what's worth narrating in each gap, generates speech, mixes it
into the original audio, and returns a described video plus a WebVTT cue sheet.

**Stack:**
- **Agent services:** Python 3.11 + `google-adk` + FastAPI, one container per agent
- **LLM / speech:** Gemini via Vertex AI (`google-adk`, `google-genai`, `google-cloud-aiplatform`)
- **Messaging:** Confluent Kafka (Confluent Cloud) — genuine producer/consumer, load-bearing
- **Frontend:** Next.js 14 / TypeScript, served as a Cloud Run service
- **Infrastructure:** Google Cloud Run (one service per agent + frontend), Cloud Storage for media
- **Containerisation:** Docker, Cloud Build for CI push-to-deploy

**Architecture — 6 services:**

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

Every inter-service handoff crosses a Confluent Kafka topic. The orchestrator is
the only service the frontend talks to directly (REST). All agent work is
fire-and-forget over topics; the frontend polls the orchestrator for status.

**Topics (one per pipeline stage boundary):**

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

## Steps

### Step 1 — End-to-end proof of concept (local, monolithic)

**Status:** `[x] done — 2025-09-07`

**Intent**  
Prove the core constraint works before building infrastructure. One Python script
takes a video file, extracts dialogue silences, generates description copy for each
gap that fits the word budget, synthesises speech, and mixes it into the original
audio. Output: a described `.mp4` and a `.vtt` file. No services, no queues, no
UI — just the proof that the fundamental pipeline is sound.

This is the step where the word-budget constraint gets asserted in code. If the
silence detection, Gemini calls, TTS, and ffmpeg mixing all work end-to-end on the
demo clip, every subsequent step is integration work, not discovery.

**Expected outcomes**
- `demo/sample.mp4` committed (≤ 90 s clip)
- `scripts/pipeline.py` produces `output/described.mp4` and `output/described.vtt`
  when run against the demo clip
- The VTT cue sheet has no cue that overlaps a dialogue region (asserted by a
  `scripts/validate_cues.py` script that returns exit code 1 on collision)
- Playing `described.mp4` with eyes closed is intelligible

**Todo list**
1. Commit `demo/sample.mp4` (a short public-domain clip, ≤ 90 s)
2. Set up Python project root: `pyproject.toml`, `requirements.txt`, `.python-version`
3. `agents/transcriber/transcriber.py` — ffmpeg-extracted audio → Gemini speech-to-text
   (via `google-generativeai` audio upload) → JSON transcript with word-level timestamps
4. `agents/framer/framer.py` — extract one representative frame per silence gap using
   `ffmpeg` + `opencv-python` or `Pillow`
5. `agents/describer/describer.py` — silence detection from transcript, word-budget
   calculation (gap_seconds × 2.75), Gemini multimodal call (frame + context) → cue copy;
   the collision guard goes here as an assertion that raises before any cue is written
6. `agents/synthesiser/synthesiser.py` — Gemini Flash TTS (`gemini-2.5-flash-preview-tts`
   via `google-genai`) per cue — same SDK as the rest of the pipeline, no extra dependency
7. `agents/mixer/mixer.py` — ffmpeg to duck original audio under narration and mux
8. `scripts/pipeline.py` — sequential orchestration of the above modules
9. `scripts/validate_cues.py` — parse VTT, assert zero collision with transcript timings
10. Run on `demo/sample.mp4`, commit output artefacts to `demo/output/`
11. Write `internal-monologue/step-01.md`

**Relevant context**
- Gemini audio understanding: `google.generativeai.upload_file()` + `gemini-1.5-pro`
- Gemini Flash TTS: `google-genai` client, model `gemini-2.5-flash-preview-tts`;
  `client.models.generate_content()` with `GenerateContentConfig(response_modalities=["AUDIO"])`
- ffmpeg: invoked via `subprocess` or `ffmpeg-python` wrapper
- Silence gap = any span ≥ 0.5 s with no transcript word overlapping it
- Word budget = `floor(gap_duration_seconds × 2.75)` — hard ceiling, not a guide

---

### Step 2 — Deployment skeleton + Confluent wiring

**Status:** `[x] done — 2025-09-07`

**Intent**  
Deploy six Cloud Run services and wire them with Confluent Kafka topics before
there is meaningful code in them. A skeleton that routes a job ID end-to-end and
can be reached at a public URL is infinitely more valuable than polished local
code with no deployment. This is the step that makes Tuesday night survivable.

**Expected outcomes**
- Six Cloud Run services deployed and publicly reachable (health endpoints return 200)
- Seven Confluent topics provisioned
- `POST /jobs` on the orchestrator publishes to `earsight.jobs` and returns a job ID
- A test consumer script prints messages as they flow through the topics
- `FRONTEND_URL`, `CONFLUENT_*`, `GCP_PROJECT`, `GCS_BUCKET` environment variables
  documented in `.env.example`; secrets in Google Secret Manager, never in git
- `deploy/` directory with `cloudbuild.yaml` and per-service `Dockerfile`s
- `README.md` first draft: project purpose, one-command local run, deploy instructions

**Todo list**
1. Create `deploy/` directory structure: `Dockerfile.orchestrator`,
   `Dockerfile.transcriber`, `Dockerfile.framer`, `Dockerfile.describer`,
   `Dockerfile.synthesiser`, `Dockerfile.mixer`, `Dockerfile.frontend`,
   `cloudbuild.yaml`
2. Scaffold each Python service as a minimal FastAPI app with `/health` and `/`
   routes; orchestrator also gets `POST /jobs` stub
3. Scaffold `frontend/` as `npx create-next-app` with TypeScript
4. Provision Confluent Cloud cluster and seven topics (can use the Confluent MCP
   server for provisioning; production code must contain producer/consumer client
   code regardless)
5. Write `agents/shared/kafka_client.py` — thin wrapper around `confluent-kafka`
   producer/consumer with retry and dead-letter handling
6. Wire orchestrator `POST /jobs` → produce to `earsight.jobs`
7. Wire each downstream service to consume its input topic, log receipt, produce to
   its output topic (stubs — no real processing yet)
8. Deploy all six services to Cloud Run via `gcloud run deploy` or Cloud Build
9. Smoke-test: `curl -X POST https://<orchestrator-url>/jobs` flows a message
   through all topics and logs show receipt at each service
10. Write `README.md` (§3 cold-clone test: clone → `.env` → `make dev` → works)
11. Write `internal-monologue/step-02.md`

**Relevant context**
- Cloud Run: each service is a separate container, separate URL
- Confluent Cloud: free tier has 5 GB/month, sufficient for hackathon
- `confluent-kafka` Python client: `Producer`, `Consumer`, schema-registry optional
- GCS bucket needed at this step for video upload/download between services
- `.env.example` must list every env var; `.env` must be gitignored

---

### Step 3 — Real transcription + gap map over Kafka

**Status:** `[x] done — 2025-09-07`

**Intent**  
Replace the transcriber and framer stubs with the real implementations from Step 1,
now running as Cloud Run services communicating over Kafka. After this step,
uploading a video via `curl` produces a real transcript and a real gap map,
persisted to GCS and signalled over topics.

**Expected outcomes**
- `POST /jobs` with a GCS video URI kicks off the full transcriber + framer flow
- `earsight.transcript` carries a JSON transcript with word-level timestamps
- `earsight.frames` carries GCS URIs for per-gap representative frames
- Both outputs readable from GCS; job status queryable at `GET /jobs/{id}`

**Todo list**
1. Move `agents/transcriber/transcriber.py` logic into the Cloud Run service,
   triggered by consuming `earsight.jobs`
2. Move `agents/framer/framer.py` logic similarly, consuming `earsight.jobs`
3. Add `GET /jobs/{id}` to orchestrator with status fields:
   `queued | transcribing | framing | describing | synthesising | mixing | done | failed`
4. Orchestrator aggregates completion events from `earsight.transcript` and
   `earsight.frames` before publishing to `earsight.gaps` (both must arrive)
5. Integration test: upload `demo/sample.mp4`, poll job status, verify transcript
   and frames land in GCS
6. Write `internal-monologue/step-03.md`

---

### Step 4 — Describer agent: salience scoring + copy writing

**Status:** `[x] done — 2025-09-07 (commit 79ff23c)`

**Intent**
The describer is the intellectual centre of the system. It consumes the transcript
and frames, decides what is worth saying in each gap, and produces copy that fits
the word budget. This is where the salience decision (§5) is made.

**Design for the salience decision:**
Two-pass approach within one Gemini call:
1. **Context pass** — the model receives the full transcript, the list of all gaps,
   and the running "established facts" memory (what has already been described).
   It returns a priority-ranked list of gaps with a rationale: what would a
   viewer lose without this cue?
2. **Copy pass** — for each prioritised gap (highest-priority first), the model
   receives the frame image, the gap duration, the hard word budget, and the
   established-facts memory. It writes copy that fits. Copy that would exceed the
   budget is rejected and the gap is skipped.

Established-facts memory is a simple append-only list per job, persisted to GCS
and threaded through the copy pass to enforce the redundancy rule.

**Expected outcomes**
- `earsight.cues` carries a list of timed cue objects: `{start, end, text, words, gap_id}`
- No cue in the list exceeds its word budget (asserted before publish)
- No cue overlaps a dialogue span (asserted before publish — this is the collision
  guard from Step 1, now enforced at the service boundary)
- A skipped gap is represented as `{start, end, text: null, reason: "budget"|"salience"|"redundant"}`

**Todo list**
1. Implement two-pass describer in `agents/describer/describer.py`
2. Established-facts memory: `agents/describer/memory.py` — load/save to GCS per job
3. Word-budget assertion: `agents/shared/budget.py` — `assert_fits(text, gap_seconds)`
4. Collision guard: `agents/shared/collision.py` — `assert_no_collision(cues, transcript)`
   — this must raise `CollisionError` before any cue reaches `earsight.cues`
5. Wire into Cloud Run service consuming `earsight.gaps`
6. Integration test with demo clip — inspect cue list, verify constraint assertions pass
7. Write `internal-monologue/step-04.md`

---

### Step 5 — Synthesiser + mixer over Kafka, full audio output

**Status:** `[x] done — 2025-09-07 (commit ad9e206)`

**Intent**
Complete the audio pipeline end-to-end over Kafka. After this step, submitting a
job via the API returns a GCS URI for the mixed audio track and the VTT file.
No UI yet — this is a `curl`-driven end-to-end test.

**Expected outcomes**
- Each cue in `earsight.cues` is synthesised to a GCS audio clip
- Mixer receives all clips, ducks original audio, mixes narration, produces
  `{job_id}/described.mp4` and `{job_id}/described.vtt` in GCS
- `GET /jobs/{id}` returns `status: done` with `result_video_url` and `vtt_url`
- `validate_cues.py` run against the output VTT passes (no collisions)
- `demo/output/` updated with the Cloud-Run-produced artefacts

**Todo list**
1. Move synthesiser logic into Cloud Run service, consuming `earsight.cues`
2. Synthesiser publishes to `earsight.audio-segments` only after all cues for the
   job are synthesised (batch publish, not one message per cue)
3. Move mixer logic into Cloud Run service, consuming `earsight.audio-segments`
4. Mixer produces final files to GCS, publishes completion to `earsight.results`
5. Orchestrator consumes `earsight.results`, updates job record, makes URLs available
6. End-to-end `curl` test using `demo/sample.mp4`, verify both output files exist
7. Cache Gemini + Flash TTS responses for the demo clip in `demo/cache/` so demo never
   hits live quota
8. Write `internal-monologue/step-05.md`

---

### Step 6 — Frontend: upload, pipeline view, player

**Status:** `[x] done — 2025-09-07`

**Intent**  
Build the Next.js frontend that makes the system usable and visually legible. This
is the step that realises §5 ("how the work is made visible") — the interesting
version shows the word budget shrinking in real time, windows being filled, cues
being placed on a timeline. The UI must pass the screen-reader test (§3).

**Design notes (from §5 — surprise me):**
- **Pipeline view:** not a spinner. A scrollable timeline of silence gaps, each
  rendered as a track segment. As the pipeline runs, segments transition:
  `gap detected → frame extracted → copy written → synthesised → placed`.
  Each segment shows its word budget as a bar that fills as copy is generated.
- **Player:** standard `<video>` element + WebVTT track. The active cue highlights
  its segment on the timeline. Play controls are keyboard-accessible.
- **Visual language:** dark background (#0a0a0a), monospaced type for cue text,
  high-contrast accent colour (amber #f5a623), film-leader aesthetic. Feels like
  a tool a post-production house would use.
- **Copy:** "Drop a video. Hear everything." — not "Upload a file".

**Expected outcomes**
- Upload form accepts `.mp4` ≤ 90 s, POSTs to orchestrator, shows job ID
- Pipeline view polls `GET /jobs/{id}` and renders gap segments updating live
- Player appears when job reaches `done`, loads described video + VTT track
- Keyboard navigation through full flow (Tab, Enter, Space for playback)
- Playwright test `docs/steps/06-pipeline.png` captured
- Lighthouse accessibility score ≥ 90 on the upload and player screens

**Todo list**
1. Scaffold `frontend/` Next.js app: layout, global styles, component directory
2. `components/UploadZone.tsx` — drag-and-drop + file input, 90 s cap shown,
   accessible labels
3. `components/PipelineView.tsx` — gap timeline with per-segment state machine,
   word-budget fill bar per segment
4. `components/Player.tsx` — `<video>` + WebVTT, cue highlight synced to timeline
5. `app/page.tsx` — orchestrates upload → poll → pipeline → player flow
6. API client `lib/api.ts` — typed wrappers for orchestrator REST endpoints
7. Playwright test: upload demo clip, wait for done, verify player visible,
   screenshot to `docs/steps/06-pipeline.png`
8. Accessibility audit: axe-core in Playwright, fix any critical violations
9. Write `internal-monologue/step-06.md`

---

### Step 7 — Resilience, reset script, and demo cache

**Status:** `[x] done — final session (Phase 3)`

**Intent**  
Make the demo reliable. Partial failure should not produce a stack trace — a job
with some cues missing is a valid result. The reset script should return the app
to pre-upload state in one command. The demo cache means the demo clip never hits
live quota.

**Expected outcomes**
- If the describer dies mid-job, the mixer works with whatever cues arrived
- `scripts/reset.sh` clears GCS job artefacts, resets orchestrator state, returns
  to upload screen — works in one command
- `demo/cache/` contains saved Gemini and TTS responses for `demo/sample.mp4`;
  `EARSIGHT_USE_CACHE=1` switches all model calls to cached responses
- Each agent service runnable standalone: `python -m agents.transcriber --input video.mp4`
- Write `internal-monologue/step-07.md`

**Todo list**
1. Deadline handling in each consumer: if a job times out (no completion event in
   N seconds), publish a partial-completion event rather than nothing
2. Mixer: accept partial `earsight.audio-segments` payload; produce what it has
3. `scripts/reset.sh` implementation
4. Cache layer in `agents/shared/cache.py` — file-backed, keyed by input hash;
   wrap every Gemini and TTS call with `@cached`
5. Generate and commit cache for `demo/sample.mp4`
6. CLI entry points: `python -m agents.<name> --help` for each agent
7. Integration test: kill describer mid-job, verify mixer still produces output
8. Write `internal-monologue/step-07.md`

---

### Step 8 — Bob evidence trail + README completion

**Status:** `[x] done — final session (Phase 4)`

**Intent**  
Ensure the repository reads as an auditable IBM Bob build to a judge who has never
spoken to us. This step produces no new product features — it produces the
artifacts that prove how the product was built.

**Expected outcomes**
- `AGENTS.md` at root and `.bob/` AGENTS.md files committed
- `.bob/rules/` encodes the §6 workflow rules (report format, stop-and-wait,
  commit trailer, runtime-dependency ban)
- `docs/bob/session-log.md` exists and has entries for each session
- `docs/steps/` has a screenshot per step (01 through 08)
- `internal-monologue/` has one entry per approved step
- `README.md` complete: title, "Built with IBM Bob" section, architecture diagram,
  local setup, deploy, demo instructions, `## Built with IBM Bob` section linking
  to `plans/`, `internal-monologue/`, `docs/steps/`
- Every commit has `Built-with: IBM-Bob` trailer
- `validate_cues.py` in CI (GitHub Actions), fails build on any collision

**Todo list**
1. Run `/init` to generate `AGENTS.md` and `.bob/` files
2. Write `.bob/rules/` files from §6
3. Set up session-log hook
4. Verify all commits have `Built-with: IBM-Bob` trailer; amend any that don't
5. Write `README.md` final version
6. GitHub Actions workflow: `validate_cues.py` on every push
7. Final cold-clone test (§3): fresh directory, follow README, one command, works
8. Write `internal-monologue/step-08.md`

---

## Dependency order

```
Step 1  (local proof)
  └─▶ Step 2  (deployment skeleton)
        └─▶ Step 3  (real transcription over Kafka)
              └─▶ Step 4  (describer: salience + copy)
                    └─▶ Step 5  (synthesiser + mixer, full audio)
                          ├─▶ Step 6  (frontend)
                          └─▶ Step 7  (resilience + demo cache)
                                └─▶ Step 8  (evidence trail + README)
```

Steps 6 and 7 can proceed in parallel after Step 5. All others are strictly
sequential.

---

## Hard constraints checklist (§4)

- [ ] No OpenAI / Anthropic / AWS / Microsoft AI in dependency tree — verified
      before every push via `grep` in CI
- [ ] Confluent topics are load-bearing: producer and consumer code ships,
      not mocked
- [ ] Collision guard asserts and raises in code — not just a check in tests
- [ ] `LICENSE` file at root from first commit — already present
- [ ] Public repo from first commit — already the case
- [ ] Input capped at 90 s — enforced in upload handler and pipeline entry point
- [ ] Bob evidence trail (§8) — Step 8 closes this

---

## Bootstrap (§7) — before Step 1

The brief specifies four bootstrap tasks that precede the step plan. These are done
**in the first agent session** before any product code is written:

1. `/init` — generate `AGENTS.md` and `.bob/` files
2. Write `.bob/rules/` from §6 (report format, stop-and-wait, commit trailer,
   runtime-dependency ban)
3. Hook: append to `docs/bob/session-log.md` on session start
4. This plan file — now complete

---

*This plan was generated in Plan mode. Implementation begins only after Alami approves it.*
