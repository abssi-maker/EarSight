# EARSIGHT — Agent Context

## What this project is

EARSIGHT is a distributed AI agent crew that produces audio description tracks for
short videos. It finds silences between dialogue, decides what's worth narrating in
each gap (constrained to a hard word budget), synthesises speech, and mixes it into
the original audio.

## Stack

- **Agent services:** Python 3.11, `google-adk`, FastAPI — one Cloud Run container per agent
- **LLM / speech:** Gemini via Vertex AI (`google-adk`, `google-genai`, `google-cloud-aiplatform`)
- **Messaging:** Confluent Kafka — genuine producer/consumer, load-bearing architecture
- **Frontend:** Next.js 14 / TypeScript, Cloud Run
- **Storage:** Google Cloud Storage for media artefacts

## Repository layout

```
agents/
  transcriber/    # audio → transcript with word-level timestamps
  framer/         # video → per-gap representative frames
  describer/      # salience scoring + word-budget copy writing
  synthesiser/    # cue text → TTS audio clips
  mixer/          # mix narration into original audio
  shared/         # kafka_client, budget, collision, cache utilities
frontend/         # Next.js app
deploy/           # Dockerfiles, cloudbuild.yaml
scripts/          # pipeline.py (local), validate_cues.py, reset.sh
demo/             # sample.mp4 + cached model responses
plans/            # build plan and revisions (Plan mode artefacts)
internal-monologue/  # one entry per approved step (IBM Bob evidence)
docs/
  bob/            # session-log.md
  steps/          # screenshots per step
.bob/             # Bob configuration, rules, custom modes
```

## The one rule that must never break

**No cue may overlap dialogue.** This is asserted in code (`CollisionError` raised
before any cue is published to Kafka). A silent gap is correct behaviour. Talking
over a line is a defect. Assert this in `agents/shared/collision.py`.

## Word budget

`floor(gap_duration_seconds × 2.75)` words. Hard ceiling. A cue that would exceed
its budget is dropped, not truncated.

## Hard runtime constraint

**Google Cloud AI only.** `google-adk`, `google-genai`, `google-generativeai`,
`google-cloud-aiplatform` — imported and actually called. No OpenAI, Anthropic,
AWS, or Microsoft AI anywhere in the dependency tree. Verified in CI.

## How we work (§6 of the brief)

- Plan mode first, implement in a separate conversation
- One step per session, from `plans/00-build-plan.md`
- Reference the plan with `@plans/` rather than restating it
- Every step ends in evidence: local run, CLI output, screenshot
- Stop and wait for approval before starting the next step
- Commit and push only after approval, one commit per step
- Commit trailer: `Built-with: IBM-Bob` on every commit
- Report format: STEP N — name / Built / Skill / Test / Changed / Uncertain / Next

## Input cap

90 seconds of video. Enforced in the upload handler and pipeline entry point.
