-- Per-document RAG context activation for runtime vector search pools
-- Run against PostgreSQL database: ai_bot_platform

ALTER TABLE knowledge_base_documents
    ADD COLUMN IF NOT EXISTS is_context_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS ix_knowledge_base_documents_context_active
    ON knowledge_base_documents(bot_id, is_context_active);
