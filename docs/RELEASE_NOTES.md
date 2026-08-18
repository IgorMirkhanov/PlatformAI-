# MP.AI v1.0.0 Release Notes

**Date:** 2026-07-20  
**Tag:** `v1.0.0`

## What's new

- Multi-tenant Organizations (companies), projects, bots, JWT + refresh auth, RBAC
- Visual Flow Builder (React Flow) with publish/versioning and Preview
- Execution engine + RAG; WhatsApp / Telegram channels; Human Handoff / Loop nodes
- **Organization-level Stripe billing** — one Stripe Customer per org; Checkout, Portal, webhooks
- Plan quotas (bots / messages / tokens) enforced per organization (HTTP 402)
- Usage meters + org analytics summary on Dashboard / Billing
- Production infra: Docker, nginx, deploy.sh, CI (tests, e2e, security scans)
- Locust load suite (10→50 users, execute p95 gate)

## Breaking / behavior changes

- Stripe Checkout/Portal are **org-scoped** (`organization_id`); user-scoped customer lookup is deprecated
- Quotas and usage aggregation key off `organization_id` (not only `user_id`)
- Creating bots beyond plan limit → **402** with `billing_url`
- Alembic head is now `020_org_stripe_customer`

## Upgrade

1. Backup DB
2. `alembic upgrade 020_org_stripe_customer` (see [STRIPE_ORG_MIGRATION.md](./STRIPE_ORG_MIGRATION.md))
3. Set `STRIPE_*` env; point webhook to `/api/v1/billing/stripe/webhook`
4. Rotate bootstrap admin password; enable guardrails + JSON logs

## Known limitations

- Password-reset email and social OAuth are stubbed until provider credentials exist
- Wallet `Subscription` rows remain on org **owner** user (mirrored org plan via StripeCustomer / companies columns)
- Full-repo pytest coverage still climbing; CI gates GA-critical modules at ≥75%
- Concurrent multi-user flow editing not yet realtime (v1.1)

## Links

- [CHANGELOG.md](../CHANGELOG.md)
- [PRODUCTION_LAUNCH_CHECKLIST.md](./PRODUCTION_LAUNCH_CHECKLIST.md)
- [GA_RECOMMENDATIONS.md](./GA_RECOMMENDATIONS.md)
- [V1.1_ROADMAP.md](./V1.1_ROADMAP.md)
- [LOAD_TESTING.md](./LOAD_TESTING.md)
