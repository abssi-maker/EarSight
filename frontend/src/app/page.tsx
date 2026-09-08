'use client';

import { useState, useCallback, useRef } from 'react';
import UploadZone from '@/components/UploadZone';
import PipelineView, { GapSegment, SegmentState } from '@/components/PipelineView';
import Player from '@/components/Player';
import { uploadVideo, createJob, getJob, JobResponse } from '@/lib/api';

// Map pipeline status → SegmentState for each gap
function statusToSegmentState(jobStatus: string): SegmentState {
  switch (jobStatus) {
    case 'transcribing': return 'detected';
    case 'framing':      return 'framing';
    case 'describing':   return 'describing';
    case 'synthesising': return 'synthesising';
    case 'mixing':       return 'synthesising';
    case 'done':         return 'placed';
    case 'failed':       return 'skipped';
    default:             return 'detected';
  }
}

function buildSegments(job: JobResponse, activeCueTime?: number): GapSegment[] {
  // If we have cue data, build one segment per cue/gap
  if (job.cues && job.cues.length > 0) {
    return job.cues.map((c) => {
      const duration = c.end - c.start;
      const budget = Math.floor(duration * 2.75);
      const isActive =
        activeCueTime !== undefined &&
        c.text !== null &&
        activeCueTime >= c.start &&
        activeCueTime <= c.end;
      return {
        gap_id: c.gap_id,
        start: c.start,
        end: c.end,
        duration,
        word_budget: budget,
        state: c.text !== null ? 'placed' : 'skipped',
        cue_text: c.text,
        word_count: c.word_count,
        skip_reason: c.skip_reason ?? null,
        active_cue: isActive,
      };
    });
  }

  // No cue data yet — synthesise placeholder segments from gap_count
  const count = job.gap_count ?? 0;
  const state = statusToSegmentState(job.status);
  // We don't have per-gap timing yet, so show equal-width placeholders
  const placeholderDuration = 5;
  return Array.from({ length: count }, (_, i) => ({
    gap_id: `gap_${String(i).padStart(3, '0')}`,
    start: i * (placeholderDuration + 1),
    end: i * (placeholderDuration + 1) + placeholderDuration,
    duration: placeholderDuration,
    word_budget: Math.floor(placeholderDuration * 2.75),
    state,
  }));
}

type AppState = 'idle' | 'uploading' | 'processing' | 'done' | 'failed';

export default function Home() {
  const [appState, setAppState] = useState<AppState>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState('');
  const [currentTime, setCurrentTime] = useState<number | undefined>(undefined);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback((id: string) => {
    stopPolling();
    const orchestratorUrl = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:8000';
    pollRef.current = setInterval(async () => {
      try {
        const data = await getJob(id);
        setJob(data);
        if (data.status === 'done') {
          stopPolling();
          setAppState('done');
        } else if (data.status === 'failed') {
          stopPolling();
          setAppState('failed');
          setError(data.error ?? 'Pipeline failed.');
        }
        // suppress unused variable warning
        void orchestratorUrl;
      } catch {
        // ignore transient poll errors
      }
    }, 2000);
  }, [stopPolling]);

  async function handleFile(file: File) {
    setError('');
    setJob(null);
    setJobId(null);
    setAppState('uploading');

    try {
      // Upload video to GCS via orchestrator /upload
      const gcsUri = await uploadVideo(file);

      const created = await createJob({ video_uri: gcsUri, label: file.name });
      setJobId(created.job_id);
      setJob(created);
      setAppState('processing');
      startPolling(created.job_id);
    } catch (err) {
      setError(String(err));
      setAppState('failed');
    }
  }

  const segments = job ? buildSegments(job, currentTime) : [];
  const isDone = appState === 'done' && job?.result_video_url && job?.vtt_url;

  return (
    <main
      id="main-content"
      style={{ maxWidth: 720, margin: '64px auto', padding: '0 24px' }}
    >
      {/* Skip link */}
      <a
        href="#main-content"
        style={{
          position: 'absolute',
          left: -9999,
          top: 'auto',
          width: 1,
          height: 1,
          overflow: 'hidden',
        }}
      >
        Skip to main content
      </a>

      {/* Header */}
      <header style={{ marginBottom: 40 }}>
        <h1 style={{ color: '#f5a623', fontSize: 28, letterSpacing: '0.06em', margin: '0 0 6px' }}>
          EARSIGHT
        </h1>
        <p style={{ color: '#767676', fontSize: 14, margin: 0 }}>
          Drop a video. Hear everything.
        </p>
      </header>

      {/* Upload zone (hidden once processing starts) */}
      {(appState === 'idle' || appState === 'uploading') && (
        <UploadZone onFile={handleFile} disabled={appState === 'uploading'} />
      )}

      {/* Error */}
      {error && (
        <p role="alert" style={{ color: '#e55', marginTop: 16, fontSize: 13 }}>
          {error}
        </p>
      )}

      {/* Job metadata */}
      {jobId && (
        <div style={{ marginTop: 24, fontSize: 12, color: '#555' }}>
          <span>Job&nbsp;</span>
          <code style={{ color: '#888' }}>{jobId}</code>
          <span style={{ marginLeft: 12 }}>
            Status:{' '}
            <strong style={{ color: job?.status === 'done' ? '#f5a623' : '#aaa' }}>
              {job?.status ?? 'queued'}
            </strong>
          </span>
        </div>
      )}

      {/* Pipeline timeline */}
      {(appState === 'processing' || appState === 'done') && (
        <PipelineView segments={segments} />
      )}

      {/* Player — appears when done */}
      {isDone && (
        <Player
          videoUrl={job!.result_video_url!}
          vttUrl={job!.vtt_url!}
          onTimeUpdate={setCurrentTime}
        />
      )}

      {/* Upload another */}
      {(appState === 'done' || appState === 'failed') && (
        <button
          onClick={() => {
            setAppState('idle');
            setJob(null);
            setJobId(null);
            setError('');
          }}
          style={{
            marginTop: 32,
            padding: '10px 20px',
            background: 'transparent',
            border: '1px solid #333',
            borderRadius: 6,
            color: '#aaa',
            cursor: 'pointer',
            fontSize: 13,
            fontFamily: 'monospace',
          }}
          aria-label="Upload a new video"
        >
          Upload another video
        </button>
      )}
    </main>
  );
}
