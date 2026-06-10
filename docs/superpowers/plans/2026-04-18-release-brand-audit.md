# Release Brand Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the remaining pre-deploy branding blockers by auditing email branding assets and ensuring the installed PWA/add-to-home-screen icon paths resolve to the intended Nexus assets.

**Architecture:** Keep the fix minimal by treating `web/public/brand/` as the Nexus icon source of truth, aligning metadata and runtime fallbacks to that source, and removing remaining old mail branding references. Add or update focused regression coverage so the audit is enforceable in future releases.

**Tech Stack:** FastAPI backend, Next.js app router, Python `unittest`, existing repo asset pipeline in `web/public/`

---

### Task 1: Lock email branding expectations with tests

**Files:**
- Modify: `backend/tests/test_mail_config.py`
- Test: `backend/tests/test_mail_config.py`

- [ ] **Step 1: Add assertions for Nexus-hosted email branding**

Add or update the mail HTML assertions so they verify the email logo source is derived from the app’s production base URL and no `linusx.xyz` asset is present.

- [ ] **Step 2: Run the targeted mail test and verify it fails first**

Run: `python -m pytest backend/tests/test_mail_config.py -k matching_text_html_and_logo -q`
Expected: FAIL because the HTML still contains the old hosted asset URL.

- [ ] **Step 3: Update the email branding source**

Change the mail service so transactional emails render a Nexus-branded header asset from the current app base URL instead of the legacy hosted asset.

- [ ] **Step 4: Re-run the targeted mail test**

Run: `python -m pytest backend/tests/test_mail_config.py -k matching_text_html_and_logo -q`
Expected: PASS.

### Task 2: Lock PWA/icon mapping expectations with tests

**Files:**
- Create: `web/src/app/__tests__/branding.test.ts`
- Test: `web/src/app/__tests__/branding.test.ts`

- [ ] **Step 1: Add focused icon-mapping assertions**

Write a small test that imports the Next metadata/manifest modules and verifies:
- favicon entries point at the expected favicon assets
- Apple touch metadata points at the intended Nexus asset
- manifest `icon-192` and `icon-512` point at the intended Nexus brand assets
- legacy top-level Lukeyz icon paths are not used for install metadata

- [ ] **Step 2: Run the targeted web test and verify it fails first**

Run: `npm test -- --runInBand branding.test.ts`
Expected: FAIL because current references and/or legacy asset fallbacks still expose old paths.

- [ ] **Step 3: Align icon source-of-truth and runtime fallbacks**

Update metadata/runtime references and legacy top-level public icon files only as needed so browser favicon, Apple touch icon, PWA install icon, and push icon paths all resolve to the intended Nexus artwork.

- [ ] **Step 4: Re-run the targeted web test**

Run: `npm test -- --runInBand branding.test.ts`
Expected: PASS.

### Task 3: Verify deploy-blocker scope end to end

**Files:**
- Review: `backend/app/services/mail.py`
- Review: `web/src/app/layout.tsx`
- Review: `web/src/app/manifest.ts`
- Review: `backend/app/services/push_notifications.py`
- Review: `backend/app/api/routes/notifications.py`
- Review: `web/public/offline.html`

- [ ] **Step 1: Audit for remaining old branding strings and paths**

Run: `rg -n "Lukeyz|linusx.xyz|/icon-192.png|/icon-512.png|/apple-touch-icon.png" backend web`
Expected: only intentional non-blocking leftovers remain, or none after the fix.

- [ ] **Step 2: Run the focused verification suite**

Run: `python -m pytest backend/tests/test_mail_config.py -q`
Run: `npm test -- --runInBand branding.test.ts`
Expected: PASS for both commands.

- [ ] **Step 3: Summarize cache implications**

Document whether existing installed PWAs or iOS home-screen icons may need a reinstall, hard refresh, or icon cache eviction because icon files and manifest metadata were changed.
