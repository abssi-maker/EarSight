/**
 * Typed wrappers for the EarSight orchestrator REST API.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:8000';

export interface JobRequest {
  video_uri: string;
  label?: string;
}

export interface JobResponse {
  job_id: string;
  status: string;
  result_video_url?: string | null;
  vtt_url?: string | null;
  error?: string | null;
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
