import { JobResponse } from './api';

/** One silence window, plus what the describer decided to do with it. */
export interface GapSegment {
  gap_id: string;
  start: number;
  end: number;
  duration: number;
  word_budget: number;
  state: 'placed' | 'skipped' | 'pending';
  cue_text?: string | null;
  word_count?: number;
  skip_reason?: string | null;
}

/**
 * Narration pace used to turn a silence window into a word budget.
 * Mirrors the describer's check_budget tool.
 */
export const WORDS_PER_SECOND = 2.75;

export function budgetFor(duration: number) {
  return Math.floor(duration * WORDS_PER_SECOND);
}

/** How long the written line takes to speak, from its word count. */
export function spokenSeconds(words: number) {
  return words / WORDS_PER_SECOND;
}

/** 0:04.2 */
export function tc(s: number) {
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  return `${m}:${rest < 10 ? '0' : ''}${rest.toFixed(1)}`;
}

/** 0:04 */
export function tcShort(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

function pendingState(jobStatus: string): GapSegment['state'] {
  return jobStatus === 'failed' ? 'skipped' : 'pending';
}

export function buildSegments(job: JobResponse): GapSegment[] {
  if (job.cues && job.cues.length > 0) {
    return job.cues.map((cue) => {
      const duration = cue.end - cue.start;
      return {
        gap_id: cue.gap_id,
        start: cue.start,
        end: cue.end,
        duration,
        word_budget: budgetFor(duration),
        state: cue.text !== null ? 'placed' : 'skipped',
        cue_text: cue.text,
        word_count: cue.word_count,
        skip_reason: cue.skip_reason ?? null,
      };
    });
  }

  // No cues yet — placeholder windows so the timeline has shape while we wait.
  const count = job.gap_count ?? 0;
  const state = pendingState(job.status);
  return Array.from({ length: count }, (_, i) => {
    const start = i * 6;
    return {
      gap_id: `gap_${String(i).padStart(3, '0')}`,
      start,
      end: start + 5,
      duration: 5,
      word_budget: budgetFor(5),
      state,
    };
  });
}

/** Plain-words budget line: "8 of 46 words allowed". */
export function budgetLine(seg: GapSegment) {
  return `${seg.word_count ?? 0} of ${seg.word_budget} words allowed`;
}

/** Why a window was left alone, in the describer's own terms. */
export function skipLine() {
  return 'Left silent — too short to say anything useful.';
}

export function skipDetail(seg: GapSegment) {
  return `Only ${seg.word_budget} words would have fitted — the agent chose to say nothing.`;
}
