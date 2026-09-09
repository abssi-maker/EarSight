'use client';

import { useRef, useState, DragEvent } from 'react';
import { c, mono, sans } from '@/lib/theme';

interface Props {
  onFile: (file: File) => void;
  disabled?: boolean;
}

export default function UploadZone({ onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState('');

  function validate(file: File): string | null {
    if (!file.type.includes('mp4') && !file.name.endsWith('.mp4')) {
      return 'Only .mp4 files are accepted.';
    }
    return null;
  }

  function checkDuration(file: File) {
    setLocalError('');
    const err = validate(file);
    if (err) { setLocalError(err); return; }

    const video = document.createElement('video');
    video.preload = 'metadata';
    video.onloadedmetadata = () => {
      URL.revokeObjectURL(video.src);
      if (video.duration > 90) {
        setLocalError('Video exceeds 90-second limit.');
        return;
      }
      onFile(file);
    };
    video.onerror = () => { URL.revokeObjectURL(video.src); onFile(file); };
    video.src = URL.createObjectURL(file);
  }

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) checkDuration(file);
    if (inputRef.current) inputRef.current.value = '';
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) checkDuration(file);
  }

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100%', background: c.bg, fontFamily: sans, padding: 24,
    }}>
      <div style={{ width: '100%', maxWidth: 560, textAlign: 'center' }}>
        <h1 style={{
          fontFamily: mono, fontSize: 14, letterSpacing: '0.3em', fontWeight: 600,
          color: c.text, margin: '0 0 26px',
        }}>
          EAR<span style={{ color: c.amber }}>SIGHT</span>
        </h1>
        <p style={{
          fontSize: 26, fontWeight: 400, color: c.text, margin: '0 0 10px',
          letterSpacing: '-0.015em',
        }}>
          Hear what you cannot watch.
        </p>
        <p style={{ fontFamily: mono, fontSize: 12, color: c.dim, margin: '0 0 28px', lineHeight: 1.7 }}>
          Six agents find the silences between dialogue and write into them —<br />
          never a word longer than the gap allows.
        </p>

        <label
          htmlFor="video-upload"
          aria-label="Drop an MP4 video here or click to choose a file. Maximum 90 seconds."
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          style={{
            display: 'block',
            border: `2px dashed ${dragging ? c.amber : c.rule2}`,
            borderRadius: 8, padding: '48px 24px', textAlign: 'center',
            cursor: disabled ? 'default' : 'pointer',
            color: dragging ? c.amber : c.dim, fontSize: 14,
            background: dragging ? 'rgba(245,166,35,0.04)' : c.panel,
            transition: 'border-color 0.15s, color 0.15s',
          }}
        >
          {disabled ? 'Uploading…' : dragging ? 'Drop to upload' : 'Drop a video here, or click to choose'}
          <span style={{ fontSize: 12, color: c.faint, marginTop: 8, display: 'block', fontFamily: mono }}>
            .mp4 · max 90 seconds
          </span>
          <input
            ref={inputRef}
            id="video-upload"
            type="file"
            accept="video/mp4,video/*"
            style={{ display: 'none' }}
            onChange={onInputChange}
            disabled={disabled}
            aria-describedby="upload-hint"
          />
        </label>
        <p id="upload-hint" style={{ display: 'none' }}>
          Upload an MP4 video file up to 90 seconds long.
        </p>

        {localError && (
          <p role="alert" style={{ color: c.err, marginTop: 12, fontSize: 13, fontFamily: mono }}>
            {localError}
          </p>
        )}
      </div>
    </div>
  );
}
