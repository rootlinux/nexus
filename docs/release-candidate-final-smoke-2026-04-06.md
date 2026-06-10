# Release Candidate Final Smoke

Date: 2026-04-06

Verdict: GO

## Release Candidate Summary

- Final smoke was run against the local production-like Docker Compose path in [`deploy/docker-compose.yml`](/Users/berkesahin/Desktop/X/deploy/docker-compose.yml).
- Runtime checks passed:
  `GET /health = 200`
  `GET /ready = 200`
  web root reachability = `200`
  migration revision = `017_user_blocks`
- Core product runtime was verified through real authenticated API flows plus browser rendering/click-through checks across auth, feed, search, profile, notifications, messages, block/safety, moderation, and admin.

## What Was Verified

- Auth/session:
  admin login, refresh/bootstrap, logout, relogin
  normal-user signup, login, refresh/bootstrap, logout, relogin
  cookie-backed refresh path issued and rotated refresh tokens correctly
- Home/feed:
  feed load
  image upload and media fetch
  post creation
  like, bookmark, repost, reply
- Search/discovery:
  matching search
  empty search
  explore
  trending/right-rail data
- Profile/membership:
  own profile
  other-member profile
  inviter/trust cue
  assigned-invite membership cue
  profile tabs for posts, replies, media, reposts
- Notifications/conversation:
  notification list
  mark one read
  mark all read
  thread/detail fetch
  browser click-through from notifications into post detail
  conversation re-entry cues rendered in browser
- Messages:
  inbox load
  thread open
  send message
  persistence after reload in browser
- Block/safety/moderation:
  block user
  blocked profile access
  blocked DM send/read
  unblock restore
  suspicious avatar created moderation queue item
  moderation dashboard, queue, detail
  false-positive dismiss path
- Admin:
  admin login
  moderation dashboard
  moderation queue
  moderation action flow
  users list/count
  invite list/detail/reveal
  admin search

## Known Non-Blockers

- None verified in this final smoke pass.

## Rollback-Ready Operator Notes

- Check first:
  `docker compose -f deploy/docker-compose.yml ps`
  `docker compose -f deploy/docker-compose.yml logs --tail=100 backend`
  `curl -fsS http://<api-host>/health`
  `curl -i http://<api-host>/ready`
  `curl -I http://<web-host>/`
- Key services:
  `postgres`
  `redis`
  `backend`
  `web`
- Migration truth:
  at the time of this smoke, the stack reached `alembic_version = 017_user_blocks`
  this document is historical smoke evidence, not the current repo migration source of truth
- Symptoms that mean rollback now:
  `GET /ready` fails or returns `503`
  backend crash-loops during `alembic upgrade head` or startup
  web is up but authenticated browser traffic cannot reach API
  login/refresh fails across the real deployment hostname
  admin or core write paths return repeatable 5xx after deploy

## Go / No-Go Recommendation

GO

## Follow-On Operating Doc

- Controlled rollout plan for the next step:
  [`docs/controlled-private-beta-rollout-2026-04-06.md`](/Users/berkesahin/Desktop/X/docs/controlled-private-beta-rollout-2026-04-06.md)
