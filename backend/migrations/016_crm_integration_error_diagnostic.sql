-- Phase A: CRM Action / Custom Webhook mid-flow failure diagnostics
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON t.oid = e.enumtypid
        WHERE t.typname = 'diagnostic_error_type' AND e.enumlabel = 'CRM_INTEGRATION_ERROR'
    ) THEN
        ALTER TYPE diagnostic_error_type ADD VALUE 'CRM_INTEGRATION_ERROR';
    END IF;
END $$;
