import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/vtt?url=<encoded-gcs-url>
 *
 * Proxies a WebVTT file from GCS (or any URL) to avoid CORS restrictions
 * when the browser loads the <track> element.
 */
export async function GET(request: NextRequest) {
  const url = request.nextUrl.searchParams.get('url');
  if (!url) {
    return new NextResponse('Missing url parameter', { status: 400 });
  }

  try {
    const upstream = await fetch(url);
    if (!upstream.ok) {
      return new NextResponse(`Upstream error: ${upstream.status}`, {
        status: 502,
      });
    }
    const text = await upstream.text();
    return new NextResponse(text, {
      status: 200,
      headers: {
        'Content-Type': 'text/vtt; charset=utf-8',
        'Cache-Control': 'no-store',
      },
    });
  } catch (err) {
    return new NextResponse(`Proxy error: ${err}`, { status: 502 });
  }
}
