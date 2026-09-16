"""Belt × chips must die with the 4 AM ET trading-day roll, like the white maps."""

import room3_trading as t


def test_friday_belt_snap_is_stale_on_monday():
    assert t.belt_snapshot_is_stale(
        {"filter_universe_day_key": "2026-09-11", "filter_universe": ["FTFT", "TNON"]},
        "2026-09-14",
    )
    assert t.belt_snapshot_is_stale(
        {"tradable_day_key": "2026-09-11", "filter_universe": ["TRUG"]},
        "2026-09-14",
    )


def test_pre_fix_snap_with_chips_is_stale():
    assert t.belt_snapshot_is_stale(
        {"tradable_day_key": "2026-09-14", "filter_universe": ["FTFT"]},
        "2026-09-14",
    )
    assert t.belt_snapshot_is_stale(
        {"filter_universe": ["TNON"]},
        "2026-09-14",
    )


def test_same_day_belt_snap_is_not_stale():
    assert t.belt_snapshot_is_stale(
        {"filter_universe_day_key": "2026-09-14", "filter_universe": ["FTFT"]},
        "2026-09-14",
    ) is False


def test_empty_belt_snap_is_not_stale():
    assert t.belt_snapshot_is_stale({}, "2026-09-14") is False
    assert t.belt_snapshot_is_stale({"filter_universe": []}, "2026-09-14") is False


def test_maps_without_chips_are_stale():
    assert t.belt_snapshot_is_stale(
        {"watch_book": {"lines": {"FTFT:1m": {"ticker": "FTFT"}}}},
        "2026-09-14",
    )


def test_empty_belt_drops_white_rows():
    import room3_watcher as w

    book = w.set_filter_universe(w.empty_book(), ["FTFT", "TNON"])
    assert "FTFT:1m" in book["lines"]
    book["lines"]["FTFT:1m"]["state"] = "in"
    cleared = w.set_filter_universe(book, [])
    assert cleared["lines"] == {}
    assert cleared["universe"] == []


def test_leftover_open_keeps_maps_off_belt():
    import room3_watcher as w

    book = w.set_filter_universe(w.empty_book(), ["FTFT"])
    book["keep_tickers"] = ["FTFT"]
    leftover = w.set_filter_universe(book, [])
    assert leftover["universe"] == []
    assert "FTFT:1m" in leftover["lines"]
    assert leftover["lines"]["FTFT:1m"]["in_filter"] is False


def test_watch_book_for_disk_drops_slices():
    import room3_watcher as w

    book = w.set_filter_universe(w.empty_book(), ["FTFT"])
    book["lines"]["FTFT:1m"]["slices"] = [{"c": 1}, {"c": 2}]
    book["_overlay_cache"] = {"FTFT": {"t": 1}}
    slim = w.watch_book_for_disk(book)
    assert "slices" not in slim["lines"]["FTFT:1m"]
    assert "_overlay_cache" not in slim
    assert slim["lines"]["FTFT:1m"]["ticker"] == "FTFT"


def test_dash_close_is_not_reviewable():
    assert t._row_has_frozen_identity(
        {"ticker": "PDSB", "timeframe": "—", "strategy": "Alpaca"}
    ) is False


def test_named_close_is_reviewable():
    assert t._row_has_frozen_identity(
        {
            "ticker": "ADBT",
            "timeframe": "5m",
            "strategy": "8B (5M)",
            "matrix_timeframe": "5m",
            "matrix_strategy": "8B (5M)",
        }
    ) is True
