-- Run once in Supabase SQL Editor (safe to re-run).
-- Fixes PGRST204: Could not find the 'form4_insider_summary' column.

ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS form4_insider_summary text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS institutional_block_accumulation boolean DEFAULT false;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS polygon_calls_remaining integer;
