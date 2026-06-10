# Cloudflare Cutover Checklist

## Required app config

- Set `APP_ENV=production`.
- Set `CORS_ALLOWED_ORIGINS` to the exact public web origins.
- Set `ALLOWED_HOSTS` to the public API hostnames that Cloudflare will proxy.
- Set `TRUST_PROXY_HEADERS=true`.
- Set `TRUSTED_PROXY_CIDRS` to the exact proxy hops that can reach the origin.
- Set `REFRESH_COOKIE_SECURE=true`.
- Set `REFRESH_COOKIE_DOMAIN` only if the refresh cookie must span subdomains.

## DNS and proxying

- Proxy the public web and API DNS records through Cloudflare.
- Keep the origin address off public links, frontend env vars, and public docs.
- Restrict direct origin access at the infrastructure layer so only Cloudflare or your trusted upstream proxy can reach it.

## Origin TLS

- Use HTTPS between Cloudflare and the origin.
- Present a valid origin certificate and prefer Full (strict) behavior at cutover.

## Cache rules baseline

- Bypass cache for all `/api/*` routes.
- Bypass cache for authenticated HTML routes such as `/messages`, `/notifications`, and `/admin`.
- Allow caching for framework static assets like `/_next/static/*`.
- Uploaded media under `/uploads/*` may be cached publicly, but the current app baseline is intentionally short-lived.

## Route policy summary

- `never cache`: auth, admin, notifications, DM, bookmarks, invites, authenticated API reads, API mutations, health.
- `bypass cache`: all `/api/*` at Cloudflare unless a later phase explicitly introduces safe public caching.
- `safe public cache`: framework static assets and uploaded media paths that are intentionally public.
- `review later before public cache`: profile pages, search/explore HTML, and any future anonymous API endpoints.

## Cloudflare-side follow-up after app prep

- Reconfirm the exact Cloudflare IP ranges or upstream proxy CIDRs used by the origin allowlist.
- Add cache bypass rules for the sensitive route groups above.
- Add origin lock-down controls so the origin is not directly reachable from the public Internet.
- Re-test login, refresh, logout, notifications, DM, search, uploads, and admin behind the proxied hostname after DNS cutover.
