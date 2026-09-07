# Step 01 — Internal Monologue

**Date:** 2025-09-07  
**Step:** 1 — Local end-to-end pipeline proof  
**Status:** Complete

---

## What I built

A sequential local pipeline that takes a video file and produces:
- A described `.mp4` with narration mixed into the audio track
- A `.vtt` WebVTT cue sheet

The pipeline runs five agents in order: transcriber → framer → describer → synthesiser → mixer.

## Key decisions made

**Demo clip.** The brief says commit a demo clip. I initially used a synthetic tone+silence clip for wiring, but switched to a 60-second excerpt from *Elephant Dream* (Blender Foundation, CC-BY) for the actual proof. The synthetic clip correctly produced 0 cues (black screen, nothing to describe). The real clip produced 4 cues with meaningful copy.

**google-genai SDK.** Started with `google-generativeai` (deprecated) and switched to `google-genai` as prompted by the deprecation warning. Used the Gemini API directly (not Vertex AI) because the GCP project didn't have Vertex AI model access enabled. Cloud Run deployments in Step 2 will use Secret Manager for the API key.

**Model selection: gemini-3.8-flash.** User requested this. Added a fallback list (`gemini-3.8-flash → gemini-3.7-flash → gemini-2.5-flash`) because the model sporadically returns 503 during high demand. The fallback is transparent — same prompt, same output format.

**Two-pass describer.** Pass 1 ranks all gaps for salience (one Gemini call seeing the full transcript). Pass 2 writes copy per included gap (one Gemini call per gap, with the frame image). The salience pass correctly filtered out 6 of 10 gaps — small-budget gaps (< 3 words) and gaps where dialogue already conveyed the scene. This is exactly the redundancy and subtraction test from §3.

**Collision guard.** Implemented as `assert_no_collision()` in `agents/shared/collision.py`, called in two places:
1. Inside the describer, before any cue is appended to the output list
2. In the pipeline script, as a belt-and-suspenders check before synthesis begins

Validated separately with `scripts/validate_cues.py`. Result: 4 cues, 0 collisions with 29 dialogue words.

**Word budget.** `floor(gap_seconds × 2.75)`. The largest gap (16.78s) had a 46-word budget; copy came in at 28 words. The smallest accepted gap (3.60s) had a 9-word budget; copy came in at 9. Tight, correct.

## What the output sounds like

The VTT cue for gap_000 (0–16.78s): *"On a frosted metal walkway flanked by towering machines and a vertical beam of bright light, one figure crawls along the floor while another stands and stumbles backward."* — this is the right shape. Specific, visual, present tense, no camera language.

## What I was uncertain about

- Whether `gemini-3.8-flash` would be stable enough for production use. It 503s intermittently. Fallback chain handles it for now; Cloud Run deployment in Step 2 should configure retry at the infrastructure level too.
- The TTS voice (`en-US-Neural2-J`) — warm and authoritative, but not tested for accessibility compliance yet. That's Step 6.

## What I did differently from the plan

- Plan said "commit `demo/sample.mp4`" — I built and committed it programmatically (tone clips → real Elephant Dream excerpt) rather than sourcing it externally. Same outcome.
- Plan said use `google-cloud-texttospeech` for TTS — kept as-is, working correctly.

## Files created this step

```
AGENTS.md
.bob/AGENTS.md
.bob/rules/01-report-format.md through 05-screenshot-requirement.md
.bob/hooks/session-log.mjs
.bob/settings.json
pyproject.toml
requirements.txt
agents/__init__.py
agents/shared/__init__.py, budget.py, collision.py, models.py
agents/transcriber/__init__.py, transcriber.py
agents/framer/__init__.py, framer.py
agents/describer/__init__.py, describer.py
agents/synthesiser/__init__.py, synthesiser.py
agents/mixer/__init__.py, mixer.py
scripts/__init__.py, pipeline.py, validate_cues.py
demo/sample.mp4
.env.example
```
