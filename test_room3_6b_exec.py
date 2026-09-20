"""6B (1M) milder dump bounce under VWAP / 15.5% pack / 3.5% stop floor."""

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


def _6b_slices():
    """Vel5 ~−2.6 (not 6A's −3/−2 pair), last green ≥2%, under VWAP."""
    rows = [_bar(1.10, 1.101, 1.098, 1.099, v=40)]
    px = 1.099
    for _ in range(7):
        nxt = round(px * 0.986, 6)
        rows.append(_bar(px, px * 1.001, nxt * 0.999, nxt, v=42))
        px = nxt
    last = _bar(px, px * 1.028, px * 0.999, px * 1.016, v=44)
    rows.append(last)
    return rows, float(last["c"])


def test_6b_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._6b_gene_ok(quiet) is False


def test_6b_gene_under_vwap_not_6a():
    slices, _px = _6b_slices()
    assert m._6b_gene_ok(slices) is True
    assert m._6a_gene_ok(slices) is False
    assert m._5a_gene_ok(slices) is False


def test_6b_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _6b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="6B (1M)",
        layout_id="6",
        structural=24.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_6b_skips_until_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _6b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="6B (1M)",
        layout_id="6",
        structural=24.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:45" in note


def test_6b_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._6b_mark_used(ss, "FAMI")
    slices, px = _6b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="6B (1M)",
        layout_id="6",
        structural=24.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_6b_pack_target_15_5pct():
    lot = {
        "strategy": "6B (1M)",
        "tf": "1m",
        "letter": "6B (1M)",
        "exit_style": m.SIX_B_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.965,
        "exit_tgt_px": 1.155,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.10,
        patience=True,
        bar={"h": 1.11, "l": 1.04, "c": 1.10},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.16,
        patience=True,
        bar={"h": 1.16, "l": 1.08, "c": 1.16},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_6b_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "6B (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 24.0,
            "exit_style": m.SIX_B_EXIT_STYLE,
            "exit_stop_px": 0.965,
            "exit_tgt_px": 1.155,
        },
    )
    assert row["exit_style"] == m.SIX_B_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.155) < 1e-6
    assert abs(float(row["exit_r_frac"]) - 0.035) < 1e-9
    assert ss.room3_6b_used_day["FAMI"]
