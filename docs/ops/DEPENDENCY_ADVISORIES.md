# Open dependency advisories — accepted risk register

Tracks advisories that `npm audit` / `pip-audit` report on the current pinned
versions and that we consciously chose **not** to fix before launch. Anything not
listed here must be fixed, not waived.

Last reviewed: **2026-09-08**. Re-review on every release tag and at least monthly.

## next 14.2.35 — 7 high advisories · deferred

`npm audit` reports SSRF via Server Actions, SSRF via attacker-controlled rewrite
destinations, a Server Actions DoS, cache-confusion of response bodies, and
disclosure of internal Server Function endpoints.

Why deferred: the only published resolution is `next@16.3.4`, a two-major jump.
`npm audit fix` cannot reach it. App Router and Server Actions surfaces need a
full re-test pass, so this is scheduled work rather than a pre-launch patch.

Exposure today is narrower than the advisory titles suggest:

- Rewrite destinations in `frontend/next.config.js` are built from
  `API_INTERNAL_URL` (our own env), never from request input.
- The app uses no Server Actions — mutations go through the FastAPI backend.

Mitigation until the bump lands: nginx fronts the app and does not forward
arbitrary rewrite targets; keep `API_INTERNAL_URL` pointed at the internal
service name only.

Owner: frontend. Target: first post-launch maintenance window.

## chromadb 0.5.23 — CVE-2026-45830 / -45831 / -45833 · no fix available

Pinned as `chromadb>=0.5.23,<0.6.0` in `backend/requirements.txt`. No patched
release exists upstream within that range, so there is no action to take today.

Exposure: ChromaDB runs on the internal Docker network only
(`docker-compose.prod.yml` does not publish its port) and is reachable solely by
the backend and Celery workers.

Owner: backend. Action: re-audit monthly; bump as soon as upstream ships a fix.

## Closed in this pass

- `@playwright/test` — bumped to `^1.55.1`, clearing the browser-download
  certificate-validation advisory. Dev/CI-only dependency, never shipped.
