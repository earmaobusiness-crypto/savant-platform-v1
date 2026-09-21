"""2B (1M) 9-bar up-window + 2% dip / 6% pack exit."""

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


def _2b_slices():
    """~+12% over 9 bars, last bar range ≥2%. No RVOL requirement."""
    rows = []
    px = 1.00
    for _ in range(8):
        nxt = round(px * 1.015, 6)
        rows.append(_bar(px, nxt, px * 0.999, nxt, v=40))
        px = nxt
    last = _bar(px, px * 1.025, px * 0.998, px * 1.012, v=50)
    rows.append(last)
    return rows, float(last["c"])


def test_2b_waits_on_wallpaper():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    ready, note = m._entry_trigger_ready(
        {"ticker": "MGN"},
        quiet,
        last_px=1.001,
        tf="1m",
        strategy="2B (1M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    assert "suited" in note or "wait" in note


def test_2b_skips_open_chop():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _2b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "MGN"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2B (1M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_2b_does_not_skip_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _2b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "MGN"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2B (1M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is True
    assert "10:00" not in note
    assert "enter now" in note


def test_2b_waits_2pct_dip_then_enters():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _2b_slices()
    line = {"ticker": "MGN"}
    ready, note = m._entry_trigger_ready(
        line,
        slices,
        last_px=px,
        tf="1m",
        strategy="2B (1M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_2b_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._2b_mark_used(ss, "MGN")
    slices, px = _2b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "MGN"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2B (1M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_2b_pack_target_6pct():
    lot = {
        "strategy": "2B (1M)",
        "tf": "1m",
        "letter": "2B (1M)",
        "exit_style": m.TWO_B_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.97,
        "exit_tgt_px": 1.06,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.03,
        patience=True,
        bar={"h": 1.04, "l": 1.01, "c": 1.03},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.07,
        patience=True,
        bar={"h": 1.07, "l": 1.04, "c": 1.07},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_2b_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "MGN",
            "tf": "1m",
            "strategy": "2B (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 12.0,
            "exit_style": m.TWO_B_EXIT_STYLE,
            "exit_stop_px": 0.97,
            "exit_tgt_px": 1.06,
        },
    )
    assert row["exit_style"] == m.TWO_B_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.06) < 1e-6
    assert ss.room3_2b_used_day["MGN"]
