-- Billing transaction ledger for SaaS balance movements
-- Run against PostgreSQL database: ai_bot_platform

CREATE TYPE billing_transaction_type AS ENUM ('TOP_UP', 'SUBSCRIPTION_CHARGE', 'BONUS', 'REFUND');
CREATE TYPE billing_transaction_status AS ENUM ('SUCCESS', 'PENDING', 'FAILED');

CREATE TABLE IF NOT EXISTS billing_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subscription_id UUID NULL REFERENCES subscriptions(id) ON DELETE SET NULL,
    transaction_type billing_transaction_type NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'KZT',
    description VARCHAR(512) NOT NULL,
    status billing_transaction_status NOT NULL DEFAULT 'SUCCESS',
    reference_id VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_billing_transactions_user_id ON billing_transactions(user_id);
CREATE INDEX IF NOT EXISTS ix_billing_transactions_subscription_id ON billing_transactions(subscription_id);
CREATE INDEX IF NOT EXISTS ix_billing_transactions_created_at ON billing_transactions(created_at DESC);
