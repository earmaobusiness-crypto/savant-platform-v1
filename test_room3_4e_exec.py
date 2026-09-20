"""4E (1M) quiet vel5 9–12% + last green ≥4% / 8.5% pack exit."""

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


def _4e_slices():
    rows = []
    px = 1.00
    for _ in range(4):
        nxt = round(px * 1.022, 6)
        rows.append(_bar(px, nxt, px * 0.999, nxt, v=40))
        px = nxt
    last = _bar(px, px * 1.048, px * 0.998, px * 1.025, v=42)
    rows.append(last)
    return rows, float(last["c"])


def test_4e_wallpaper_does_not_gene():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._4e_gene_ok(quiet) is False


def test_4e_gene_hits_not_4a_or_4d():
    slices, _px = _4e_slices()
    assert m._4e_gene_ok(slices) is True
    assert m._4a_gene_ok(slices) is False
    assert m._4d_gene_ok(slices) is False
    assert m._4b_gene_ok(slices) is False


def test_4e_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _4e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4E (1M)",
        layout_id="4",
        structural=24.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_4e_skips_until_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _4e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4E (1M)",
        layout_id="4",
        structural=24.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:45" in note


def test_4e_first_of_day_blocks():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._4e_mark_used(ss, "FAMI")
    slices, px = _4e_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="1m",
        strategy="4E (1M)",
        layout_id="4",
        structural=24.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_4e_pack_target_8_5pct():
    lot = {
        "strategy": "4E (1M)",
        "tf": "1m",
        "letter": "4E (1M)",
        "exit_style": m.FOUR_E_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.97,
        "exit_tgt_px": 1.085,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.05,
        patience=True,
        bar={"h": 1.06, "l": 1.02, "c": 1.05},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.09,
        patience=True,
        bar={"h": 1.09, "l": 1.04, "c": 1.09},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_4e_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FAMI",
            "tf": "1m",
            "strategy": "4E (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 24.0,
            "exit_style": m.FOUR_E_EXIT_STYLE,
            "exit_stop_px": 0.97,
            "exit_tgt_px": 1.085,
        },
    )
    assert row["exit_style"] == m.FOUR_E_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 1.085) < 1e-6
    assert ss.room3_4e_used_day["FAMI"]
