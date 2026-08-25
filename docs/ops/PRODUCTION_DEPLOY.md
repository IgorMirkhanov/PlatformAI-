# MP.AI Production migration & deploy guide
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
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T whatsapp_service wget -qO- http://127.0.0.1:3001/health
```

