-- Post-mortem retro-analysis telemetry on strategy_executions.

ALTER TABLE strategy_executions ADD COLUMN IF NOT EXISTS layout_match_pct integer DEFAULT 0;
ALTER TABLE strategy_executions ADD COLUMN IF NOT EXISTS structural_move_pct double precision DEFAULT 0;
