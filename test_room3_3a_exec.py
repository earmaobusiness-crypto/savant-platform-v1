"""3A (1M) under-VWAP morning window + 1.5% dip / 8% pack exit."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_engine
import room3_matrix as m
import room3_recipes

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def _bar(o, h, l, c, v=100.0):
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def _3a_slices():
    """Elevated VWAP, then a ≥1.5% bar under it with volume."""
    rows = []
    px = 1.08
    for _ in range(5):
        nxt = round(px * 1.001, 6)
        rows.append(_bar(px, px * 1.004, px * 0.998, nxt, v=20))
        px = nxt
    last = _bar(1.01, 1.028, 0.995, 1.00, v=200)
    rows.append(last)
    return rows, 1.00


def test_3a_waits_on_wallpaper():
    ss = _SS(_now_et=datetime(2026, 9, 11, 11, 0, tzinfo=ET))
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=20)] * 8
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        quiet,
        last_px=1.001,
        tf="1m",
        strategy="3A (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_3a_skips_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _3a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3A (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_3a_no_new_shot_after_noon():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 5, tzinfo=ET))
    slices, px = _3a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3A (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is False
    assert "12:00" in note


def test_3a_waits_1pct_dip_then_enters():
    ss = _SS(_now_et=datetime(2026, 9, 11, 11, 0, tzinfo=ET))
    slices, px = _3a_slices()
    assert m._3a_gene_ok(slices)
    line = {"ticker": "FAMI"}
    ready, note = m._entry_trigger_ready(
        line,
        slices,
        last_px=px,
        tf="1m",
        strategy="3A (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_3a_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 11, 0, tzinfo=ET))
    m._3a_mark_used(ss, "FAMI")
    slices, px = _3a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3A (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_3a_stop_floor_35_target_10():
    slices, px = _3a_slices()
    stop_px, tgt_px, stop_frac = m._3a_pack_exits(slices, px)
    assert abs(tgt_px - 1.10) < 1e-6
    assert abs(stop_frac - 0.035) < 1e-6
    assert abs(stop_px - px * 0.965) < 1e-6


def test_3a_pack_target_10pct():
    lot = {
        "strategy": "3A (1M)",
        "tf": "1m",
        "letter": "3A (1M)",
        "exit_style": m.THREE_A_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.965,
        "exit_tgt_px": 1.10,
        "entry_ts": "2026-09-11T11:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 11, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.04,
        patience=True,
        bar={"h": 1.05, "l": 1.02, "c": 1.04},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.11,
        patience=True,
        bar={"h": 1.11, "l": 1.05, "c": 1.11},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_3a_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "3A (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 21.0,
            "exit_style": m.THREE_A_EXIT_STYLE,
            "exit_stop_px": 0.965,
            "exit_tgt_px": 1.10,
        },
    )
    assert row["exit_style"] == m.THREE_A_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.10) < 1e-6
    assert ss.room3_3a_used_day["FAMI"]


def test_3a_order_style_is_limit():
    assert room3_recipes.order_style_for("3A (1M)", "1m", structural_move_pct=21.0) == "market"
    assert room3_recipes.order_style_for("3A (1M)", "1m", structural_move_pct=1.0) == "market"
