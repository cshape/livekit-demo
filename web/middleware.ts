import { type NextRequest, NextResponse } from 'next/server';

// The root layout can't see the pathname, so stamp the locale onto the request
// headers here: /jp (and anything under it) is Japanese, everything else English.
// app/layout.tsx reads `x-locale` to pick the html lang + localized page copy.
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-locale', pathname === '/jp' || pathname.startsWith('/jp/') ? 'ja' : 'en');
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  // Page routes only — skip API routes, Next internals, and static files.
  matcher: ['/((?!api|_next|.*\\..*).*)'],
};
