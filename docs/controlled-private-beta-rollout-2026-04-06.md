# Controlled Private Beta Rollout

Date: 2026-04-06

Recommendation: READY FOR SMALL PRIVATE BETA

## Summary

- The current release candidate is `GO` and is suitable for a small controlled private beta.
- This phase is for operational learning, reliability validation, and safety validation under real but limited usage.
- This is not a growth push. Keep the user group small, attributable, and easy to support manually.

## 1. Recommended First Beta Cohort

- Size:
  `10-20` people total
- User type:
  trusted friends, former coworkers, builder-types, and socially active users who will actually post, reply, DM, and report issues clearly
- Why this cohort first:
  they create interpretable feedback, they are more likely to exercise the core social loops, and the blast radius stays small if something breaks

Preferred first-cohort traits:

- tolerant of rough edges
- responsive in chat
- willing to retry normal flows like login, posting, replies, notifications, and messages

Avoid first:

- users who expect a polished public launch experience
- users who need heavy onboarding support
- users likely to redistribute invites outside the intended cohort

## 2. Rollout Stages

### Stage 0: internal/self

- Keep founder/operator accounts active, one admin account, and a few internal test identities.
- Before opening real beta traffic on the final deploy, revoke any leftover staff refresh tokens from pre-launch testing.
  `docker compose -f deploy/docker-compose.yml exec postgres psql -U postgres -d xplatform -c "UPDATE refresh_tokens AS rt SET revoked = TRUE FROM staff_permissions AS sp WHERE sp.user_id = rt.user_id AND rt.revoked = FALSE;"`
- Right after deploy, confirm production-host auth, posting, notifications, DM, block, moderation queue, and admin views.
- Do not add outside users until the live host path looks boring.

### Stage 1: trusted micro-cohort

- Invite `10-20` personally known users over `2-3` days, not all at once.
- Release invites in batches of `3-5`.
- Wait between batches to observe auth, posting, replies, notifications, DM, and support noise.

### Stage 2: controlled invite-only beta

- Expand to roughly `30-75` total users only if Stage 1 stays healthy for several days.
- Keep invites deliberate and attributable to a known source.
- No open sharing and no uncontrolled forwarding.

### Stage 3: slightly broader private beta

- Expand only after a stable week with low support noise and no safety leakage.
- Growth remains invite-led and wave-based.
- Do not widen faster than moderation and operator review capacity.

### Gate To Move Stages

- no recurring auth/session failures
- no moderation or block leakage
- no repeated DM or notification failures
- no runtime instability around `GET /ready`, startup, or core write flows
- support load remains understandable and manually manageable

## 3. Success Signals

Good early beta health looks like:

- new invitees can validate invite, sign up, log in, refresh, and return later without session confusion
- users create real posts with replies, likes, reposts, bookmarks, or media uploads
- a few genuine DM conversations happen and survive reload and re-entry
- search, profile, and notification flows are used without users getting stuck
- block and moderation paths stay quiet in the good way: no leakage, no obvious abuse gaps, no "I can still see or message this person" reports
- support questions are low-volume and mostly clarifications, not broken-core-flow complaints
- operators can explain each notable issue quickly instead of discovering vague instability

## 4. Warning Signals

Trigger concern quickly if any of these appear more than once or affect more than one user:

- auth/session problems:
  signup failure, login loops, refresh or cookie issues, surprise logouts, broken relogin
- core social regressions:
  post create fails, replies disappear, feed load errors, search returns bad or empty results unexpectedly
- notification or DM failures:
  messages not sending, threads not loading, notifications not appearing, click-throughs landing broken
- safety/control failures:
  block does not fully cut profile or DM access, moderation queue misses suspicious content, admin actions fail or lag
- deploy/runtime issues:
  `GET /ready` instability, backend crash-loops, Redis/Postgres dependency problems, repeated `5xx` on write paths
- support friction:
  multiple users needing direct operator help for the same action

### Immediate Hold Criteria

- any confirmed moderation or block leakage
- repeated auth/session breakage
- repeated DM data loss or send/read inconsistency
- readiness or startup instability after deploy

If any hold criterion is hit, pause new invites and return to internal-only verification until the issue is understood.

## 5. Operator Review Cadence

### First 24 hours

- Review closely after release, then at least every few hours while users are active.
- Check:
  `docker compose -f deploy/docker-compose.yml ps`
  `docker compose -f deploy/docker-compose.yml logs --tail=100 backend`
  `curl -fsS http://<api-host>/health`
  `curl -i http://<api-host>/ready`
- Also verify one real auth flow and one real product flow on the live hostname.

### First 3 days

- Do a morning and evening review.
- Check runtime health, signup/login success, post/reply/DM behavior, moderation queue, admin signals, and whether support questions cluster around one broken area.

### First week

- Do a daily review.
- Focus on recurring failure patterns, safety incidents, and whether usage is real enough to justify widening the cohort.

### Operator Note Template

Record one short note per review:

- what changed
- what broke
- what feels noisy but acceptable
- rollout decision: `hold`, `continue`, or `pause`

## 6. Invite Discipline

- Use personal invites first, not broad waves.
- Founder or admin should manually assign every invite in Stage 1.
- Keep every beta user attributable to a known source.
- Release invites in small batches of `3-5`, then observe before sending more.
- Do not let first-cohort users freely redistribute invites yet.
- Only move to small waves in Stage 2 after Stage 1 looks stable and understandable.

## 7. Feedback Collection

Keep this lightweight and founder-usable:

- one private chat channel or group thread for fast reporting
- one simple bug template with:
  `what happened`
  `what you expected`
  `device/browser`
  `screenshot if relevant`
  `time it happened`
- one internal running log grouped into:
  `bug`
  `confusion`
  `trust/safety`
  `product feel`

Ask beta users for feedback in three buckets only:

- what broke
- what felt confusing
- what felt unexpectedly good or bad in real use

## 8. User-Facing Known Limits

Current status: no verified non-blockers were recorded in the final smoke pass.

Suggested cohort framing:

- This is a small private beta, so you may see occasional rough edges or fast changes.
- Please report anything involving login, posting, messages, notifications, blocking, or safety immediately.
- Invite access is intentionally limited while reliability and moderation quality are being verified.

Keep the tone calm and controlled. Do not apologize pre-emptively and do not imply broader launch readiness yet.

## Brief Rollout Recommendation

- Recommendation:
  `ready for small private beta`
- Shape:
  start with a `10-20` person trusted cohort, use manual invites, monitor closely, and keep explicit pause criteria
- Expansion rule:
  do not widen beyond that until auth, messaging, notifications, and safety controls stay boring for several days

## Assumptions

- The current release candidate remains the deployed build baseline.
- Invite-only access, moderation, block behavior, and admin review paths are available as verified in the release smoke.
- No additional feature work is part of this beta. The objective is controlled rollout, operational learning, and safety validation.
