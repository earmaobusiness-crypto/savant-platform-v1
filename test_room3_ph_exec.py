"""Placeholder Handle for unspecialized letters (1m / 5m / 15m)."""

from datetime import datetime
from zoneinfo import ZoneInfo

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


def test_1m_placeholder_no_rvol_gate():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=20)] * 8
    ready, note = m._entry_trigger_ready(
        {"ticker": "CRE"},
        quiet,
        last_px=1.001,
        tf="1m",
        strategy="9A (1M)",
        layout_id="6",
        structural=8.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note
    assert "RVOL" not in note


def test_5m_placeholder_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "CRE"},
        [_bar(1, 1.01, 0.99, 1.0, v=100)] * 4,
        last_px=1.0,
        tf="5m",
        strategy="3B (5M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_5m_placeholder_holds_after_dip():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices = [_bar(1.0, 1.01, 0.995, 1.0, v=100)] * 4
    line = {"ticker": "CRE"}
    ready, note = m._entry_trigger_ready(
        line,
        slices,
        last_px=1.0,
        tf="5m",
        strategy="3B (5M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    assert "pullback" in note
    dip = _bar(1.0, 1.002, 0.992, 0.994, v=110)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip],
        last_px=0.994,
        tf="5m",
        strategy="3B (5M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is False
    hold = _bar(0.994, 1.004, 0.993, 1.001, v=120)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip, hold],
        last_px=1.001,
        tf="5m",
        strategy="3B (5M)",
        layout_id="2",
        structural=12.0,
        session_state=ss,
    )
    assert ready is True
    assert "hold" in note


def test_15m_placeholder_holds_after_08_dip():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 45, tzinfo=ET))
    slices = [_bar(2.0, 2.02, 1.99, 2.0, v=100)] * 3
    line = {"ticker": "CRE"}
    ready, note = m._entry_trigger_ready(
        line,
        slices,
        last_px=2.0,
        tf="15m",
        strategy="8A (15M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" not in note
    dip = _bar(2.0, 2.01, 1.982, 1.988, v=110)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip],
        last_px=1.988,
        tf="15m",
        strategy="8A (15M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is False
    hold = _bar(1.988, 2.01, 1.986, 2.002, v=120)
    ready, note = m._entry_trigger_ready(
        line,
        slices + [dip, hold],
        last_px=2.002,
        tf="15m",
        strategy="8A (15M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is True
    assert "hold" in note
