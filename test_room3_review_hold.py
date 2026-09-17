"""Unvoted Operator review cards drop at 9:00 AM ET the next morning."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_trading as t

ET = ZoneInfo("America/New_York")


def test_unvoted_expires_next_morning_9am():
    row = {
        "session_date": "2026-09-15",
        "exit_time": "16:01:38",
        "ticker": "ADBT",
        "strategy": "2D (5M)",
        "timeframe": "5m",
    }
    until = t._review_hold_until(row)
    assert until == datetime(2026, 9, 16, 9, 0, tzinfo=ET)


def test_same_session_still_held_before_9am():
    row = {"session_date": "2026-09-17", "exit_time": "12:02:07"}
    until = t._review_hold_until(row)
    assert until == datetime(2026, 9, 18, 9, 0, tzinfo=ET)


def test_wednesday_16_batch_holds_one_extra_morning():
    row = {"session_date": "2026-09-16", "exit_time": "12:02:07"}
    until = t._review_hold_until(row)
    assert until == datetime(2026, 9, 18, 9, 0, tzinfo=ET)
    assert until == t._review_extra_hold_drop()


def test_thursday_17_drops_with_wednesday_16_friday_morning():
    row = {"session_date": "2026-09-17", "exit_time": "15:59:00"}
    until = t._review_hold_until(row)
    assert until == datetime(2026, 9, 18, 9, 0, tzinfo=ET)


def test_friday_18_back_to_normal_next_morning():
    row = {"session_date": "2026-09-18", "exit_time": "12:00:00"}
    until = t._review_hold_until(row)
    assert until == datetime(2026, 9, 19, 9, 0, tzinfo=ET)


def test_voted_row_is_not_held():
    row = {
        "session_date": "2026-09-16",
        "exit_time": "12:02:07",
        "operator_vote": "good",
    }
    assert t._within_review_hold(row) is False
