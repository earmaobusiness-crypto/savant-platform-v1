-- pgvector spatial lane — optional acceleration for layout cosine matching.
-- Falls back to 007 array RPC if extension unavailable.

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE forensic_patterns
  ADD COLUMN IF NOT EXISTS master_signature_vector vector(8);

CREATE OR REPLACE FUNCTION public._sig_vec_pg(query_vector double precision[])
RETURNS vector
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT query_vector::vector;
$$;

CREATE OR REPLACE FUNCTION public.match_layout_spatial_pgvector(query_vector double precision[])
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  q vector;
  rec record;
  best_layout text := 'NEW_LAYOUT';
  best_cos double precision := 0;
  best_euc double precision := 999;
  cos double precision;
  euc double precision;
BEGIN
  IF query_vector IS NULL OR array_length(query_vector, 1) IS NULL THEN
    RETURN jsonb_build_object(
      'spatial_match_pct', 0,
      'cosine_similarity', 0,
      'euclidean_distance', 999,
      'nearest_layout_id', 'NEW_LAYOUT'
    );
  END IF;

  q := query_vector::vector;

  FOR rec IN
    SELECT DISTINCT ON (macro_weather_layout)
      macro_weather_layout,
      COALESCE(
        master_signature_vector,
        _sig_vec(master_signature_json::jsonb)::vector
      ) AS sig_vec
    FROM forensic_patterns
    WHERE vault_track = 'track_1_validated'
      AND (state IS NULL OR state = 'active')
      AND macro_weather_layout IS NOT NULL
      AND master_signature_json IS NOT NULL
    ORDER BY macro_weather_layout, timestamp DESC
    LIMIT 500
  LOOP
    IF rec.sig_vec IS NULL THEN
      CONTINUE;
    END IF;
    cos := 1 - (q <=> rec.sig_vec);
    euc := (q <-> rec.sig_vec);
    IF cos > best_cos THEN
      best_cos := cos;
      best_euc := euc;
      best_layout := rec.macro_weather_layout;
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    'spatial_match_pct', (GREATEST(0, best_cos) * 100)::int,
    'cosine_similarity', round(GREATEST(0, best_cos)::numeric, 4),
    'euclidean_distance', round(best_euc::numeric, 4),
    'nearest_layout_id', best_layout
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.match_layout_spatial_pgvector(double precision[]) TO anon, authenticated, service_role;
