"""A sibling TF's unfilled stamp must not freeze 1m on the same name."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_matrix as m
import room3_watcher as w

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def _ss():
    return _SS(
        _now_et=datetime(2026, 9, 16, 12, 40, tzinfo=ET),
        room3_tradable_today=1000.0,
        room3_cash_claimed=0.0,
        room3_open_positions=[],
        room3_lots=[],
        room3_filter_universe=["MEDS"],
    )


def _book():
    book = w.empty_book()
    book["universe"] = ["MEDS"]
    w.ensure_ticker_maps(book, "MEDS")
    five = book["lines"][w.line_key("MEDS", "5m")]
    five["state"] = "committed"
    five["order_pending"] = True
    five["pending_order_id"] = "alpaca-ghost"
    five["entry_signal"] = {"strategy": "5B (5M)", "letter": "5B (5M)"}
    five["entry_strategy"] = "5B (5M)"
    five["entry_qty"] = 10
    five["entry_price"] = 8.8
    one = book["lines"][w.line_key("MEDS", "1m")]
    one["state"] = "watching"
    one["children"] = [
        {
            "letter": "6A (1M)",
            "layout_id": "6",
            "strategy": "6A (1M)",
            "match_pct": 93,
            "structural_move_pct": 8.0,
            "ticker": "MEDS",
            "family_armed_px": 1.0,
            "trigger_phase": "ready",
        }
    ]
    return book


def test_unfilled_5m_does_not_own_seat():
    book = _book()
    one = book["lines"][w.line_key("MEDS", "1m")]
    five = book["lines"][w.line_key("MEDS", "5m")]
    assert w._line_owns_seat(five) is False
    assert w._sibling_seat_tf(book, one) == ""
    note = w._why_not_firing(one, book)
    assert "already in" not in note


def test_filled_5m_still_owns_seat():
    book = _book()
    five = book["lines"][w.line_key("MEDS", "5m")]
    five["state"] = "in"
    five.pop("order_pending", None)
    one = book["lines"][w.line_key("MEDS", "1m")]
    assert w._sibling_seat_tf(book, one) == "5m"
    note = w._why_not_firing(one, book)
    assert "5m" in note and "in" in note


def test_1m_can_queue_while_5m_limit_is_working():
    book = _book()
    one = book["lines"][w.line_key("MEDS", "1m")]
    slices = [{"o": 1.0, "h": 1.01, "l": 0.99, "c": 1.0, "v": 100}] * 4
    queued = m._try_queue_child_entry(
        book,
        one,
        session_state=_ss(),
        ticker="MEDS",
        tf="1m",
        last_px=1.0,
        slices=slices,
        layouts=[],
        match={"second_cosine": 0.2, "cosine_similarity": 0.93},
    )
    assert queued is True
    assert one.get("entry_signal")
    assert str((one.get("entry_signal") or {}).get("strategy") or "").startswith("6A")


def test_same_tf_still_waits_on_its_own_working_order():
    book = _book()
    five = book["lines"][w.line_key("MEDS", "5m")]
    five["children"] = [
        {
            "letter": "5A (5M)",
            "layout_id": "5",
            "strategy": "5A (5M)",
            "match_pct": 90,
            "structural_move_pct": 8.0,
            "ticker": "MEDS",
            "family_armed_px": 8.8,
            "trigger_phase": "ready",
        }
    ]
    queued = m._try_queue_child_entry(
        book,
        five,
        session_state=_ss(),
        ticker="MEDS",
        tf="5m",
        last_px=8.8,
        slices=[{"o": 8.8, "h": 8.9, "l": 8.7, "c": 8.8, "v": 100}] * 4,
        layouts=[],
        match={"second_cosine": 0.2, "cosine_similarity": 0.9},
    )
    assert queued is False
    assert (five.get("entry_signal") or {}).get("strategy") == "5B (5M)"
