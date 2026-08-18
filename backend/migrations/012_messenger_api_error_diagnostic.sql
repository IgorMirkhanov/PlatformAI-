-- Step 4: messenger outbound failure diagnostics for live webhook inference
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'diagnostic_error_type' AND e.enumlabel = 'MESSENGER_API_ERROR'
    ) THEN
        ALTER TYPE diagnostic_error_type ADD VALUE 'MESSENGER_API_ERROR';
    END IF;
END $$;
