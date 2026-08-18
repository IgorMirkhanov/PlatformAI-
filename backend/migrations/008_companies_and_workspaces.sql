-- Multi-tenant companies and user workspace memberships (008)

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Almaty',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_companies_owner_user_id ON companies(owner_user_id);

CREATE TABLE IF NOT EXISTS user_company_workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role user_role NOT NULL DEFAULT 'OWNER',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_company_workspace UNIQUE (user_id, company_id)
);

CREATE INDEX IF NOT EXISTS ix_user_company_workspaces_user_id ON user_company_workspaces(user_id);
CREATE INDEX IF NOT EXISTS ix_user_company_workspaces_company_id ON user_company_workspaces(company_id);

ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Almaty';

-- Backfill one company per existing user workspace
INSERT INTO companies (id, name, owner_user_id, timezone)
SELECT u.company_id,
       u.company_name,
       u.id,
       COALESCE(u.timezone, 'Asia/Almaty')
FROM users u
WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.id = u.company_id);

INSERT INTO user_company_workspaces (user_id, company_id, role)
SELECT u.id, u.company_id, u.role
FROM users u
WHERE NOT EXISTS (
    SELECT 1
    FROM user_company_workspaces w
    WHERE w.user_id = u.id AND w.company_id = u.company_id
);
