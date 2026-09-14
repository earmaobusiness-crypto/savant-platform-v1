"""2A (1M) pack-like gene gate + 1% dip / pack exit."""

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


def _up_pack_slices():
    """~+12% window, last bar ≥5% range, green, RVOL ≥2."""
    rows = []
    px = 1.00
    for _ in range(6):
        nxt = round(px * 1.018, 4)
        rows.append(_bar(px, nxt, px * 0.999, nxt, v=50))
        px = nxt
    last = _bar(px, px * 1.06, px * 0.994, px * 1.05, v=400)
    rows.append(last)
    return rows, float(last["c"])


def test_2a_waits_on_wallpaper():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        quiet,
        last_px=1.001,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    assert "pack-like" in note


def test_2a_skips_open_chop():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _up_pack_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_2a_skips_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _up_pack_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_2a_waits_dip_then_enters_green_reclaim():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _up_pack_slices()
    line = {"ticker": "BIAF"}
    ready, note = m._entry_trigger_ready(
        line,
        slices,
        last_px=px,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    assert "dip" in note or "reclaim" in note or "pullback" in note
    dip = _bar(px, px * 1.002, px * 0.985, px * 0.988, v=120)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip],
        last_px=float(dip["c"]),
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    reclaim_px = float(dip["c"]) * 1.02
    reclaim = _bar(float(dip["c"]), reclaim_px * 1.01, float(dip["c"]), reclaim_px, v=150)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip, reclaim],
        last_px=reclaim_px,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is True
    assert "reclaim" in note


def test_2a_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._2a_mark_used(ss, "BIAF")
    slices, px = _up_pack_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="1m",
        strategy="2A (1M)",
        layout_id="2",
        structural=34.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_2a_pack_target_not_2p5():
    lot = {
        "strategy": "2A (1M)",
        "tf": "1m",
        "letter": "2A (1M)",
        "exit_style": m.TWO_A_EXIT_STYLE,
        "structural_move_pct": 34.0,
        "entry_px": 1.10,
        "exit_stop_px": 1.07,
        "exit_tgt_px": 1.10 * 1.10,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.13,
        patience=True,
        bar={"h": 1.14, "l": 1.09, "c": 1.13},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.29,
        patience=True,
        bar={"h": 1.30, "l": 1.20, "c": 1.29},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_2a_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "BIAF",
            "tf": "1m",
            "strategy": "2A (1M)",
            "qty": 10,
            "entry_px": 1.10,
            "structural_move_pct": 34.0,
            "exit_style": m.TWO_A_EXIT_STYLE,
            "exit_stop_px": 1.07,
            "exit_tgt_px": 1.10 * 1.10,
        },
    )
    assert row["exit_style"] == m.TWO_A_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.10 * 1.10) < 1e-6
    assert ss.room3_2a_used_day["BIAF"]
