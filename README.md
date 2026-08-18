# MP.AI

Multi-tenant AI bot SaaS: React Flow builder, RAG, WhatsApp/Telegram, billing.

## Quick start (dev)

```bash
# Backend
cd backend && pip install -r requirements.txt
python scripts/bootstrap_database.py
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm ci && npm run dev
```

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
