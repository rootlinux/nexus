# Project Audit And Secret Scrub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify backend and web health, fix reproducible breakages, and remove committed local secrets so the repo is safe to push without actually pushing.

**Architecture:** Treat backend and web as separate verification surfaces. Reproduce failures first, fix only root causes covered by failing tests or builds, then normalize tracked env files so real credentials are replaced by placeholders or empty values that match the examples.

**Tech Stack:** FastAPI, Python 3.11, pytest/unittest, Next.js 16, React 19, ESLint, Node.js

---

### Task 1: Baseline Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-05-28-project-audit-and-secret-scrub.md`
- Inspect: `backend/README.md`
- Inspect: `web/package.json`

- [ ] **Step 1: Record the baseline repo state**

Run: `git status --short`
Expected: Existing unrelated untracked files remain visible so later edits stay narrowly scoped.

- [ ] **Step 2: Verify backend toolchain exists**

Run: `backend/scripts/bootstrap_test_env.sh`
Expected: `backend/.venv` reported ready with Python 3.11.

- [ ] **Step 3: Verify frontend dependencies exist**

Run: `npm run lint --prefix web`
Expected: Either a clean lint pass or a reproducible lint failure to investigate.

### Task 2: Backend Failure Reproduction And Fixes

**Files:**
- Modify: `backend/tests/...` as needed for failing regression coverage
- Modify: `backend/app/...` only where root cause is identified

- [ ] **Step 1: Run the backend verification surface**

Run: `cd backend && .venv/bin/pytest -q`
Expected: Full pass or a concrete failing test, import error, or startup error with file references.

- [ ] **Step 2: If backend fails, add or tighten a failing regression test first**

Run: `cd backend && .venv/bin/pytest -q path/to/targeted_test.py`
Expected: The targeted test fails for the root cause being fixed.

- [ ] **Step 3: Implement the minimal backend fix**

Run: `cd backend && .venv/bin/pytest -q path/to/targeted_test.py`
Expected: The targeted regression passes.

- [ ] **Step 4: Re-run the full backend suite**

Run: `cd backend && .venv/bin/pytest -q`
Expected: Full suite passes with no newly introduced failures.

### Task 3: Web Failure Reproduction And Fixes

**Files:**
- Modify: `web/src/...` only if lint/build/test failures require changes
- Modify: `web/tests/service-worker.test.mjs` only if regression coverage is needed

- [ ] **Step 1: Run the web verification surface**

Run: `cd web && npm run lint && npm run build && node --test tests/service-worker.test.mjs`
Expected: Clean pass or a reproducible failure with source locations.

- [ ] **Step 2: If web fails, add or tighten the smallest failing regression**

Run: `cd web && npm run lint`
Expected: The failure remains targeted to the issue being fixed.

- [ ] **Step 3: Implement the minimal web fix**

Run: `cd web && npm run build`
Expected: Build succeeds after the fix.

- [ ] **Step 4: Re-run the full web verification surface**

Run: `cd web && npm run lint && npm run build && node --test tests/service-worker.test.mjs`
Expected: All web checks pass.

### Task 4: Secret Scrub And Push Readiness

**Files:**
- Modify: `backend/.env`
- Modify: `deploy/x-backend/.env`
- Modify: `deploy/.env.docker`
- Modify: `nexus-mcp/.env`
- Modify: `.gitignore` only if tracked-sensitive local files need stronger ignore coverage

- [ ] **Step 1: Identify tracked or likely-to-be-added local secrets**

Run: `rg -n "(API_KEY|TOKEN|PASSWORD|SECRET_KEY|PRIVATE_KEY|SERVICE_TOKEN)" backend/.env deploy/.env.docker deploy/x-backend/.env nexus-mcp/.env`
Expected: Exact files and variables that must be scrubbed.

- [ ] **Step 2: Replace live secret values with placeholders or empty values aligned with example files**

Run: `git diff -- backend/.env deploy/.env.docker deploy/x-backend/.env nexus-mcp/.env .gitignore`
Expected: Diff shows no real credentials.

- [ ] **Step 3: Verify the scrub**

Run: `rg -n "(re_[A-Za-z0-9_]+|[A-Fa-f0-9]{48,}|SERVICE_TOKEN=.+)" backend/.env deploy/.env.docker deploy/x-backend/.env nexus-mcp/.env`
Expected: No live credential material remains.

### Task 5: Final Verification And Readiness Report

**Files:**
- Inspect: `git diff`

- [ ] **Step 1: Re-run fresh verification after all edits**

Run: `cd backend && .venv/bin/pytest -q && cd ../web && npm run lint && npm run build && node --test tests/service-worker.test.mjs`
Expected: All checks pass on the final tree.

- [ ] **Step 2: Summarize push readiness without pushing**

Run: `git status --short`
Expected: Only intentional code/env edits and any pre-existing unrelated files remain.
