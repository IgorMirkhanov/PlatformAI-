-- Google Drive KB sync: document format label + diagnostic enum
ALTER TABLE knowledge_base_documents
    ADD COLUMN IF NOT EXISTS format VARCHAR(64) NULL;

CREATE INDEX IF NOT EXISTS ix_knowledge_base_documents_format
    ON knowledge_base_documents(format);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'diagnostic_error_type' AND e.enumlabel = 'GOOGLE_SYNC_FAILED'
    ) THEN
        ALTER TYPE diagnostic_error_type ADD VALUE 'GOOGLE_SYNC_FAILED';
    END IF;
END $$;
