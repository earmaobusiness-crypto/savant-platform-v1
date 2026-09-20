"""3C (1M) above-VWAP quiet + 16% pack / 3.5% stop floor."""

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


def _3c_slices():
    """Session VWAP near 1.00, last print above it, range ≥4%, quiet volume."""
    rows = [_bar(1.00, 1.002, 0.998, 1.00, v=40)] * 8
    last = _bar(1.02, 1.065, 1.015, 1.04, v=42)
    rows.append(last)
    return rows, float(last["c"])


def test_3c_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._3c_gene_ok(quiet) is False


def test_3c_gene_above_vwap_not_3b():
    slices, _px = _3c_slices()
    assert m._3c_gene_ok(slices) is True
    assert m._3a_gene_ok(slices) is False
    assert m._3b_gene_ok(slices) is False


def test_3c_red_bar_above_vwap_still_genes():
    rows = [_bar(1.00, 1.002, 0.998, 1.00, v=40)] * 8
    rows.append(_bar(1.06, 1.06, 1.01, 1.022, v=42))
    assert m._3c_gene_ok(rows) is True


def test_3c_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 30, tzinfo=ET))
    slices, px = _3c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3C (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note
    assert "12:00" not in note


def test_3c_skips_until_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _3c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3C (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:45" in note


def test_3c_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._3c_mark_used(ss, "FAMI")
    slices, px = _3c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="3C (1M)",
        layout_id="3",
        structural=21.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_3c_pack_target_16pct():
    lot = {
        "strategy": "3C (1M)",
        "tf": "1m",
        "letter": "3C (1M)",
        "exit_style": m.THREE_C_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.965,
        "exit_tgt_px": 1.16,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.10,
        patience=True,
        bar={"h": 1.12, "l": 1.04, "c": 1.10},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.17,
        patience=True,
        bar={"h": 1.17, "l": 1.08, "c": 1.17},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_3c_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "3C (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 21.0,
            "exit_style": m.THREE_C_EXIT_STYLE,
            "exit_stop_px": 0.965,
            "exit_tgt_px": 1.16,
        },
    )
    assert row["exit_style"] == m.THREE_C_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.16) < 1e-6
    assert abs(float(row["exit_r_frac"]) - 0.035) < 1e-9
    assert ss.room3_3c_used_day["FAMI"]
