-- Room 2 hardening: incubation shelf + playbook floor telemetry.

ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS layout_match_pct integer DEFAULT 0;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS anomaly_repeat_count integer DEFAULT 0;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS shelf_expires_at timestamptz;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS structural_move_pct double precision DEFAULT 0;

CREATE INDEX IF NOT EXISTS forensic_patterns_incubation_idx
    ON forensic_patterns (state, shelf_expires_at)
    WHERE state = 'incubation';
