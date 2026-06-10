# Lukeyz Brand Package

This folder is the canonical in-repo brand package for the beta handoff.

## Canonical assets

- `source/downloads-import/2026-04-06-lukeyz-website-lockup.jpg`
  Final approved website logo lockup imported from `~/Downloads/web.jpg`.
- `source/downloads-import/2026-04-06-lukeyz-pwa-icon.png`
  Final approved app/PWA icon source imported from `~/Downloads/pwa.png`.
- `exports/web/lukeyz-logo-lockup.jpg`
  Web-ready lockup used by the site UI.
- `exports/web/lukeyz-mark-master.png`
  Canonical square icon source for downstream web exports.
- `exports/web/lukeyz-mark-512.png`
  Primary PWA icon export.
- `exports/web/lukeyz-mark-192.png`
  Smaller PWA icon export.
- `exports/web/lukeyz-apple-touch-icon.png`
  Apple home-screen icon export.
- `exports/web/lukeyz-favicon.ico`
  Browser favicon export.

## Runtime copies

The live web app serves copies of the approved exports from `web/public/`:

- `web/public/brand/lukeyz-logo-lockup.jpg`
- `web/public/brand/lukeyz-mark.png`
- `web/public/icon-192.png`
- `web/public/icon-512.png`
- `web/public/icon-maskable-512.png`
- `web/public/apple-touch-icon.png`
- `web/public/icon.svg`
- `web/src/app/favicon.ico`

## Legacy assets

Older pre-final public brand SVGs were moved to `brand/archive/legacy-web-public/` so the repo keeps provenance without leaving stale production choices in the active path.
