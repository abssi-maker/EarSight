'use client';

import { useRef, useState, DragEvent } from 'react';

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
    // reset so same file can be re-selected
    if (inputRef.current) inputRef.current.value = '';
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) checkDuration(file);
  }

  const borderColor = dragging ? '#f5a623' : disabled ? '#222' : '#333';

  return (
    <div>
      <label
        htmlFor="video-upload"
        aria-label="Drop an MP4 video here or click to choose a file. Maximum 90 seconds."
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        style={{
          display: 'block',
          border: `2px dashed ${borderColor}`,
          borderRadius: 8,
          padding: '48px 24px',
          textAlign: 'center',
          cursor: disabled ? 'default' : 'pointer',
          color: dragging ? '#f5a623' : '#aaa',
          fontSize: 14,
          transition: 'border-color 0.15s, color 0.15s',
          background: dragging ? 'rgba(245,166,35,0.04)' : 'transparent',
        }}
      >
        {disabled
          ? 'Processing…'
          : dragging
          ? 'Drop to upload'
          : 'Drop a video. Hear everything.'}
        <br />
        <span style={{ fontSize: 12, color: '#555', marginTop: 8, display: 'block' }}>
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
        <p role="alert" style={{ color: '#e55', marginTop: 8, fontSize: 13 }}>
          {localError}
        </p>
      )}
    </div>
  );
}
