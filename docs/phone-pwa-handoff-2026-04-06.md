# Lukeyz Phone / PWA Handoff

## What is used where

- Website logo in the web UI: `web/public/brand/lukeyz-logo-lockup.jpg`
- Primary icon-only mark in the web UI and icon exports: `web/public/brand/lukeyz-mark.png`
- PWA manifest icons: `web/public/icon-192.png`, `web/public/icon-512.png`
- Apple home-screen icon: `web/public/apple-touch-icon.png`
- Browser favicon: `web/src/app/favicon.ico`

## iPhone home-screen notes

- iPhone uses `apple-touch-icon.png` when the site is added to the home screen.
- The current export is derived from the approved `brand/source/downloads-import/2026-04-06-lukeyz-pwa-icon.png`.
- Best manual check: add the site to the home screen, then confirm the icon crop, edge padding, and dark background feel correct against iOS.

## PWA notes

- The manifest currently points to `icon-192.png`, `icon-512.png`, and `icon-maskable-512.png`.
- `icon-maskable-512.png` currently uses the same approved square export as the main 512 icon.
- Canonical manifest source: `web/src/app/manifest.ts`
- Canonical service worker source: `web/public/sw.js`
- Best manual check: install the PWA and confirm the launcher icon, splash presentation, and install prompt asset all match the new mark.

## Current limitations

- The approved lockup source available locally is a raster image, not a transparent vector.
- The maskable icon is a safe beta-ready reuse of the same approved icon crop, not a separately tuned Android maskable composition.
- Browser favicon is updated from the approved icon source, but tiny favicon rendering should still be spot-checked in Safari and Chrome.

## What to verify on phone

- Home-screen icon uses the new Lukeyz monogram, not the older `L` icon.
- Add-to-home-screen flow succeeds on iPhone.
- Installed PWA opens with the expected name `Lukeyz`.
- Icon padding and rounded-corner presentation look balanced.
- No old branding appears in Safari tab UI or install surfaces.

## How to replace icons later

1. Put the newly approved lockup/icon sources into `brand/source/` with a dated filename.
2. Regenerate the web exports in `brand/exports/web/`.
3. Copy the updated exports into the matching `web/public/` runtime files.
4. Rebuild the web app and manually re-check iPhone home-screen install plus PWA install.
