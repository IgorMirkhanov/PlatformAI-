# MP.AI

Multi-tenant AI bot SaaS: React Flow builder, RAG, WhatsApp/Telegram, billing.

## Quick start (dev)

```bash
# Backend
cd backend && pip install -r requirements.txt
python scripts/bootstrap_database.py
alembic stamp head
python scripts/seed_initial_data.py
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm ci && npm run dev
```

On a **brand-new, empty database** use exactly the commands above. Do **not** run
`alembic upgrade head` on an empty database — the chain starts at revision `017`
and layers additively onto the schema that `bootstrap_database.py` creates
(`017_tenancy_auth` adds FKs to a `users` table no migration defines), so it will
fail. `alembic upgrade head` is the right command only for an **existing**
deployment that is behind on migrations.

Admin Panel access comes from `PLATFORM_SUPERADMIN_EMAILS` (comma-separated) in
your env — there is no built-in default owner, and the listed accounts must be
registered before the grant applies.

OpenAPI: http://localhost:8000/docs  
Prometheus: http://localhost:8000/metrics  

## Production

See [docs/ops/PRODUCTION_DEPLOY.md](docs/ops/PRODUCTION_DEPLOY.md) and `./deploy.sh`.

## v1.0 SaaS

- Roadmap: [docs/V1_ROADMAP.md](docs/V1_ROADMAP.md)
- Launch checklist: [docs/PRODUCTION_LAUNCH_CHECKLIST.md](docs/PRODUCTION_LAUNCH_CHECKLIST.md)
- Architecture: [docs/architecture/SAAS_V1.md](docs/architecture/SAAS_V1.md)
- User guide: [docs/user/getting-started.md](docs/user/getting-started.md)

## CI

GitHub Actions: `.github/workflows/ci.yml` (lint/test/build/security), `deploy-preview.yml`.
