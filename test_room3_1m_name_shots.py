"""1m max 3 fills per name per day — shared across letters."""

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


def test_fourth_1m_shot_on_name_blocked():
    ss = _SS(_now_et=datetime(2026, 9, 17, 11, 0, tzinfo=ET))
    assert m.ONE_M_NAME_SHOT_MAX == 3
    m._1m_mark_name_shot(ss, "DTSS")
    m._1m_mark_name_shot(ss, "DTSS")
    m._1m_mark_name_shot(ss, "DTSS")
    assert m._1m_name_shots_today(ss, "DTSS") == 3
    ready, note = m._entry_trigger_ready(
        {"ticker": "DTSS"},
        [{"o": 1, "h": 1.1, "l": 0.9, "c": 1.05, "v": 100}],
        last_px=1.05,
        tf="1m",
        strategy="2D (1M)",
        layout_id="TEST",
        structural=0.0,
        session_state=ss,
    )
    assert ready is False
    assert "max 3" in note


def test_name_shot_does_not_block_other_ticker():
    ss = _SS(_now_et=datetime(2026, 9, 17, 11, 0, tzinfo=ET))
    m._1m_mark_name_shot(ss, "DTSS")
    m._1m_mark_name_shot(ss, "DTSS")
    m._1m_mark_name_shot(ss, "DTSS")
    assert m._1m_name_shots_blocked(ss, "DAIC") is False
