'use client';

import { c, mono, sans } from '@/lib/theme';
import { GapSegment, cueLabel, spokenSeconds, tcShort } from '@/lib/segments';

interface Props {
  peaks?: number[] | null;
  duration: number;
  segments: GapSegment[];
  currentTime: number;
  selectedId: string | null;
  onSelect: (gapId: string) => void;
  onSeek: (t: number) => void;
}

const trackLabel: React.CSSProperties = {
  flex: 1, borderBottom: `1px solid ${c.rule}`, display: 'flex',
  flexDirection: 'column', justifyContent: 'center', padding: '0 12px', gap: 2,
};

export default function Timeline({
  peaks, duration, segments, currentTime, selectedId, onSelect, onSeek,
}: Props) {
  const dur = duration > 0 ? duration : 60;
  const pct = (t: number) => `${(t / dur) * 100}%`;
  const wid = (a: number, b: number) => `${((b - a) / dur) * 100}%`;

  // Tick every 5s, and never more than ~14 labels.
  const step = dur > 140 ? 30 : dur > 70 ? 10 : 5;
  const ticks: number[] = [];
  for (let s = 0; s <= dur; s += step) ticks.push(s);

  const inGap = (t: number) => segments.some((g) => t >= g.start && t <= g.end);

  function seekFromEvent(e: React.MouseEvent<HTMLDivElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(dur, ((e.clientX - box.left) / box.width) * dur)));
  }

  return (
    <section
      aria-label="Timeline"
      style={{
        background: c.panel, display: 'grid', gridTemplateColumns: '118px 1fr',
        minHeight: 0, borderTop: `1px solid ${c.rule}`, fontFamily: sans,
      }}
    >
      {/* track headers */}
      <div style={{ borderRight: `1px solid ${c.rule}`, display: 'flex', flexDirection: 'column' }}>
        <div style={{ height: 26, borderBottom: `1px solid ${c.rule}`, flex: 'none' }} />
        {[
          ['DIALOGUE', 'we must stay silent'],
          ['DESCRIPTION', 'where we may speak'],
          ['NARRATION', 'spoken length'],
        ].map(([t, s], i) => (
          <div key={t} style={{ ...trackLabel, borderBottom: i === 2 ? 0 : `1px solid ${c.rule}` }}>
            <b style={{ fontFamily: mono, fontSize: 10, fontWeight: 500, color: c.text, letterSpacing: '0.06em' }}>{t}</b>
            <span style={{ fontFamily: mono, fontSize: 9, color: c.faint }}>{s}</span>
          </div>
        ))}
      </div>

      {/* tracks */}
      <div style={{ position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
           onClick={seekFromEvent}>
        {/* ruler */}
        <div style={{ height: 26, borderBottom: `1px solid ${c.rule}`, position: 'relative', flex: 'none' }}>
          {ticks.map((s) => (
            <div key={s} style={{ position: 'absolute', top: 0, bottom: 0, left: pct(s), borderLeft: `1px solid ${c.rule2}` }}>
              <span style={{ position: 'absolute', left: 5, top: 7, fontFamily: mono, fontSize: 9.5, color: c.faint }}>
                {tcShort(s)}
              </span>
            </div>
          ))}
        </div>

        {/* 1 — dialogue */}
        <div style={{ flex: 1, borderBottom: `1px solid ${c.rule}`, position: 'relative' }}>
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', gap: 1, padding: '0 1px' }}>
            {(peaks ?? []).map((v, i) => {
              const t = ((i + 0.5) / (peaks!.length)) * dur;
              const quiet = inGap(t);
              return (
                <div key={i} style={{
                  flex: 1, borderRadius: 1, background: c.blue,
                  opacity: quiet ? 0.5 : 0.55,
                  height: `${Math.max(2, (quiet ? v * 0.12 : v) * 78)}%`,
                }} />
              );
            })}
          </div>
          {segments.map((g) => (
            <div key={g.gap_id} style={{
              position: 'absolute', top: 0, bottom: 0, left: pct(g.start), width: wid(g.start, g.end),
              background: c.amberWash,
              borderLeft: `1px solid ${c.amberEdge}`, borderRight: `1px solid ${c.amberEdge}`,
            }} />
          ))}
        </div>

        {/* 2 — description */}
        <div style={{ flex: 1, borderBottom: `1px solid ${c.rule}`, position: 'relative' }}>
          {segments.map((g, i) => {
            const sel = g.gap_id === selectedId;
            const isSilent = g.state === 'skipped';
            return (
              <button
                key={g.gap_id}
                onClick={(e) => { e.stopPropagation(); onSelect(g.gap_id); }}
                title={cueLabel(g)}
                style={{
                  position: 'absolute', top: 10, bottom: 10,
                  left: pct(g.start), width: wid(g.start, g.end),
                  background: isSilent ? 'transparent' : (sel ? c.amberFillSel : c.amberFill),
                  border: `1px ${isSilent ? 'dashed' : 'solid'} ${isSilent ? c.rule2 : c.amber}`,
                  boxShadow: sel && !isSilent ? `0 0 0 1px ${c.amber}` : 'none',
                  borderRadius: 3, display: 'flex', alignItems: 'center',
                  padding: '0 8px', overflow: 'hidden', cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{
                  fontFamily: mono, fontSize: 10, whiteSpace: 'nowrap',
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  color: g.state === 'placed' ? c.amber : c.dim,
                  fontStyle: g.state === 'placed' ? 'normal' : 'italic',
                }}>
                  {cueLabel(g, true)}
                </span>
              </button>
            );
          })}
        </div>

        {/* 3 — narration */}
        <div style={{ flex: 1, position: 'relative' }}>
          {segments.filter((g) => g.state === 'placed').map((g) => {
            const spoken = Math.max(0.6, spokenSeconds(g.word_count ?? 0));
            const from = g.start + 0.4;
            return (
              <div key={g.gap_id} style={{ display: 'contents' }}>
                <div
                  title={`${g.word_count} words · ${spoken.toFixed(1)}s of speech inside a ${g.duration.toFixed(1)}s window`}
                  style={{
                    position: 'absolute', top: 14, bottom: 14,
                    left: pct(from), width: wid(0, spoken),
                    background: 'rgba(245,166,35,0.5)', border: `1px solid ${c.amber}`,
                    borderRadius: 3,
                  }}
                />
                <span style={{
                  position: 'absolute', top: '50%', left: pct(from + spoken),
                  transform: 'translateY(-50%)', marginLeft: 7,
                  fontFamily: mono, fontSize: 9.5, color: c.dim, whiteSpace: 'nowrap',
                }}>
                  {g.word_count} words · {spoken.toFixed(1)}s
                </span>
              </div>
            );
          })}
        </div>

        {/* playhead */}
        <div style={{
          position: 'absolute', top: 0, bottom: 0, width: 1,
          background: c.amber, left: pct(Math.min(currentTime, dur)), zIndex: 5,
          pointerEvents: 'none',
        }}>
          <div style={{
            position: 'absolute', top: -1, left: -4, width: 9, height: 9,
            background: c.amber, borderRadius: 1,
          }} />
        </div>
      </div>
    </section>
  );
}
