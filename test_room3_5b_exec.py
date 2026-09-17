"""5B (1M) dump-then-hold + RVOL, first of day, pack-sized exit."""

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


def _climax_slices():
    quiet = _bar(3.05, 3.06, 3.04, 3.05, v=50)
    dump = _bar(3.02, 3.025, 2.84, 2.9215, v=800)
    hold = _bar(2.93, 2.95, 2.92, 2.9409, v=80)
    return [quiet] * 5 + [dump, hold]


def test_other_1m_placeholder_waits_dip():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    fat = [_bar(1, 1.02, 0.99, 1.01, v=400)] + [_bar(1, 1.01, 0.99, 1.0, v=80)] * 5
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        fat,
        last_px=1.0,
        tf="1m",
        strategy="3B (1M)",
        layout_id="3",
        structural=8.0,
        session_state=ss,
    )
    assert ready is False
    assert "pullback" in note
    assert "RVOL" not in note
    assert m._enter_on_print("5B (1M)", "1m", "5", 33.0) is False
    assert m._enter_on_print("3B (1M)", "1m", "3", 8.0) is False


def test_1m_placeholder_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [_bar(1, 1.02, 0.99, 1.01, v=400)] * 6,
        last_px=1.01,
        tf="1m",
        strategy="3B (1M)",
        layout_id="3",
        structural=8.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_15m_placeholder_does_not_skip_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [_bar(1, 1.01, 0.99, 1.0, v=100)] * 4,
        last_px=1.0,
        tf="15m",
        strategy="1A (15M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" not in note
    assert "pullback" in note or "waiting" in note


def test_5b_skips_open_chop():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    dump = _bar(3.02, 3.03, 2.85, 2.92, v=500)
    hold = _bar(2.93, 2.95, 2.92, 2.94, v=100)
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [dump] * 5 + [dump, hold],
        last_px=2.94,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_5b_waits_small_dump():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 59, tzinfo=ET))
    quiet = _bar(3.05, 3.06, 3.04, 3.05, v=50)
    dump = _bar(3.02, 3.025, 2.90, 2.94, v=800)
    hold = _bar(2.95, 2.97, 2.94, 2.96, v=80)
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [quiet] * 5 + [dump, hold],
        last_px=2.96,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "dump-then-hold" in note
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 55, tzinfo=ET))
    knife = _bar(3.02, 3.06, 2.97, 2.99, v=200)
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [knife] * 6,
        last_px=2.99,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "dump-then-hold" in note


def test_5b_waits_without_rvol():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 59, tzinfo=ET))
    quiet = _bar(3.05, 3.06, 3.04, 3.05, v=100)
    dump = _bar(3.02, 3.025, 2.84, 2.9215, v=250)
    hold = _bar(2.93, 2.95, 2.92, 2.9409, v=80)
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        [quiet] * 5 + [dump, hold],
        last_px=2.9409,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "RVOL" in note


def test_5b_climax_enters_after_hold():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 59, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        _climax_slices(),
        last_px=2.9409,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is True
    assert "climax" in note
    assert "RVOL" in note


def test_5b_first_of_day_blocks_second_shot():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 10, tzinfo=ET))
    m._5b_mark_used(ss, "FTFT")
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        _climax_slices(),
        last_px=2.9409,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "first of day" in note


def test_5b_exit_hits_pack_target_not_2p5_or_1r():
    lot = {
        "strategy": "5B (1M)",
        "tf": "1m",
        "letter": "5B (1M)",
        "exit_style": m.FIVE_B_EXIT_STYLE,
        "structural_move_pct": 33.0,
        "entry_px": 2.9409,
        "exit_r_frac": 0.05,
        "exit_stop_px": 2.851,
        "exit_tgt_px": 2.9409 * 1.165,
        "entry_ts": "2026-09-11T12:59:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 10, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=3.00,
        patience=True,
        bar={"h": 3.01, "l": 2.93, "c": 3.00},
        session_state=ss,
    )
    assert still == ""  # +2% is not the pack target
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=3.43,
        patience=True,
        bar={"h": 3.44, "l": 3.20, "c": 3.43},
        session_state=ss,
    )
    assert why.startswith("target")


def test_5b_pack_does_not_time_out_at_8_min():
    lot = {
        "strategy": "5B (1M)",
        "tf": "1m",
        "letter": "5B (1M)",
        "exit_style": m.FIVE_B_EXIT_STYLE,
        "structural_move_pct": 33.0,
        "entry_px": 2.9409,
        "exit_stop_px": 2.851,
        "exit_tgt_px": 2.9409 * 1.165,
        "entry_ts": "2026-09-11T12:59:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 10, tzinfo=ET))
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=2.96,
        patience=True,
        bar={"h": 2.97, "l": 2.93, "c": 2.96},
        session_state=ss,
    )
    assert why == ""


def test_5b_legacy_1r_still_times_out():
    lot = {
        "strategy": "5B (1M)",
        "tf": "1m",
        "letter": "5B (1M)",
        "exit_style": m.FIVE_B_EXIT_STYLE_LEGACY,
        "entry_px": 2.9409,
        "exit_r_frac": 0.02,
        "exit_stop_px": 2.8821,
        "exit_tgt_px": 2.9997,
        "entry_ts": "2026-09-11T12:59:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 10, tzinfo=ET))
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=2.96,
        patience=True,
        bar={"h": 2.97, "l": 2.93, "c": 2.96},
        session_state=ss,
    )
    assert why.startswith("time")


def test_5b_stop_cools_reentry():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 10, tzinfo=ET))
    m._5b_mark_stop_cool(ss, "FTFT")
    ss["_now_et"] = datetime(2026, 9, 11, 13, 12, tzinfo=ET)
    ready, note = m._entry_trigger_ready(
        {"ticker": "FTFT"},
        _climax_slices(),
        last_px=2.94,
        tf="1m",
        strategy="5B (1M)",
        layout_id="5",
        structural=33.0,
        session_state=ss,
    )
    assert ready is False
    assert "cool" in note


def test_append_lot_stamps_5b_pack_exit():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FTFT",
            "tf": "1m",
            "strategy": "5B (1M)",
            "qty": 10,
            "entry_px": 2.9409,
            "structural_move_pct": 33.0,
            "exit_style": m.FIVE_B_EXIT_STYLE,
            "exit_stop_px": 2.851,
            "exit_tgt_px": 2.9409 * 1.165,
        },
    )
    assert row["exit_style"] == m.FIVE_B_EXIT_STYLE
    assert abs(row["exit_tgt_px"] - 2.9409 * 1.165) < 1e-6
    assert abs(row["exit_stop_px"] - 2.851) < 1e-6
    assert row.get("entry_ts")
    assert ss.room3_5b_used_day["FTFT"]
