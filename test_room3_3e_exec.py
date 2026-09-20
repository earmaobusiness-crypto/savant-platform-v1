"""3E (1M) quiet above-VWAP leftover of 3F / loc ≥0.50 / 17% pack / 3.5% stop floor."""

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


def _3e_slices():
    """Session up ≥0, last 2–<3.5% loc ≥0.50 above VWAP, quiet RVOL. Not 3F/4A."""
    rows = [_bar(1.00, 1.002, 0.998, 1.00, v=40)] * 8
    last = _bar(1.01, 1.032, 1.006, 1.022, v=42)
    rows.append(last)
    return rows, float(last["c"])


def test_3e_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._3e_gene_ok(quiet) is False


def test_3e_weak_loc_does_not_gene():
    rows = [_bar(1.00, 1.002, 0.998, 1.00, v=40)] * 8
    last = _bar(1.01, 1.032, 1.006, 1.012, v=42)
    rows.append(last)
    assert m._bar_close_loc(last) < 0.50
    assert m._3e_gene_ok(rows) is False


def test_3e_gene_above_vwap_not_3f_or_4a():
    slices, _px = _3e_slices()
    assert m._3e_gene_ok(slices) is True
    assert m._3f_gene_ok(slices) is False
    assert m._3d_gene_ok(slices) is False
    assert m._4a_gene_ok(slices) is False


def test_3e_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _3e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3E (1M)",
        layout_id="3",
        structural=22.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_3e_skips_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _3e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3E (1M)",
        layout_id="3",
        structural=22.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_3e_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._3e_mark_used(ss, "FAMI")
    slices, px = _3e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3E (1M)",
        layout_id="3",
        structural=22.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_3e_pack_target_17pct():
    lot = {
        "strategy": "3E (1M)",
        "tf": "1m",
        "letter": "3E (1M)",
        "exit_style": m.THREE_E_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.965,
        "exit_tgt_px": 1.17,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.08,
        patience=True,
        bar={"h": 1.09, "l": 1.03, "c": 1.08},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.18,
        patience=True,
        bar={"h": 1.18, "l": 1.05, "c": 1.18},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_3e_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "3E (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 22.0,
            "exit_style": m.THREE_E_EXIT_STYLE,
            "exit_stop_px": 0.965,
            "exit_tgt_px": 1.17,
        },
    )
    assert row["exit_style"] == m.THREE_E_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.17) < 1e-6
    assert abs(float(row["exit_r_frac"]) - 0.035) < 1e-9
    assert ss.room3_3e_used_day["FAMI"]
