# Step 4 — Describer agent: salience scoring + copy writing

**Date:** 2025-09-07  
**Status:** ✅ complete

## What was done

### Confluent Kafka provisioning
- Cluster `lkc-do1v39z` (GCP us-east1, Standard) confirmed UP
- Created all 8 topics: `earsight.jobs`, `earsight.transcript`, `earsight.frames`,
  `earsight.gaps`, `earsight.cues`, `earsight.audio-segments`, `earsight.results`,
  `earsight.dead-letter` — 3 partitions each
- Created API key `5NLLGUL7RENJMG2V` for cluster access
- Updated `.env` with bootstrap servers and API key/secret

### Kafka smoke test
- `agents/shared/kafka_client.py` producer published to `earsight.jobs`
- Consumer verified round-trip: message read back within 8s
- Both producer and consumer connected to Confluent Cloud over SASL_SSL

### Describer integration test
- Ran `agents/describer/describer.py` against `demo/output/transcript.json` + `demo/output/gaps.json`
- Two-pass Gemini pipeline executed successfully (model fallback chain used due to quota)
- 10 gaps processed: 4 active cues written, 6 skipped (2 salience, 4 budget < 3 words)
- All constraint assertions passed hard:
  - `assert_fits()` — all 4 active cues within word budget
  - `assert_no_collision()` — zero overlap with 29 dialogue words
- `validate_cues.py --vtt demo/output/described.vtt --transcript demo/output/transcript.json`
  → `OK: 4 cues, no collisions with 29 dialogue words`
- Output written to `demo/output/cues_step4.json`

## Code components verified

| Component | File | Status |
|---|---|---|
| Two-pass describer | `agents/describer/describer.py` | ✓ live |
| Established-facts memory | `agents/describer/memory.py` | ✓ live |
| Word-budget assertion | `agents/shared/budget.py` | ✓ asserts |
| Collision guard | `agents/shared/collision.py` | ✓ raises CollisionError |
| Cloud Run service | `agents/describer/app.py` | ✓ consumes earsight.gaps |
| Kafka client | `agents/shared/kafka_client.py` | ✓ connected to Confluent |

## Constraint verification

```
Active cues: 4
  ✓ gap_000: 27/46 words
  ✓ gap_001: 8/11 words
  ✓ gap_008: 16/22 words
  ✓ gap_009: 17/33 words
✓ assert_no_collision passed
✓ All constraints satisfied — Step 4 integration test PASS
```

## Known state going into Step 5

- Cloud Run API is not yet enabled for `earsight-prod-2026` — services run locally
- Vertex AI API disabled for the project; describer uses `GOOGLE_API_KEY` (Gemini API key)
  locally via `GOOGLE_CLOUD_PROJECT=""` override
- The `describer/app.py` Cloud Run service is ready but not deployed; Step 5 will
  resolve the Cloud Run/Vertex AI setup alongside deploying synthesiser + mixer

## Sample cues generated

```json
[
  {"gap_id": "gap_000", "text": "On a frost-covered metallic platform, a woman struggles...", "word_count": 27},
  {"gap_id": "gap_001", "text": "The man leans forward, looking across at her.", "word_count": 8},
  {"gap_id": "gap_008", "text": "A hunched, bald man with a distorted face emerges...", "word_count": 16},
  {"gap_id": "gap_009", "text": "The woman battles the man on the narrow, wired platform...", "word_count": 17}
]
```
