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
DB_PGBOUNCER_COMPAT=true      # REQUIRED — see below
CELERY_BROKER_URL=... # unchanged — this only affects the Postgres connection

docker compose -f docker-compose.prod.yml --env-file .env.production \
  --profile pgbouncer up -d
```

`PGBOUNCER_DEFAULT_POOL_SIZE=50` means pgbouncer itself only ever holds 50 real
backend connections to Postgres, however many client connections
(`PGBOUNCER_MAX_CLIENT_CONN=1000`) the app opens against it — this is what
actually decouples "requests in flight" from "Postgres connections used."

**This was actually stood up and load-tested** (PgBouncer 1.22, transaction
pooling, `default_pool_size=50`), not just documented from the compose file.
Two real incompatibilities surfaced immediately and are now fixed in code —
if you deploy PgBouncer without these, the API breaks on the first request:

1. **`unsupported startup parameter: statement_timeout`.** `app/db/session.py`
   used to send `statement_timeout` / `lock_timeout` /
   `idle_in_transaction_session_timeout` via asyncpg's `server_settings`
   (a Postgres startup-packet parameter). PgBouncer only forwards a fixed
   whitelist of startup parameters and rejects the rest outright — every
   request failed at connect time. Fixed by moving these three GUCs to
   `ALTER DATABASE ... SET` (migration `067_db_session_timeouts`), which
   Postgres applies to every new backend session whether it arrived directly
   or through a pooler. Run this migration **directly against Postgres**
   (port 5432), not through PgBouncer — like any DDL, it doesn't belong in a
   pooled transaction-mode connection.

2. **`DuplicatePreparedStatementError: prepared statement "__asyncpg_stmt_1__"
   already exists`.** asyncpg caches prepared statements per client
   connection, but PgBouncer in transaction mode can hand the same client
   connection a *different* Postgres backend on every transaction, so a
   statement prepared against backend A doesn't exist on backend B. This is
   a well-known asyncpg/PgBouncer incompatibility (asyncpg's own error
   message names the fix). Fixed with a new flag:
   `DB_PGBOUNCER_COMPAT=true` sets `statement_cache_size=0` on the asyncpg
   connection, which disables client-side prepared-statement caching. Leave
   this **unset/false** when `DATABASE_URL` points straight at Postgres —
   there's a small perf cost to disabling the cache, so only pay it when
   PgBouncer is actually in front.

Verified after both fixes: 60 concurrent authenticated requests through
PgBouncer with zero errors, then a full Locust run (10→25→50 users, 9 min)
against the API pointed at PgBouncer — 0% failures, and noticeably *lower*
latency than the same run direct-to-Postgres (though that direct-Postgres
run had a `next build` competing for CPU on the same box, so treat the
absolute numbers as directional, not a clean pooled-vs-direct comparison).

## 12. Observability: cache hit-rate, rate-limit abuse, LLM pipeline health

### LLM response cache hit-rate

`app/core/llm_cache.py` only implements **exact-match** caching today —
`get_semantic_cached_response` / `register_semantic_turn` are unimplemented
stubs that always miss (no embedding index wired up yet). Don't tune a
"semantic similarity threshold" that doesn't exist; if semantic caching gets
built later, wire its hit/miss into the same `mpai_llm_cache_lookups_total`
counter with `cache_type="semantic"`.

Every exact-match lookup now increments
`mpai_llm_cache_lookups_total{cache_type="exact",result="hit"|"miss"}`.
Hit-rate query:

```promql
sum(rate(mpai_llm_cache_lookups_total{cache_type="exact",result="hit"}[1h]))
/
clamp_min(sum(rate(mpai_llm_cache_lookups_total{cache_type="exact"}[1h])), 0.001)
```

A low hit rate on a bot with repetitive traffic (FAQ-style flows) usually
means `normalize_incoming_text` isn't collapsing enough variance (punctuation,
emoji, case) — that's the first thing to widen, not a similarity threshold.

### Rate-limit abuse / undersized limits

`POST /bots/{bot_id}/execute`'s 429s (and every other endpoint's) now
increment `mpai_rate_limit_exceeded_total{scope="execute"|"default"}`, and
`monitoring/alerts.yml` has `MpaiRateLimitSpike` (>100 rejections/10m). The
metric is deliberately **not** labeled by `bot_id` — that would be an
unbounded cardinality label on a Redis-backed counter with potentially
thousands of bots. To find *which* bot is hammering a limit, grep the
existing `RateLimit.exceeded` log line (already emitted on every 429,
`path=` includes the bot id) for the alert's time window — that log line was
already there, it just had no matching metric/alert to point you at it
before now.

### LLM pipeline health — real traffic, not a synthetic prober

The stress test showed `/execute` accounting for most of the run's timeouts
— exactly the traffic a synthetic health-check would need to probe. A
synthetic prober that fires a real completion request on every `/health`
scrape would burn tokens/money on every poll interval and could itself get
rate-limited by the vendor; instead, `ResilientLLMGateway.complete()` now
records **every real completion attempt** (success or failure, per
provider) to two previously-unused-but-already-declared metrics:

- `mpai_llm_completions_total{provider,result}` — `result` is `success`,
  `error`, `auth_error`, or `exhausted` (all providers failed/circuit-open).
- `ai_provider_latency_seconds{provider,model}` — was declared in
  `app/core/metrics.py` but never actually `.observe()`d anywhere; that gap
  meant there was no way to see LLM latency in Prometheus at all before this.

Two new alerts consume them: `MpaiLLMPipelineDegraded` (>20% completion
failure rate over 10m — the earliest signal /execute is unhealthy, ahead of
user reports) and `MpaiLLMPipelineSlow` (p95 latency >8s over 10m).

### Fallback-chain redundancy check at boot

`ResilientLLMGateway` already builds a real ordered fallback chain
(`LLM_PROVIDER` → `FALLBACK_LLM_PROVIDER`, default `groq`) — this was
already correct in code, not a gap. The actual risk is operational: if only
one provider's API key is ever set in `.env.production`, the "fallback" is a
keyless stub that can never serve traffic, so a single vendor outage takes
`/execute` down completely. `main.py`'s startup now logs
`Application.no_llm_fallback_redundancy` (warning level) whenever fewer than
2 of `{OPENAI,ANTHROPIC,GROQ,GEMINI,DEEPSEEK,OPENROUTER}_API_KEY` are
configured — check for that line in the boot log before commercial launch,
and set at least the primary + `FALLBACK_LLM_PROVIDER`'s key.

