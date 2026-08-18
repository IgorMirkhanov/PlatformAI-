-- SaaS expansion: subscriptions + advanced bot agent profile fields
-- Run against PostgreSQL database: ai_bot_platform

CREATE TYPE subscription_plan_name AS ENUM ('FREE', 'PRO', 'ENTERPRISE');
CREATE TYPE subscription_status AS ENUM ('ACTIVE', 'EXPIRED');

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_name subscription_plan_name NOT NULL DEFAULT 'FREE',
    balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    status subscription_status NOT NULL DEFAULT 'ACTIVE',
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions(user_id);

ALTER TABLE bots ADD COLUMN IF NOT EXISTS default_chat_state BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Almaty';
ALTER TABLE bots ADD COLUMN IF NOT EXISTS schedule_config JSONB NOT NULL DEFAULT '{"enabled": false, "timezone": "Asia/Almaty", "windows": []}'::jsonb;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS prompt_instructions TEXT NOT NULL DEFAULT '';
ALTER TABLE bots ADD COLUMN IF NOT EXISTS llm_model_name VARCHAR(128) NOT NULL DEFAULT 'gpt-4o-mini';
ALTER TABLE bots ADD COLUMN IF NOT EXISTS llm_temperature DOUBLE PRECISION NOT NULL DEFAULT 0.5;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS message_split BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS message_buffer_delay INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS custom_code_snippet TEXT NOT NULL DEFAULT '';
