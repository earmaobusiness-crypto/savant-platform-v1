"""FIFO close pairing — stacked lots across days must become session rows."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_alpaca

ET = ZoneInfo("America/New_York")


def _ev(sym, side, qty, px, day, hhmmss, oid):
    h, m, s = (int(x) for x in hhmmss.split(":"))
    y, mo, d = (int(x) for x in day.split("-"))
    return {
        "symbol": sym,
        "side": side,
        "qty": qty,
        "price": px,
        "ts": datetime(y, mo, d, h, m, s, tzinfo=ET),
        "id": oid,
        "source": "order",
    }


def test_stacked_lots_close_on_later_session():
    events = [
        _ev("FAMI", "buy", 100, 1.00, "2026-09-02", "10:00:00", "b1"),
        _ev("FAMI", "buy", 50, 1.10, "2026-09-02", "11:00:00", "b2"),
        _ev("MIMI", "buy", 200, 2.00, "2026-09-03", "10:15:00", "b3"),
        _ev("FAMI", "sell", 150, 0.90, "2026-09-02", "15:59:00", "s1"),
        _ev("MIMI", "sell", 200, 2.20, "2026-09-03", "15:59:00", "s2"),
        _ev("GELS", "buy", 10, 3.00, "2026-09-04", "09:45:00", "b4"),
        _ev("GELS", "sell", 10, 2.80, "2026-09-04", "15:59:00", "s3"),
    ]
    closed = room3_alpaca._closed_from_events(events)
    days = sorted({str(r.get("session_date") or "") for r in closed})
    assert "2026-09-02" in days
    assert "2026-09-03" in days
    assert "2026-09-04" in days
    fami = [r for r in closed if r["ticker"] == "FAMI"]
    assert fami
    assert abs(float(fami[0]["qty"]) - 150) < 1e-9


def test_15m_add_blocked_when_lots_lost_but_broker_still_in():
    import room3_matrix

    class _S:
        def __init__(self):
            self.room3_lots = []
            self.room3_open_positions = [{"ticker": "PPBT", "qty": 900}]
            self.room3_watch_book = {"lines": {}}

        def get(self, k, default=None):
            return getattr(self, k, default)

    assert room3_matrix._15m_can_open_lot(_S(), "PPBT") is False


if __name__ == "__main__":
    test_stacked_lots_close_on_later_session()
    test_15m_add_blocked_when_lots_lost_but_broker_still_in()
    print("ok")
