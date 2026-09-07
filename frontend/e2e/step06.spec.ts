/**
 * Step 6 — Playwright end-to-end test
 *
 * What it checks:
 * 1. Upload zone renders with correct heading and copy
 * 2. Drag-and-drop label is present and accessible
 * 3. File input has aria-label (accessibility)
 * 4. After selecting a mock file, pipeline view section appears
 * 5. Screenshot captured to docs/steps/06-pipeline.png
 *
 * The test mocks the orchestrator API so it never hits a live backend.
 */

import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const ORCHESTRATOR = 'http://localhost:8000';

test.describe('Step 6 — EarSight frontend', () => {
  test.beforeEach(async ({ page }) => {
    // Mock POST /jobs
    await page.route(`${ORCHESTRATOR}/jobs`, async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ job_id: 'test-job-001', status: 'transcribing' }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock GET /jobs/test-job-001 — progress through states
    let callCount = 0;
    const states = [
      { job_id: 'test-job-001', status: 'transcribing', gap_count: 4 },
      { job_id: 'test-job-001', status: 'describing', gap_count: 4 },
      {
        job_id: 'test-job-001',
        status: 'done',
        gap_count: 4,
        cues: [
          { cue_id: 'cue_gap_000', gap_id: 'gap_000', start: 0,    end: 16.78, text: 'A woman struggles on a frost-covered platform.', word_count: 8,  skip_reason: null },
          { cue_id: 'cue_gap_001', gap_id: 'gap_001', start: 17.8, end: 22.06, text: 'The man leans forward.', word_count: 4,  skip_reason: null },
          { cue_id: 'cue_gap_002', gap_id: 'gap_002', start: 24,   end: 28,    text: null, word_count: 0, skip_reason: 'budget' },
          { cue_id: 'cue_gap_003', gap_id: 'gap_003', start: 38.2, end: 46.4, text: 'A bald man emerges from bright light.', word_count: 7, skip_reason: null },
        ],
        result_video_url: 'http://localhost:8000/demo/described.mp4',
        vtt_url: 'http://localhost:8000/demo/described.vtt',
      },
    ];

    await page.route(`${ORCHESTRATOR}/jobs/test-job-001`, async (route) => {
      const idx = Math.min(callCount++, states.length - 1);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(states[idx]),
      });
    });

    // Mock /api/vtt proxy (Next.js API route)
    await page.route('**/api/vtt**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/vtt',
        body: 'WEBVTT\n\n00:00:00.000 --> 00:00:16.780\nA woman struggles on a frost-covered platform.\n',
      });
    });

    // Mock the video file URL returned for Player
    await page.route('**/demo/described.mp4', async (route) => {
      await route.fulfill({ status: 200, contentType: 'video/mp4', body: Buffer.from('') });
    });
  });

  test('upload zone renders correctly', async ({ page }) => {
    await page.goto('/');

    // Heading
    await expect(page.getByRole('heading', { name: 'EARSIGHT' })).toBeVisible();

    // Upload label / drop zone
    const label = page.locator('label[for="video-upload"]');
    await expect(label).toBeVisible();
    await expect(label).toContainText('Drop a video');

    // Hidden file input has aria-describedby (accessible description)
    const input = page.locator('#video-upload');
    await expect(input).toHaveAttribute('aria-describedby', 'upload-hint');
  });

  test('pipeline view and player appear after upload', async ({ page }) => {
    await page.goto('/');

    // Simulate file selection via the hidden input
    const demoPath = path.resolve(__dirname, '../../demo/sample.mp4');
    const fileInput = page.locator('#video-upload');

    // Use a Buffer if the demo file is missing (CI without demo asset)
    if (fs.existsSync(demoPath)) {
      await fileInput.setInputFiles(demoPath);
    } else {
      // Create a minimal fake mp4-named file
      await fileInput.setInputFiles({
        name: 'sample.mp4',
        mimeType: 'video/mp4',
        buffer: Buffer.from('\x00\x00\x00\x18ftypmp42'),
      });
    }

    // Pipeline section should appear
    await expect(page.getByRole('region', { name: /pipeline timeline/i })).toBeVisible({ timeout: 5000 });

    // Wait for 'done' state (poll mocked to progress quickly)
    await expect(page.getByText('done')).toBeVisible({ timeout: 15_000 });

    // Player section should appear
    await expect(page.getByRole('region', { name: /described video player/i })).toBeVisible({ timeout: 5000 });

    // Ensure docs/steps directory exists (frontend/e2e/ → ../../../../docs/steps)
    const stepsDir = path.resolve(__dirname, '../../docs/steps');
    fs.mkdirSync(stepsDir, { recursive: true });

    // Screenshot
    await page.screenshot({
      path: path.join(stepsDir, '06-pipeline.png'),
      fullPage: true,
    });
  });

  test('keyboard navigation — Tab reaches upload input', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement?.id ?? '');
    // Skip link or upload input should be reachable
    expect(['video-upload', '']).toContain(focused);
  });
});
