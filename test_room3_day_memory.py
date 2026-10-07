from datetime import datetime
from zoneinfo import ZoneInfo

import room3_day_memory as mem

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def get(self, k, default=None):
        return super().get(k, default)


def test_purge_after_next_day_4pm(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    sess = "2026-10-07"
    path = tmp_path / f"{sess}.jsonl"
    path.write_text("{}\n")
    still = datetime(2026, 10, 8, 15, 59, tzinfo=ET)
    assert mem.purge(now=still) == []
    assert path.exists()
    gone = mem.purge(now=datetime(2026, 10, 8, 16, 0, tzinfo=ET))
    assert gone == [sess]
    assert not path.exists()


def test_between_keeps_match_and_fills(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    ss = _SS(
        room3_engine_armed=True,
        room3_unattended_armed=True,
        room3_filter_universe=["XHG"],
        room3_tradable_today=1000,
        room3_watch_book={
            "lines": {
                "XHG:15m": {
                    "ticker": "XHG",
                    "timeframe": "15m",
                    "match_pct": 92,
                    "nearest_layout": "S",
                    "nearest_strategy": "S1 (15M)",
                    "state": "watching",
                    "size_usd": 750,
                }
            }
        },
        room3_trade_history=[{"id": "1", "ticker": "XHG", "strategy": "S1 (15M)", "pnl": 10.5}],
        room3_open_positions=[],
    )
    t0 = datetime(2026, 10, 7, 9, 32, tzinfo=ET)
    t1 = datetime(2026, 10, 7, 9, 47, tzinfo=ET)
    mem.remember(ss, now=t0)
    ss["room3_watch_book"]["lines"]["XHG:15m"]["match_pct"] = 88
    mem.remember(ss, now=t1)
    rows = mem.between("09:30", "10:00", sess="2026-10-07")
    assert len(rows) == 2
    assert rows[0]["lines"][0]["match"] == 92
    assert rows[1]["lines"][0]["match"] == 88
    assert rows[0]["fills"] == 1
    assert rows[0]["arm"] is True
