"""4A (1M) middle 5-bar 3–8% + RVOL <1.5 / 6% pack exit."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_engine
import room3_matrix as m

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


def _4a_slices():
    """~+5% over 5 bars, last bar range ≥2%, even quiet volume."""
    rows = []
    px = 1.00
    for _ in range(4):
        nxt = round(px * 1.01, 6)
        rows.append(_bar(px, nxt, px * 0.999, nxt, v=40))
        px = nxt
    last = _bar(px, px * 1.025, px * 0.998, px * 1.01, v=42)
    rows.append(last)
    return rows, float(last["c"])


def test_4a_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._4a_gene_ok(quiet) is False


def test_4a_gene_hits_middle_window():
    slices, _px = _4a_slices()
    assert m._4a_gene_ok(slices) is True
    assert m._2a_gene_ok(slices) is False


def test_4a_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _4a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4A (1M)",
        layout_id="4",
        structural=19.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_4a_skips_until_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _4a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4A (1M)",
        layout_id="4",
        structural=19.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:45" in note


def test_4a_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._4a_mark_used(ss, "FAMI")
    slices, px = _4a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4A (1M)",
        layout_id="4",
        structural=19.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_4a_pack_target_6pct():
    lot = {
        "strategy": "4A (1M)",
        "tf": "1m",
        "letter": "4A (1M)",
        "exit_style": m.FOUR_A_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.97,
        "exit_tgt_px": 1.06,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
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
        last_px=1.07,
        patience=True,
        bar={"h": 1.07, "l": 1.03, "c": 1.07},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_4a_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "4A (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 19.0,
            "exit_style": m.FOUR_A_EXIT_STYLE,
            "exit_stop_px": 0.97,
            "exit_tgt_px": 1.06,
        },
    )
    assert row["exit_style"] == m.FOUR_A_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.06) < 1e-6
    assert ss.room3_4a_used_day["FAMI"]
