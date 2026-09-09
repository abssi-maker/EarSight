'use client';

import { RefObject, useEffect, useRef, useState } from 'react';
import { c, mono, sans } from '@/lib/theme';
import { tc } from '@/lib/segments';

interface Props {
  videoRef: RefObject<HTMLVideoElement>;
  src: string;
  vttUrl: string;
  described: boolean;
  activeText: string | null;
  currentTime: number;
  duration: number;
  onTime: (t: number) => void;
  onDuration: (d: number) => void;
}

const iconBtn: React.CSSProperties = {
  fontFamily: mono, fontSize: 10.5, color: c.dim,
  border: `1px solid ${c.rule2}`, borderRadius: 4, padding: '5px 9px',
  background: 'transparent', cursor: 'pointer',
};

export default function Player({
  videoRef, src, vttUrl, described, activeText, currentTime, duration,
  onTime, onDuration,
}: Props) {
  const [playing, setPlaying] = useState(false);
  const lastT = useRef(0);
  const wasPlaying = useRef(false);
  const pending = useRef<number | null>(null);

  // Swapping ORIGINAL/DESCRIBED reloads the element — restore the position
  // and play state so the comparison is seamless.
  useEffect(() => {
    pending.current = lastT.current;
  }, [src]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;

    const onTimeUpdate = () => {
      lastT.current = v.currentTime;
      onTime(v.currentTime);
    };
    const onMeta = () => {
      onDuration(v.duration || 0);
      if (pending.current != null) {
        v.currentTime = pending.current;
        pending.current = null;
        if (wasPlaying.current) void v.play();
      }
    };
    const onPlayEv = () => { setPlaying(true); wasPlaying.current = true; };
    const onPauseEv = () => { setPlaying(false); wasPlaying.current = false; };

    v.addEventListener('timeupdate', onTimeUpdate);
    v.addEventListener('loadedmetadata', onMeta);
    v.addEventListener('play', onPlayEv);
    v.addEventListener('pause', onPauseEv);
    return () => {
      v.removeEventListener('timeupdate', onTimeUpdate);
      v.removeEventListener('loadedmetadata', onMeta);
      v.removeEventListener('play', onPlayEv);
      v.removeEventListener('pause', onPauseEv);
    };
  }, [videoRef, onTime, onDuration]);

  function toggle() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play(); else v.pause();
  }
  function nudge(by: number) {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, v.currentTime + by);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|BUTTON|A)$/.test(el.tagName)) return;
      if (e.code === 'Space') { e.preventDefault(); toggle(); }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); nudge(-5); }
      else if (e.code === 'ArrowRight') { e.preventDefault(); nudge(5); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  return (
    <section
      aria-label="Described video player"
      style={{ background: '#050506', display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: sans }}
    >
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, minHeight: 0 }}>
        <div style={{ position: 'relative', height: '100%', maxWidth: '100%', aspectRatio: '16 / 9' }}>
          <video
            ref={videoRef}
            src={src}
            style={{ width: '100%', height: '100%', display: 'block', background: '#000', borderRadius: 3 }}
          >
            <track kind="descriptions" src={`/api/vtt?url=${encodeURIComponent(vttUrl)}`} default />
          </video>
          {described && activeText && (
            <div style={{ position: 'absolute', left: 0, right: 0, bottom: 22, textAlign: 'center', padding: '0 30px' }}>
              <span style={{
                fontFamily: mono, fontSize: 13.5, color: '#fff',
                background: 'rgba(0,0,0,0.74)', padding: '6px 13px',
                borderRadius: 3, lineHeight: 1.5,
              }}>
                {activeText}
              </span>
            </div>
          )}
        </div>
      </div>

      <div style={{
        flex: 'none', display: 'flex', alignItems: 'center', gap: 14,
        padding: '9px 16px', background: c.panel, borderTop: `1px solid ${c.rule}`,
      }}>
        <button
          onClick={toggle}
          aria-label={playing ? 'Pause' : 'Play'}
          style={{
            width: 30, height: 30, borderRadius: '50%', background: c.raised,
            border: `1px solid ${c.rule2}`, color: c.amber, fontSize: 10,
            cursor: 'pointer', flex: 'none',
          }}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <span style={{ fontFamily: mono, fontSize: 11.5, color: c.text }}>
          {tc(currentTime)}
          <span style={{ color: c.faint }}> / {tc(duration)}</span>
        </span>
        <button onClick={() => nudge(-5)} style={iconBtn} aria-label="Back 5 seconds">◂ 5s</button>
        <button onClick={() => nudge(5)} style={iconBtn} aria-label="Forward 5 seconds">5s ▸</button>
        <span aria-live="polite" style={{ fontFamily: mono, fontSize: 10, color: c.faint, marginLeft: 'auto' }}>
          {described
            ? (activeText ? 'description playing' : 'space play/pause · ← → seek 5s · click the timeline to jump')
            : 'original audio — no description'}
        </span>
      </div>
    </section>
  );
}
