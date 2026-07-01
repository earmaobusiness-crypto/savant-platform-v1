-- Cloud offload RPC — spatial cosine matching + genetic merge on database servers.
-- Run in Supabase SQL editor. Vectors never need to hydrate into the local terminal.

CREATE OR REPLACE FUNCTION public._sig_vec(sig jsonb)
RETURNS double precision[]
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT ARRAY(
    SELECT (elem::text)::double precision
    FROM jsonb_array_elements_text(
      COALESCE(sig->'master_signature', sig->'master_signature_preview', '[]'::jsonb)
    ) AS elem
  );
$$;

CREATE OR REPLACE FUNCTION public._cosine_similarity_array(a double precision[], b double precision[])
RETURNS double precision
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN a IS NULL OR b IS NULL
      OR array_length(a, 1) IS NULL OR array_length(b, 1) IS NULL
      OR array_length(a, 1) <> array_length(b, 1) THEN 0::double precision
    ELSE GREATEST(
      0::double precision,
      LEAST(
        1::double precision,
        (
          SELECT sum(u * v) / NULLIF(sqrt(sum(u * u)) * sqrt(sum(v * v)), 0)
          FROM unnest(a, b) AS t(u, v)
        )
      )
    )
  END;
$$;

CREATE OR REPLACE FUNCTION public.match_layout_spatial(query_vector double precision[])
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  best_layout text := 'NEW_LAYOUT';
  best_cos double precision := 0;
  best_euc double precision := 999;
  rec record;
  v double precision[];
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

  FOR rec IN
    SELECT DISTINCT ON (macro_weather_layout)
      macro_weather_layout,
      master_signature_json
    FROM forensic_patterns
    WHERE vault_track = 'track_1_validated'
      AND (state IS NULL OR state = 'active')
      AND macro_weather_layout IS NOT NULL
      AND master_signature_json IS NOT NULL
    ORDER BY macro_weather_layout, timestamp DESC
    LIMIT 500
  LOOP
    v := _sig_vec(rec.master_signature_json::jsonb);
    IF array_length(v, 1) IS NULL OR array_length(v, 1) <> array_length(query_vector, 1) THEN
      CONTINUE;
    END IF;
    cos := _cosine_similarity_array(query_vector, v);
    euc := sqrt((SELECT sum((u - w) * (u - w)) FROM unnest(query_vector, v) AS t(u, w)));
    IF cos > best_cos THEN
      best_cos := cos;
      best_euc := euc;
      best_layout := rec.macro_weather_layout;
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    'spatial_match_pct', (best_cos * 100)::int,
    'cosine_similarity', round(best_cos::numeric, 4),
    'euclidean_distance', round(best_euc::numeric, 4),
    'nearest_layout_id', best_layout
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.top_layout_alignments(
  query_vector double precision[],
  row_limit integer DEFAULT 5
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  results jsonb := '[]'::jsonb;
  rec record;
  v double precision[];
  cos double precision;
BEGIN
  IF query_vector IS NULL OR array_length(query_vector, 1) IS NULL THEN
    RETURN results;
  END IF;

  FOR rec IN
    SELECT DISTINCT ON (macro_weather_layout)
      macro_weather_layout,
      ticker,
      timeframe_resolution,
      master_signature_json
    FROM forensic_patterns
    WHERE vault_track = 'track_1_validated'
      AND (state IS NULL OR state = 'active')
      AND macro_weather_layout IS NOT NULL
      AND master_signature_json IS NOT NULL
    ORDER BY macro_weather_layout, timestamp DESC
    LIMIT 256
  LOOP
    v := _sig_vec(rec.master_signature_json::jsonb);
    IF array_length(v, 1) IS NULL OR array_length(v, 1) <> array_length(query_vector, 1) THEN
      CONTINUE;
    END IF;
    cos := _cosine_similarity_array(query_vector, v);
    results := results || jsonb_build_array(
      jsonb_build_object(
        'layout_id', rec.macro_weather_layout,
        'reference_ticker', rec.ticker,
        'timeframe_resolution', rec.timeframe_resolution,
        'cosine_similarity', round(cos::numeric, 4),
        'spatial_match_pct', (cos * 100)::int
      )
    );
  END LOOP;

  RETURN results;
END;
$$;

CREATE OR REPLACE FUNCTION public.merge_layout_signature(
  query_vector double precision[],
  match_threshold double precision DEFAULT 0.85,
  noise_epsilon double precision DEFAULT 0.18
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  best_layout text := 'PURGATORY_PENDING';
  best_cos double precision := 0;
  ref_vector double precision[];
  rec record;
  v double precision[];
  cos double precision;
  merged double precision[];
  i integer;
  discarded integer := 0;
  pure integer := 0;
  overlap_pct integer;
BEGIN
  IF query_vector IS NULL OR array_length(query_vector, 1) IS NULL THEN
    RETURN jsonb_build_object(
      'master_signature', query_vector,
      'layout_id', 'PURGATORY_PENDING',
      'overlap_pct', 0,
      'noise_discarded', true,
      'dimensions_trashed', 0,
      'pure_overlap_dims', 0
    );
  END IF;

  FOR rec IN
    SELECT DISTINCT ON (macro_weather_layout)
      macro_weather_layout,
      master_signature_json
    FROM forensic_patterns
    WHERE vault_track = 'track_1_validated'
      AND (state IS NULL OR state = 'active')
      AND macro_weather_layout IS NOT NULL
      AND master_signature_json IS NOT NULL
    ORDER BY macro_weather_layout, timestamp DESC
    LIMIT 500
  LOOP
    v := _sig_vec(rec.master_signature_json::jsonb);
    IF array_length(v, 1) IS NULL OR array_length(v, 1) <> array_length(query_vector, 1) THEN
      CONTINUE;
    END IF;
    cos := _cosine_similarity_array(query_vector, v);
    IF cos > best_cos THEN
      best_cos := cos;
      best_layout := rec.macro_weather_layout;
      ref_vector := v;
    END IF;
  END LOOP;

  overlap_pct := (best_cos * 100)::int;
  IF best_cos >= match_threshold AND ref_vector IS NOT NULL THEN
    merged := ARRAY[]::double precision[];
    FOR i IN 1..array_length(query_vector, 1) LOOP
      IF abs(query_vector[i] - ref_vector[i]) <= noise_epsilon THEN
        merged := merged || round(((query_vector[i] + ref_vector[i]) / 2.0)::numeric, 6);
        pure := pure + 1;
      ELSE
        merged := merged || round(ref_vector[i]::numeric, 6);
        discarded := discarded + 1;
      END IF;
    END LOOP;
    RETURN jsonb_build_object(
      'master_signature', to_jsonb(merged),
      'layout_id', best_layout,
      'overlap_pct', overlap_pct,
      'noise_discarded', discarded > 0,
      'dimensions_trashed', discarded,
      'pure_overlap_dims', pure
    );
  END IF;

  RETURN jsonb_build_object(
    'master_signature', to_jsonb(query_vector),
    'layout_id', 'PURGATORY_PENDING',
    'overlap_pct', overlap_pct,
    'noise_discarded', true,
    'dimensions_trashed', array_length(query_vector, 1),
    'pure_overlap_dims', 0
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.match_layout_spatial(double precision[]) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.top_layout_alignments(double precision[], integer) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.merge_layout_signature(double precision[], double precision, double precision) TO anon, authenticated, service_role;
