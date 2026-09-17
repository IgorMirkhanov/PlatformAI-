# MP.AI Production migration & deploy guide
#
# Free / cheap public hosting (Vercel vs Docker VM vs Cloudflare Tunnel):
#   docs/ops/FREE_HOSTING.md
#
# Target layout after this upgrade:
#   docker-compose.prod.yml  — postgres, redis, chromadb, backend, celery,
#                              whatsapp_service, frontend, nginx (+ optional monitoring)
#   nginx/mpai.conf          — single nginx entrypoint
#   whatsapp-service/Dockerfile
#   ./deploy.sh              — backup → migrate → rolling restart → verify

## 1. Pre-flight

1. Pull latest code on the server.
2. Ensure Docker Compose v2 (`docker compose version`).
3. Copy env if missing:
   ```bash
   cp .env.production.example .env.production
   ```
4. Fill all `CHANGE_ME_*` values. Required new keys:
   - `WHATSAPP_SERVICE_URL=http://whatsapp_service:3001`
   - `WHATSAPP_SERVICE_WS_URL=ws://whatsapp_service:3001`
   - `WHATSAPP_FASTAPI_WEBHOOK_URL=http://backend_api:8000/api/v1/webhooks/whatsapp-qr`
5. Confirm TLS paths (`SSL_CERT_PATH` / `SSL_KEY_PATH`) or leave
   `ALLOW_SELF_SIGNED=1` for first boot.
6. Stop using legacy nginx mounts (`nginx.prod.conf`, `nginx.prod.http.conf`).
   Compose now mounts **only** `nginx/mpai.conf`.

## 2. First-time / upgrade deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

What the script does (idempotent):

1. Validates secrets (rejects `CHANGE_ME`, short passwords, mismatched WS tokens).
2. Ensures TLS material (self-signed if needed).
3. Builds images **before** swapping containers.
4. Starts postgres/redis/chromadb.
5. `pg_dump` → `backups/pg_<db>_<utc>.sql.gz` (skipped on brand-new empty stack).
6. ORM bootstrap + tracked SQL migrations (`schema_migrations`).
7. Rolling recreate: `backend_api` → `whatsapp_service` → `celery_worker` →
   `frontend_app` → `nginx` (each waits for health where available).
8. Probes API ready, WhatsApp `/health`, nginx `/healthz`.

Useful subcommands:

```bash
./deploy.sh backup     # dump only
./deploy.sh migrate    # backup + migrations
./deploy.sh verify     # health probes
ENABLE_MONITORING=1 ./deploy.sh   # also start Prometheus/Grafana/cAdvisor
```

## 3. WhatsApp session volume

Baileys auth state lives in Docker volume `mpai_whatsapp_sessions`
(`/app/whatsapp-sessions`). Do **not** delete this volume on redeploy or QR
sessions will reset.

If you previously ran WhatsApp on the host with `./whatsapp-sessions`, copy
once:

```bash
docker run --rm -v mpai_whatsapp_sessions:/to -v "$PWD/whatsapp-service/whatsapp-sessions":/from alpine \
  sh -c 'cp -a /from/. /to/'
```

## 4. Let's Encrypt (after DNS points to the host)

```bash
# Example (host certbot + webroot already mounted at CERTBOT_WEBROOT)
certbot certonly --webroot -w ./nginx/certbot -d app.example.com
# Then set in .env.production:
# SSL_CERT_PATH=/etc/letsencrypt/live/app.example.com/fullchain.pem
# SSL_KEY_PATH=/etc/letsencrypt/live/app.example.com/privkey.pem
./deploy.sh   # recreates nginx with real certs
```

## 5. Optional monitoring

```bash
ENABLE_MONITORING=1 ./deploy.sh
# Prometheus: http://127.0.0.1:9090
# Grafana:    http://127.0.0.1:3002  (admin / GRAFANA_ADMIN_PASSWORD)
```

Bind addresses default to localhost — tunnel via SSH for remote access.

Alert rules live in `monitoring/alerts.yml` (5xx rate, Stripe webhook failures, disk/memory, container restarts). Grafana dashboards: Containers + API.

## 6. Rollback

1. Restore DB:
   ```bash
   gunzip -c backups/pg_mpai_production_YYYYMMDDTHHMMSSZ.sql.gz \
     | docker compose -f docker-compose.prod.yml --env-file .env.production \
       exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
   ```
2. Check out previous git revision and `./deploy.sh` again.
3. WhatsApp sessions remain in the named volume unless you remove it.

## 7. Frontend image: bake-time vs runtime env

Next.js `output: "standalone"` serializes `next.config.js` (including
**rewrites**) at **build** time. `API_INTERNAL_URL` is a Docker **build-arg**
(default `http://backend_api:8000` in `frontend/Dockerfile.prod`).

| Variable | When it applies |
|----------|-----------------|
| `API_INTERNAL_URL` | **Build only** — baked into `/api`, `/ws`, `/uploads` rewrites |
| `NEXT_PUBLIC_*` | **Build only** — inlined into the client bundle |
| Runtime `environment:` in compose | Does **not** change rewrites after the image exists |

If you change the internal API URL in `.env.production`, you must **rebuild**
the frontend image (`docker compose … build frontend_app` / `./deploy.sh`),
not only recreate the container.

**Always build the production frontend inside Linux Docker** (`Dockerfile.prod`).
Do not copy a local Windows `.next/` into the image — that leaks host paths and
Preview Mode keys, and may bake `127.0.0.1:8000` rewrites.

`frontend/.dockerignore` excludes `.next`; the runner stage copies only
`.next/standalone` + `.next/static`. Never commit `.next/` (root +
`frontend/.gitignore`). After any accidental leak of Preview Mode keys, delete
local `.next` and rebuild so Next regenerates them.

## 8. Secrets rotation

See [SECRETS_ROTATION.md](./SECRETS_ROTATION.md). Snapshot env + `./deploy.sh backup` first. Do not rotate `CREDENTIALS_ENCRYPTION_KEY` / `ENCRYPTION_KEY` without a restore plan.

## 9. Test checklist

See section “Checklist” in the ops summary / PR description, or run:

```bash
./deploy.sh verify
curl -fk https://$MPAI_DOMAIN/healthz
curl -fk https://$MPAI_DOMAIN/healthcheck
curl -fk https://$MPAI_DOMAIN/api/v1/health/live
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T whatsapp_service wget -qO- http://127.0.0.1:3001/health
```

**Do not** treat bare `GET /api/v1/health/ready` as a public readiness probe.
In production that route returns **403** unless you send `X-Internal-Api-Key`
(or the metrics scrape token). Prefer `/healthcheck` and `/api/v1/health/live`
for external smoke tests.

## 10. Windows / PowerShell (no Git Bash)

On hosts without a working `bash` (common on Windows Desktop), use
[`deploy.ps1`](../../deploy.ps1) instead of `./deploy.sh`:

```powershell
# From repo root, Docker Desktop running:
.\deploy.ps1              # build → data plane → mark SQL applied → app tier → verify
.\deploy.ps1 -VerifyOnly  # health probes only
.\deploy.ps1 -SkipBuild   # recreate containers from existing images
```

Behaviour notes:

- **SQL vs Alembic:** `deploy.sh` applies `backend/migrations/*.sql` into
  `schema_migrations`. On an already-bootstrapped DB those SQL files fail
  (`type "subscription_plan_name" already exists`). `deploy.ps1` **marks**
  those files applied and relies on the API entrypoint
  (`bootstrap_database.py` + `alembic upgrade head`) as the source of truth —
  equivalent to `SKIP_SQL_MIGRATIONS=1` for bash deploys on an Alembic DB.
- **Verify probes:** `/healthz`, `/healthcheck`, `/api/v1/health/live`,
  WhatsApp `/health`, Celery ping. A 403 on `/api/v1/health/ready` without
  an internal key is **expected**.
- Do **not** delete volume `mpai_whatsapp_sessions` on redeploy.

## 11. Protecting the DB under a traffic spike

Three things keep a burst of inbound traffic from taking down Postgres.
All three are on by default except PgBouncer.

### Request-rate limiting is Redis-backed

`app/core/rate_limit.py` (SlowAPI) is keyed off `REDIS_URL`, so the configured
limits (`RATE_LIMIT_DEFAULT`, `RATE_LIMIT_EXECUTE`) are enforced **across every
uvicorn worker and every replica**, not per-process. An in-memory limiter would
silently multiply its real ceiling by the worker count — verify this stays
Redis-backed if you ever touch `limiter = Limiter(...)`.

`POST /bots/{bot_id}/execute` — the one endpoint that does an LLM call plus DB
writes per request — is keyed by `bot_id` (`RATE_LIMIT_EXECUTE`, default
`60/minute`), not by IP: a chat widget embedded on a public site has many
visitors sharing one IP/NAT, and a flood aimed at a single bot shouldn't need
an org lookup to be contained.

### Connection-pool math vs. `max_connections`

The backend's own pool (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`, default 50 + 20 =
70) is **per uvicorn worker**. With the Dockerfile's `--workers 4` that's up
to **280** possible connections from the API alone, before Celery workers,
`whatsapp-service`, or the Telegram/GreenAPI pollers open their own. Stock
Postgres ships with `max_connections=100` — comfortably below that ceiling.

`docker-compose.prod.yml`'s `postgres` service now sets
`max_connections=${PG_MAX_CONNECTIONS:-300}` and
`shared_buffers=${PG_SHARED_BUFFERS:-512MB}` so the app degrades on its own
backpressure (pool timeout → 503) instead of Postgres refusing new connections
outright (`FATAL: sorry, too many clients already`, which affects *every*
tenant at once). If you raise `DB_POOL_SIZE` or add more uvicorn/Celery
replicas, raise `PG_MAX_CONNECTIONS` (and `PG_MEM_LIMIT`) to match.

### PgBouncer — enable for real horizontal scale-out

For more than one backend/Celery deployment, or sustained high concurrency,
raising `max_connections` further stops being the right lever (each Postgres
connection reserves real memory). The compose file already ships a `pgbouncer`
service in transaction-pooling mode; it's opt-in:

```bash
# .env.production
DATABASE_URL=postgresql+asyncpg://mpai_app:...@pgbouncer:5432/mpai_production
CELERY_BROKER_URL=... # unchanged — this only affects the Postgres connection

docker compose -f docker-compose.prod.yml --env-file .env.production \
  --profile pgbouncer up -d
```

`PGBOUNCER_DEFAULT_POOL_SIZE=50` means pgbouncer itself only ever holds 50 real
backend connections to Postgres, however many client connections
(`PGBOUNCER_MAX_CLIENT_CONN=1000`) the app opens against it — this is what
actually decouples "requests in flight" from "Postgres connections used."

