"""Unify live DNA math with Room 2: velocity, adaptive cosine, Handle on layouts."""

import room3_bridge as b
import room3_matrix as m
import room3_recipes as r


def test_live_velocity_is_last_minus_first_over_first():
    line = {
        "timeframe": "1m",
        "slices": [
            {"o": 10.0, "h": 10.2, "l": 9.9, "c": 10.0, "v": 100, "ret": 0.0},
            {"o": 10.0, "h": 10.5, "l": 10.0, "c": 10.4, "v": 120, "ret": 0.04},
            {"o": 10.4, "h": 10.6, "l": 10.3, "c": 10.5, "v": 110, "ret": 0.0096},
            {"o": 10.5, "h": 10.7, "l": 10.4, "c": 11.0, "v": 130, "ret": 0.0476},
            {"o": 11.0, "h": 11.2, "l": 10.9, "c": 11.0, "v": 90, "ret": 0.0},
        ],
    }
    vec = m.build_live_feature_vector(line)
    assert vec is not None
    assert abs(vec[0] - 10.0) < 1e-6


def test_moments_use_median_not_mean():
    vectors = [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]
    centers, scales = m._adaptive_feature_moments(vectors, 8)
    assert abs(centers[0] - 2.5) < 1e-9
    assert scales[0] > 0
    mean = (1.0 + 2.0 + 3.0 + 100.0) / 4.0
    assert abs(centers[0] - mean) > 10.0


def test_zscore_hard_clips_at_five():
    z = m._zscore_vec([100.0], [0.0], [1.0])
    assert z == [5.0]
    z = m._zscore_vec([-100.0], [0.0], [1.0])
    assert z == [-5.0]


def test_no_raw_fallback_on_dead_dims():
    layouts = [
        {"layout_id": "1", "strategy": "1A (1M)", "vector": [0.0] * 8, "timeframe_resolution": "1m"},
        {"layout_id": "2", "strategy": "2A (1M)", "vector": [0.0] * 8, "timeframe_resolution": "1m"},
    ]
    live = [99.0] * 8
    hit = m.match_spatial(live, layouts, watch_timeframe="1m")
    assert int(hit["spatial_match_pct"]) == 0
    assert hit["nearest_strategy"] in ("", "—")


def test_adaptive_zscore_drops_constant_dim():
    layouts = [
        {"layout_id": "1", "strategy": "1A (1M)", "vector": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.2], "timeframe_resolution": "1m"},
        {"layout_id": "2", "strategy": "2A (1M)", "vector": [8.0, 2.5, 3.2, 4.1, 5.2, 6.1, 0.0, 0.4], "timeframe_resolution": "1m"},
        {"layout_id": "3", "strategy": "2B (1M)", "vector": [2.0, 9.0, 3.1, 4.2, 5.1, 6.2, 0.0, -0.1], "timeframe_resolution": "1m"},
    ]
    live = [8.1, 2.4, 3.15, 4.05, 5.15, 6.05, 99.0, 0.39]
    hit = m.match_spatial(live, layouts, watch_timeframe="1m")
    assert hit["nearest_strategy"] == "2A (1M)"
    assert int(hit["spatial_match_pct"]) >= 85


def test_weights_prioritize_velocity_and_volume():
    assert m.FEATURE_MATCH_WEIGHTS[0] >= m.FEATURE_MATCH_WEIGHTS[1] >= m.FEATURE_MATCH_WEIGHTS[2]
    assert m.FEATURE_MATCH_WEIGHTS[3] > m.FEATURE_MATCH_WEIGHTS[5]
    assert m.FEATURE_MATCH_WEIGHTS[4] > m.FEATURE_MATCH_WEIGHTS[7]
    assert m.FEATURE_MATCH_WEIGHTS[6] == 0.0
    vel = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    vol = [0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    quiet = [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0]
    mixed = [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    w = list(m.FEATURE_MATCH_WEIGHTS)
    assert m.cosine_similarity(mixed, vel, w) > m.cosine_similarity(mixed, quiet, w)
    assert m.cosine_similarity(mixed, vol, w) > m.cosine_similarity(mixed, quiet, w)


def test_handle_stamps_on_vault_layout_without_mutating_vector():
    vec = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.1]
    entry = b._layout_entry(
        layout_id="5",
        vector=list(vec),
        timeframe_resolution="1m",
        structural_move_pct=33.0,
        strategy="5B (1M)",
        source="vault_collective",
        pattern_count=3,
    )
    assert entry is not None
    assert entry["vector"][:8] == vec[:8]
    assert int(entry.get("window_hours") or 0) == 168
    assert int(entry.get("pattern_count") or 0) == 3
    assert str(entry.get("window_start") or "").endswith("Z")
    handle = entry.get("handle_execution") or {}
    assert handle.get("entry") == "fill_now"
    assert handle.get("vault_dna_mutated") is False
    assert handle.get("skip_until") == "09:45"
    assert abs(float(handle.get("target_pct") or 0) - 16.5) < 1e-9


def test_5m_placeholder_handle_is_dip_hold():
    spec = r.handle_execution_for("6A (5M)", "5m", structural_move_pct=12.0)
    assert spec["entry"] == "dip_hold"
    assert spec["skip_until"] == "09:45"
    assert abs(float(spec["dip_frac"]) - 0.006) < 1e-9
    assert abs(float(spec["target_pct"]) - 9.0) < 1e-9
    assert abs(float(spec["trail_after_target_pct"]) - 8.0) < 1e-9
    fifteen = r.handle_execution_for("1D (15M)", "15m", structural_move_pct=12.0)
    assert abs(float(fifteen["target_pct"]) - 12.0) < 1e-9
    assert "trail_after_target_pct" not in fifteen


def test_operator_clips_locked_2026_09_19():
    assert abs(m.TWO_D_TARGET_FRAC - 0.065) < 1e-9
    assert abs(m.THREE_A_TARGET_FRAC - 0.09) < 1e-9
    assert abs(m.TWO_B_TARGET_FRAC - 0.06) < 1e-9
    assert abs(m.TWO_C_TARGET_FRAC - 0.10) < 1e-9
    assert abs(m.ONE_A_TRIP_TRAIL_FRAC - 0.12) < 1e-9
    assert abs(m.PH_5M_STRUCT_FRAC - 0.75) < 1e-9
    assert abs(m.PH_5M_TRAIL_FRAC - 0.08) < 1e-9
    assert abs(m.PH_15M_TARGET_FRAC - 0.12) < 1e-9
    d2 = r.handle_execution_for("2D (1M)", "1m")
    a3 = r.handle_execution_for("3A (1M)", "1m")
    b2 = r.handle_execution_for("2B (1M)", "1m")
    c2 = r.handle_execution_for("2C (1M)", "1m")
    a1 = r.handle_execution_for("1A (1M)", "1m")
    assert abs(float(d2["target_pct"]) - 6.5) < 1e-9
    assert abs(float(a3["target_pct"]) - 9.0) < 1e-9
    assert abs(float(b2["target_pct"]) - 6.0) < 1e-9
    assert abs(float(c2["target_pct"]) - 10.0) < 1e-9
    assert "trail_12" in str(a1["target_pct"])
