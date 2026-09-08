'use client';

/**
 * Player.tsx — custom transport controls for described video.
 *
 * Features:
 * - Play/pause button with keyboard shortcut (Space)
 * - Waveform-based scrubber (reuses Waveform component)
 * - Live cue readout showing the active description text as it speaks
 * - Keyboard: Space = play/pause, ← = −5s, → = +5s, Tab-navigable
 * - Full ARIA labels and visible focus rings
 * - Active cue wired back via onTimeUpdate for timeline highlight
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Waveform from './Waveform';
import { GapSegment } from './PipelineView';
import { PeaksData } from '@/lib/api';

interface Props {
  videoUrl: string;
  vttUrl: string;
  onTimeUpdate?: (currentTime: number) => void;
  segments?: GapSegment[];
  peaksData?: PeaksData | null;
}

export default function Player({
  videoUrl,
  vttUrl,
  onTimeUpdate,
  segments = [],
  peaksData,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [activeCueText, setActiveCueText] = useState<string | null>(null);

  // Proxy VTT to avoid CORS on GCS signed URLs
  const proxiedVtt = `/api/vtt?url=${encodeURIComponent(vttUrl)}`;

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const t = video.currentTime;
    setCurrentTime(t);
    onTimeUpdate?.(t);

    // Find active cue text from segments
    const active = segments.find(
      (s) => s.cue_text && t >= s.start && t <= s.end
    );
    setActiveCueText(active?.cue_text ?? null);
  }, [onTimeUpdate, segments]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('durationchange', () => setDuration(video.duration || 0));
    video.addEventListener('play', () => setPlaying(true));
    video.addEventListener('pause', () => setPlaying(false));
    return () => {
      video.removeEventListener('timeupdate', handleTimeUpdate);
    };
  }, [handleTimeUpdate]);

  // Keyboard handler on the player section
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    const video = videoRef.current;
    if (!video) return;
    if (e.key === ' ' || e.code === 'Space') {
      e.preventDefault();
      playing ? video.pause() : video.play();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      video.currentTime = Math.max(0, video.currentTime - 5);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      video.currentTime = Math.min(video.duration, video.currentTime + 5);
    }
  }, [playing]);

  function togglePlay() {
    const video = videoRef.current;
    if (!video) return;
    playing ? video.pause() : video.play();
  }

  function handleSeek(t: number) {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = t;
  }

  function fmt(s: number): string {
    if (!isFinite(s)) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  }

  // Build word spans from segments for the waveform dialogue shading
  const wordSpans = segments.map((s) => ({ start: s.start, end: s.end }));
  const effectiveDuration = peaksData?.duration || duration || 60;

  return (
    <section
      aria-label="Described video player"
      style={{ marginTop: 32 }}
      onKeyDown={handleKeyDown}
    >
      <h2 style={{ fontSize: 13, color: '#767676', letterSpacing: '0.1em', marginBottom: 12, textTransform: 'uppercase' }}>
        Player
      </h2>

      {/* Hidden video element */}
      <video
        ref={videoRef}
        style={{ display: 'none' }}
        aria-label="Described video with audio description track"
        preload="metadata"
      >
        <source src={videoUrl} type="video/mp4" />
        <track
          kind="descriptions"
          src={proxiedVtt}
          srcLang="en"
          label="Audio descriptions"
          default
        />
      </video>

      {/* Waveform scrubber */}
      {peaksData && (
        <div style={{ marginBottom: 12 }}>
          <Waveform
            peaks={peaksData.peaks}
            duration={effectiveDuration}
            segments={segments}
            currentTime={currentTime}
            wordSpans={wordSpans}
            onSeek={handleSeek}
            height={72}
          />
        </div>
      )}

      {/* Transport controls */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          padding: '10px 0',
        }}
      >
        {/* Play/pause */}
        <button
          onClick={togglePlay}
          aria-label={playing ? 'Pause' : 'Play'}
          style={{
            width: 40, height: 40,
            background: 'transparent',
            border: '1px solid #333',
            borderRadius: 4,
            color: '#f5a623',
            cursor: 'pointer',
            fontSize: 18,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            outline: 'none',
          }}
          onFocus={(e) => (e.currentTarget.style.outline = '2px solid #f5a623')}
          onBlur={(e) => (e.currentTarget.style.outline = 'none')}
        >
          {playing ? '⏸' : '▶'}
        </button>

        {/* Time display */}
        <span
          aria-live="off"
          style={{ fontSize: 12, color: '#767676', fontFamily: 'monospace', minWidth: 90 }}
        >
          {fmt(currentTime)} / {fmt(effectiveDuration)}
        </span>

        {/* Seek back */}
        <button
          onClick={() => handleSeek(Math.max(0, currentTime - 5))}
          aria-label="Seek back 5 seconds"
          style={{
            background: 'transparent', border: '1px solid #222', borderRadius: 4,
            color: '#767676', cursor: 'pointer', fontSize: 11, padding: '4px 8px',
          }}
          onFocus={(e) => (e.currentTarget.style.outline = '2px solid #f5a623')}
          onBlur={(e) => (e.currentTarget.style.outline = 'none')}
        >
          ← 5s
        </button>

        {/* Seek forward */}
        <button
          onClick={() => handleSeek(Math.min(effectiveDuration, currentTime + 5))}
          aria-label="Seek forward 5 seconds"
          style={{
            background: 'transparent', border: '1px solid #222', borderRadius: 4,
            color: '#767676', cursor: 'pointer', fontSize: 11, padding: '4px 8px',
          }}
          onFocus={(e) => (e.currentTarget.style.outline = '2px solid #f5a623')}
          onBlur={(e) => (e.currentTarget.style.outline = 'none')}
        >
          5s →
        </button>
      </div>

      {/* Active cue readout */}
      <div
        role="status"
        aria-live="polite"
        aria-label="Current audio description"
        style={{
          minHeight: 36,
          padding: '8px 12px',
          background: activeCueText ? 'rgba(245,166,35,0.08)' : 'transparent',
          border: activeCueText ? '1px solid rgba(245,166,35,0.3)' : '1px solid transparent',
          borderRadius: 4,
          transition: 'background 0.3s, border-color 0.3s',
          marginTop: 4,
        }}
      >
        {activeCueText ? (
          <p style={{ margin: 0, fontSize: 13, color: '#f5a623', fontFamily: 'monospace', lineHeight: 1.5 }}>
            {activeCueText}
          </p>
        ) : (
          <p style={{ margin: 0, fontSize: 11, color: '#333', fontFamily: 'monospace' }}>
            no active description
          </p>
        )}
      </div>

      <p style={{ fontSize: 11, color: '#555', marginTop: 8 }}>
        Space: play/pause · ← →: seek 5s · click waveform to seek
      </p>
    </section>
  );
}
