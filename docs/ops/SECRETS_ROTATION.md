# Secrets rotation runbook — MP.AI

**Owner:** Security + Ops  
**When:** scheduled (90 days) or after any suspected leak.  
**Never** commit rotated values. Edit `.env.production` on the host only.

Prerequisites: SSH to the production host, `docker compose` v2, a recent `./deploy.sh backup`.

---

## 0. Before you start

1. Announce a short maintenance window if JWT or DB credentials change (users will be signed out).
2. Snapshot:

```bash
./deploy.sh backup
cp .env.production ".env.production.bak.$(date -u +%Y%m%dT%H%M%SZ)"
```

3. Keep the backup **offline** (not in git, not on a public volume).

---

## 1. JWT_SECRET_KEY

**Effect:** all access/refresh tokens become invalid; everyone re-logins.

```bash
openssl rand -hex 32
# set JWT_SECRET_KEY=... in .env.production
./deploy.sh
```

Do **not** reuse this value for `CREDENTIALS_ENCRYPTION_KEY` or `ENCRYPTION_KEY`.

---

## 2. INTERNAL_SERVICE_API_KEY / OPERATOR_WS_TOKEN / METRICS_SCRAPE_TOKEN

**Effect:** Celery ↔ API, operator websocket, Prometheus scrape (if gated).

1. Generate new hex secrets.
2. Update `.env.production`.
3. `./deploy.sh` so API, Celery, frontend, and Prometheus pick up the same values.
4. If Grafana/Prometheus used `x-metrics-token`, update the scrape config the same minute.

---

## 3. Postgres / Redis passwords

**Effect:** brief outage while containers recreate.

1. Generate new passwords (`openssl rand -hex 16`).
2. Update **all** of: `POSTGRES_PASSWORD`, `DATABASE_URL`, `REDIS_PASSWORD`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`.
3. For Postgres already running with the old password, change inside the volume first:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "ALTER USER ${POSTGRES_USER} WITH PASSWORD '<new>';"
```

4. Then write the new URLs into `.env.production` and `./deploy.sh`.

Redis: set `requirepass` via compose env and recreate `redis` (RDB persists; clients reconnect).

---

## 4. CREDENTIALS_ENCRYPTION_KEY / ENCRYPTION_KEY (Fernet / AES-GCM vault)

**Danger:** rotating without re-encrypting **destroys** tenant tokens (Telegram, Wazzup, CRM, BYOK).

Preferred path:

1. Keep the **old** key available as `CREDENTIALS_ENCRYPTION_KEY_PREVIOUS` only if a dual-read path is deployed. Current v1 does **not** dual-read — do not rotate these keys unless you have a re-encrypt job and a restore drill.
2. If a leak is confirmed: restore DB from backup taken **before** the leak, then rotate, then ask tenants to reconnect channels.

Until a dual-key migrator ships, treat vault keys as **rotate-only-with-restore**.

---

## 5. Stripe / TipTop

1. Roll restricted keys in the provider dashboard.
2. Create a **new** webhook signing secret; point the endpoint at `POST /api/v1/billing/stripe/webhook`.
3. Update `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `TIPTOP_API_SECRET`.
4. Replay failed events from the Stripe Dashboard after `./deploy.sh`.

---

## 6. Platform LLM keys (OpenAI / Groq / OpenRouter)

Revoke in the vendor console → put the new key in `.env.production` → recreate `backend_api` and `celery_worker`. Tenant BYOK tokens live in the vault, not in this file.

---

## 7. Bootstrap superadmin password

Change via the admin UI or SQL bcrypt update. Checklist §2.3: do this **before** inviting design partners. Never leave the documented `admin@mp.ai` default in production.

---

## 8. Verify

```bash
./deploy.sh verify
# login once; send a test Telegram or execute call
# confirm Stripe test webhook (Dashboard → Send test event)
```

If login or decrypt fails, restore `.env.production.bak.*` and the matching backup from step 0, then `./deploy.sh`.

---

## Related

- [PRODUCTION_DEPLOY.md](./PRODUCTION_DEPLOY.md) — deploy / rollback
- [PRODUCTION_LAUNCH_CHECKLIST.md](../PRODUCTION_LAUNCH_CHECKLIST.md) §2, §4.3
