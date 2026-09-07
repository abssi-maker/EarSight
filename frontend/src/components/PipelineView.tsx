'use client';

// Segment states in pipeline order
export type SegmentState =
  | 'detected'
  | 'framing'
  | 'describing'
  | 'synthesising'
  | 'placed'
  | 'skipped';

export interface GapSegment {
  gap_id: string;
  start: number;
  end: number;
  duration: number;
  word_budget: number;
  state: SegmentState;
  cue_text?: string | null;
  word_count?: number;
  skip_reason?: string | null;
  active_cue?: boolean; // true when video playback is inside this cue
}

interface Props {
  segments: GapSegment[];
  totalDuration?: number;
}

const STATE_LABELS: Record<SegmentState, string> = {
  detected: 'gap detected',
  framing: 'extracting frame',
  describing: 'writing copy',
  synthesising: 'synthesising',
  placed: 'placed',
  skipped: 'skipped',
};

const STATE_COLORS: Record<SegmentState, string> = {
  detected: '#444',
  framing: '#6b5',
  describing: '#56b',
  synthesising: '#b96',
  placed: '#f5a623',
  skipped: '#333',
};

function fmt(s: number): string {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1).padStart(4, '0');
  return `${m}:${sec}`;
}

export default function PipelineView({ segments, totalDuration }: Props) {
  if (segments.length === 0) {
    return (
      <p style={{ color: '#555', fontSize: 13, marginTop: 24 }}>
        Waiting for gap map…
      </p>
    );
  }

  const total = totalDuration ?? (segments[segments.length - 1]?.end ?? 60);

  return (
    <section aria-label="Pipeline timeline" style={{ marginTop: 32 }}>
      <h2 style={{ fontSize: 13, color: '#666', letterSpacing: '0.1em', marginBottom: 12, textTransform: 'uppercase' }}>
        Pipeline · {segments.length} gaps
      </h2>

      {/* Macro timeline bar */}
      <div
        role="img"
        aria-label="Timeline showing gap positions"
        style={{
          position: 'relative',
          height: 8,
          background: '#1a1a1a',
          borderRadius: 4,
          marginBottom: 24,
          overflow: 'hidden',
        }}
      >
        {segments.map((seg) => (
          <div
            key={seg.gap_id}
            style={{
              position: 'absolute',
              left: `${(seg.start / total) * 100}%`,
              width: `${Math.max((seg.duration / total) * 100, 0.5)}%`,
              height: '100%',
              background: STATE_COLORS[seg.state],
              opacity: seg.active_cue ? 1 : 0.6,
              transition: 'background 0.4s',
            }}
          />
        ))}
      </div>

      {/* Per-gap cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {segments.map((seg) => {
          const fillPct =
            seg.state === 'placed' && seg.word_budget > 0
              ? Math.min(100, ((seg.word_count ?? 0) / seg.word_budget) * 100)
              : seg.state === 'skipped'
              ? 0
              : seg.state === 'detected'
              ? 0
              : 50; // in-progress states show half-filled

          return (
            <article
              key={seg.gap_id}
              aria-label={`Gap ${seg.gap_id} from ${fmt(seg.start)} to ${fmt(seg.end)}, state: ${STATE_LABELS[seg.state]}`}
              style={{
                border: `1px solid ${seg.active_cue ? '#f5a623' : '#1e1e1e'}`,
                borderRadius: 6,
                padding: '10px 14px',
                background: seg.active_cue ? 'rgba(245,166,35,0.06)' : '#111',
                transition: 'border-color 0.2s, background 0.2s',
              }}
            >
              {/* Header row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: '#555', fontFamily: 'monospace' }}>
                  {fmt(seg.start)} – {fmt(seg.end)}&nbsp;
                  <span style={{ color: '#333' }}>({seg.duration.toFixed(1)}s)</span>
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: STATE_COLORS[seg.state],
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                  }}
                >
                  {STATE_LABELS[seg.state]}
                </span>
              </div>

              {/* Word-budget fill bar */}
              <div
                aria-label={`Word budget: ${seg.word_count ?? 0} of ${seg.word_budget} words used`}
                style={{
                  height: 3,
                  background: '#1e1e1e',
                  borderRadius: 2,
                  marginBottom: seg.cue_text ? 8 : 0,
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    width: `${fillPct}%`,
                    background: seg.state === 'skipped' ? '#333' : '#f5a623',
                    transition: 'width 0.5s',
                  }}
                />
              </div>

              {/* Cue text or skip reason */}
              {seg.cue_text && (
                <p
                  style={{
                    margin: 0,
                    fontSize: 12,
                    color: '#c8c8c8',
                    lineHeight: 1.5,
                    fontFamily: 'monospace',
                  }}
                >
                  {seg.cue_text}
                  <span style={{ color: '#555', marginLeft: 8 }}>
                    [{seg.word_count}/{seg.word_budget}w]
                  </span>
                </p>
              )}
              {seg.state === 'skipped' && seg.skip_reason && (
                <p style={{ margin: 0, fontSize: 11, color: '#444', fontFamily: 'monospace' }}>
                  skipped: {seg.skip_reason}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
