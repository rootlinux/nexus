# Nexus Brand Asset Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the final Nexus PNG branding assets from Downloads, generate the required web icon derivatives, and update the frontend to serve the new logo pack everywhere old Lukeyz assets were referenced.

**Architecture:** Keep the downloaded PNGs as the source of truth for this integration by copying the approved files into `web/public/brand/`, then derive all runtime icon sizes from the approved rounded-square app icon and square mark asset. Update the Next.js metadata and `BrandLogo` component to point at the new static asset paths while preserving existing layout behavior.

**Tech Stack:** Next.js App Router, static assets in `web/public`, shell image tooling (`sips` and macOS `iconutil`/ImageMagick if available)

---

### Task 1: Identify and map the approved source assets

**Files:**
- Read: `~/Downloads/*.png`
- Read: `web/src/components/BrandLogo.tsx`
- Read: `web/src/app/layout.tsx`
- Read: `web/src/app/manifest.ts`

- [ ] **Step 1: Inspect the downloaded PNGs**

Run: `for f in ~/Downloads/*.png; do echo "$f"; sips -g pixelWidth -g pixelHeight "$f" | tail -n +2; done`
Expected: Distinguish horizontal logo files from square icon files by dimensions.

- [ ] **Step 2: Visually confirm each required asset**

Check for:
- dark navy horizontal lockup on transparent background
- white horizontal lockup on transparent background
- dark navy standalone symbol on transparent background
- white standalone symbol on transparent background
- rounded-square app icon PNG

- [ ] **Step 3: Stop if any mapping is ambiguous**

Expected: No file is copied or renamed until every required mapping is identified with confidence.

### Task 2: Import approved assets and generate derived icons

**Files:**
- Create: `web/public/brand/nexus-logo-on-light.png`
- Create: `web/public/brand/nexus-logo-on-dark.png`
- Create: `web/public/brand/nexus-mark-on-light.png`
- Create: `web/public/brand/nexus-mark-on-dark.png`
- Create: `web/public/brand/apple-touch-icon.png`
- Create: `web/public/brand/icon-192.png`
- Create: `web/public/brand/icon-512.png`
- Create: `web/public/favicon-16x16.png`
- Create: `web/public/favicon-32x32.png`
- Create: `web/public/favicon.ico`

- [ ] **Step 1: Ensure the destination directory exists**

Run: `mkdir -p web/public/brand`
Expected: `web/public/brand` exists for the imported Nexus assets.

- [ ] **Step 2: Copy the approved source PNGs into their final filenames**

Run: `cp "<source>" web/public/brand/<target>.png`
Expected: The five approved source assets exist under their exact final filenames.

- [ ] **Step 3: Generate the derived PNG icons**

Run:
- `sips -z 192 192 web/public/brand/apple-touch-icon.png --out web/public/brand/icon-192.png`
- `sips -z 512 512 web/public/brand/apple-touch-icon.png --out web/public/brand/icon-512.png`
- `sips -z 32 32 web/public/brand/nexus-mark-on-light.png --out web/public/favicon-32x32.png`
- `sips -z 16 16 web/public/brand/nexus-mark-on-light.png --out web/public/favicon-16x16.png`
Expected: The resized PNG outputs exist at the required paths.

- [ ] **Step 4: Generate the ICO file from the favicon PNGs**

Run a local icon generation command using ImageMagick if available; otherwise use a macOS-compatible fallback that produces `web/public/favicon.ico`.
Expected: `web/public/favicon.ico` contains the Nexus favicon sizes.

### Task 3: Wire the new assets into the frontend

**Files:**
- Modify: `web/src/components/BrandLogo.tsx`
- Modify: `web/src/app/layout.tsx`
- Modify: `web/src/app/manifest.ts`
- Modify: `web/public/icon.svg`

- [ ] **Step 1: Update `BrandLogo` to use the new Nexus asset files**

Expected: The lockup and mark variants render the new brand images without changing sizing behavior.

- [ ] **Step 2: Update root metadata icon references**

Expected: `layout.tsx` points at the new favicon, Apple touch icon, and PWA icon asset paths.

- [ ] **Step 3: Update manifest icons**

Expected: The manifest serves the new `brand/icon-192.png` and `brand/icon-512.png` paths.

- [ ] **Step 4: Replace remaining old Lukeyz logo asset references**

Run: `rg -n "lukeyz" web`
Expected: No stale runtime references remain in the web app after the update.

### Task 4: Verify the integration before completion

**Files:**
- Read: `web/public/brand/*`
- Read: `web/public/favicon-*`
- Read: `web/public/favicon.ico`

- [ ] **Step 1: Confirm the generated asset files exist with expected dimensions**

Run: `for f in web/public/brand/*.png web/public/favicon-16x16.png web/public/favicon-32x32.png; do echo "$f"; sips -g pixelWidth -g pixelHeight "$f" | tail -n +2; done`
Expected: Dimensions match the target sizes for the derived assets.

- [ ] **Step 2: Search for stale Lukeyz references again**

Run: `rg -n "lukeyz" web`
Expected: No remaining runtime branding references in the web app, or a clear list of intentional leftovers outside runtime paths.

- [ ] **Step 3: Review the git diff for only the intended branding changes**

Run: `git diff -- web/public web/src/components/BrandLogo.tsx web/src/app/layout.tsx web/src/app/manifest.ts`
Expected: Only the Nexus asset integration changes appear in the diff.
