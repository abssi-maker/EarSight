'use client';

import { useState } from 'react';

export default function Home() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [uploading, setUploading] = useState(false);

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // 90-second cap enforced client-side too
    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = async () => {
      URL.revokeObjectURL(video.src);
      if (video.duration > 90) {
        setError('Video exceeds 90-second limit.');
        return;
      }
      await submitJob(file);
    };
    video.src = URL.createObjectURL(file);
  }

  async function submitJob(file: File) {
    setUploading(true);
    setError('');
    try {
      const orchestratorUrl = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://localhost:8000';

      // Upload file to get a GCS URI (Step 3 will wire GCS upload;
      // for now we pass the filename as a placeholder)
      const res = await fetch(`${orchestratorUrl}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_uri: `local://${file.name}`, label: file.name }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      setStatus(data.status);
      poll(data.job_id, orchestratorUrl);
    } catch (err) {
      setError(String(err));
    } finally {
      setUploading(false);
    }
  }

  function poll(id: string, baseUrl: string) {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${baseUrl}/jobs/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        setStatus(data.status);
        if (data.status === 'done' || data.status === 'failed') {
          clearInterval(interval);
        }
      } catch {
        // ignore poll errors
      }
    }, 2000);
  }

  return (
    <main style={{ maxWidth: 720, margin: '80px auto', padding: '0 24px' }}>
      <h1 style={{ color: '#f5a623', fontSize: 28, letterSpacing: '0.05em', marginBottom: 8 }}>
        EARSIGHT
      </h1>
      <p style={{ color: '#888', marginBottom: 40, fontSize: 15 }}>
        Drop a video. Hear everything.
      </p>

      <label
        htmlFor="video-upload"
        style={{
          display: 'block',
          border: '2px dashed #333',
          borderRadius: 8,
          padding: '40px 24px',
          textAlign: 'center',
          cursor: 'pointer',
          color: '#aaa',
          fontSize: 14,
        }}
      >
        {uploading ? 'Submitting…' : 'Choose an .mp4 file (≤ 90 seconds)'}
        <input
          id="video-upload"
          type="file"
          accept="video/mp4"
          style={{ display: 'none' }}
          onChange={handleFile}
          disabled={uploading}
          aria-label="Upload MP4 video (90 seconds maximum)"
        />
      </label>

      {error && (
        <p role="alert" style={{ color: '#e55', marginTop: 16, fontSize: 14 }}>
          {error}
        </p>
      )}

      {jobId && (
        <div style={{ marginTop: 32 }}>
          <p style={{ fontSize: 13, color: '#888' }}>Job ID: <code style={{ color: '#f5a623' }}>{jobId}</code></p>
          <p style={{ fontSize: 13, color: '#888' }}>Status: <strong style={{ color: '#e5e5e5' }}>{status}</strong></p>
        </div>
      )}
    </main>
  );
}
