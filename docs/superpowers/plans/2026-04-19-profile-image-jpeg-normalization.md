# Profile Image JPEG Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize profile avatar and cover uploads so transparent images are flattened onto a dark background and stored as JPEG without changing the endpoints' public contract.

**Architecture:** Keep moderation, auth, routing, and storage architecture unchanged. Add a profile-only image preprocessing helper in `backend/app/api/routes/users.py`, then save the transformed bytes through the existing storage provider as `image/jpeg` so storage keys use `.jpg`.

**Tech Stack:** FastAPI, Pillow, unittest/pytest, local storage provider

---

### Task 1: Add regression tests for profile upload normalization

**Files:**
- Create: `backend/tests/test_profile_image_processing.py`
- Test: `backend/tests/test_local_storage_provider.py`

- [ ] **Step 1: Write failing tests for image normalization and JPEG storage**

Add tests that:
- build a transparent PNG with EXIF orientation metadata
- call the shared profile-image normalization helper
- assert the result is JPEG, RGB, correctly orientation-normalized, and flattened against `#0d0e12`
- call both `upload_my_avatar` and `upload_my_cover` with a transparent PNG and assert the storage provider receives `image/jpeg`, a `.jpg` URL remains in the response, and `avatar_url` / `cover_url` response shapes remain unchanged

- [ ] **Step 2: Run targeted tests to verify they fail**

Run: `cd backend && python3 -m pytest backend/tests/test_profile_image_processing.py -q`

Expected: failure because profile uploads currently pass raw bytes and original content type through to storage.

### Task 2: Implement profile-only normalization helper

**Files:**
- Modify: `backend/app/api/routes/users.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add Pillow dependency declaration**

Add `Pillow==12.1.0` under utilities in `backend/requirements.txt` if it is not already declared there.

- [ ] **Step 2: Add minimal helper logic in `users.py`**

Implement a helper that:
- opens upload bytes with Pillow
- applies `ImageOps.exif_transpose`
- detects transparency for `RGBA`, `LA`, and palette images with transparency metadata
- composites onto `#0d0e12` when transparency exists
- converts to RGB
- writes optimized JPEG bytes with quality `91`

- [ ] **Step 3: Route avatar and cover uploads through the helper**

After moderation passes, preprocess the bytes and save with:
- `content=normalized_bytes`
- `content_type="image/jpeg"`
- `original_filename=file.filename`

### Task 3: Verify and review regression safety

**Files:**
- Modify: `backend/tests/test_profile_image_processing.py`

- [ ] **Step 1: Re-run targeted tests**

Run: `cd backend && python3 -m pytest backend/tests/test_profile_image_processing.py backend/tests/test_local_storage_provider.py -q`

Expected: passing tests confirming `.jpg` storage behavior and stable response fields.

- [ ] **Step 2: Review risks against requirements**

Check explicitly that:
- endpoint paths are unchanged
- request/response shapes are unchanged
- moderation still evaluates original upload bytes before storage
- only avatar and cover flows are affected
