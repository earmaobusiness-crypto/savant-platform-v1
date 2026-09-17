"""2D (1M) Hunt extra + fill-now / 6.25% pack exit."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import room3_engine
import room3_matrix as m
import room3_recipes

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


def _hot_slices():
    """RVOL ≥3, last bar green, range ≥3%."""
    rows = []
    px = 1.00
    for _ in range(12):
        nxt = round(px * 1.004, 6)
        rows.append(_bar(px, nxt, px * 0.999, nxt, v=40))
        px = nxt
    last = _bar(px, px * 1.03, px * 0.99, px * 1.02, v=2000)
    rows.append(last)
    return rows, float(last["c"])


def _wallpaper():
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 12
    return quiet, 1.001


def _ready(ss, slices, px, *, match=92, line=None):
    row = {"ticker": "SPWR", "match_pct": match}
    if line:
        row.update(line)
        row.setdefault("match_pct", match)
    return m._entry_trigger_ready(
        row,
        slices,
        last_px=px,
        tf="1m",
        strategy="2D (1M)",
        layout_id="2",
        structural=18.0,
        session_state=ss,
    )


def test_2d_skips_wallpaper():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _wallpaper()
    ready, note = _ready(ss, slices, px)
    assert ready is True
    assert "enter now" in note


def test_2d_skips_open_chop():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is False
    assert "9:30" in note


def test_2d_skips_match_under_91():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px, match=88)
    assert ready is True
    assert "enter now" in note


def test_2d_fills_now_when_hunt_ok():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px, match=92)
    assert ready is True
    assert "enter now" in note


def test_2d_second_shot_after_stop_cool():
    now = datetime(2026, 9, 11, 12, 0, tzinfo=ET)
    ss = _SS(_now_et=now)
    m._2d_mark_shot(ss, "SPWR")
    ss.room3_2d_cool_until = {"SPWR": (now - timedelta(seconds=30)).isoformat()}
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is True
    assert "enter now" in note


def test_2d_no_second_after_target():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    m._2d_mark_shot(ss, "SPWR")
    m._2d_mark_used(ss, "SPWR")
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is False
    assert "done" in note or "first" in note or "two" in note


def test_2d_no_third_shot():
    ss = _SS(_now_et=datetime(2026, 9, 11, 13, 0, tzinfo=ET))
    m._2d_mark_shot(ss, "SPWR")
    m._2d_mark_shot(ss, "SPWR")
    slices, px = _hot_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is False
    assert "done" in note or "two" in note


def test_2d_pack_target_625():
    lot = {
        "strategy": "2D (1M)",
        "tf": "1m",
        "letter": "2D (1M)",
        "exit_style": m.TWO_D_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.90,
        "exit_tgt_px": 1.0625,
        "entry_ts": "2026-09-11T12:00:00-04:00",
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot,
        cur_match=92,
        last_px=1.04,
        patience=True,
        bar={"h": 1.05, "l": 1.03, "c": 1.04},
        session_state=ss,
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=92,
        last_px=1.07,
        patience=True,
        bar={"h": 1.07, "l": 1.04, "c": 1.07},
        session_state=ss,
    )
    assert why.startswith("target")


def test_append_lot_stamps_2d_pack_exit_without_using_day():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "SPWR",
            "tf": "1m",
            "strategy": "2D (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "structural_move_pct": 18.0,
            "exit_style": m.TWO_D_EXIT_STYLE,
            "exit_r_frac": 0.02,
            "exit_stop_px": 0.90,
            "exit_tgt_px": 1.0625,
        },
    )
    assert row["exit_style"] == m.TWO_D_EXIT_STYLE
    assert abs(float(row["exit_tgt_px"]) - 1.0625) < 1e-6
    assert not (ss.get("room3_2d_used_day") or {}).get("SPWR")


def test_2d_order_style_is_market_in_rth():
    assert room3_recipes.order_style_for("2D (1M)", "1m", structural_move_pct=18.0) == "market"
