"""Walk-forward folds + 5B fill-now replay on synthetic 1m bars."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import room3_matrix as m
import room3_walkforward as wf

ET = ZoneInfo("America/New_York")
SESS = date(2026, 9, 11)


def _ts(hour, minute, sess=SESS):
    return datetime(sess.year, sess.month, sess.day, hour, minute, tzinfo=ET)


def _bar(ts, o, h, l, c, v=100.0):
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c, "v": v}


def _climax_day():
    """Quiet open, 5B dump+hold after 9:45, then tag the 16.5% target."""
    bars = []
    px = 3.05
    for i in range(5):
        t = _ts(9, 45) + timedelta(minutes=i)
        bars.append(_bar(t, px, px + 0.01, px - 0.01, px, v=50))
    dump_t = _ts(9, 50)
    hold_t = _ts(9, 51)
    bars.append(_bar(dump_t, 3.02, 3.025, 2.84, 2.9215, v=800))
    hold_c = 2.9409
    bars.append(_bar(hold_t, 2.93, 2.95, 2.92, hold_c, v=80))
    tgt = hold_c * (1.0 + 0.165)
    t = hold_t + timedelta(minutes=1)
    bars.append(_bar(t, hold_c, tgt + 0.01, hold_c, tgt + 0.005, v=90))
    return bars


def test_rolling_folds_train5_test1_step1():
    days = wf.weekday_sessions()
    assert date(2026, 9, 7) not in days
    assert days[0] == date(2026, 9, 2)
    assert days[-1] == date(2026, 9, 11)
    assert len(days) == 7
    folds = wf.rolling_folds(days)
    assert len(folds) == 2
    assert folds[0]["train"] == days[:5]
    assert folds[0]["test"] == [date(2026, 9, 10)]
    assert folds[1]["test"] == [date(2026, 9, 11)]


def test_5b_fill_now_hits_target_on_1000_book():
    bars = _climax_day()
    row = wf.replay_session(SESS, {"FAMI": bars}, book=1000.0, letters=("5B",))
    assert row["fills"] == 1
    trade = row["trades"][0]
    assert trade["letter"] == "5B"
    assert trade["exit_reason"] == "target"
    assert float(trade["pnl_usd"]) > 0
    assert row["win_rate"] == 1.0
    assert trade["qty"] * trade["entry_px"] <= 800.0 + 1e-6


def test_5b_skips_open_chop():
    dump = _bar(_ts(9, 31), 3.02, 3.025, 2.84, 2.9215, v=800)
    hold = _bar(_ts(9, 32), 2.93, 2.95, 2.92, 2.9409, v=80)
    quiet = [_bar(_ts(9, 30), 3.05, 3.06, 3.04, 3.05, v=50)]
    row = wf.replay_session(
        SESS, {"FAMI": quiet + [dump, hold]}, book=1000.0, letters=("5B",)
    )
    assert row["fills"] == 0


def test_walk_forward_oos_uses_test_days_only():
    bars = _climax_day()

    def load(ticker, sess):
        return bars if ticker == "FAMI" else []

    blob = wf.walk_forward(
        book=1000.0,
        letters=("5B",),
        load_bars=load,
        sessions=wf.weekday_sessions(),
    )
    assert len(blob["folds"]) == 2
    oos_dates = [d for fold in blob["folds"] for d in fold["test_dates"]]
    assert oos_dates == ["2026-09-10", "2026-09-11"]
    assert blob["oos"]["fills"] == 2
    assert blob["oos"]["wins"] == 2
    assert blob["oos"]["win_rate"] == 1.0
    line = blob["folds"][0]["test"]["line"]
    assert "win rate" in line
    assert "$1,000" in line


def test_15m_sim_target_locked_at_12():
    bars = [{"o": 1.0, "h": 1.01, "l": 0.99, "c": 1.0, "v": 100.0}] * 4
    stop, tgt, _frac = wf.fifteen_m_pack_exits(bars, 1.00, structural_move_pct=40.0)
    assert abs(tgt - 1.12) < 1e-6
    assert abs(m.PH_15M_TARGET_FRAC - 0.12) < 1e-9
    lot = {
        "strategy": "1D (15M)",
        "tf": "15m",
        "exit_style": m.PH_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.98,
        "exit_tgt_px": tgt,
    }
    still = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.08,
        patience=True,
        bar={"h": 1.10, "l": 1.05, "c": 1.08},
    )
    assert still == ""
    why = m._lot_should_exit(
        lot,
        cur_match=90,
        last_px=1.13,
        patience=True,
        bar={"h": 1.13, "l": 1.10, "c": 1.13},
    )
    assert why.startswith("target")
