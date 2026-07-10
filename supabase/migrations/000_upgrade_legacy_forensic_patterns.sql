-- Run once in Supabase SQL Editor if forensic_patterns already exists with an older schema.
-- Safe to re-run: every statement uses IF NOT EXISTS.

ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS pattern_category text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS entry_time text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS exit_time text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS operator_context text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS quantum_report text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS bar_count integer DEFAULT 0;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS source_room text DEFAULT 'forensic_pattern_lab';
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS timestamp timestamptz DEFAULT now();
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS timeframe_resolution text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS macro_weather_layout text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS execution_strategy text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS buffer_context_window text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS vault_track text DEFAULT 'track_1_validated';
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS data_feed_mode text DEFAULT 'carousel_15s';
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS state text DEFAULT 'active';
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS layout_match_pct integer DEFAULT 0;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS anomaly_repeat_count integer DEFAULT 0;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS shelf_expires_at timestamptz;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS structural_move_pct double precision DEFAULT 0;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS text_matrix_string text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS forensic_dragnet_blob text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS master_signature_json text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS metric_envelopes_json text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS semantic_catalyst_json text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS day_context_json text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS strategy_trust_tier text DEFAULT 'candidate';
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS form4_insider_summary text;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS institutional_block_accumulation boolean DEFAULT false;
ALTER TABLE public.forensic_patterns ADD COLUMN IF NOT EXISTS polygon_calls_remaining integer;

CREATE INDEX IF NOT EXISTS forensic_patterns_ticker_ts_idx
    ON public.forensic_patterns (ticker, timestamp DESC);

CREATE INDEX IF NOT EXISTS forensic_patterns_state_idx
    ON public.forensic_patterns (state, deleted_at);
