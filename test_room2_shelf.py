"""Dated S1 dump: current shelf fires as S1; Purgatory-named rows still do not."""

from __future__ import annotations

from datetime import date

import room2_shelf as shelf
import room3_bridge as br
import room3_matrix as m
import room3_recipes as r


def test_s1_release_is_tradeable_and_not_purgatory():
    extra = shelf.layouts_as_of(date(2026, 10, 6))
    assert extra
    assert all(str(e.get("strategy") or "").startswith("S1") for e in extra)
    assert all(e.get("tradeable") for e in extra)
    assert all(
        not r.is_purgatory_letter(str(e.get("layout_id") or ""), str(e.get("strategy") or ""))
        for e in extra
    )


def test_s1_release_is_as_of():
    before = shelf.layouts_as_of(date(2026, 7, 28))
    assert before == []
    jtai = shelf.layouts_as_of(date(2026, 7, 29))
    assert jtai
    assert all(str(e.get("strategy") or "").startswith("S1") for e in jtai)
    assert len(jtai) < len(shelf.layouts_as_of(date(2026, 10, 6)))


def test_s1_matches_own_vector():
    extra = shelf.layouts_as_of(date(2026, 10, 6))
    one = next(e for e in extra if str(e.get("strategy")) == "S1 (1M)")
    hit = m.match_spatial(list(one["vector"]), extra, watch_timeframe="1m")
    assert int(hit.get("spatial_match_pct") or 0) >= 85
    assert str(hit.get("nearest_strategy") or "").startswith("S1")


def test_purgatory_named_still_dropped():
    row = br._layout_entry(
        layout_id="Purgatory",
        vector=[0.1] * 8,
        timeframe_resolution="1m",
        strategy="P1 (1M)",
        pattern_count=3,
        source="test",
    )
    assert row is None
