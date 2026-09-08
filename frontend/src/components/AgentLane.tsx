'use client';

/**
 * AgentLane.tsx — animated Kafka pipeline visualisation.
 *
 * Six service nodes arranged left-to-right:
 *   orchestrator → transcriber → framer → describer → synthesiser → mixer
 * Each pipeline event pulses an amber dot along the relevant edge.
 * A running message count is shown per topic edge.
 */

import { useEffect, useRef, useState } from 'react';
import { PipelineEvent } from '@/lib/api';

interface Props {
  events: PipelineEvent[];
}

const SERVICES = ['orchestrator', 'transcriber', 'framer', 'describer', 'synthesiser', 'mixer'] as const;
type Service = typeof SERVICES[number];

// Topic → edge (from → to)
const TOPIC_EDGES: Record<string, [Service, Service]> = {
  'earsight.jobs':          ['orchestrator', 'transcriber'],
  'earsight.transcript':    ['transcriber', 'describer'],
  'earsight.frames':        ['framer', 'describer'],
  'earsight.gaps':          ['orchestrator', 'describer'],
  'earsight.cues':          ['describer', 'synthesiser'],
  'earsight.audio-segments':['synthesiser', 'mixer'],
  'earsight.results':       ['mixer', 'orchestrator'],
};

const NODE_LABEL: Record<Service, string> = {
  orchestrator: 'orch.',
  transcriber:  'transc.',
  framer:       'framer',
  describer:    'descr.',
  synthesiser:  'synth.',
  mixer:        'mixer',
};

interface Pulse {
  id: string;
  topic: string;
  edge: [Service, Service];
  startedAt: number;
}

export default function AgentLane({ events }: Props) {
  const [pulses, setPulses] = useState<Pulse[]>([]);
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const newPulses: Pulse[] = [];
    for (const ev of events) {
      const key = `${ev.ts}-${ev.topic}`;
      if (seenRef.current.has(key)) continue;
      seenRef.current.add(key);
      const edge = TOPIC_EDGES[ev.topic];
      if (edge) {
        newPulses.push({ id: key, topic: ev.topic, edge, startedAt: Date.now() });
      }
    }
    if (newPulses.length > 0) {
      setPulses((prev) => [...prev, ...newPulses]);
      // Remove pulses after animation
      setTimeout(() => {
        setPulses((prev) => prev.filter((p) => Date.now() - p.startedAt < 1200));
      }, 1300);
    }
  }, [events]);

  // Count messages per topic
  const topicCounts: Record<string, number> = {};
  for (const ev of events) {
    topicCounts[ev.topic] = (topicCounts[ev.topic] ?? 0) + 1;
  }

  // Layout
  const W = 680;
  const H = 120;
  const nodeW = 68;
  const nodeH = 32;
  const nodeY = H / 2 - nodeH / 2;
  const spacing = W / (SERVICES.length - 1);

  function nodeX(s: Service): number {
    return SERVICES.indexOf(s) * spacing;
  }
  function nodeCX(s: Service): number {
    return nodeX(s) + nodeW / 2;
  }

  // Collect active pulses with animation progress
  const now = Date.now();
  const activePulses = pulses.filter((p) => now - p.startedAt < 1200);

  return (
    <section aria-label="Agent pipeline lane" style={{ marginTop: 24, marginBottom: 8 }}>
      <h2 style={{ fontSize: 11, color: '#555', letterSpacing: '0.1em', marginBottom: 8, textTransform: 'uppercase' }}>
        Agent pipeline · {events.length} messages · {Object.keys(topicCounts).length} topics active
      </h2>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: H, display: 'block', overflow: 'visible' }}
        aria-hidden="true"
      >
        {/* Draw topic edges */}
        {Object.entries(TOPIC_EDGES).map(([topic, [from, to]]) => {
          const x1 = nodeCX(from);
          const x2 = nodeCX(to);
          const count = topicCounts[topic] ?? 0;
          const midX = (x1 + x2) / 2;
          const midY = nodeY - 14;
          // skip self-edges that would be invisible
          if (from === to) return null;
          return (
            <g key={topic}>
              <line
                x1={x1} y1={H / 2}
                x2={x2} y2={H / 2}
                stroke={count > 0 ? '#2a2a2a' : '#1a1a1a'}
                strokeWidth={1.5}
              />
              {count > 0 && (
                <text
                  x={midX} y={midY}
                  textAnchor="middle"
                  fontSize={8}
                  fill="#444"
                  fontFamily="monospace"
                >
                  {topic.replace('earsight.', '')} ×{count}
                </text>
              )}
            </g>
          );
        })}

        {/* Animate pulses */}
        {activePulses.map((pulse) => {
          const progress = Math.min(1, (now - pulse.startedAt) / 1000);
          const [from, to] = pulse.edge;
          const x1 = nodeCX(from);
          const x2 = nodeCX(to);
          const cx = x1 + (x2 - x1) * progress;
          return (
            <circle
              key={pulse.id}
              cx={cx} cy={H / 2}
              r={4}
              fill="#f5a623"
              opacity={1 - progress * 0.6}
            />
          );
        })}

        {/* Service nodes */}
        {SERVICES.map((s) => {
          const x = nodeX(s);
          const isActive = events.some((e) => e.service === s);
          return (
            <g key={s}>
              <rect
                x={x} y={nodeY}
                width={nodeW} height={nodeH}
                rx={4}
                fill="#111"
                stroke={isActive ? '#f5a623' : '#222'}
                strokeWidth={1}
              />
              <text
                x={x + nodeW / 2} y={nodeY + nodeH / 2 + 4}
                textAnchor="middle"
                fontSize={9}
                fill={isActive ? '#f5a623' : '#444'}
                fontFamily="monospace"
              >
                {NODE_LABEL[s]}
              </text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}
