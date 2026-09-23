"""Detect stays 85% (the gene). Firing needs 88% (Handle). Book is 15m-heavy."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_matrix as m
import room3_watcher as w

ET = ZoneInfo("America/New_York")


def _slices(n: int = 6) -> list[dict]:
    out = []
    px = 10.0
    for _ in range(n):
        out.append({"o": px, "h": px * 1.03, "l": px * 0.99, "c": px * 1.02, "v": 50_000})
        px *= 1.02
    return out


def test_gene_floor_did_not_move():
    """Every letter lock says 'nearest ≥85%, same TF'. Keep that true."""
    assert m.MATCH_THRESHOLD_PCT == 85
    assert m.FIRE_FLOOR_PCT == 88
    assert m.FIRE_FLOOR_PCT > m.MATCH_THRESHOLD_PCT


def test_family_band_watches_and_does_not_buy():
    for pct in (85, 86, 87):
        ready, note = m._entry_trigger_ready(
            {"ticker": "MEDS"},
            _slices(),
            last_px=11.0,
            tf="15m",
            strategy="2B (15M)",
            layout_id="L2",
            structural=12.0,
            match_pct=pct,
        )
        assert ready is False, f"{pct}% should not fire"
        assert "fires at ≥88%" in note


def test_eighty_eight_is_past_the_floor():
    """88 clears the money gate — whatever the letter's own Hunt then decides."""
    _ready, note = m._entry_trigger_ready(
        {"ticker": "MEDS"},
        _slices(),
        last_px=11.0,
        tf="15m",
        strategy="2B (15M)",
        layout_id="L2",
        structural=12.0,
        match_pct=88,
    )
    assert "fires at ≥88%" not in note


def test_book_is_fifteen_minute_heavy():
    frac = m.TF_BUCKET_FRAC
    assert abs(sum(frac.values()) - 1.0) < 1e-9
    assert frac["15m"] > frac["5m"] + frac["1m"]
    assert abs(frac["15m"] - 0.75) < 1e-9


def test_both_floors_are_said_out_loud():
    """Hidden-defaults rule: money gates must be visible, not discovered at fill."""
    assert "88" in m.SIZE_EXPLAIN and "75%" in m.SIZE_EXPLAIN
    line = {"ticker": "MEDS", "match_pct": 86, "slices": _slices()}
    note = w._why_not_firing(line, {"engine_armed": True, "entries_allowed": True})
    assert "86%" in note and "88%" in note
