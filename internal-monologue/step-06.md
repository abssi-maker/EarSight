# Step 6 — Frontend: upload, pipeline view, player

**Date:** 2025-09-07  
**Status:** ✅ complete

## What was done

### Components built

| Component | File | Description |
|---|---|---|
| UploadZone | `frontend/src/components/UploadZone.tsx` | Drag-and-drop + file input; 90s duration cap checked client-side; accessible `aria-label` on the label, `aria-describedby` on the input |
| PipelineView | `frontend/src/components/PipelineView.tsx` | Scrollable timeline of gap segments; macro timeline bar; per-segment state machine (detected → framing → describing → synthesising → placed / skipped); amber word-budget fill bar |
| Player | `frontend/src/components/Player.tsx` | `<video>` element with WebVTT `<track kind="descriptions">`; `onTimeUpdate` callback drives active-cue highlight in timeline |

### Page & API wiring

- `app/page.tsx` fully rewritten — state machine: `idle → uploading → processing → done/failed`
- `lib/api.ts` extended with `uploadVideo()` (FormData POST to `/upload`), `CueRecord` type, `gap_count` / `cues` fields on `JobResponse`
- `app/api/vtt/route.ts` — Next.js API route that proxies WebVTT from GCS URLs to avoid CORS on the `<track>` element

### Build + TypeScript

- `npx tsc --noEmit` → zero errors
- `next build` → clean, 91.8 kB first load JS

### Playwright tests (3/3 pass)

```
[1/3] upload zone renders correctly          ✓
[2/3] pipeline view and player appear        ✓  (screenshot: docs/steps/06-pipeline.png)
[3/3] keyboard navigation — Tab reachable   ✓
```

## Screenshot

`docs/steps/06-pipeline.png` — full-page capture showing:
- EARSIGHT heading (amber, monospace)
- Job ID + `done` status
- Pipeline · 4 GAPS timeline header with macro bar
- 3 × PLACED segments with cue text and [words/budget] counts
- 1 × SKIPPED segment (reason: budget)
- Player with native controls visible
- "Upload another video" button

## Visual language confirmed

- Background `#0a0a0a`, accent `#f5a623`, monospaced type throughout
- No spinners — gap cards show state transitions in real time
- Keyboard: Tab reaches upload input; Space/arrows work on player natively

## State going into Step 7

- Cloud Run deploy still deferred (services run locally)
- `EARSIGHT_USE_CACHE=1` needed in production env for demo
- Orchestrator `/upload` endpoint not yet implemented — frontend falls back to `local://` stub gracefully
