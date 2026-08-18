-- 017: multi-tenancy Project layer + auth flags + org slug
-- Safe / idempotent for deploy.sh SQL migration runner.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS slug VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_slug ON companies (slug);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(64) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_org_slug UNIQUE (organization_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects (organization_id);
CREATE INDEX IF NOT EXISTS ix_projects_slug ON projects (slug);

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES companies(id) ON DELETE SET NULL;

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_bots_organization_id ON bots (organization_id);
CREATE INDEX IF NOT EXISTS ix_bots_project_id ON bots (project_id);

UPDATE bots AS b
SET organization_id = u.company_id
FROM users AS u
WHERE b.user_id = u.id
  AND b.organization_id IS NULL
  AND u.company_id IS NOT NULL;

-- Seed a default project per organization that has none
INSERT INTO projects (id, organization_id, name, slug, description, is_active)
SELECT gen_random_uuid(), c.id, 'Default', 'default', 'Default project', true
FROM companies c
WHERE NOT EXISTS (
    SELECT 1 FROM projects p WHERE p.organization_id = c.id AND p.slug = 'default'
);
