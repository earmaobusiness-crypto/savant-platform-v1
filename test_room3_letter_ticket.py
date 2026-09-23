"""Per-letter ticket cap: extra Trading-today $ stays with letters that scale."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_matrix as m
import room3_recipes as r

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def _ss(tradable: float = 2_000_000.0) -> _SS:
    return _SS(
        _now_et=datetime(2026, 9, 16, 12, 40, tzinfo=ET),
        room3_tradable_today=float(tradable),
        room3_cash_claimed=0.0,
        room3_open_positions=[],
        room3_lots=[],
        room3_filter_universe=["MEDS"],
    )


def test_letter_caps_table():
    assert r.letter_max_ticket_usd("5m", "1A (5M)") is None
    assert r.letter_max_ticket_usd("5m", "8A") is None
    assert abs(float(r.letter_max_ticket_usd("5m", "1C (5M)")) - 200_000.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "5B")) - 200_000.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "5C (5M)")) - 0.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "6A")) - 200_000.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "5A (5M)")) - 200_000.0) < 1e-9
    assert r.letter_max_ticket_usd("15m", "1A (15M)") is None
    assert abs(float(r.letter_max_ticket_usd("15m", "1B (15M)")) - 300_000.0) < 1e-9
    assert r.letter_max_ticket_usd("1m", "3G (1M)") is None
    assert abs(float(r.letter_max_ticket_usd("1m", "2A (1M)")) - 100_000.0) < 1e-9
    assert r.letter_max_ticket_usd("5m", "") is None


def test_caps_follow_the_live_nominations():
    """2B (15M) carried the real detect path; these four bled on it."""
    assert r.letter_max_ticket_usd("15m", "2B (15M)") is None
    assert abs(float(r.letter_max_ticket_usd("15m", "8B (15M)")) - 0.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("15m", "9A (15M)")) - 300_000.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "3A (5M)")) - 0.0) < 1e-9
    assert abs(float(r.letter_max_ticket_usd("5m", "4A (5M)")) - 0.0) < 1e-9


def test_handle_stamps_cap():
    a1 = r.handle_execution_for("1A (5M)", "5m")
    assert "max_ticket_usd" not in a1
    c5 = r.handle_execution_for("5C (5M)", "5m")
    assert abs(float(c5["max_ticket_usd"]) - 0.0) < 1e-9
    b5 = r.handle_execution_for("5B (5M)", "5m")
    assert abs(float(b5["max_ticket_usd"]) - 200_000.0) < 1e-9
    c1 = r.handle_execution_for("1C (5M)", "5m")
    assert abs(float(c1["max_ticket_usd"]) - 200_000.0) < 1e-9


def test_five_c_does_not_take_the_two_million_slot():
    plan = m.compute_entry_plan(
        price=2.0,
        timeframe="5m",
        match_pct=90.0,
        session_state=_ss(),
        strategy="5C (5M)",
    )
    assert float(plan["qty"]) < 1
    assert float(plan["notional"]) <= 0.0
    assert "letter cap $0" in str(plan["note"])


def test_five_b_clips_to_two_hundred_k_when_slot_is_huge():
    plan = m.compute_entry_plan(
        price=2.0,
        timeframe="5m",
        match_pct=90.0,
        session_state=_ss(),
        strategy="5B (5M)",
    )
    assert float(plan["notional"]) <= 200_000.0 + 1e-6
    assert float(plan["notional"]) >= 150_000.0
    assert "letter cap $200,000" in str(plan["note"])


def test_one_a_keeps_the_grown_slot():
    a1 = m.compute_entry_plan(
        price=2.0,
        timeframe="5m",
        match_pct=90.0,
        session_state=_ss(),
        strategy="1A (5M)",
    )
    b5 = m.compute_entry_plan(
        price=2.0,
        timeframe="5m",
        match_pct=90.0,
        session_state=_ss(),
        strategy="5B (5M)",
    )
    assert float(a1["notional"]) > 200_000.0
    assert float(a1["notional"]) > float(b5["notional"])
    assert a1.get("letter_cap") is None
