# Local Predeploy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove local-only smoke, cache, and temporary artifacts that should not ride along in a release-candidate rsync, while preserving production-relevant source, docs, migrations, and configs.

**Architecture:** Inspect candidates against repository references and ignore rules first, then remove only clearly local/generated leftovers. Finish with fresh verification of the remaining suspicious files so the cleanup report distinguishes deleted items from intentionally kept items.

**Tech Stack:** Shell utilities, git status, ripgrep, filesystem cleanup

---

### Task 1: Identify Safe Cleanup Targets

**Files:**
- Modify: `docs/superpowers/plans/2026-04-17-local-predeploy-cleanup.md`
- Inspect: `.gitignore`
- Inspect: `README.md`
- Inspect: `docs/final-predeploy-completion-2026-04-12.md`

- [ ] **Step 1: Inventory suspicious files and directories**

Run: `git status --short && rg --files && find . -maxdepth 4 \\( -type d -name 'tmp' -o -type d -name 'test-results' -o -type d -name '.pytest_cache' -o -type d -name '__pycache__' \\)`
Expected: a concrete list of smoke artifacts, caches, temp outputs, duplicate directories, and local env files to review.

- [ ] **Step 2: Verify references before deletion**

Run: `rg -n "tmp/mail|testsprite_tests|feedback_private_uploads|backend/uploads|app 2|constants 2|utils 2|stitch\\.zip|tmp_admin_|smoke_test\\.py" .`
Expected: identify which suspicious paths are actively referenced and which are dead or local-only.

### Task 2: Remove Only Clearly Local Artifacts

**Files:**
- Remove: `smoke_test.py`
- Remove: `tmp_admin_playwright_smoke.spec.ts`
- Remove: `tmp_admin_webauthn_flow.js`
- Remove: `tmp_virtual_authenticator_credentials.json`
- Remove: `test-results/`
- Remove: `testsprite_tests/`
- Remove: `archive/verification-artifacts/`
- Remove: `backend/tmp/`
- Remove: `web/test-results/`
- Remove: `web/testsprite_tests/`
- Remove: `mobile/app 2/`
- Remove: `mobile/constants 2/`
- Remove: `mobile/utils 2/`
- Remove: local cache directories such as `.pytest_cache/`, `backend/.pytest_cache/`, `__pycache__/`, `web/.next/`, `mobile/.expo/`, `mobile/.expo 2/`

- [ ] **Step 1: Delete the verified local-only artifacts**

Run: `rm -rf ...`
Expected: only local smoke/debug outputs, duplicate directories, and generated caches are removed.

- [ ] **Step 2: Preserve ambiguous or runtime-relevant files**

Keep in place: `backend/.env`, `deploy/.env.local-smoke`, `web/.env.local`, `backend/uploads/`, `backend/feedback_private_uploads/`, `docs/`, `deploy/`, migrations, and example env/config files.
Expected: the workspace still contains all source, deployment docs, and local runtime directories that may be needed outside this cleanup pass.

### Task 3: Verify Release-Candidate State

**Files:**
- Inspect: remaining repo root

- [ ] **Step 1: Re-scan for removed artifact categories**

Run: `find . -maxdepth 4 \\( -type d -name 'tmp' -o -type d -name 'test-results' -o -type d -name '.pytest_cache' -o -type d -name '__pycache__' \\) | sort`
Expected: only intentionally kept runtime paths remain.

- [ ] **Step 2: Verify final suspicious keeps**

Run: `ls -d backend/uploads backend/feedback_private_uploads deploy/.env.local-smoke backend/.env web/.env.local 2>/dev/null`
Expected: confirm the intentionally kept runtime/env paths still exist for manual handling or runtime use.

- [ ] **Step 3: Capture final delta**

Run: `git status --short`
Expected: shows the cleanup deletions and the added plan document, with no accidental source-file removals.
