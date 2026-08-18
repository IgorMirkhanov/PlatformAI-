# Stripe Organization Customer — data migration

## What changed

| Before | After |
|--------|--------|
| `stripe_customer_links.user_id` primary | `stripe_customers.organization_id` (1:1) |
| Checkout metadata `user_id` | metadata + `client_reference_id` = `organization_id` |
| Quotas / usage by user | Quotas / usage by `organization_id` |
| Portal lookup by user | Portal lookup by org |

`companies` gains: `stripe_customer_id`, `stripe_subscription_id`, `stripe_status`, `stripe_plan`.

Legacy `stripe_customer_links` is **kept** for rollback; new customers write both when `user_id` is passed.

## Steps

```bash
cd backend
# 1. Backup
pg_dump "$DATABASE_URL" > backup_pre_020.sql

# 2. Migrate
alembic upgrade 020_org_stripe_customer

# 3. Verify backfill
psql "$DATABASE_URL" -c "SELECT organization_id, stripe_customer_id, status FROM stripe_customers LIMIT 20;"
psql "$DATABASE_URL" -c "SELECT id, slug, stripe_status, stripe_plan FROM companies WHERE stripe_customer_id IS NOT NULL;"
```

## Manual repair (if user had Stripe but no company)

```sql
-- Attach orphan link to owner's company
UPDATE stripe_customer_links scl
SET organization_id = u.company_id
FROM users u
WHERE scl.user_id = u.id AND scl.organization_id IS NULL AND u.company_id IS NOT NULL;

-- Re-run insert for missing orgs (idempotent pattern)
INSERT INTO stripe_customers (id, organization_id, stripe_customer_id, stripe_subscription_id, status, created_at, updated_at)
SELECT gen_random_uuid(), scl.organization_id, scl.stripe_customer_id, scl.stripe_subscription_id,
       CASE WHEN scl.stripe_subscription_id IS NOT NULL THEN 'active' ELSE 'none' END,
       NOW(), NOW()
FROM stripe_customer_links scl
WHERE scl.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM stripe_customers sc WHERE sc.organization_id = scl.organization_id);
```

## API

- `POST /api/v1/billing/checkout` (alias `/billing/stripe/checkout`) — body may include `organization_id`, `price_id`
- `POST /api/v1/billing/portal`
- `GET /api/v1/billing/stripe/status?organization_id=`

## Rollback

1. Redeploy previous app image (still reads links if needed via legacy webhook path).
2. Do not drop `stripe_customers` until confirmed unused.
3. `alembic downgrade 019_saas_core` only after backup restore decision.
