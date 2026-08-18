-- Omnichannel Integration Hub: bot_channels ledger
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hub_channel_type') THEN
        CREATE TYPE hub_channel_type AS ENUM (
            'telegram',
            'telegram_business',
            'instagram',
            'wazzup',
            'waba',
            'whatsapp_qr'
        );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hub_channel_status') THEN
        CREATE TYPE hub_channel_status AS ENUM (
            'connected',
            'disconnected',
            'pending'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS bot_channels (
    id UUID PRIMARY KEY,
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    channel_type hub_channel_type NOT NULL,
    status hub_channel_status NOT NULL DEFAULT 'disconnected',
    encrypted_token TEXT NULL,
    reference_id VARCHAR(255) NULL,
    meta_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_bot_channels_bot_type UNIQUE (bot_id, channel_type)
);

CREATE INDEX IF NOT EXISTS ix_bot_channels_bot_id ON bot_channels (bot_id);
CREATE INDEX IF NOT EXISTS ix_bot_channels_channel_type ON bot_channels (channel_type);
CREATE INDEX IF NOT EXISTS ix_bot_channels_status ON bot_channels (status);
