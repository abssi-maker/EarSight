'use client';

import { c, mono, sans } from '@/lib/theme';
import { GapSegment, budgetLine, skipLine, tc } from '@/lib/segments';

interface Props {
  segments: GapSegment[];
  frameUrls?: Record<string, string> | null;
  selectedId: string | null;
  onSelect: (gapId: string) => void;
}

function frameSrc(url?: string) {
  return url ? `/api/frame?url=${encodeURIComponent(url)}` : undefined;
}

export default function CueList({ segments, frameUrls, selectedId, onSelect }: Props) {
  const described = segments.filter((s) => s.state === 'placed').length;
  const silent = segments.filter((s) => s.state === 'skipped').length;

  return (
    <section
      aria-label="Description decisions"
      style={{
        background: c.panel, borderRight: `1px solid ${c.rule}`,
        display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: sans,
      }}
    >
      <div style={{ padding: '12px 14px 10px', borderBottom: `1px solid ${c.rule}`, flex: 'none' }}>
        <p style={{ fontSize: 12.5, fontWeight: 600, margin: 0, color: c.text }}>Descriptions</p>
        <p style={{ fontFamily: mono, fontSize: 10, color: c.dim, margin: '4px 0 0' }}>
          {segments.length} silence window{segments.length === 1 ? '' : 's'} · {described} described · {silent} left silent
        </p>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 8, display: 'flex', flexDirection: 'column' }}>
        {segments.map((seg, i) => {
          const sel = seg.gap_id === selectedId;
          const isSilent = seg.state === 'skipped';
          return (
            <button
              key={seg.gap_id}
              onClick={() => onSelect(seg.gap_id)}
              aria-pressed={sel}
              style={{
                display: 'grid', gridTemplateColumns: '88px 1fr', gap: 11,
                padding: '11px 10px', borderRadius: 5, marginBottom: 6,
                border: `1px solid ${sel ? c.amberDim : 'transparent'}`,
                background: sel ? c.hi : 'transparent',
                cursor: 'pointer', textAlign: 'left', width: '100%',
                opacity: isSilent ? 0.72 : 1, fontFamily: sans,
              }}
            >
              <span style={{
                aspectRatio: '16 / 9', borderRadius: 3, display: 'block',
                border: `1px solid ${c.rule2}`, overflow: 'hidden', background: c.raised,
              }}>
                {frameSrc(frameUrls?.[seg.gap_id]) && (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    src={frameSrc(frameUrls?.[seg.gap_id])}
                    alt=""
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                  />
                )}
              </span>
              <span style={{ display: 'block', minWidth: 0 }}>
                <span style={{
                  fontFamily: mono, fontSize: 9, color: c.faint,
                  letterSpacing: '0.1em', display: 'block',
                }}>
                  {String(i + 1).padStart(2, '0')} · {tc(seg.start)} → {tc(seg.end)}
                </span>
                <span style={{
                  fontSize: 12.5, lineHeight: 1.4, margin: '4px 0 6px', display: 'block',
                  color: isSilent ? c.dim : c.text,
                  fontStyle: isSilent ? 'italic' : 'normal',
                }}>
                  {isSilent ? skipLine() : `“${seg.cue_text}”`}
                </span>
                <span style={{
                  fontFamily: mono, fontSize: 9.5, display: 'block',
                  color: sel ? c.amber : c.dim,
                }}>
                  {isSilent ? `only ${seg.word_budget} words would fit` : budgetLine(seg)}
                </span>
              </span>
            </button>
          );
        })}

        <div style={{
          marginTop: 'auto', padding: '12px 6px 4px', borderTop: `1px solid ${c.rule}`,
          fontFamily: mono, fontSize: 10, color: c.faint, lineHeight: 1.9,
        }}>
          Every window was measured before a word was written.<br />
          Nothing was said over dialogue.
        </div>
      </div>
    </section>
  );
}
