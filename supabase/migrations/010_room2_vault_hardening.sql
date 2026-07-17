-- Room 2 vault hardening (additive). Safe to run multiple times.
-- Does not wipe existing forensic_patterns rows.

ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS rubric_version text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS regime_tag text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS avg_dollar_volume_per_bar double precision;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS min_dollar_volume_per_bar double precision;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS halt_check_status text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS halt_detected boolean DEFAULT false;

CREATE INDEX IF NOT EXISTS forensic_patterns_skip_sighting_idx
    ON public.forensic_patterns (pattern_category, ticker, timestamp DESC)
    WHERE pattern_category = 'SKIP_SIGHTING';
