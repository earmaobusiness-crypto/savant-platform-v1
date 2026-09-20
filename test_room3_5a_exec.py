"""5A (1M) grind-down not 5B climax / 10% pack exit."""

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


def _5a_slices():
    """9-bar grind down ≥4% on both 5 and 9, last bar green range ≥2%. Not 5B."""
    rows = []
    px = 1.00
    for _ in range(4):
        nxt = round(px * 0.995, 6)
        rows.append(_bar(px, px * 1.001, nxt, nxt, v=50))
        px = nxt
    for _ in range(4):
        nxt = round(px * 0.985, 6)
        rows.append(_bar(px, px * 1.001, nxt, nxt, v=50))
        px = nxt
    last = _bar(px, px * 1.025, px * 0.998, px * 1.002, v=52)
    rows.append(last)
    return rows, float(last["c"])


def test_5a_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._5a_gene_ok(quiet) is False


def test_5a_gene_hits_grind_down():
    slices, _px = _5a_slices()
    assert m._5a_gene_ok(slices) is True
    assert m._5b_climax_ok(slices) is False


def test_5a_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _5a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="5A (1M)",
        layout_id="5",
        structural=27.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_5a_skips_until_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _5a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="5A (1M)",
        layout_id="5",
        structural=27.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:45" in note


def test_5a_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._5a_mark_used(ss, "FAMI")
    slices, px = _5a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="5A (1M)",
        layout_id="5",
        structural=27.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_5a_pack_target_10pct():
    lot = {
        "strategy": "5A (1M)",
        "tf": "1m",
        "letter": "5A (1M)",
        "exit_style": m.FIVE_A_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.97,
        "exit_tgt_px": 1.10,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.06,
        patience=True,
        bar={"h": 1.07, "l": 1.03, "c": 1.06},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.12,
        patience=True,
        bar={"h": 1.12, "l": 1.08, "c": 1.12},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_5a_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "5A (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 27.0,
            "exit_style": m.FIVE_A_EXIT_STYLE,
            "exit_stop_px": 0.97,
            "exit_tgt_px": 1.10,
        },
    )
    assert row["exit_style"] == m.FIVE_A_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.10) < 1e-6
    assert ss.room3_5a_used_day["FAMI"]
