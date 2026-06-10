import { NextResponse, type NextRequest } from 'next/server'

const EXCLUDED_PATHS = new Set([
  '/favicon.ico',
  '/manifest.webmanifest',
  '/offline.html',
  '/sw.js',
  '/robots.txt',
  '/sitemap.xml',
])

const STATIC_PREFIXES = ['/api/', '/_next/', '/brand/']
const STATIC_FILE_PATTERN = /\.[a-z0-9]+$/i

function isStaticAsset(pathname: string): boolean {
  if (EXCLUDED_PATHS.has(pathname)) {
    return true
  }
  if (STATIC_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return true
  }
  return STATIC_FILE_PATTERN.test(pathname)
}

function resolveCspSource(urlValue?: string): string | null {
  const candidate = urlValue?.trim()
  if (!candidate) return null
  try {
    return new URL(candidate).origin
  } catch {
    return candidate.replace(/\/$/, '')
  }
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Static assets: no CSP nonce or cache headers needed
  if (isStaticAsset(pathname)) {
    return NextResponse.next()
  }

  // Generate a cryptographically random per-request nonce
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64')
  const isDev = process.env.NODE_ENV === 'development'

  // Build dynamic CSP with per-request nonce
  const apiOrigin = resolveCspSource(process.env.NEXT_PUBLIC_API_BASE_URL)
  const connectSources = ["'self'"]
  const imageSources = ["'self'", 'data:', 'blob:']
  const mediaSources = ["'self'", 'blob:']

  if (apiOrigin) {
    connectSources.push(apiOrigin)
    imageSources.push(apiOrigin)
    mediaSources.push(apiOrigin)
  }

  const scriptSrcParts = [
    "'self'",
    `'nonce-${nonce}'`,
    "'strict-dynamic'",
    // React uses eval in dev for enhanced error stack reconstruction
    ...(isDev ? ["'unsafe-eval'"] : []),
  ]

  const cspHeader = [
    "default-src 'self'",
    'base-uri \'self\'',
    "object-src 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "frame-src 'none'",
    "manifest-src 'self'",
    "worker-src 'self'",
    `script-src ${scriptSrcParts.join(' ')}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src ${imageSources.join(' ')}`,
    `media-src ${mediaSources.join(' ')}`,
    "font-src 'self' data:",
    `connect-src ${connectSources.join(' ')}`,
  ].join('; ')

  // Forward nonce to downstream server components via request header
  const requestHeaders = new Headers(request.headers)
  requestHeaders.set('x-nonce', nonce)

  if (!['GET', 'HEAD'].includes(request.method)) {
    // Non-GET/HEAD (server actions, etc.): set CSP but skip cache-control
    const response = NextResponse.next({
      request: { headers: requestHeaders },
    })
    response.headers.set('Content-Security-Policy', cspHeader)
    return response
  }

  // GET/HEAD page requests: set CSP + no-store cache headers
  const response = NextResponse.next({
    request: { headers: requestHeaders },
  })
  response.headers.set('Content-Security-Policy', cspHeader)
  response.headers.set('Cache-Control', 'no-store, max-age=0')
  response.headers.set('Pragma', 'no-cache')
  response.headers.set('Expires', '0')
  response.headers.set('Vary', 'Authorization, Cookie')
  return response
}

export const config = {
  matcher: '/:path*',
}
