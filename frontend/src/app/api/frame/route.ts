import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/frame?url=<encoded-signed-url>
 *
 * Proxies a per-gap frame image from GCS (signed URL) to avoid CORS
 * restrictions. Mirrors app/api/peaks/route.ts, but streams bytes.
 */
export async function GET(request: NextRequest) {
  const url = request.nextUrl.searchParams.get('url');
  if (!url) return new NextResponse('Missing url parameter', { status: 400 });

  try {
    const upstream = await fetch(url);
    if (!upstream.ok) {
      return new NextResponse(`Upstream error: ${upstream.status}`, { status: 502 });
    }
    const buf = await upstream.arrayBuffer();
    return new NextResponse(buf, {
      status: 200,
      headers: {
        'Content-Type': upstream.headers.get('content-type') ?? 'image/jpeg',
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch (err) {
    return new NextResponse(`Proxy error: ${err}`, { status: 502 });
  }
}
