-- Superadmin impersonation support
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS ix_users_is_superadmin
    ON users(is_superadmin)
    WHERE is_superadmin = TRUE;
