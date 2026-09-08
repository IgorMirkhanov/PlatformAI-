# Open dependency advisories — accepted risk register

Tracks advisories that `npm audit` / `pip-audit` report on the current pinned
versions and that we consciously chose **not** to fix. Anything not listed here
must be fixed, not waived.

Last reviewed: **2026-09-08**. Re-review on every release tag and at least monthly.

## chromadb 0.5.23 — CVE-2026-45830 / -45831 / -45833 · no upstream fix

Pinned as `chromadb>=0.5.23,<0.6.0` in `backend/requirements.txt`, Docker image
`chromadb/chroma:0.5.23`. The same cluster is still open in PyPI `chromadb==1.5.9`
(latest as of this review): there is **no patched release** to bump to.
Jumping the client/server to 1.x would also break the 0.5 HTTP/collection API
this repo uses, without closing the CVE.

Mitigations in this repo:

- Chroma is bound to the internal Docker network only (`expose`, not `ports`).
- Production compose requires `CHROMA_AUTH_TOKEN` /
  `CHROMA_AUTHN_PROVIDER=chromadb.auth.token_authn.TokenAuthenticationServerProvider`.
  The FastAPI client sends the same token. Unauthenticated IDOR/RCE from the
  advisory assumes an open listener.
- Application RAG already isolates tenants by collection name (`org_{id}` /
  `bot_{id}`).

Owner: backend. Action: re-audit monthly; bump the pin the day upstream ships a
fix that still speaks the 0.5 HTTP API, or schedule a dedicated 1.x migration.

## Closed in this pass

- `next@14.2.35` — upgraded to `next@16.3.4` (React 19.2). Clears the seven
  high Server Actions / rewrite advisories. Middleware stays as `middleware.ts`
  (deprecated in 16, still supported).
- `@playwright/test` — `^1.55.1`, browser-download cert-validation advisory.
