import { NextRequest, NextResponse } from 'next/server';

/**
 * GET /api/peaks?url=<encoded-signed-url>
 *
 * Proxies the peaks.json file from GCS (signed URL) to avoid CORS restrictions.
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
    const data = await upstream.json();
    return NextResponse.json(data, {
      status: 200,
      headers: {
        'Cache-Control': 'public, max-age=3600',
      },
    });
  } catch (err) {
    return new NextResponse(`Proxy error: ${err}`, { status: 502 });
  }
}
