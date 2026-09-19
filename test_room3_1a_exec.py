"""1A (1M) fluid Handle: mild 8% / violent 12% / trip runner."""

from datetime import datetime
from zoneinfo import ZoneInfo

import room3_engine
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


def _chain(n, start=1.0, ret=0.01, vol=40, last_rng=0.035, last_vol=2000):
    rows = []
    px = start
    for _ in range(n - 1):
        nxt = round(px * (1.0 + ret), 6)
        hi = max(px, nxt) * 1.001
        lo = min(px, nxt) * 0.999
        rows.append(_bar(px, hi, lo, nxt, vol))
        px = nxt
    hi = px * (1.0 + last_rng * 0.65)
    lo = px * (1.0 - last_rng * 0.35)
    c = px * (1.0 + last_rng * 0.45)
    rows.append(_bar(px, hi, lo, c, last_vol))
    return rows, float(c)


def _wallpaper():
    return _chain(20, ret=0.001, last_rng=0.004, last_vol=80, vol=80)


def _mild_slices():
    # 15 quiet + 5 fast ≈ vel5 ≥8, vel20 < 20, fat green, RVOL.
    quiet, px = _chain(15, ret=0.001, last_rng=0.004, last_vol=40, vol=40)
    tail, last = _chain(5, start=px, ret=0.022, last_rng=0.04, last_vol=2000, vol=40)
    return quiet[:-1] + tail, last


def _violent_slices():
    # ~22% / 20 bars, last range ~3.5% — violent, not trip.
    return _chain(20, ret=0.011, last_rng=0.036, last_vol=2000)


def _trip_slices():
    return _chain(20, ret=0.0135, last_rng=0.06, last_vol=2000)


def _ready(ss, slices, px, line=None):
    return m._entry_trigger_ready(
        line if line is not None else {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="1m",
        strategy="1A (1M)",
        layout_id="1",
        structural=31.0,
        session_state=ss,
    )


def test_1a_classifies_three_handles():
    mild, _ = _mild_slices()
    violent, _ = _violent_slices()
    trip, _ = _trip_slices()
    wall, _ = _wallpaper()
    assert m._1a_classify(mild) == "mild"
    assert m._1a_classify(violent) == "violent"
    assert m._1a_classify(trip) == "trip"
    assert m._1a_classify(wall) == ""


def test_1a_skips_wallpaper():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _wallpaper()
    ready, note = _ready(ss, slices, px)
    assert ready is True
    assert "enter now" in note


def test_1a_skips_open_chop():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _violent_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is False
    assert "9:30" in note


def test_1a_trip_and_mild_wait_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    trip, tpx = _trip_slices()
    ready, note = _ready(ss, trip, tpx)
    assert ready is True
    assert "enter now" in note
    mild, mpx = _mild_slices()
    ready, note = _ready(ss, mild, mpx, line={"ticker": "FAMI"})
    assert ready is True
    assert "enter now" in note


def test_1a_violent_may_arm_after_945():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _violent_slices()
    line = {"ticker": "BIAF"}
    ready, note = _ready(ss, slices, px, line=line)
    assert ready is True
    assert line.get("1a_handle") == "violent"
    assert "enter now" in note


def test_1a_first_of_day():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    ss.room3_1a_used_day = {"BIAF": "2026-09-11"}
    slices, px = _violent_slices()
    ready, note = _ready(ss, slices, px)
    assert ready is False
    assert "first of day" in note


def test_1a_violent_target_12():
    lot = {
        "strategy": "1A (1M)",
        "tf": "1m",
        "exit_style": m.ONE_A_EXIT_VIOLENT,
        "entry_px": 1.00,
        "exit_stop_px": 0.90,
        "exit_tgt_px": 1.12,
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    assert (
        m._lot_should_exit(
            lot, cur_match=90, last_px=1.06, patience=True, bar={"h": 1.07, "l": 1.04, "c": 1.06}, session_state=ss
        )
        == ""
    )
    why = m._lot_should_exit(
        lot, cur_match=90, last_px=1.13, patience=True, bar={"h": 1.13, "l": 1.10, "c": 1.13}, session_state=ss
    )
    assert why.startswith("target")


def test_1a_mild_target_8():
    lot = {
        "strategy": "1A (1M)",
        "tf": "1m",
        "exit_style": m.ONE_A_EXIT_MILD,
        "entry_px": 1.00,
        "exit_stop_px": 0.90,
        "exit_tgt_px": 1.08,
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    why = m._lot_should_exit(
        lot, cur_match=90, last_px=1.09, patience=True, bar={"h": 1.09, "l": 1.05, "c": 1.09}, session_state=ss
    )
    assert why.startswith("target")


def test_1a_trip_runs_past_12_then_trails():
    lot = {
        "strategy": "1A (1M)",
        "tf": "1m",
        "exit_style": m.ONE_A_EXIT_TRIP,
        "entry_px": 1.00,
        "exit_stop_px": 0.90,
        "exit_tgt_px": 0.0,
    }
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 20, tzinfo=ET))
    still = m._lot_should_exit(
        lot, cur_match=90, last_px=1.13, patience=True, bar={"h": 1.14, "l": 1.10, "c": 1.13}, session_state=ss
    )
    assert still == ""
    assert lot.get("exit_runner_on") is True
    hold = m._lot_should_exit(
        lot, cur_match=90, last_px=1.04, patience=True, bar={"h": 1.14, "l": 1.04, "c": 1.04}, session_state=ss
    )
    assert hold == ""  # 12% trail off 1.14 is 1.0032
    why = m._lot_should_exit(
        lot, cur_match=90, last_px=0.99, patience=True, bar={"h": 1.14, "l": 0.99, "c": 0.99}, session_state=ss
    )
    assert why.startswith("runner")


def test_append_lot_stamps_1a_trip_no_hard_target():
    ss = _SS()
    ss.room3_lots = []
    row = room3_engine.lots.append_lot(
        ss,
        {
            "ticker": "FTFT",
            "tf": "1m",
            "strategy": "1A (1M)",
            "qty": 10,
            "entry_px": 1.00,
            "exit_style": m.ONE_A_EXIT_TRIP,
            "exit_r_frac": 0.02,
            "exit_stop_px": 0.90,
            "exit_tgt_px": 0,
            "1a_handle": "trip",
        },
    )
    assert row["exit_style"] == m.ONE_A_EXIT_TRIP
    assert float(row.get("exit_tgt_px") or 0) == 0.0
    assert ss.room3_1a_used_day["FTFT"]
    assert row.get("1a_handle") == "trip"
