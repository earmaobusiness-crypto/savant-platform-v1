-- Forensic Data Shattering & Digital Genetics — additive vault columns.
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS forensic_dragnet_blob text;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS master_signature_json text;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS metric_envelopes_json text;
ALTER TABLE forensic_patterns ADD COLUMN IF NOT EXISTS semantic_catalyst_json text;
