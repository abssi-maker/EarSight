'use client';

import { PipelineEvent } from '@/lib/api';
import { c, mono, sans } from '@/lib/theme';

interface Props {
  events: PipelineEvent[];
}

/**
 * The six Cloud Run agents in pipeline order, and the real Confluent topic
 * each handoff crosses. `earsight.gaps` loops inside the describer and
 * `earsight.dead-letter` catches failures, so both sit outside the chain.
 */
const CHAIN: { agent: string; topicAfter?: string }[] = [
  { agent: 'orchestrator', topicAfter: 'jobs' },
  { agent: 'transcriber',  topicAfter: 'transcript' },
  { agent: 'framer',       topicAfter: 'frames' },
  { agent: 'describer',    topicAfter: 'cues' },
  { agent: 'synthesiser',  topicAfter: 'audio-segments' },
  { agent: 'mixer',        topicAfter: 'results' },
  { agent: 'orchestrator' },
];

const ASIDE_TOPICS = ['gaps', 'dead-letter'];

export default function AgentLane({ events }: Props) {
  const counts = new Map<string, number>();
  for (const e of events) {
    const short = e.topic.replace(/^earsight\./, '');
    counts.set(short, (counts.get(short) ?? 0) + 1);
  }
  const n = (topic: string) => counts.get(topic) ?? 0;

  const railLabel: React.CSSProperties = {
    fontFamily: mono, fontSize: 9.5, letterSpacing: '0.15em',
    textTransform: 'uppercase', color: c.faint, whiteSpace: 'nowrap', lineHeight: 1.6,
  };

  return (
    <section
      aria-label="Agent pipeline"
      style={{
        background: c.panel, borderTop: `1px solid ${c.rule}`,
        borderBottom: `1px solid ${c.rule}`, display: 'flex', alignItems: 'center',
        gap: 14, padding: '0 16px', overflow: 'hidden', fontFamily: sans,
      }}
    >
      <div style={railLabel}>Pipeline<br />{events.length} messages</div>

      <div style={{ display: 'flex', alignItems: 'center', flex: 1, minWidth: 0 }}>
        {CHAIN.map((step, i) => {
          const live = step.topicAfter ? n(step.topicAfter) > 0 : true;
          return (
            <div key={`${step.agent}-${i}`} style={{ display: 'contents' }}>
              <div style={{
                fontFamily: mono, fontSize: 10.5,
                color: live ? c.amber : c.dim,
                background: c.raised,
                border: `1px solid ${live ? c.amberDim : c.rule2}`,
                borderRadius: 3, padding: '5px 9px', whiteSpace: 'nowrap',
              }}>
                {step.agent}
              </div>
              {step.topicAfter && (
                <div style={{
                  flex: 1, minWidth: 20, height: 30, display: 'flex',
                  flexDirection: 'column', justifyContent: 'center',
                  alignItems: 'center', gap: 2, padding: '0 5px',
                }}>
                  <span style={{ fontFamily: mono, fontSize: 9, color: c.dim, whiteSpace: 'nowrap' }}>
                    {step.topicAfter}
                  </span>
                  <span style={{
                    width: '100%', height: 1,
                    background: n(step.topicAfter)
                      ? `linear-gradient(90deg, ${c.amberDim}, rgba(245,166,35,0.55))`
                      : c.rule2,
                  }} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {ASIDE_TOPICS.map((t) => (
        <div key={t} style={{
          fontFamily: mono, fontSize: 9.5, color: c.faint,
          border: `1px solid ${c.rule2}`, borderRadius: 99,
          padding: '3px 9px', whiteSpace: 'nowrap',
        }}>
          {t} · {n(t)}
        </div>
      ))}

      <div style={{ ...railLabel, textAlign: 'right' }}>
        8 real Confluent<br />Kafka topics
      </div>
    </section>
  );
}
