'use client';

import { c, mono, sans } from '@/lib/theme';
import { tcShort } from '@/lib/segments';

interface Props {
  fileLabel: string;
  duration: number;
  jobId: string | null;
  status: string;
  described: boolean;
  canCompare: boolean;
  onToggle: (described: boolean) => void;
  onReset: () => void;
  downloadUrl?: string | null;
}

const btn: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 11,
  padding: '8px 14px',
  border: `1px solid ${c.rule2}`,
  borderRadius: 5,
  background: c.raised,
  color: c.dim,
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  textDecoration: 'none',
};

export default function TopBar({
  fileLabel, duration, jobId, status, described, canCompare,
  onToggle, onReset, downloadUrl,
}: Props) {
  const segBtn = (on: boolean): React.CSSProperties => ({
    fontFamily: mono,
    fontSize: 11.5,
    letterSpacing: '0.18em',
    padding: '9px 28px',
    background: on ? c.amber : 'transparent',
    color: on ? c.onAmber : c.dim,
    fontWeight: on ? 600 : 400,
    border: 0,
    cursor: 'pointer',
  });

  return (
    <header
      style={{
        display: 'flex', alignItems: 'center', gap: 18, padding: '0 16px',
        background: c.panel, borderBottom: `1px solid ${c.rule}`,
        fontFamily: sans,
      }}
    >
      <h1 style={{
        fontFamily: mono, fontSize: 14, letterSpacing: '0.3em',
        fontWeight: 600, margin: 0, whiteSpace: 'nowrap', color: c.text,
      }}>
        EAR<span style={{ color: c.amber }}>SIGHT</span>
      </h1>

      <div style={{ width: 1, height: 24, background: c.rule2 }} />

      <div style={{ fontFamily: mono, fontSize: 10.5, color: c.dim, whiteSpace: 'nowrap' }}>
        {fileLabel}{duration > 0 && ` · ${tcShort(duration)}`}
      </div>

      {jobId && (
        <div style={{ fontFamily: mono, fontSize: 10.5, color: c.dim, whiteSpace: 'nowrap' }}>
          <span style={{
            display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
            background: status === 'done' ? c.ok : c.amber, marginRight: 6,
            verticalAlign: 1,
          }} />
          JOB {jobId.slice(0, 8).toUpperCase()} ·{' '}
          <b style={{ color: status === 'done' ? c.ok : c.amber, fontWeight: 500 }}>
            {status.toUpperCase()}
          </b>
        </div>
      )}

      {/* HERO — the comparison */}
      <div style={{ margin: '0 auto', display: 'flex', alignItems: 'center', gap: 14 }}>
        {canCompare && (
          <>
            <div
              role="group"
              aria-label="Compare original and described audio"
              style={{
                display: 'inline-flex', border: `1px solid ${c.rule2}`,
                borderRadius: 6, overflow: 'hidden', background: c.raised,
              }}
            >
              <button onClick={() => onToggle(false)} aria-pressed={!described} style={segBtn(!described)}>
                ORIGINAL
              </button>
              <button onClick={() => onToggle(true)} aria-pressed={described} style={segBtn(described)}>
                DESCRIBED
              </button>
            </div>
            <span style={{ fontFamily: mono, fontSize: 10, color: c.faint, whiteSpace: 'nowrap' }}>
              close your eyes — then switch
            </span>
          </>
        )}
      </div>

      <button onClick={onReset} style={btn}>New video</button>
      {downloadUrl && (
        <a
          href={downloadUrl}
          download
          style={{ ...btn, borderColor: c.amberDim, color: c.amber }}
        >
          Download
        </a>
      )}
    </header>
  );
}
