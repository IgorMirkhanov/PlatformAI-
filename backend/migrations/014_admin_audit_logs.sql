-- Admin impersonation audit trail
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action VARCHAR(64) NOT NULL,
    ip_address VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_admin_id
    ON admin_audit_logs (admin_id);

CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_target_user_id
    ON admin_audit_logs (target_user_id);

CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_created_at
    ON admin_audit_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_action
    ON admin_audit_logs (action);
