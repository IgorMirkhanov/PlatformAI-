# GA recommendations — first 30 days (MP.AI v1.0)

## Days 0–3 (stabilize)

1. On-call for 5xx, Stripe webhook failures, WhatsApp session drops.
2. Reconcile Checkout sessions vs `stripe_customers` / `companies.stripe_status` daily.
3. Confirm Locust baseline still holds on production-sized hardware.
4. Freeze non-critical deploys; hotfixes only.

## Days 4–14 (learn)

1. Interview design partners: constructor UX, billing clarity, quota messaging.
2. Triage top 10 bugs; ship weekly patch train (`v1.0.x`).
3. Turn on Stripe Metering only after Meter + price are live.
4. Expand coverage list in CI toward more of `app/services/*`.

## Days 15–30 (grow)

1. Soft-open self-serve signup if Go-Live Criteria stay green.
2. Groom **v1.1** backlog (PWA, advanced nodes, templates, collab) — see [V1.1_ROADMAP.md](./V1.1_ROADMAP.md).
3. Legal: Privacy/Terms localization if expanding regions.
4. Optional: PostHog/product analytics — keep `UsageEvent` as billing SoT.

## Do not slip

- Org Stripe identity (already shipped) — do not reintroduce user-only customers for new checkouts.
- Skipping backup restore drills.
- Raising quotas without plan/price alignment.

## Exit to v1.1 kickoff

When: no Sev-0 for 14 days, Stripe org path trusted, support load sustainable, checklist archived as passed.
