"""Fat-tape Handle: same letter, this temperament. Not a TNON gene."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_matrix as m
import room3_recipes as r
import room3_walkforward as wf

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def _ss(**extra) -> _SS:
    now = extra.pop("_now_et", datetime(2026, 8, 19, 12, 0, tzinfo=ET))
    bag = _SS(
        _now_et=now,
        room3_tradable_today=2_000_000.0,
        room3_cash_claimed=0.0,
        room3_open_positions=[],
        room3_lots=[],
        room3_filter_universe=["TNON"],
    )
    bag.update(extra)
    return bag


def _quiet(n: int = 5) -> list[dict]:
    rows = []
    px = 10.0
    for _ in range(n):
        rows.append({"o": px, "h": px * 1.004, "l": px * 0.998, "c": px * 1.002, "v": 2_000})
        px *= 1.002
    return rows


def _fat_bar(close=10.20, high=10.55, low=10.00, open_=10.02, v=8_000) -> dict:
    return {"o": open_, "h": high, "l": low, "c": close, "v": v}


def _fat_15m():
    rows = _quiet(5)
    last = _fat_bar()
    rows.append(last)
    return rows, float(last["c"])


def test_fat_detects_four_point_five():
    quiet = _quiet()
    assert r.tape_is_fat(quiet) is False
    slices, _ = _fat_15m()
    assert r.last_bar_range_pct(slices) >= 4.5
    assert r.tape_is_fat(slices) is True
    assert r.fat_stop_pct(slices) >= 8.0
    assert r.fat_stop_pct(slices) >= r.last_bar_range_pct(slices)


def test_handle_overlay_is_temperament_not_a_letter():
    base = r.handle_execution_for("2B (15M)", "15m")
    assert base.get("first_of_day") is True
    fat = r.apply_fat_to_handle(base, _fat_15m()[0])
    assert fat["fat_tape"] is True
    assert fat["first_of_day"] is False
    assert fat["cool_sec"] == 0
    assert fat["entry"] == "wick"
    assert fat["exit_source"] == "fat_tape"
    assert fat.get("target_pct") in (None, 0, 0.0) or "target_pct" not in fat
    assert fat.get("stop_cap_pct") is None
    assert fat["hold_minutes"] == 20
    assert r._letter_head(fat["letter"]) == "2B"


def test_first_of_day_does_not_block_fat_tape():
    slices, px = _fat_15m()
    ss = _ss()
    m._15m_spec_mark_used(ss, "2B", "TNON")
    assert m._15m_spec_used_today(ss, "2B", "TNON") is True
    ready, note = m._entry_trigger_ready(
        {"ticker": "TNON"},
        slices,
        last_px=10.10,
        tf="15m",
        strategy="2B (15M)",
        layout_id="L2",
        structural=12.0,
        session_state=ss,
        match_pct=90,
    )
    assert m._tape_fat(ss) is True
    assert "first of day" not in note
    assert ready is True


def test_cool_does_not_block_fat_tape():
    slices, _px = _fat_15m()
    ss = _ss()
    m._15m_spec_mark_stop_cool(ss, "2B", "TNON")
    assert m._15m_spec_cool_until(ss, "2B", "TNON") is not None
    ready, note = m._entry_trigger_ready(
        {"ticker": "TNON"},
        slices,
        last_px=10.10,
        tf="15m",
        strategy="2B (15M)",
        layout_id="L2",
        structural=12.0,
        session_state=ss,
        match_pct=90,
    )
    assert "cool" not in note
    assert ready is True


def test_live_bar_waits_for_the_wick():
    slices, _ = _fat_15m()
    slices[-1] = _fat_bar(close=10.50, high=10.55, low=10.00)
    ready, note = m._1m_live_fill_now(
        {"ticker": "TNON", "_slices": slices, "_last_px": 10.50},
        "2B (15M)",
    )
    assert ready is False
    assert "wait the wick" in note


def test_completed_bar_fills_the_wick():
    slices, _ = _fat_15m()
    ready, note = m._1m_live_fill_now(
        {
            "ticker": "TNON",
            "_slices": slices,
            "_last_px": 10.50,
            "_fat_bar_complete": True,
        },
        "2B (15M)",
    )
    assert ready is True
    assert "enter now" in note


def test_fat_exit_is_not_a_twenty_take():
    lot = {
        "fat_tape": True,
        "letter": "2B",
        "strategy": "2B (15M)",
        "tf": "15m",
        "entry_px": 10.0,
        "exit_stop_px": 9.2,
        "exit_tgt_px": 0.0,
        "entry_ts": datetime(2026, 8, 19, 12, 0, tzinfo=ET).isoformat(),
        "hold_minutes": 20,
    }
    ss = _ss(_now_et=datetime(2026, 8, 19, 12, 10, tzinfo=ET))
    reason = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=12.5,
        patience=True,
        bar={"o": 12.0, "h": 12.6, "l": 11.8, "c": 12.5},
        session_state=ss,
    )
    assert reason == ""


def test_fat_exit_time_box():
    lot = {
        "fat_tape": True,
        "letter": "2B",
        "entry_px": 10.0,
        "exit_stop_px": 9.2,
        "entry_ts": datetime(2026, 8, 19, 12, 0, tzinfo=ET).isoformat(),
        "hold_minutes": 20,
    }
    ss = _ss(_now_et=datetime(2026, 8, 19, 12, 20, tzinfo=ET))
    reason = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=11.0,
        patience=True,
        bar={"o": 10.8, "h": 11.1, "l": 10.7, "c": 11.0},
        session_state=ss,
    )
    assert reason == "time box 20m"


def test_fat_exit_letter_flip():
    lot = {
        "fat_tape": True,
        "letter": "2B",
        "strategy": "2B (15M)",
        "entry_px": 10.0,
        "exit_stop_px": 9.2,
        "entry_ts": datetime(2026, 8, 19, 12, 0, tzinfo=ET).isoformat(),
        "_now_letter": "1B (15M)",
    }
    ss = _ss(_now_et=datetime(2026, 8, 19, 12, 5, tzinfo=ET))
    reason = m._lot_should_exit(
        lot,
        cur_match=86,
        last_px=10.4,
        patience=True,
        bar={"o": 10.3, "h": 10.5, "l": 10.2, "c": 10.4},
        session_state=ss,
    )
    assert reason == "letter flipped"


def test_fat_stop_is_wider_than_three_five():
    slices, px = _fat_15m()
    stamped = {}
    sig = {}
    m._apply_fat_exits(stamped, sig, slices, px)
    assert stamped["fat_tape"] is True
    assert stamped["exit_tgt_px"] == 0.0
    stop_pct = (px - float(stamped["exit_stop_px"])) / px * 100.0
    assert stop_pct + 1e-9 >= 8.0
    assert abs(stop_pct - r.fat_stop_pct(slices)) < 1e-6


def test_walkforward_fat_exit_ignores_target():
    lot = {
        "fat_tape": True,
        "letter": "2D",
        "entry_px": 10.0,
        "exit_stop_px": 9.2,
        "exit_tgt_px": 12.0,
        "entry_ts": datetime(2026, 8, 19, 10, 0, tzinfo=ET).isoformat(),
        "hold_minutes": 20,
    }
    bar = {
        "ts": datetime(2026, 8, 19, 10, 10, tzinfo=ET),
        "o": 11.5,
        "h": 12.4,
        "l": 11.2,
        "c": 12.2,
    }
    reason, px = wf._lot_exit(lot, bar, 12.2)
    assert reason == ""
    assert px == 0.0
    later = {
        **bar,
        "ts": datetime(2026, 8, 19, 10, 20, tzinfo=ET),
        "h": 11.1,
        "c": 11.0,
    }
    reason, px = wf._lot_exit(lot, later, 11.0)
    assert reason == "time box"
    assert px == 11.0
