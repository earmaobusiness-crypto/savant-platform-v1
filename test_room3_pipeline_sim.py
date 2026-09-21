"""Pre-paper sim: 168h centroid → MAD match → live gates (size, Arm, belt, TF, Handle)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import room3_bridge as b
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


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fresh_ts() -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=3))


def _stale_ts() -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=169))


def _ss(*, tradable: float, hour: int = 12, minute: int = 0) -> _SS:
    return _SS(
        _now_et=datetime(2026, 9, 17, hour, minute, tzinfo=ET),
        room3_tradable_today=float(tradable),
        room3_cash_claimed=0.0,
        room3_open_positions=[],
        room3_lots=[],
        room3_filter_universe=["SIMX"],
    )


def _bar(o, h, l, c, v=100.0, ret=0.0):
    return {"o": o, "h": h, "l": l, "c": c, "v": v, "ret": ret}


def _1m_slices():
    return [
        _bar(10.0, 10.2, 9.9, 10.0, v=100, ret=0.0),
        _bar(10.0, 10.5, 10.0, 10.4, v=120, ret=0.04),
        _bar(10.4, 10.6, 10.3, 10.5, v=110, ret=0.0096),
        _bar(10.5, 10.7, 10.4, 11.0, v=130, ret=0.0476),
        _bar(11.0, 11.2, 10.9, 11.0, v=90, ret=0.0),
        _bar(11.0, 11.3, 10.95, 11.1, v=95, ret=0.009),
        _bar(11.1, 11.4, 11.0, 11.2, v=100, ret=0.009),
        _bar(11.2, 11.5, 11.1, 11.3, v=105, ret=0.009),
    ]


def _5m_slices():
    return [
        _bar(2.0, 2.02, 1.99, 2.0, v=100),
        _bar(2.0, 2.03, 1.995, 2.01, v=110),
        _bar(2.01, 2.04, 2.0, 2.02, v=90),
        _bar(2.02, 2.05, 2.01, 2.03, v=95),
    ]


def _vault_row(*, strategy: str, tf: str, vector: list[float], ts: str, layout_id: str = "6"):
    return {
        "macro_weather_layout": layout_id,
        "execution_strategy": strategy,
        "timeframe_resolution": tf,
        "master_signature_json": {"master_signature": list(vector)},
        "timestamp": ts,
        "structural_move_pct": 10.0,
        "ticker": "SIMX",
    }


def _library_from_live(line: dict, *, strategy: str, tf: str, ts: str) -> list[dict]:
    vec = m.build_live_feature_vector(line)
    assert vec is not None
    twin = list(vec)
    twin[0] = round(float(twin[0]) + 0.8, 4)
    return b._aggregate_rows_into_layouts(
        [
            _vault_row(strategy=strategy, tf=tf, vector=vec, ts=ts),
            _vault_row(strategy=strategy, tf=tf, vector=twin, ts=ts, layout_id="7"),
        ]
    )


def _book(ticker: str = "SIMX", tf: str = "1m", slices=None) -> tuple[dict, dict]:
    book = w.empty_book()
    book["universe"] = [ticker]
    w.ensure_ticker_maps(book, ticker)
    line = book["lines"][w.line_key(ticker, tf)]
    line["in_filter"] = True
    line["state"] = "watching"
    line["slices"] = list(slices if slices is not None else _1m_slices())
    line["ticker"] = ticker
    line["timeframe"] = tf
    return book, line


def _run(line, layouts, ss, book, *, armed: bool = True, entries: bool = True):
    rep = {"layouts": layouts, "ready": True}
    with patch.object(m, "_approaching_day_close", return_value=False):
        m.maybe_queue_matrix_signals(
            book,
            line,
            rep,
            ss,
            engine_armed=armed,
            entries_allowed=entries,
        )
    return line


def test_stale_vault_starves_match_and_does_not_queue():
    book, line = _book()
    vec = m.build_live_feature_vector(line)
    layouts = b._aggregate_rows_into_layouts(
        [_vault_row(strategy="6A (1M)", tf="1m", vector=list(vec), ts=_stale_ts())]
    )
    assert layouts == []
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) == 0
    assert not line.get("entry_signal")
    assert float(line.get("size_usd") or 0) == 0


def test_in_window_1m_fill_now_queues_when_sized():
    book, line = _book()
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    assert layouts
    assert int(layouts[0]["window_hours"]) == 168
    assert int(layouts[0]["pattern_count"]) >= 1
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) >= 85
    assert line.get("nearest_strategy") == "6A (1M)"
    sig = line.get("entry_signal") or {}
    assert sig.get("side") == "buy"
    assert "enter now" in str(sig.get("trigger") or "")
    assert float(line.get("size_usd") or 0) > 0


def test_trading_today_zero_blocks_ticket():
    book, line = _book()
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    ss = _ss(tradable=0)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) >= 85
    assert float(line.get("size_usd") or 0) == 0
    assert not line.get("entry_signal")


def test_disarmed_does_not_queue():
    book, line = _book()
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book, armed=False)
    assert int(line.get("match_pct") or 0) >= 85
    assert not line.get("entry_signal")


def test_purgatory_never_in_library_or_match():
    book, line = _book()
    vec = m.build_live_feature_vector(line)
    layouts = b._aggregate_rows_into_layouts(
        [
            _vault_row(
                strategy="P1 (1M)",
                tf="1m",
                vector=list(vec),
                ts=_fresh_ts(),
                layout_id="Purgatory",
            )
        ]
    )
    assert layouts == []
    hit = m.match_spatial(list(vec), layouts, watch_timeframe="1m")
    assert int(hit["spatial_match_pct"]) == 0
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert not line.get("entry_signal")


def test_1m_open_chop_blocks_fill_now():
    book, line = _book()
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    ss = _ss(tradable=1000, hour=9, minute=35)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) >= 85
    assert not line.get("entry_signal")


def test_5m_still_dip_hold_not_fill_now():
    book, line = _book(tf="5m", slices=_5m_slices())
    layouts = _library_from_live(line, strategy="3B (5M)", tf="5m", ts=_fresh_ts())
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) >= 85
    assert not line.get("entry_signal")
    kids = [c for c in (line.get("children") or []) if isinstance(c, dict)]
    notes = " ".join(str(c.get("patience_note") or "") for c in kids)
    assert "pullback" in notes or "hold" in notes or "waiting" in notes.lower()


def test_off_belt_does_not_queue_entry():
    book, line = _book()
    line["in_filter"] = False
    book["universe"] = ["OTHER"]
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert not line.get("entry_signal")


def test_same_tf_only_15m_dna_does_not_fire_1m():
    book, line = _book()
    vec = m.build_live_feature_vector(line)
    layouts = b._aggregate_rows_into_layouts(
        [
            _vault_row(strategy="1D (15M)", tf="15m", vector=list(vec), ts=_fresh_ts(), layout_id="1"),
            _vault_row(
                strategy="1D (15M)",
                tf="15m",
                vector=[round(x + 0.5, 4) for x in vec],
                ts=_fresh_ts(),
                layout_id="2",
            ),
        ]
    )
    ss = _ss(tradable=1000)
    _run(line, layouts, ss, book)
    assert int(line.get("match_pct") or 0) == 0
    assert not line.get("entry_signal")


def test_handle_stamp_does_not_mutate_centroid_vector():
    book, line = _book()
    vec = m.build_live_feature_vector(line)
    raw = list(vec)
    layouts = b._aggregate_rows_into_layouts(
        [
            _vault_row(strategy="5B (1M)", tf="1m", vector=raw, ts=_fresh_ts()),
            _vault_row(
                strategy="5B (1M)",
                tf="1m",
                vector=[round(x + 0.4, 4) for x in raw],
                ts=_fresh_ts(),
                layout_id="7",
            ),
        ]
    )
    by_id = {str(e.get("layout_id")): e for e in layouts}
    assert by_id["6"]["vector"][:8] == raw[:8]
    handle = by_id["6"].get("handle_execution") or {}
    assert handle.get("vault_dna_mutated") is False
    assert handle.get("entry") == "fill_now"


def test_approaching_close_blocks_new_entry_when_already_in():
    book, line = _book()
    line["state"] = "in"
    layouts = _library_from_live(line, strategy="6A (1M)", tf="1m", ts=_fresh_ts())
    ss = _ss(tradable=1000)
    rep = {"layouts": layouts, "ready": True}
    with patch.object(m, "_approaching_day_close", return_value=True):
        m.maybe_queue_matrix_signals(
            book, line, rep, ss, engine_armed=True, entries_allowed=True
        )
    assert int(line.get("match_pct") or 0) >= 85
    assert not line.get("entry_signal")
