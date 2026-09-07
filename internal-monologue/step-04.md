# Step 4 — Describer: Salience Scoring + Copy Writing

**Date:** 2025-09-07  
**Status:** done

## What I built

The describer is the intellectual centre of the pipeline. It converts a gap map + transcript into a list of timed narration cues, each fitting a hard word budget and verified not to collide with any dialogue.

### Two-pass architecture (`agents/describer/describer.py`)

**Pass 1 — salience ranking:**  
Gemini receives the full transcript, all gaps (with durations, preceding/following dialogue, and word budgets), and the established-facts list. It returns a priority-ranked list: which gaps would a blind viewer lose meaningful story information without, and why? Gaps with budget < 3 words are skipped before this call — not enough words to say anything useful.

**Pass 2 — copy writing:**  
For each gap Gemini ranked `include: true`, a second call sends the frame image (if available), the gap timing, the hard word budget, and the established-facts list. Gemini writes one present-tense, active-voice description. If the returned copy exceeds the budget, the cue is dropped (not truncated). If the model decides there's nothing worth saying, it returns `{"text": null}` and the gap is recorded as skipped with reason `"redundant"`.

### Constraint enforcement (both layers)

- **In `describer.py`:** `assert_no_collision()` is called per candidate cue before it's added to the list. Any cue that would collide with a dialogue word raises `CollisionError` and is dropped, never reaching output.
- **In `app.py`:** a second sweep of `assert_fits()` + `assert_no_collision()` runs over all active cues before they're serialised to GCS or published to `earsight.cues`. Belt-and-suspenders.

### Established-facts memory (`agents/describer/memory.py`)

An append-only list of all description texts written so far for a job. GCS-backed (`jobs/{job_id}/established_facts.json`), loaded at the start of each describer run and saved after. Passed into both Gemini passes so the model can avoid repeating things already established.

### Cloud Run wiring (`agents/describer/app.py`)

- Consumes `earsight.gaps`
- Downloads transcript JSON + frames manifest from GCS
- Downloads frame images to a temp directory
- Runs two-pass describer
- Asserts constraints
- Uploads `cues.json` to GCS
- Publishes to `earsight.cues`

## Integration test result

Run against `demo/sample.mp4` artefacts (local, Step 1 output):

```
[describer] Pass 1: ranking gaps for salience...
[describer] gap_000: ✓ 'An older man in a suit clutches his chest...' (35/46 words)
[describer] gap_001: ✓ 'The man watches as the woman slowly sits up.' (9/11 words)
[describer] gap_002: SKIP (salience)
[describer] gap_003: SKIP (salience)
[describer] gap_004–007: SKIP (budget < 3)
[describer] gap_008: ✓ 'A gaunt, bald man hunches forward...' (17/22 words)
[describer] gap_009: ✓ 'Two figures grapple aggressively...' (26/33 words)

validate_cues.py: OK: 4 cues, no collisions with 29 dialogue words
```

4 active cues, 6 skipped (4 budget, 2 salience). All within budget. Zero collisions.

## What I was uncertain about

- Model names: `gemini-3.8-flash` and `gemini-3.7-flash` don't exist via the AI Studio API key path. Fixed the fallback list to `gemini-2.5-flash → gemini-2.0-flash → gemini-1.5-flash`.
- Vertex AI was disabled for `earsight-prod-2026` locally — ran integration test via API key path (`GOOGLE_CLOUD_PROJECT=""`).

## Next step

Step 5 — Synthesiser + mixer over Kafka, full audio output.
