-- Soft-launch manual deposits + admin notification ledger
-- Extends billing_transactions and adds system_notifications.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'billing_transaction_type' AND e.enumlabel = 'MANUAL_DEPOSIT'
    ) THEN
        ALTER TYPE billing_transaction_type ADD VALUE 'MANUAL_DEPOSIT';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'billing_transaction_status' AND e.enumlabel = 'APPROVED'
    ) THEN
        ALTER TYPE billing_transaction_status ADD VALUE 'APPROVED';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'billing_transaction_status' AND e.enumlabel = 'REJECTED'
    ) THEN
        ALTER TYPE billing_transaction_status ADD VALUE 'REJECTED';
    END IF;
END $$;

ALTER TABLE billing_transactions
    ADD COLUMN IF NOT EXISTS organization_id UUID NULL REFERENCES companies(id) ON DELETE SET NULL;

ALTER TABLE billing_transactions
    ADD COLUMN IF NOT EXISTS receipt_url VARCHAR(1024) NULL;

CREATE INDEX IF NOT EXISTS ix_billing_transactions_organization_id
    ON billing_transactions(organization_id);

CREATE INDEX IF NOT EXISTS ix_billing_transactions_status
    ON billing_transactions(status);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'system_notification_category') THEN
        CREATE TYPE system_notification_category AS ENUM ('BILLING_DEPOSIT', 'SYSTEM');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'system_notification_severity') THEN
        CREATE TYPE system_notification_severity AS ENUM ('INFO', 'WARNING', 'CRITICAL');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS system_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NULL REFERENCES companies(id) ON DELETE SET NULL,
    actor_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    category system_notification_category NOT NULL,
    severity system_notification_severity NOT NULL DEFAULT 'INFO',
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    reference_id VARCHAR(128) NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_system_notifications_organization_id
    ON system_notifications(organization_id);
CREATE INDEX IF NOT EXISTS ix_system_notifications_created_at
    ON system_notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_system_notifications_severity
    ON system_notifications(severity);
CREATE INDEX IF NOT EXISTS ix_system_notifications_category
    ON system_notifications(category);
