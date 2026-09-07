import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'EarSight — Audio Description for Video',
  description: 'Drop a video. Hear everything.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#0a0a0a', color: '#e5e5e5', fontFamily: 'monospace' }}>
        {children}
      </body>
    </html>
  );
}
