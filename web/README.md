This is the Lukeyz web app built with Next.js.

## Getting Started

First, run the development server:

```bash
npm run dev
```

This repo intentionally uses the webpack dev runtime for local work. On Next.js 16, plain `next dev` defaults to Turbopack, and that path has been unstable here on dynamic routes like `/auth`, `/[username]`, and `/post/[id]` during browser smoke verification.

`npm run dev` clears `web/.next/dev` before starting so local development does not inherit stale or mixed-runtime artifacts from a previous session.

If you need to compare against Turbopack explicitly, use:

```bash
npm run dev:turbopack
```

That opt-in path also clears `web/.next/dev` first so switching between webpack and Turbopack does not require a manual cache delete.

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

For the local production-like smoke path, use the root deploy docs and `deploy/docker-compose.yml` instead of ad hoc web-only deploy assumptions.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Notes

- Manifest source of truth: `web/src/app/manifest.ts`
- Service worker source of truth: `web/public/sw.js`
- Deploy/runbook source of truth lives in the repo-root `docs/` and `deploy/` paths, not Vercel template defaults.
- Final predeploy operator pack: `docs/final-predeploy-completion-2026-04-12.md`
