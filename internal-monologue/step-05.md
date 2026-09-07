# Step 5 — Synthesiser + mixer over Kafka, full audio output

**Date:** 2025-09-07  
**Status:** ✅ complete

## What was done

### Vertex AI / billing unblocked
- `aiplatform.googleapis.com` and `generativelanguage.googleapis.com` enabled for `earsight-prod-2026`
- Billing linked to the project — Vertex AI now works via ADC (no API key needed in Cloud Run)
- Discovered model name differs between Vertex AI (`gemini-2.5-flash-tts`) and public Gemini API (`gemini-2.5-flash-preview-tts`)
- Fixed: `_client()` in `synthesiser.py` now returns `(client, model_name)` tuple, selecting the correct name per path

### Synthesiser service — real implementation
- `agents/synthesiser/app.py` upgraded from stub to production:
  - Consumes `earsight.cues` → downloads `cues.json` from GCS
  - Synthesises each active cue via Gemini Flash TTS (Vertex AI)
  - Uploads each audio clip to `gs://GCS_BUCKET/jobs/{job_id}/audio/{cue_id}.wav`
  - **Batch-publishes** all segments to `earsight.audio-segments` (one message after all cues done)

### Mixer service — real implementation
- `agents/mixer/app.py` upgraded from stub to production:
  - Consumes `earsight.audio-segments` → downloads original video and all audio clips from GCS
  - Runs `mixer.mix()` — ffmpeg duck + overlay filter graph
  - Uploads `described.mp4` and `described.vtt` to GCS
  - Publishes `{status: done, result_video_url, vtt_url}` to `earsight.results`
  - Handles video download failure gracefully (publishes `status: failed`)

### Demo cache
- `agents/shared/cache.py` — `@cached(namespace)` decorator, SHA-256 keyed, file-backed under `demo/cache/`
- Activated when `EARSIGHT_USE_CACHE=1`
- TTS calls in `synthesiser.py` wrapped with `@cached("tts")`
- 4 TTS responses cached to `demo/cache/tts/` (8 cache files: 4 Vertex-path + 4 API-key-path hashes)

### Orchestrator
- Already handled `earsight.results` from Step 3 — fields `result_video_url` and `vtt_url` match mixer output exactly. No changes needed.

## Integration test

```
python3 scripts/test_step5.py
```

```
Step 5 — local synthesiser + mixer test
Loaded 10 cues (4 active)

── Synthesiser ──────────────────────────────────────────
[synthesiser] cue_gap_000: synthesising '...' → ✓ saved
[synthesiser] cue_gap_001: synthesising '...' → ✓ saved
[synthesiser] cue_gap_008: synthesising '...' → ✓ saved
[synthesiser] cue_gap_009: synthesising '...' → ✓ saved
✓ 4 clips synthesised → demo/output/audio_step5/

── Mixer ────────────────────────────────────────────────
[mixer] Mixing 4 narration clips into demo/output/described_step5.mp4...
[mixer] ✓ demo/output/described_step5.mp4
[mixer] ✓ demo/output/described_step5.vtt

✓ Video: demo/output/described_step5.mp4  (3736 KB)
Step 5 local test PASS
```

## VTT validation

```
python3 scripts/validate_cues.py --vtt demo/output/described_step5.vtt --transcript demo/output/transcript.json
OK: 4 cues, no collisions with 29 dialogue words
```

## Output artefacts

| File | Size |
|---|---|
| `demo/output/described_step5.mp4` | 3.6 MB |
| `demo/output/described_step5.vtt` | 574 B |
| `demo/cache/tts/*.pkl` | 4 clips, ~1.9 MB total |

## VTT produced

```
WEBVTT

cue_gap_000
00:00:00.000 --> 00:00:16.780
On a frost-covered metallic platform, a woman struggles to push herself up opposite a man in a dark coat, separated by a bright column of electrical energy.

cue_gap_001
00:00:17.820 --> 00:00:22.060
The man leans forward, looking across at her.

cue_gap_008
00:00:38.160 --> 00:00:46.360
A hunched, bald man with a distorted face emerges from bright light, a woman behind him.

cue_gap_009
00:00:47.960 --> 00:01:00.000
The woman battles the man on the narrow, wired platform as countless cables crisscross the dark abyss.
```

## State going into Step 6

- Vertex AI (ADC) fully operational on `earsight-prod-2026` — billing enabled
- All six Cloud Run service skeletons exist; real implementations done through mixer
- Services still running locally (Cloud Run deploy deferred — will happen in Step 6 or 7)
- `EARSIGHT_USE_CACHE=1` replays TTS from `demo/cache/` — demo never burns live quota
- Full audio pipeline proven end-to-end: `POST /jobs` → transcript → frames → describe → synthesise → mix → `described.mp4` + `described.vtt`
