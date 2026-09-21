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


def test_size_impact_compresses_vs_naive():
    bars = _climax_day()
    naive = wf.replay_session(SESS, {"FAMI": bars}, book=1_000_000.0, letters=("5B",))
    sized = wf.replay_session(
        SESS,
        {"FAMI": bars},
        book=1_000_000.0,
        letters=("5B",),
        part_frac=0.10,
        impact_k=0.10,
        impact_cap=0.03,
    )
    assert naive["fills"] == 1
    assert sized["fills"] == 1
    assert sized["pnl_pct"] < naive["pnl_pct"]
    assert sized["trades"][0]["qty"] < naive["trades"][0]["qty"]


def test_iceberg_clips_across_bars():
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
    for i in range(1, 25):
        t = hold_t + timedelta(minutes=i)
        bars.append(_bar(t, hold_c, hold_c + 0.02, hold_c - 0.01, hold_c + 0.01, v=80))
    row = wf.replay_session(
        SESS,
        {"FAMI": bars},
        book=50_000.0,
        letters=("5B",),
        iceberg_frac=0.02,
        impact_k=0.10,
    )
    assert row["fills"] == 1
    trade = row["trades"][0]
    assert int(trade.get("iceberg_clips") or 0) >= 3
    assert float(trade["qty"]) > 1


def test_loud_stretch_skips_quiet_5b():
    quiet = wf.replay_session(
        SESS, {"FAMI": _climax_day()}, book=1000.0, letters=("5B",), loud_pct=90.0
    )
    assert quiet["fills"] == 0
    bars = []
    px = 3.05
    for i in range(20):
        t = _ts(9, 45) + timedelta(minutes=i)
        bars.append(_bar(t, px, px + 0.01, px - 0.01, px, v=20))
    dump_t = _ts(10, 5)
    hold_t = _ts(10, 6)
    bars.append(_bar(dump_t, 3.02, 3.025, 2.84, 2.9215, v=800))
    hold_c = 2.9409
    bars.append(_bar(hold_t, 2.93, 2.95, 2.92, hold_c, v=8000))
    tgt = hold_c * (1.0 + 0.165)
    bars.append(_bar(hold_t + timedelta(minutes=1), hold_c, tgt + 0.01, hold_c, tgt + 0.005, v=90))
    loud = wf.replay_session(
        SESS, {"FAMI": bars}, book=1000.0, letters=("5B",), loud_pct=90.0
    )
    assert loud["fills"] == 1
    assert loud["trades"][0]["exit_reason"] == "target"


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


def test_15m_sim_hard_clip_20_live_stays_12():
    bars = [{"o": 1.0, "h": 1.01, "l": 0.99, "c": 1.0, "v": 100.0}] * 4
    stop, tgt, _frac = wf.fifteen_m_pack_exits(bars, 1.00, structural_move_pct=40.0)
    assert abs(tgt - 1.20) < 1e-6
    assert abs(wf.SIM_15M_TARGET_FRAC - 0.20) < 1e-9
    assert abs(m.PH_15M_TARGET_FRAC - 0.12) < 1e-9
    live_lot = {
        "strategy": "1D (15M)",
        "tf": "15m",
        "exit_style": m.PH_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.98,
        "exit_tgt_px": 1.12,
    }
    still = m._lot_should_exit(
        live_lot,
        cur_match=90,
        last_px=1.08,
        patience=True,
        bar={"h": 1.10, "l": 1.05, "c": 1.08},
    )
    assert still == ""
    why = m._lot_should_exit(
        live_lot,
        cur_match=90,
        last_px=1.13,
        patience=True,
        bar={"h": 1.13, "l": 1.10, "c": 1.13},
    )
    assert why.startswith("target")
    sim_lot = {
        "strategy": "1D (15M)",
        "tf": "15m",
        "exit_style": m.PH_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": 0.98,
        "exit_tgt_px": tgt,
    }
    miss, _px = wf._lot_exit(sim_lot, {"h": 1.13, "l": 1.10, "c": 1.13}, 1.13)
    assert miss == ""
    hit, px = wf._lot_exit(sim_lot, {"h": 1.21, "l": 1.18, "c": 1.20}, 1.20)
    assert hit == "target"
    assert abs(px - 1.20) < 1e-6


def test_5m_sim_15_hard_clip_no_trail():
    bars = [{"o": 1.0, "h": 1.02, "l": 0.98, "c": 1.0, "v": 100.0}] * 4
    stop, tgt, _frac = wf.five_m_pack_exits(bars, 1.00, "1A")
    assert abs(tgt - 1.15) < 1e-6
    lot = {
        "exit_style": wf.SIM_5M_EXIT_STYLE,
        "entry_px": 1.00,
        "exit_stop_px": stop,
        "exit_tgt_px": tgt,
        "tf": "5m",
    }
    hit, px = wf._lot_exit(lot, {"h": 1.16, "l": 1.14, "c": 1.15}, 1.15)
    assert hit == "target"
    assert abs(px - 1.15) < 1e-9
    still, _ = wf._lot_exit(
        {**lot, "exit_tgt_px": 1.50},
        {"h": 1.16, "l": 1.06, "c": 1.07},
        1.07,
    )
    assert still == ""


def test_sim_1a_trip_does_not_trail():
    lot = {
        "exit_style": m.ONE_A_EXIT_TRIP,
        "entry_px": 1.00,
        "exit_stop_px": 0.965,
        "exit_tgt_px": 0.0,
        "tf": "1m",
    }
    why, _px = wf._lot_exit(lot, {"h": 1.20, "l": 1.10, "c": 1.18}, 1.18)
    assert why == ""
    why, _px = wf._lot_exit(lot, {"h": 1.18, "l": 1.05, "c": 1.06}, 1.06)
    assert why == ""
