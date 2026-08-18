-- Expand hub_channel_type enum for Site chat / API / Calls (screenshot parity).
-- Safe to re-run: ADD VALUE IF NOT EXISTS (PG 9.1+ / IF NOT EXISTS on PG 15+).

DO $$
BEGIN
  ALTER TYPE hub_channel_type ADD VALUE IF NOT EXISTS 'web_widget';
EXCEPTION
  WHEN duplicate_object THEN NULL;
  WHEN undefined_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE hub_channel_type ADD VALUE IF NOT EXISTS 'api';
EXCEPTION
  WHEN duplicate_object THEN NULL;
  WHEN undefined_object THEN NULL;
END $$;

DO $$
BEGIN
  ALTER TYPE hub_channel_type ADD VALUE IF NOT EXISTS 'calls';
EXCEPTION
  WHEN duplicate_object THEN NULL;
  WHEN undefined_object THEN NULL;
END $$;

