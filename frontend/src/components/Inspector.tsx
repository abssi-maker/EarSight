'use client';

import { c, mono, sans } from '@/lib/theme';
import {
  GapSegment, cueLabel, skipDetail, WORDS_PER_SECOND,
} from '@/lib/segments';

interface Props {
  segment: GapSegment | null;
  index: number;
  frameUrl?: string;
}

const groupHead: React.CSSProperties = {
  fontFamily: mono, fontSize: 9.5, letterSpacing: '0.15em',
  textTransform: 'uppercase', color: c.faint, marginBottom: 8,
};

export default function Inspector({ segment, index, frameUrl }: Props) {
  const src = frameUrl ? `/api/frame?url=${encodeURIComponent(frameUrl)}` : undefined;
  const isSilent = segment?.state === 'skipped';

  return (
    <section
      aria-label="Selected description"
      style={{
        background: c.panel, borderLeft: `1px solid ${c.rule}`,
        display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: sans,
      }}
    >
      <div style={{
        padding: '11px 14px', borderBottom: `1px solid ${c.rule}`, flex: 'none',
        fontFamily: mono, fontSize: 10.5, letterSpacing: '0.1em',
        textTransform: 'uppercase', color: c.text,
        borderBottomColor: c.rule,
      }}>
        <span style={{ borderBottom: `2px solid ${c.amber}`, paddingBottom: 9 }}>
          Description {String(index + 1).padStart(2, '0')}
        </span>
      </div>

      {!segment ? (
        <p style={{ padding: 14, fontFamily: mono, fontSize: 11, color: c.dim }}>
          Select a description on the left.
        </p>
      ) : (
        <div style={{ padding: 14, overflowY: 'auto' }}>
          <div style={{
            aspectRatio: '16 / 9', borderRadius: 4, overflow: 'hidden',
            border: `1px solid ${c.rule2}`, background: c.raised,
          }}>
            {src && (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={src}
                alt={`Video frame at ${segment.start.toFixed(1)} seconds, analysed for this description`}
                style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              />
            )}
          </div>
          <div style={{
            fontFamily: mono, fontSize: 9.5, color: c.faint, letterSpacing: '0.09em',
            textTransform: 'uppercase', margin: '7px 0 16px',
            display: 'flex', justifyContent: 'space-between', gap: 8,
          }}>
            <span>the frame gemini watched</span>
            <span>{segment.gap_id}</span>
          </div>

          <p style={{
            fontSize: 16.5, lineHeight: 1.42, margin: '0 0 16px',
            letterSpacing: '-0.008em',
            color: segment.state === 'placed' ? c.text : c.dim,
            fontStyle: segment.state === 'placed' ? 'normal' : 'italic',
          }}>
            {cueLabel(segment)}
          </p>

          <div style={{ marginBottom: 15 }}>
            <div style={groupHead}>Word budget</div>
            {!isSilent && (
              <div style={{
                height: 6, background: c.raised, borderRadius: 99,
                overflow: 'hidden', border: `1px solid ${c.rule}`,
              }}>
                <div style={{
                  height: '100%', background: c.amber,
                  width: `${Math.min(100, ((segment.word_count ?? 0) / Math.max(1, segment.word_budget)) * 100)}%`,
                }} />
              </div>
            )}
            <div style={{ fontFamily: mono, fontSize: 12, color: c.text, marginTop: 8 }}>
              {isSilent ? skipDetail(segment) : (
                <>
                  <b style={{ color: c.amber, fontWeight: 600 }}>{segment.word_count ?? 0}</b>
                  {` of ${segment.word_budget} words allowed`}
                </>
              )}
            </div>
            {!isSilent && (
              <>
                <div style={{ fontFamily: mono, fontSize: 10.5, color: c.ok, marginTop: 6 }}>
                  ✓ fits inside the {segment.duration.toFixed(1)}s of silence
                </div>
                <div style={{ fontFamily: mono, fontSize: 10.5, color: c.ok, marginTop: 6 }}>
                  ✓ clear of dialogue on both sides
                </div>
              </>
            )}
          </div>

          <div>
            <div style={groupHead}>Why {segment.word_budget}</div>
            <div style={{
              fontFamily: mono, fontSize: 10, color: c.dim, lineHeight: 1.7,
              borderLeft: `2px solid ${c.rule2}`, paddingLeft: 10,
            }}>
              {segment.duration.toFixed(1)}s of silence at {WORDS_PER_SECOND} words per second.
              The window already excludes a 0.4s margin at each end, so the
              narration never runs into speech.
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
