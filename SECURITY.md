# Security Policy

Nexus is a portfolio project built with a security-first mindset (see the
[Security Features](README.md#security-features) section of the README). If
you find a vulnerability, please report it responsibly.

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Preferred: use [GitHub's private security advisory reporting](../../security/advisories/new)
for this repository. This lets us discuss and fix the issue before it's
public.

If that's not available, email `beta@example.com` with:

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept code or requests welcome)
- The affected component (`backend/`, `web/`, `nexus-mcp/`, `deploy/`)

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

## Response

This is a personal project, not a company with an SLA. Expect an
acknowledgment within a few days and a fix or mitigation plan once the report
is triaged. Credit is given in release notes unless you'd prefer to stay
anonymous.
