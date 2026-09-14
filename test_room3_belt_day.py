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
