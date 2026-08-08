# Security Policy

Nexus is a portfolio project built with a security-first mindset (see the
[Security Features](README.md#security-features) section of the README). If
you find a vulnerability, please report it responsibly.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities**, and do not
disclose the issue publicly (blog post, social media, conference talk) before
a fix is available.

Report through
[GitHub's private vulnerability reporting](https://github.com/rootlinux/nexus/security/advisories/new)
for this repository. That is the only reporting channel — there is no
dedicated security mailbox for this project, and any email address claiming to
be one is not ours. Private advisories let us discuss and fix the issue before
it becomes public, and GitHub notifies you of every update on the thread.

Please include:

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept code or requests welcome)
- The affected component (`backend/`, `web/`, `nexus-mcp/`, `deploy/`)
- The commit SHA or branch you tested against

If private vulnerability reporting is disabled for your account or otherwise
unavailable to you, open a **public issue containing no technical detail** —
just "I would like to report a security issue privately" — and a private
channel will be opened from there.

## Scope

In scope:

- Authentication, session, and authorization logic (`backend/app/api`,
  `backend/app/core`)
- The admin service API and `nexus-mcp/` integration
- Deployment configuration in `deploy/` (Caddy, Docker Compose, proxy trust)

Out of scope:

- Findings that require a compromised admin/service credential to begin with
- Denial-of-service via brute-force volume rather than a logic flaw
- Issues in third-party dependencies — report those upstream, but let us know
  if Nexus is affected
- Anything that depends on a development-only escape hatch being enabled
  (`ENABLE_BOOTSTRAP_ADMIN`, `ENABLE_ADMIN_WEBAUTHN_RECOVERY`). Both are
  rejected at startup when `APP_ENV` is a production value — a report that
  *those startup guards can be bypassed* is very much in scope.

## Supported Versions

Nexus is a single-deployment project with no released versions. Only the
current `main` branch is supported; there are no backports to older commits.

## Response

This is a personal project, not a company with an SLA. Expect an
acknowledgment within a few days and a fix or mitigation plan once the report
is triaged. Credit is given in release notes unless you'd prefer to stay
anonymous.
