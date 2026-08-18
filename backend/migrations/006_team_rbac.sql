-- Multi-tenant team management and RBAC
-- Run against PostgreSQL database: ai_bot_platform

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('OWNER', 'ADMIN', 'PROMPT_ENGINEER', 'OPERATOR');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'team_invitation_status') THEN
        CREATE TYPE team_invitation_status AS ENUM ('PENDING', 'ACCEPTED', 'EXPIRED');
    END IF;
END $$;

ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id UUID;
ALTER TABLE users ADD COLUMN IF NOT EXISTS role user_role NOT NULL DEFAULT 'OWNER';

UPDATE users SET company_id = id WHERE company_id IS NULL;
ALTER TABLE users ALTER COLUMN company_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_company_id ON users(company_id);

CREATE TABLE IF NOT EXISTS team_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL,
    email VARCHAR(255) NOT NULL,
    role user_role NOT NULL,
    token VARCHAR(128) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    status team_invitation_status NOT NULL DEFAULT 'PENDING',
    invited_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_team_invitations_company_id ON team_invitations(company_id);
CREATE INDEX IF NOT EXISTS ix_team_invitations_email ON team_invitations(email);
CREATE INDEX IF NOT EXISTS ix_team_invitations_token ON team_invitations(token);
