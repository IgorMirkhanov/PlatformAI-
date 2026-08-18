# Production infra migration (MP.AI)

Unified edge config is **`nginx/mpai.conf` only**.  
Legacy `nginx.prod.conf` / `nginx.prod.http.conf` are deprecated stubs.

## 1. Migrate from previous compose

```bash
cd /path/to/ai-bot-platform

# Keep existing volumes — do NOT docker volume rm
docker compose -f docker-compose.prod.yml --env-file .env.production ps

# Merge new env keys from example (WhatsApp, JWT, resource limits, LOG_*)
cp .env.production .env.production.bak.$(date +%s)
# manually merge keys from .env.production.example into .env.production

# Ensure WhatsApp URLs are Docker-internal (not localhost):
#   WHATSAPP_SERVICE_URL=http://whatsapp_service:3001
#   WHATSAPP_SERVICE_WS_URL=ws://whatsapp_service:3001

chmod +x deploy.sh
./deploy.sh
```

What happens:

1. Secret validation (rejects `CHANGE_ME`, short passwords, mismatched WS tokens).
2. Parallel image build (`backend` / `frontend` / `whatsapp`).
3. Data plane up → **backup** into `backups/<UTC-stamp>/` (Postgres, Redis RDB, Chroma tarball, WhatsApp sessions).
4. Idempotent migrations.
5. Graceful stop nginx/celery/frontend → rolling recreate → full verify.

## 2. First-time install

```bash
cp .env.production.example .env.production
# edit all CHANGE_ME_*
./deploy.sh
```

Self-signed TLS is auto-created when certs missing (`ALLOW_SELF_SIGNED=1`).

## 3. Test commands

```bash
# Stack status
docker compose -f docker-compose.prod.yml --env-file .env.production ps

# Deploy verify only
./deploy.sh verify

# Healthchecks
curl -fk https://$MPAI_DOMAIN/healthz
curl -fk https://$MPAI_DOMAIN/healthcheck
curl -fk https://$MPAI_DOMAIN/api/v1/health/live
curl -fk https://$MPAI_DOMAIN/api/v1/health/ready

# WhatsApp (from host via nginx path or exec)
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T whatsapp_service wget -qO- http://127.0.0.1:3001/health

# Metrics
curl -fk https://$MPAI_DOMAIN/metrics || \
  docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec -T backend_api python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read()[:200])"

# Backup only
./deploy.sh backup
ls -la backups/
```

## 4. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Lost WhatsApp QR sessions | Never delete volume `mpai_whatsapp_sessions`; backups include `whatsapp-sessions.tgz` |
| `deploy.resources` ignored on plain Compose | Limits apply under Swarm; on Compose they are advisory — still set for Swarm/K8s portability; use cgroup limits via Docker Desktop/OS if needed |
| Self-signed TLS breaks messengers | Issue Let's Encrypt before Telegram/WhatsApp Cloud webhooks |
| Brotli not in stock `nginx:alpine` | Gzip + `gzip_static` enabled; for Brotli switch image to `fholzer/nginx-brotli` |
| Circular start: WA waits for API | Intentional; inbound webhooks need API. First boot: API healthy → WA |
| Failed migration mid-flight | Abort keeps prior containers if recreate not yet done; restore `backups/<stamp>/postgres.sql.gz` |
| Redis BGSAVE lag | Backup waits 2s; empty RDB on first boot is OK |

## 5. Rollback

```bash
# Restore Postgres
gunzip -c backups/<stamp>/postgres.sql.gz | \
  docker compose -f docker-compose.prod.yml --env-file .env.production \
    exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# Restore WhatsApp sessions
docker run --rm -v mpai_whatsapp_sessions:/to -v "$PWD/backups/<stamp>":/from alpine \
  sh -c 'cd /to && tar xzf /from/whatsapp-sessions.tgz'

git checkout <previous-sha>
./deploy.sh
```
