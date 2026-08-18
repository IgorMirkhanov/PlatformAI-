-- Knowledge base document metadata for per-bot RAG corpora
-- Run against PostgreSQL database: ai_bot_platform

CREATE TABLE IF NOT EXISTS knowledge_base_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    file_name VARCHAR(512) NOT NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'file',
    character_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_knowledge_base_documents_bot_id
    ON knowledge_base_documents(bot_id);
