# Changelog

All notable changes to MP.AI are documented in this file.

## [1.0.0] — 2026-07-20

### Added
- Organization-level `StripeCustomer` model + Alembic `020_org_stripe_customer` with data backfill
- Company mirror fields: `stripe_status`, `stripe_plan`, `stripe_customer_id`, `stripe_subscription_id`
- Billing aliases `POST /api/v1/billing/checkout` and `/portal` accepting `organization_id`
- Org billing snapshot on `GET /billing/stripe/status`
- Locust suite: auth, bots, flow, execute, WhatsApp; ramp 10→50; CSV + threshold asserts
- Docs: PRODUCTION_LAUNCH_CHECKLIST, STRIPE_ORG_MIGRATION, LOAD_TESTING, V1.1_ROADMAP

### Changed
- `StripeBillingService` customer/checkout/portal/webhook keyed by `organization_id`
- `QuotaService` / `UsageService` aggregate and enforce at organization level
- Billing UI shows organization Stripe status/plan

### Security
- Webhook idempotency retained via `processed_stripe_events`; webhook commits after apply

## [1.0.0-rc] — 2026-07-20

### Added
- Stripe Checkout / Portal / webhook / optional Meter events (user-scoped RC)
- Plan quotas → HTTP 402; Analytics summary; Flow Loop / Handoff; Locust execute smoke
- CI coverage gate, Playwright, Trivy, pip-audit, npm audit, Gitleaks, Dependabot

### Changed
- OpenAPI `1.0.0-rc`; Billing UI prefers Stripe when configured

### Security
- Prompt-injection guardrails; auth rate limits; secrets scanning in CI

## [0.2.0] — 2026-07

- Multi-tenant Company/Project/Bot core, React Flow builder, WhatsApp/Telegram webhooks, wallet billing skeleton
