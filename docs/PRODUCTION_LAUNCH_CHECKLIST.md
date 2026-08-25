# Production Launch Checklist — MP.AI SaaS v1.0

**Product:** MP.AI  
**Release:** `v1.0.0`  
**Gate:** all Go-Live Criteria checked or explicitly waived (owner + date).

Engineering artifacts in this repo (2026-08-24): §2.7 env defaults, §2.8 correlation IDs on HTTP 4xx/5xx, §4.3 [secrets rotation runbook](./ops/SECRETS_ROTATION.md), §7.2 Prometheus alert pack + Grafana API dashboard, §8.1–8.2 / 8.4–8.5 legal+help pages, CI security **fails on `v*` tags**. Ops/Product still sign live boxes (TLS, backups, Stripe live, Locust, soft-launch).

| Field | Value |
|-------|--------|
| Target GA date | _______________ |
| Release branch / tag | `v1.0.0` |
| Primary owner (Eng) | _______________ |
| Security owner | _______________ |
| Ops owner | _______________ |
| Product owner | _______________ |

---

## 1. Pre-Launch — Code

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 1.1 | CI green on release branch (backend pytest, frontend build, e2e smoke, security job) | Eng | T-3d | [ ] |
| 1.2 | Alembic head applied: `020_org_stripe_customer` (after `019_saas_core`) | Eng | T-2d | [ ] |
| 1.3 | Org-level StripeCustomer backfill verified on staging | Eng | T-2d | [ ] |
| 1.4 | OpenAPI / version string = `1.0.0` (not `-rc`) | Eng | T-1d | [x] in-repo (`backend/main.py`) |
| 1.5 | No known Sev-0/1 bugs open on Flow Builder, Execute, Billing | Eng | T-1d | [ ] |
| 1.6 | CHANGELOG + RELEASE_NOTES reviewed by Product | Product | T-1d | [ ] |

---

## 2. Pre-Launch — Security

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 2.1 | No `CHANGE_ME` / placeholder secrets in `.env.production` | Security | T-3d | [ ] |
| 2.2 | Distinct `JWT_SECRET_KEY`, `CREDENTIALS_ENCRYPTION_KEY`, DB passwords; offline backup | Security | T-3d | [ ] |
| 2.3 | Bootstrap superadmin password rotated | Security | T-2d | [ ] |
| 2.4 | TLS Let's Encrypt (not self-signed) on public domain | Ops | T-2d | [ ] |
| 2.5 | Postgres / Redis not publicly reachable | Ops | T-2d | [ ] |
| 2.6 | Trivy / pip-audit / npm audit / Gitleaks reviewed; CRITICAL fixed or waived | Security | T-2d | [ ] |
| 2.7 | `AI_GUARDRAILS_ENABLED=true`, `RATE_LIMIT_ENABLED=true`, `LOG_FORMAT=json` | Eng | T-1d | [x] in-repo (example + compose; confirm live `.env.production`) |
| 2.8 | Correlation IDs present on 5xx / 402 responses | Eng | T-1d | [x] in-repo |

---

## 3. Pre-Launch — Infrastructure

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 3.1 | `docker-compose.prod.yml` + `deploy.sh` dry-run on staging | Ops | T-3d | [ ] |
| 3.2 | nginx rate limits + TLS terminate verified | Ops | T-2d | [ ] |
| 3.3 | Health: `/api/v1/health/live` + readiness behind LB | Ops | T-2d | [ ] |
| 3.4 | Disk alerts > 80%; container restart policy confirmed | Ops | T-2d | [ ] |
| 3.5 | WhatsApp Baileys session volume persists across restart | Eng | T-2d | [x] in-repo (`mpai_whatsapp_sessions`) |

---

## 4. Data & Ops

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 4.1 | Automated Postgres backup (daily) + retention ≥ 30 days | Ops | T-3d | [ ] |
| 4.2 | **Restore drill** signed off (restore to staging, smoke auth + billing) | Ops | T-2d | [ ] |
| 4.3 | Secrets rotation runbook documented | Security | T-2d | [x] [ops/SECRETS_ROTATION.md](./ops/SECRETS_ROTATION.md) |
| 4.4 | Rollback plan rehearsed (previous image + alembic downgrade note) | Ops | T-1d | [ ] |
| 4.5 | Data migration note for org Stripe executed — see § Billing | Eng | T-2d | [ ] |

---

## 5. Billing (Stripe org-level)

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 5.1 | Live/test keys: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_ENTERPRISE` | Eng | T-3d | [ ] |
| 5.2 | Webhook endpoint: `POST /api/v1/billing/stripe/webhook` (signature verified) | Eng | T-2d | [ ] |
| 5.3 | Checkout for **organization** → `stripe_customers` row + `companies.stripe_status=active` | Eng | T-2d | [ ] |
| 5.4 | Customer Portal opens from Billing UI (`/billing/portal`) | Eng | T-2d | [ ] |
| 5.5 | `invoice.paid` renews owner wallet `expires_at` + org mirror | Eng | T-2d | [ ] |
| 5.6 | Quotas (bots / messages / tokens) keyed by `organization_id` → HTTP **402** | Eng | T-2d | [ ] |
| 5.7 | Optional metering: `STRIPE_METERING_ENABLED` only after Meter configured | Eng | T-1d | [ ] |
| 5.8 | Wallet fallback still works when Stripe disabled | Eng | T-1d | [ ] |

**Data migration (org Stripe):**

```bash
cd backend
alembic upgrade 020_org_stripe_customer
# Verify:
# SELECT organization_id, stripe_customer_id, status FROM stripe_customers;
# SELECT id, stripe_status, stripe_plan, stripe_customer_id FROM companies;
```

Legacy `stripe_customer_links` is retained for rollback; new writes go to `stripe_customers`.

---

## 6. Testing

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 6.1 | Pytest green; GA-critical cov ≥ 75% (quota/stripe/analytics/usage/flow/rag/guardrails) | Eng | T-2d | [ ] |
| 6.2 | Playwright e2e smoke (login → flow-builder → billing) | Eng | T-2d | [ ] |
| 6.3 | Locust: ramp 10→50 users; ~20 RPS; **p95 `/execute` < 2s**; fail ratio < 1% | Perf | T-1d | [ ] |
| 6.4 | Manual: publish flow, Preview, Telegram webhook, WhatsApp QR, handoff | Product | T-1d | [ ] |

Locust quick start: see `docs/LOAD_TESTING.md` and `backend/locustfile.py`.

---

## 7. Monitoring & Observability

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 7.1 | Prometheus scrapes `/metrics` | Ops | T-2d | [ ] |
| 7.2 | Alerts: 5xx rate, Stripe webhook failures, disk, container restarts | Ops | T-1d | [x] pack in `monitoring/alerts.yml` (enable profile; wire receivers) |
| 7.3 | Structured JSON logs + correlation_id searchable | Eng | T-1d | [x] in-repo (`LOG_FORMAT=json`) |
| 7.4 | Dashboard: Usage meters match `UsageEvent` / org analytics | Eng | T-1d | [ ] |

---

## 8. Documentation & Legal

| # | Item | Owner | Due | Done |
|---|------|-------|-----|------|
| 8.1 | Privacy Policy + Terms linked in product footer | Product | T-2d | [x] `/privacy` `/terms` (counsel review before GA copy) |
| 8.2 | Support contact published | Product | T-2d | [x] `/support` + `NEXT_PUBLIC_SUPPORT_EMAIL` |
| 8.3 | RELEASE_NOTES + CHANGELOG published to design partners | Product | T-1d | [ ] |
| 8.4 | User guides (constructor, billing) linked from app help | Product | T-1d | [x] `/help` |
| 8.5 | Known limitations disclosed (email/OAuth stubs) | Product | T-1d | [x] `/legal/limitations` |

---

## 9. Soft-Launch Plan

| Phase | Window | Scope | Success criteria | Done |
|-------|--------|-------|------------------|------|
| Invite | T-14 → T-7 | ≥5 design-partner orgs | Onboarding completed | [ ] |
| Observe | T-7 → T-0 | Production-like staging or limited prod | No Sev-0; Stripe happy-path works | [ ] |
| Feedback | Daily standup | Bugs → triage board | Top 5 UX issues logged | [ ] |
| Freeze | T-2 | Code freeze except blockers | Checklist ≥90% | [ ] |

---

## 10. Go-Live Criteria

Must be **true** to tag `v1.0.0` and open public signup:

- [ ] Sections 1–8 signed (or waived with written risk acceptance)
- [ ] Soft-launch: ≥5 orgs, ≥14 days, **zero Sev-0**
- [ ] Stripe org Checkout + Portal + webhook verified on staging **and** production test mode or live
- [ ] Backup restore drill signed within last 30 days
- [ ] Locust thresholds met or Product accepts risk in writing
- [ ] Support rota for first 72h assigned

---

## 11. Post-Launch (first 72h + 30d)

| # | Item | Owner | Window | Done |
|---|------|-------|--------|------|
| 11.1 | Watch 5xx, webhook errors, quota 402 spikes | Ops | 0–72h | [ ] |
| 11.2 | Daily Stripe reconciliation (Checkout vs `stripe_customers`) | Eng | 0–7d | [ ] |
| 11.3 | Hotfix process: branch `hotfix/*` → CI → deploy | Eng | on-call | [ ] |
| 11.4 | Rollback: previous Docker image; DB forward-only unless approved | Ops | on-call | [ ] |
| 11.5 | Kick off v1.1 roadmap grooming | Product | Day 7 | [ ] |
| 11.6 | Coverage expansion toward full-app 75% | Eng | Day 30 | [ ] |

### Rollback plan (summary)

1. Freeze deploys; announce status page if public.
2. Redeploy previous known-good image tag.
3. Do **not** auto-downgrade Alembic past `020` without backup restore.
4. If Stripe webhooks poisoned: disable endpoint, replay after fix via Stripe Dashboard.
5. Post-mortem within 48h.

---

## Sign-off

| Role | Name | Date | Notes |
|------|------|------|-------|
| Eng | | | |
| Security | | | |
| Ops | | | |
| Product | | | |

---

## Coverage note

CI enforces **≥75%** on GA-critical modules (`quota_service`, `stripe_billing_service`, `analytics_service`, `usage_service`, `flow_execution_service`, `rag_service`, `ai_guardrails`). Whole-app `app/` remains lower — expand post-GA.
