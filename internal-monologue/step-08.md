# Step 8 — Internal Monologue

**Date:** 2025-09-08  
**Step:** 8 — CI, README, IBM Bob evidence trail  
**Session focus:** Final evidence session. No new product features. Pure documentation, CI, and proof-of-build artefacts.

---

## What I did

### 1. Fixed fabricated Kafka topic names in the Playwright fixture

`frontend/e2e/step06.spec.ts` had three invented topic names: `earsight.uploads`,
`earsight.transcripts` (plural), and `earsight.completed`. None of these exist on the
Confluent cluster. Replaced the events fixture with the seven real topics verified live:
`earsight.jobs`, `earsight.transcript`, `earsight.frames`, `earsight.gaps`,
`earsight.cues`, `earsight.audio-segments`, `earsight.results`. The AgentLane component
derives its "N topics active" header by counting unique topic names in the events array,
so with 7 unique real topics the header now reads "7 topics active" — matching the README
topic table. Screenshot captured to `docs/steps/06-pipeline.png`. All 4 Playwright tests
passed.

### 2. CI workflow

Added `.github/workflows/ci.yml`. On every push it runs:
1. `python scripts/validate_cues.py --vtt demo/output/described.vtt --transcript demo/output/transcript.json` — exits 1 on any cue/dialogue collision, gatekeeping the core constraint.
2. A banned-dependency grep — exits 1 if `openai`, `anthropic`, `bedrock`, or `azure.cognitiveservices` appears anywhere in agent Python files or requirements. This is the runtime-dependency ban from `.bob/rules/04` encoded into CI.

Updated `.gitignore` to un-ignore `demo/output/described.vtt` and `demo/output/transcript.json` (text only — the generated `.mp4` and `.wav` remain ignored). Both files are committed so CI has something to validate against.

### 3. README — IBM track qualification

Restructured the README so "Built with IBM Bob" is the first section after the title, above architecture. Added:
- Verifiable commit counts (11/12 carry `Built-with: IBM-Bob`; 10/12 carry `Co-authored-by`)
- Two `git log` commands a judge can run to verify the trailer counts themselves
- Table of `.bob/rules/` files and their purposes
- Explicit Confluent section: 7 topics, producer `acks=all` + idempotence, dead-letter topic, live Confluent Cloud claim
- Gemini + ADK section: model names, ADK `LlmAgent`/`Runner` pattern, forced function tools (`check_budget`, `check_collision`), VideoMetadata offsets, SynthID watermarking
- Known limitations stated plainly: in-memory job store, no Agent Engine, Step 7 resilience descoped

### 4. Step 7 note

Step 7 (resilience) was deliberately skipped. The decision is recorded in the README
"Known limitations" section. The step marker in `plans/00-build-plan.md` is left
`[ ] pending` — not marked done, because it was not done.

### 5. Step 8 marked done

After the commit lands, `plans/00-build-plan.md` Step 8 status updated to `[x] done`.

---

## Decisions made

- **14 events in the fixture, 7 unique topics.** The AgentLane counts unique topic names
  dynamically, so the count is correct without changing any component code. The extra
  events show the `earsight.gaps` internal loop (describer produces to gaps, then
  consumes from it for the copy pass) — this is architecturally accurate.
- **Text-only CI artefacts.** `described.vtt` and `transcript.json` are small text files
  (< 3 KB each). Committing them as CI fixtures avoids needing a live Confluent/Gemini
  call in CI, which would require secret management. The `.mp4` stays gitignored.
- **No rewriting of pushed commits.** `d69def3` is missing `Co-authored-by` but carries
  `Built-with: IBM-Bob`. It was pushed. Not amended. The README acknowledges this
  honestly so a judge is not confused by the count discrepancy.

---

## What I did not do

- Did not implement any resilience features (Step 7) — deliberately descoped.
- Did not run Playwright more than once this session (rule: once per step for doc steps).
- Did not touch any agent service code — this step is evidence-only.
