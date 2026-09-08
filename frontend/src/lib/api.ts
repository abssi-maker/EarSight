/**
 * Typed wrappers for the EarSight orchestrator REST API.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:8000';

export interface JobRequest {
  video_uri: string;
  label?: string;
}

export interface CueRecord {
  cue_id: string;
  gap_id: string;
  start: number;
  end: number;
  text: string | null;
  word_count: number;
  skip_reason?: string | null;
}

export interface PipelineEvent {
  ts: number;
  topic: string;
  service: string;
  direction: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
  gap_count?: number | null;
  transcript_word_count?: number | null;
  peaks_uri?: string | null;
  cues?: CueRecord[] | null;
  events?: PipelineEvent[] | null;
  result_video_url?: string | null;
  vtt_url?: string | null;
  error?: string | null;
}

export interface PeaksData {
  duration: number;
  peaks: number[];
}

export async function uploadVideo(file: File): Promise<string> {
  // Upload the video to the orchestrator's /upload endpoint, which saves to GCS
  // and returns a gs:// URI.
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /upload ${res.status}: ${text}`);
  }
  const data = await res.json();
  return data.gcs_uri as string;
}

export async function createJob(req: JobRequest): Promise<JobResponse> {
  const res = await fetch(`${BASE_URL}/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST /jobs ${res.status}: ${text}`);
  }
  return res.json();
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const res = await fetch(`${BASE_URL}/jobs/${jobId}`);
  if (!res.ok) {
    throw new Error(`GET /jobs/${jobId} ${res.status}`);
  }
  return res.json();
}

export async function fetchPeaks(peaksUri: string): Promise<PeaksData | null> {
  // peaks_uri is a GCS signed URL or gs:// — proxy via our own API
  try {
    const proxyUrl = `/api/peaks?url=${encodeURIComponent(peaksUri)}`;
    const res = await fetch(proxyUrl);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
