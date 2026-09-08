'use client';

/**
 * Waveform.tsx — inline SVG waveform timeline.
 *
 * Full width, time-proportional across the real video duration.
 * - Peaks: normalised amplitude bars rendered as dim grey background
 * - Dialogue regions: slightly lighter grey (from transcript word spans)
 * - Silence gap windows: amber outline
 * - Active gap: fills with solid amber as its cue plays
 * - Playhead: thin amber vertical line tracking video.currentTime
 */

import { useEffect, useRef } from 'react';
import { GapSegment } from './PipelineView';

interface WordSpan {
  start: number;
  end: number;
}

interface Props {
  peaks: number[];           // 0.0–1.0, length ~1000
  duration: number;          // total video duration in seconds
  segments: GapSegment[];    // silence gaps with state
  currentTime?: number;      // video playhead in seconds
  wordSpans?: WordSpan[];    // dialogue word spans for shading
  onSeek?: (t: number) => void; // called when user clicks to seek
  height?: number;
}

export default function Waveform({
  peaks,
  duration,
  segments,
  currentTime = 0,
  wordSpans = [],
  onSeek,
  height = 80,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  if (!peaks || peaks.length === 0 || duration <= 0) {
    return (
      <div
        style={{
          height,
          background: '#111',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span style={{ color: '#333', fontSize: 11, fontFamily: 'monospace' }}>
          waveform loading…
        </span>
      </div>
    );
  }

  const W = 720; // logical SVG width
  const H = height;
  const mid = H / 2;

  function toPx(t: number): number {
    return (t / duration) * W;
  }

  // Build peak bars path
  const barWidth = W / peaks.length;
  const peakBars = peaks
    .map((v, i) => {
      const x = i * barWidth;
      const barH = Math.max(1, v * mid * 0.9);
      return `M${x.toFixed(1)},${(mid - barH).toFixed(1)}L${x.toFixed(1)},${(mid + barH).toFixed(1)}`;
    })
    .join(' ');

  function handleClick(e: React.MouseEvent<SVGSVGElement>) {
    if (!onSeek || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    onSeek(ratio * duration);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height, display: 'block', cursor: onSeek ? 'crosshair' : 'default' }}
      role="img"
      aria-label={`Waveform timeline. ${segments.length} silence gaps detected.`}
      onClick={handleClick}
    >
      {/* Background */}
      <rect x={0} y={0} width={W} height={H} fill="#0e0e0e" />

      {/* Peak amplitude bars — dim grey */}
      <path d={peakBars} stroke="#2a2a2a" strokeWidth={barWidth * 0.8} fill="none" />

      {/* Dialogue word spans — slightly lighter grey overlay */}
      {wordSpans.map((span, i) => (
        <rect
          key={i}
          x={toPx(span.start)}
          y={0}
          width={Math.max(1, toPx(span.end) - toPx(span.start))}
          height={H}
          fill="#1e1e1e"
          opacity={0.7}
        />
      ))}

      {/* Silence gap windows */}
      {segments.map((seg) => {
        const x = toPx(seg.start);
        const w = Math.max(2, toPx(seg.end) - toPx(seg.start));
        const isPlaced = seg.state === 'placed';
        const isActive = seg.active_cue;
        return (
          <g key={seg.gap_id}>
            {/* Amber fill — solid when active/placed */}
            <rect
              x={x} y={0} width={w} height={H}
              fill={isActive ? '#f5a623' : isPlaced ? 'rgba(245,166,35,0.18)' : 'rgba(245,166,35,0.05)'}
              stroke="#f5a623"
              strokeWidth={1}
              opacity={1}
            />
          </g>
        );
      })}

      {/* Playhead */}
      {duration > 0 && (
        <line
          x1={toPx(currentTime)}
          y1={0}
          x2={toPx(currentTime)}
          y2={H}
          stroke="#f5a623"
          strokeWidth={1.5}
          opacity={0.9}
        />
      )}
    </svg>
  );
}
