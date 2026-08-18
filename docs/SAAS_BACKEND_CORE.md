# SaaS Backend Core — migrations & smoke test

## Apply migrations

From `backend/`:

```bash
# Ensure DATABASE_URL / JWT_SECRET_KEY / CREDENTIALS_ENCRYPTION_KEY are set
alembic upgrade head
```

Expected revisions:

1. `017_tenancy_auth` — org slug, projects, auth flags
2. `019_saas_core` — soft deletes, refresh/reset/oauth tables, integrations, BotFlow nodes/edges

Fresh empty DB also works with:

```bash
python scripts/bootstrap_database.py
alembic stamp head   # if bootstrap already created tables matching models
# OR
alembic upgrade head
python scripts/bootstrap_database.py
```

Bootstrap seeds:

- Superadmin: `BOOTSTRAP_SUPERADMIN_EMAIL` / `BOOTSTRAP_SUPERADMIN_PASSWORD` (defaults `admin@mp.ai` / `ChangeMeNow!`)
- Default Organization + Project (`slug=default`)

## Smoke test auth

```bash
# Register
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"password123","full_name":"Demo","company_name":"Demo Org"}'

# Login (returns access_token + refresh_token)
curl -s -X POST http://localhost:8000/api/v1/auth/login/json \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"password123"}'

# Refresh
curl -s -X POST http://localhost:8000/api/v1/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh_token":"<REFRESH>"}'

# Me (tenant via JWT company_id or X-Tenant-ID)
curl -s http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer <ACCESS>"

# Tenant-scoped bots
curl -s http://localhost:8000/api/v1/saas/bots \
  -H "Authorization: Bearer <ACCESS>" \
  -H "X-Tenant-ID: <ORG_UUID>"

# Health
curl -s http://localhost:8000/api/v1/health/live
curl -s http://localhost:8000/api/v1/health/ready
curl -s http://localhost:8000/metrics
```

## Password reset (email stub)

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/forgot-password \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com"}'
# Token is logged by EmailStub (LOG_FORMAT=json recommended)
```

## Optional fastapi-users

Set `FASTAPI_USERS_ENABLED=true` to mount `/api/v1/users` (me/update). Login/register stay on `/api/v1/auth`.

## Layout

```
backend/app/
├── api/routers/     # auth extensions, organizations, saas bots, billing/webhooks aliases
├── api/endpoints/   # production routes (bots, webhooks, …)
├── core/            # config, db, security, deps, middleware, tenant
├── models/          # user, organization, integration, auth_tokens, mixins
├── schemas/
├── repositories/    # tenant-aware data access
├── services/
├── tasks/
└── utils/           # encryption façade
```

RBAC roles: `OWNER` / `ADMIN` / member (`PROMPT_ENGINEER` | `OPERATOR`).
