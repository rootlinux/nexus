import type { NextConfig } from "next";

function resolveCspSource(urlValue?: string) {
  const candidate = urlValue?.trim();
  if (!candidate) {
    return null;
  }

  try {
    return new URL(candidate).origin;
  } catch {
    return candidate.replace(/\/$/, '');
  }
}

const isProd = process.env.NODE_ENV === 'production';

const nextConfig: NextConfig = {
  reactCompiler: true,
  output: isProd ? 'standalone' : undefined,
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=(), payment=()',
          },
          // CSP header is set in src/middleware.ts with per-request nonce
        ],
      },
      {
        source: '/messages',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/messages/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/notifications',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/notifications/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/bookmarks',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/invites',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/admin',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/admin/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/auth',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/auth/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/login',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/register',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/security',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/security/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-store' }],
      },
      {
        source: '/manifest.webmanifest',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' }],
      },
      {
        source: '/sw.js',
        headers: [{ key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' }],
      },
    ];
  },
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
