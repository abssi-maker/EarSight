import type { Metadata } from 'next';
import { c, sans } from '@/lib/theme';

export const metadata: Metadata = {
  title: 'EarSight — Audio Description for Video',
  description: 'Hear what you cannot watch.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          background: c.bg,
          color: c.text,
          fontFamily: sans,
          WebkitFontSmoothing: 'antialiased',
          overflow: 'hidden',
        }}
      >
        {children}
      </body>
    </html>
  );
}
