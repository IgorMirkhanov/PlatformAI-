-- AI Error Vault: granular bot execution diagnostics
-- Run against PostgreSQL database: ai_bot_platform

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'diagnostic_error_type') THEN
        CREATE TYPE diagnostic_error_type AS ENUM (
            'LLM_TIMEOUT',
            'RAG_EMPTY',
            'CRM_DISCONNECT',
            'INSUFFICIENT_FUNDS'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS bot_diagnostic_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    client_id UUID NULL REFERENCES clients(id) ON DELETE SET NULL,
    error_type diagnostic_error_type NOT NULL,
    error_message TEXT NOT NULL,
    node_id VARCHAR(255) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_bot_diagnostic_logs_bot_id ON bot_diagnostic_logs(bot_id);
CREATE INDEX IF NOT EXISTS ix_bot_diagnostic_logs_created_at ON bot_diagnostic_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_bot_diagnostic_logs_error_type ON bot_diagnostic_logs(error_type);
