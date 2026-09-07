'use client';

import { useEffect, useRef } from 'react';

interface Props {
  videoUrl: string;
  vttUrl: string;
  onTimeUpdate?: (currentTime: number) => void;
}

export default function Player({ videoUrl, vttUrl, onTimeUpdate }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);

  // Proxy VTT through our API route to avoid CORS on GCS signed URLs
  const proxiedVtt = `/api/vtt?url=${encodeURIComponent(vttUrl)}`;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    function handler() {
      onTimeUpdate?.(video!.currentTime);
    }
    video.addEventListener('timeupdate', handler);
    return () => video.removeEventListener('timeupdate', handler);
  }, [onTimeUpdate]);

  return (
    <section aria-label="Described video player" style={{ marginTop: 32 }}>
      <h2 style={{ fontSize: 13, color: '#666', letterSpacing: '0.1em', marginBottom: 12, textTransform: 'uppercase' }}>
        Player
      </h2>
      <video
        ref={videoRef}
        controls
        style={{
          width: '100%',
          borderRadius: 6,
          background: '#000',
          outline: 'none',
        }}
        aria-label="Described video with audio description track"
      >
        <source src={videoUrl} type="video/mp4" />
        <track
          kind="descriptions"
          src={proxiedVtt}
          srcLang="en"
          label="Audio descriptions"
          default
        />
        Your browser does not support the video element.
      </video>
      <p style={{ fontSize: 11, color: '#444', marginTop: 8 }}>
        Audio descriptions embedded · WebVTT · keyboard: Space to play/pause, ← → to seek
      </p>
    </section>
  );
}
