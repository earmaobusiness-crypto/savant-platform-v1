from datetime import datetime
from zoneinfo import ZoneInfo

import room3_day_memory as mem

ET = ZoneInfo("America/New_York")


class _SS(dict):
    def get(self, k, default=None):
        return super().get(k, default)


def test_kept_sessions_includes_yesterday_until_8pm(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    (tmp_path / "2026-10-07.jsonl").write_text("{}\n")
    (tmp_path / "2026-10-08.jsonl").write_text("{}\n")
    morning = datetime(2026, 10, 8, 10, 0, tzinfo=ET)
    assert mem.kept_sessions(now=morning) == ["2026-10-07", "2026-10-08"]
    afternoon = datetime(2026, 10, 8, 16, 0, tzinfo=ET)
    assert mem.kept_sessions(now=afternoon) == ["2026-10-07", "2026-10-08"]
    after = datetime(2026, 10, 8, 20, 0, tzinfo=ET)
    assert mem.kept_sessions(now=after) == ["2026-10-08"]


def test_purge_after_next_day_8pm(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    sess = "2026-10-07"
    path = tmp_path / f"{sess}.jsonl"
    path.write_text("{}\n")
    still = datetime(2026, 10, 8, 19, 59, tzinfo=ET)
    assert mem.purge(now=still) == []
    assert path.exists()
    gone = mem.purge(now=datetime(2026, 10, 8, 20, 0, tzinfo=ET))
    assert gone == [sess]
    assert not path.exists()


def test_between_keeps_match_and_fills(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    ss = _SS(
        room3_engine_armed=True,
        room3_allowed_sessions=["rth"],
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
                    "feed": "massive",
                    "fat_tape": True,
                    "slices": [{"o": 2.1, "h": 2.4, "l": 2.0, "c": 2.2, "v": 1000}],
                }
            }
        },
        room3_trade_history=[{
            "id": "1", "ticker": "XHG", "strategy": "S1 (15M)", "pnl": 10.5,
            "entry_price": 2.1, "exit_price": 2.3, "qty": 10,
        }],
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
    assert rows[0]["lines"][0]["feed"] == "massive"
    assert rows[0]["lines"][0]["fat"] is True
    assert rows[0]["lines"][0]["last"]["c"] == 2.2
    assert rows[0]["log"][0]["entry"] == 2.1
    assert rows[1]["lines"][0]["match"] == 88
    assert rows[0]["fills"] == 1
    assert rows[0]["arm"] is True


def test_idle_after_flatten_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    live = _SS(
        room3_engine_armed=True,
        room3_allowed_sessions=["rth"],
        room3_filter_universe=["BIYA"],
        room3_tradable_today=1000,
        room3_watch_book={"lines": {}},
        room3_trade_history=[{"id": "1", "ticker": "BIYA", "pnl": -1}],
        room3_open_positions=[],
    )
    t0 = datetime(2026, 10, 7, 10, 10, tzinfo=ET)
    mem.remember(live, now=t0)
    live["room3_filter_universe"] = []
    t1 = datetime(2026, 10, 7, 16, 5, tzinfo=ET)
    mem.remember(live, now=t1)
    t2 = datetime(2026, 10, 7, 16, 10, tzinfo=ET)
    mem.remember(live, now=t2)
    rows = mem.load_session("2026-10-07")
    assert len(rows) == 2
    assert rows[1].get("gate_off") is True


def test_same_book_keeps_once_a_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    ss = _SS(
        room3_engine_armed=True,
        room3_allowed_sessions=["rth"],
        room3_filter_universe=["BIYA"],
        room3_tradable_today=1000,
        room3_watch_book={
            "lines": {
                "BIYA:1m": {
                    "ticker": "BIYA",
                    "timeframe": "1m",
                    "match_pct": 90,
                    "nearest_strategy": "2B (1M)",
                    "state": "watching",
                    "size_usd": 50,
                }
            }
        },
        room3_trade_history=[],
        room3_open_positions=[],
    )
    t0 = datetime(2026, 10, 7, 10, 10, tzinfo=ET)
    mem.remember(ss, now=t0)
    mem.remember(ss, now=datetime(2026, 10, 7, 10, 10, 20, tzinfo=ET))
    mem.remember(ss, now=datetime(2026, 10, 7, 10, 11, 5, tzinfo=ET))
    rows = mem.load_session("2026-10-07")
    assert len(rows) == 2
    assert rows[0]["lines"][0]["match"] == 90


def test_unticked_window_is_a_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEM_DIR", tmp_path)
    ss = _SS(
        room3_engine_armed=True,
        room3_allowed_sessions=["premarket", "postmarket"],
        room3_filter_universe=["JZ"],
        room3_tradable_today=1000,
        room3_watch_book={"lines": {}},
        room3_trade_history=[],
        room3_open_positions=[],
    )
    off = _SS(
        room3_engine_armed=True,
        room3_allowed_sessions=["rth"],
        room3_filter_universe=["JZ"],
        room3_tradable_today=1000,
        room3_watch_book={"lines": {}},
        room3_trade_history=[],
        room3_open_positions=[],
    )
    assert mem.remember(off, now=datetime(2026, 10, 7, 8, 15, tzinfo=ET)) is None
    mem.remember(ss, now=datetime(2026, 10, 8, 8, 0, tzinfo=ET))
    mem.remember(ss, now=datetime(2026, 10, 8, 11, 0, tzinfo=ET))
    mem.remember(ss, now=datetime(2026, 10, 8, 11, 30, tzinfo=ET))
    mem.remember(ss, now=datetime(2026, 10, 8, 16, 5, tzinfo=ET))
    rows = mem.load_session("2026-10-08")
    assert [r["ts"][:5] for r in rows] == ["08:00", "11:00", "16:05"]
    assert rows[1].get("gate_off") is True
    assert rows[2].get("gate_off") is not True
