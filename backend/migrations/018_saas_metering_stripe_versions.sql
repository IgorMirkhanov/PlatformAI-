-- 018: SaaS metering, Stripe idempotency, flow revisions, moderation audit

DO $$ BEGIN
    CREATE TYPE usage_metric_type AS ENUM (
        'LLM_TOKENS', 'MESSAGE_IN', 'MESSAGE_OUT', 'BOT_CREATED', 'CRM_CALL', 'RAG_QUERY'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE moderation_action AS ENUM ('ALLOW', 'BLOCK', 'REDACT');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS usage_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES companies(id) ON DELETE SET NULL,
    bot_id UUID REFERENCES bots(id) ON DELETE SET NULL,
    metric_type usage_metric_type NOT NULL,
    quantity BIGINT NOT NULL DEFAULT 0,
    unit_cost NUMERIC(12, 6) NOT NULL DEFAULT 0,
    total_cost NUMERIC(12, 4) NOT NULL DEFAULT 0,
    currency VARCHAR(8) NOT NULL DEFAULT 'KZT',
    meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_usage_events_user_id ON usage_events(user_id);
CREATE INDEX IF NOT EXISTS ix_usage_events_bot_id ON usage_events(bot_id);
CREATE INDEX IF NOT EXISTS ix_usage_events_metric_type ON usage_events(metric_type);
CREATE INDEX IF NOT EXISTS ix_usage_events_created_at ON usage_events(created_at);

CREATE TABLE IF NOT EXISTS stripe_customer_links (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES companies(id) ON DELETE CASCADE,
    stripe_customer_id VARCHAR(128) NOT NULL,
    stripe_subscription_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_stripe_customer_id UNIQUE (stripe_customer_id)
);
CREATE INDEX IF NOT EXISTS ix_stripe_customer_links_user_id ON stripe_customer_links(user_id);

CREATE TABLE IF NOT EXISTS bot_flow_revisions (
    id UUID PRIMARY KEY,
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    flow_id UUID,
    version INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT 'Untitled',
    graph_data JSONB NOT NULL DEFAULT '{}',
    created_by_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note TEXT,
    CONSTRAINT uq_bot_flow_revision_version UNIQUE (bot_id, version)
);
CREATE INDEX IF NOT EXISTS ix_bot_flow_revisions_bot_id ON bot_flow_revisions(bot_id);

CREATE TABLE IF NOT EXISTS moderation_events (
    id UUID PRIMARY KEY,
    bot_id UUID,
    user_id UUID,
    direction VARCHAR(16) NOT NULL DEFAULT 'inbound',
    action moderation_action NOT NULL,
    reason VARCHAR(255) NOT NULL DEFAULT '',
    score NUMERIC(6, 4),
    sample TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_moderation_events_bot_id ON moderation_events(bot_id);

CREATE TABLE IF NOT EXISTS processed_stripe_events (
    id UUID PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL UNIQUE,
    event_type VARCHAR(128) NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
