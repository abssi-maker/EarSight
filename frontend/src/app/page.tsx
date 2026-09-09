'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import UploadZone from '@/components/UploadZone';
import TopBar from '@/components/TopBar';
import CueList from '@/components/CueList';
import Inspector from '@/components/Inspector';
import Player from '@/components/Player';
import Timeline from '@/components/Timeline';
import AgentLane from '@/components/AgentLane';
import {
  uploadVideo, createJob, getJob, JobResponse, fetchPeaks, PeaksData,
} from '@/lib/api';
import { buildSegments } from '@/lib/segments';
import { c, mono } from '@/lib/theme';

type AppState = 'idle' | 'uploading' | 'processing' | 'done' | 'failed';

export default function Home() {
  const [appState, setAppState] = useState<AppState>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [fileLabel, setFileLabel] = useState('');
  const [error, setError] = useState('');
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [peaksData, setPeaksData] = useState<PeaksData | null>(null);
  const [described, setDescribed] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const peaksFetchedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPolling = useCallback((id: string) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const data = await getJob(id);
        setJob(data);

        if (data.peaks_uri && !peaksFetchedRef.current) {
          peaksFetchedRef.current = true;
          fetchPeaks(data.peaks_uri).then((p) => { if (p) setPeaksData(p); });
        }

        if (data.status === 'done') { stopPolling(); setAppState('done'); }
        else if (data.status === 'failed') {
          stopPolling(); setAppState('failed');
          setError(data.error ?? 'Pipeline failed.');
        }
      } catch {
        // transient poll error — keep polling
      }
    }, 2000);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  async function handleFile(file: File) {
    setError(''); setJob(null); setJobId(null); setPeaksData(null);
    setSelectedId(null); setCurrentTime(0); setDuration(0);
    peaksFetchedRef.current = false;
    setFileLabel(file.name);
    setAppState('uploading');
    try {
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

  function reset() {
    stopPolling();
    setAppState('idle'); setJob(null); setJobId(null); setError('');
    setPeaksData(null); setSelectedId(null); setFileLabel('');
    setCurrentTime(0); setDuration(0); setDescribed(true);
    peaksFetchedRef.current = false;
  }

  const segments = job ? buildSegments(job) : [];

  // Default the inspector to the first window as soon as cues arrive.
  useEffect(() => {
    if (!selectedId && segments.length > 0) setSelectedId(segments[0].gap_id);
  }, [segments, selectedId]);

  const selectedIndex = Math.max(0, segments.findIndex((s) => s.gap_id === selectedId));
  const selected = segments[selectedIndex] ?? null;

  const active = segments.find(
    (s) => s.cue_text && currentTime >= s.start && currentTime <= s.end,
  );

  const ready = Boolean(job?.result_video_url && job?.vtt_url);
  const src = described
    ? (job?.result_video_url ?? '')
    : (job?.source_video_url ?? job?.result_video_url ?? '');

  function seek(t: number) {
    const v = videoRef.current;
    if (v) v.currentTime = t;
    setCurrentTime(t);
  }

  if (appState === 'idle' || appState === 'uploading') {
    return (
      <main style={{ height: '100vh', background: c.bg }}>
        <UploadZone onFile={handleFile} disabled={appState === 'uploading'} />
        {error && (
          <p role="alert" style={{
            position: 'fixed', bottom: 24, left: 0, right: 0, textAlign: 'center',
            color: c.err, fontFamily: mono, fontSize: 13,
          }}>
            {error}
          </p>
        )}
      </main>
    );
  }

  return (
    <main
      style={{
        height: '100vh',
        display: 'grid',
        gridTemplateRows: '54px minmax(0, 1fr) 62px 250px',
        background: c.bg,
      }}
    >
      <TopBar
        fileLabel={fileLabel || 'video'}
        duration={duration}
        jobId={jobId}
        status={job?.status ?? 'queued'}
        described={described}
        canCompare={Boolean(job?.source_video_url) && ready}
        onToggle={setDescribed}
        onReset={reset}
        downloadUrl={ready ? job?.result_video_url : null}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '268px minmax(0, 1fr) 330px', minHeight: 0 }}>
        <CueList
          segments={segments}
          frameUrls={job?.frame_urls}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />

        {ready ? (
          <Player
            videoRef={videoRef}
            src={src}
            vttUrl={job!.vtt_url!}
            described={described}
            activeText={active?.cue_text ?? null}
            currentTime={currentTime}
            duration={duration}
            onTime={setCurrentTime}
            onDuration={setDuration}
          />
        ) : (
          <section
            aria-label="Described video player"
            style={{
              background: '#050506', display: 'flex', alignItems: 'center',
              justifyContent: 'center', flexDirection: 'column', gap: 10,
            }}
          >
            <p style={{ fontFamily: mono, fontSize: 13, color: c.dim, margin: 0 }}>
              {error ? 'Pipeline failed.' : 'Finding the silences…'}
            </p>
            <p style={{ fontFamily: mono, fontSize: 11, color: c.faint, margin: 0 }}>
              {error || `${job?.status ?? 'queued'} · ${segments.length} window${segments.length === 1 ? '' : 's'} so far`}
            </p>
          </section>
        )}

        <Inspector
          segment={selected}
          index={selectedIndex}
          frameUrl={selected ? job?.frame_urls?.[selected.gap_id] : undefined}
        />
      </div>

      <AgentLane events={job?.events ?? []} />

      <Timeline
        peaks={peaksData?.peaks}
        duration={peaksData?.duration ?? duration}
        segments={segments}
        currentTime={currentTime}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onSeek={seek}
      />
    </main>
  );
}
