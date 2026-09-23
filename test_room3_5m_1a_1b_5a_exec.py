"""1A / 1B / 5A (5M) first-lock Handle. Fill now. No 3.5 stop cap."""

from datetime import datetime
from zoneinfo import ZoneInfo

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


def _1a_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.03, 6)
        rows.append(_bar(c, nxt * 1.01, c * 0.999, nxt, v=80))
        c = nxt
    h = c * 1.04
    lo = c * 0.985
    close = c * 1.02
    rows.append(_bar(c, h, lo, close, v=90))
    return rows, float(close)


def _1b_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.015, 6)
        rows.append(_bar(c, nxt * 1.005, c * 0.999, nxt, v=70))
        c = nxt
    h = c * 1.03
    lo = c * 0.985
    close = c * 1.01
    rows.append(_bar(c, h, lo, close, v=75))
    return rows, float(close)


def _5a_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=220)] * 5
    rows.append(_bar(1.10, 1.10, 1.085, 1.088, v=60))
    rows.append(_bar(1.088, 1.089, 1.075, 1.078, v=55))
    rows.append(_bar(1.078, 1.079, 1.068, 1.070, v=50))
    last = _bar(1.070, 1.098, 1.068, 1.074, v=50)
    rows.append(last)
    return rows, float(last["c"])


def test_1a_5m_gene_not_1b():
    slices, _px = _1a_slices()
    assert m._1a_5m_gene_ok(slices) is True
    assert m._1b_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._1a_5m_gene_ok(quiet) is False


def test_1b_5m_gene_not_1a():
    slices, _px = _1b_slices()
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is True


def test_5a_5m_gene_under_vwap_dump():
    slices, _px = _5a_slices()
    assert m._5a_5m_gene_ok(slices) is True
    assert m._6a_5m_gene_ok(slices) is False
    assert m._5b_5m_gene_ok(slices) is False
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is False


def test_1a_5m_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _1a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=float(slices[-1]["l"] or px),
        tf="5m",
        strategy="1A (5M)",
        layout_id="1",
        structural=50.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_1a_5m_wallpaper_waits():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 8
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        quiet,
        last_px=1.001,
        tf="5m",
        strategy="1A (5M)",
        layout_id="1",
        structural=50.0,
        session_state=ss,
    )
    assert ready is False
    assert "suited" in note or "wait" in note


def test_1a_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _1a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="1A (5M)",
        layout_id="1",
        structural=50.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_5a_5m_skips_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _5a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="5A (5M)",
        layout_id="5",
        structural=41.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_1b_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _1b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="5m",
        strategy="1B (5M)",
        layout_id="1",
        structural=50.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_5m_pack_targets_and_no_cap():
    slices, px = _1a_slices()
    _stop, tgt, _frac = m._1a_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.16) < 1e-9
    b_slices, b_px = _1b_slices()
    _sb, tgt_b, _fb = m._1b_5m_pack_exits(b_slices, b_px)
    assert abs(tgt_b / b_px - 1.08) < 1e-9
    s5, px5 = _5a_slices()
    _s5, tgt_5, frac_5 = m._5a_5m_pack_exits(s5, px5)
    assert abs(tgt_5 / px5 - 1.065) < 1e-9
    assert frac_5 >= 0.035 - 1e-9
    deep_stop, _t, _fr = m._1a_5m_pack_exits(
        [_bar(1.0, 1.0, 0.90, 1.0)] * 4, 1.0
    )
    assert deep_stop <= 0.90 + 1e-9


def test_1a_1m_does_not_steal_5m():
    assert m._is_1a_5m("1A (5M)", "5m") is True
    assert m._is_1a_1m("1A (5M)", "5m") is False
    assert m._is_1a_5m("1A (1M)", "1m") is False
    assert m._is_5a_5m("5A (5M)", "5m") is True
    assert m._is_5a_1m("5A (5M)", "5m") is False
    assert m._is_1c_5m("1C (5M)", "5m") is True
    assert m._is_1c_5m("1C (1M)", "1m") is False
    assert m._is_9a_5m("9A (5M)", "5m") is True
    assert m._is_9a_5m("9A (1M)", "1m") is False
    assert m._is_5b_5m("5B (5M)", "5m") is True
    assert m._is_5b_5m("5B (1M)", "1m") is False
    assert m._is_2b_5m("2B (5M)", "5m") is True
    assert m._is_2b_5m("2B (1M)", "1m") is False


def _1c_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.005, 6)
        rows.append(_bar(c, nxt * 1.002, c * 0.999, nxt, v=80))
        c = nxt
    h = c * 1.025
    lo = c * 0.985
    close = c * 1.02
    rows.append(_bar(c, h, lo, close, v=80))
    return rows, float(close)


def _9a_slices():
    rows = [_bar(0.70, 0.71, 0.69, 0.70, v=500)] * 10
    rows.append(_bar(1.12, 1.13, 1.10, 1.12, v=40))
    rows.append(_bar(1.12, 1.12, 1.08, 1.09, v=40))
    rows.append(_bar(1.09, 1.10, 1.06, 1.07, v=40))
    rows.append(_bar(1.07, 1.08, 1.04, 1.05, v=40))
    last = _bar(1.05, 1.09, 1.04, 1.08, v=40)
    rows.append(last)
    return rows, float(last["c"])


def test_1c_5m_gene_not_1a_1b():
    slices, _px = _1c_slices()
    assert m._1c_5m_gene_ok(slices) is True
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._1c_5m_gene_ok(quiet) is False


def test_9a_5m_gene_not_5a():
    slices, _px = _9a_slices()
    assert m._9a_5m_gene_ok(slices) is True
    assert m._5a_5m_gene_ok(slices) is False
    s5, _ = _5a_slices()
    assert m._9a_5m_gene_ok(s5) is False


def test_1c_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _1c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="1C (5M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_9a_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _9a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=float(slices[-1]["l"] or px),
        tf="5m",
        strategy="9A (5M)",
        layout_id="9",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_1c_9a_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    c_slices, c_px = _1c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        c_slices,
        last_px=c_px,
        tf="5m",
        strategy="1C (5M)",
        layout_id="1",
        structural=16.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note
    a_slices, a_px = _9a_slices()
    ready9, note9 = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        a_slices,
        last_px=a_px,
        tf="5m",
        strategy="9A (5M)",
        layout_id="9",
        structural=20.0,
        session_state=ss,
    )
    assert ready9 is False
    assert "9:30" in note9


def test_1c_9a_pack_targets():
    slices, px = _1c_slices()
    _stop, tgt, _frac = m._1c_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.14) < 1e-9
    s9, px9 = _9a_slices()
    _s9, tgt9, frac9 = m._9a_5m_pack_exits(s9, px9)
    assert abs(tgt9 / px9 - 1.075) < 1e-9


def _5b_slices():
    rows = [_bar(1.12, 1.13, 1.11, 1.12, v=220)] * 6
    rows.append(_bar(1.12, 1.12, 1.06, 1.07, v=60))
    rows.append(_bar(1.07, 1.08, 1.03, 1.04, v=55))
    last = _bar(1.04, 1.09, 1.03, 1.08, v=50)
    rows.append(last)
    return rows, float(last["c"])


def _2b_slices():
    rows = []
    c = 1.0
    for _ in range(8):
        nxt = round(c * 1.01, 6)
        rows.append(_bar(c, nxt * 1.002, c * 0.999, nxt, v=80))
        c = nxt
    h = c * 1.022
    lo = c * 0.995
    close = c * 1.015
    rows.append(_bar(c, h, lo, close, v=80))
    return rows, float(close)


def test_5b_5m_gene_not_5a():
    slices, _px = _5b_slices()
    assert m._5b_5m_gene_ok(slices) is True
    assert m._5a_5m_gene_ok(slices) is False
    s5, _ = _5a_slices()
    assert m._5b_5m_gene_ok(s5) is False
    assert m._5a_5m_gene_ok(s5) is True


def test_2b_5m_gene_not_1a_1b():
    slices, _px = _2b_slices()
    assert m._2b_5m_gene_ok(slices) is True
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._2b_5m_gene_ok(quiet) is False


def test_5b_5m_fill_now_after_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _5b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=float(slices[-1]["l"] or px),
        tf="5m",
        strategy="5B (5M)",
        layout_id="5",
        structural=41.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_5b_5m_skips_until_10():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _5b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="5B (5M)",
        layout_id="5",
        structural=41.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_2b_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _2b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="5m",
        strategy="2B (5M)",
        layout_id="2",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_2b_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _2b_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "BIAF"},
        slices,
        last_px=px,
        tf="5m",
        strategy="2B (5M)",
        layout_id="2",
        structural=20.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_5b_2b_pack_targets():
    slices, px = _5b_slices()
    _stop, tgt, _frac = m._5b_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.08) < 1e-9
    s2, px2 = _2b_slices()
    _s2, tgt2, _f2 = m._2b_5m_pack_exits(s2, px2)
    assert abs(tgt2 / px2 - 1.10) < 1e-9


def _5c_slices():
    rows = [_bar(1.125, 1.13, 1.12, 1.125, v=80)] * 6
    rows.append(_bar(1.125, 1.126, 1.112, 1.114, v=50))
    rows.append(_bar(1.114, 1.115, 1.108, 1.110, v=50))
    rows.append(_bar(1.110, 1.111, 1.104, 1.106, v=50))
    last = _bar(1.106, 1.132, 1.104, 1.108, v=50)
    rows.append(last)
    return rows, float(last["c"])


def _8a_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.025, 6)
        rows.append(_bar(c, nxt * 1.002, c * 0.999, nxt, v=40))
        c = nxt
    for _ in range(4):
        nxt = round(c * 1.001, 6)
        rows.append(_bar(c, nxt * 1.004, c * 0.999, nxt, v=40))
        c = nxt
    h = c * 1.018
    lo = c * 0.997
    close = c * 1.012
    rows.append(_bar(c, h, lo, close, v=400))
    return rows, float(close)


def test_5c_8a_5m_ids():
    assert m._is_5c_5m("5C (5M)", "5m") is True
    assert m._is_5c_5m("5C (1M)", "1m") is False
    assert m._is_8a_5m("8A (5M)", "5m") is True
    assert m._is_8a_5m("8A (1M)", "1m") is False


def test_5c_5m_gene_not_5a():
    slices, _px = _5c_slices()
    assert m._5c_5m_gene_ok(slices) is True
    assert m._5a_5m_gene_ok(slices) is False
    assert m._5b_5m_gene_ok(slices) is False


def test_8a_5m_gene_not_2b():
    slices, _px = _8a_slices()
    assert m._8a_5m_gene_ok(slices) is True
    assert m._2b_5m_gene_ok(slices) is False
    assert m._1a_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._8a_5m_gene_ok(quiet) is False


def test_5c_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _5c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "GIPR"},
        slices,
        last_px=px,
        tf="5m",
        strategy="5C (5M)",
        layout_id="5",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_8a_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _8a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="8A (5M)",
        layout_id="8",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_5c_8a_pack_targets():
    slices, px = _5c_slices()
    _stop, tgt, _frac = m._5c_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.08) < 1e-9
    s8, px8 = _8a_slices()
    _s8, tgt8, _f8 = m._8a_5m_pack_exits(s8, px8)
    assert abs(tgt8 / px8 - 1.08) < 1e-9


def _6a_slices():
    rows = [_bar(1.12, 1.13, 1.11, 1.12, v=220)] * 6
    rows.append(_bar(1.12, 1.12, 1.06, 1.07, v=60))
    rows.append(_bar(1.07, 1.08, 1.03, 1.04, v=55))
    last = _bar(1.04, 1.06, 1.03, 1.055, v=50)
    rows.append(last)
    return rows, float(last["c"])


def test_6a_5m_ids():
    assert m._is_6a_5m("6A (5M)", "5m") is True
    assert m._is_6a_5m("6A (1M)", "1m") is False


def test_6a_5m_gene_not_5a_or_5b():
    slices, _px = _6a_slices()
    assert m._6a_5m_gene_ok(slices) is True
    assert m._5a_5m_gene_ok(slices) is False
    assert m._5b_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._6a_5m_gene_ok(quiet) is False


def test_6a_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _6a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="6A (5M)",
        layout_id="6",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_6a_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 50, tzinfo=ET))
    slices, px = _6a_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="5m",
        strategy="6A (5M)",
        layout_id="6",
        structural=20.0,
        session_state=ss,
    )
    assert ready is False
    assert "10:00" in note


def test_6a_5m_pack_target():
    slices, px = _6a_slices()
    _stop, tgt, _frac = m._6a_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.09) < 1e-9


def _2c_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.128, 1.098, 1.099, v=400)
    rows.append(last)
    return rows, float(last["c"])


def _2d_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.108, 1.095, 1.102, v=400)
    rows.append(last)
    return rows, float(last["c"])


def test_2c_2d_5m_ids():
    assert m._is_2c_5m("2C (5M)", "5m") is True
    assert m._is_2c_5m("2C (1M)", "1m") is False
    assert m._is_2d_5m("2D (5M)", "5m") is True
    assert m._is_2d_5m("2D (1M)", "1m") is False


def test_2c_5m_gene_no_last_green_required():
    slices, _px = _2c_slices()
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._2c_5m_gene_ok(slices) is True
    assert m._2d_5m_gene_ok(slices) is False
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._2c_5m_gene_ok(quiet) is False


def test_2d_5m_gene_not_2c():
    slices, _px = _2d_slices()
    assert m._2d_5m_gene_ok(slices) is True
    assert m._2c_5m_gene_ok(slices) is False


def test_2c_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _2c_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "AMIX"},
        slices,
        last_px=px,
        tf="5m",
        strategy="2C (5M)",
        layout_id="2",
        structural=31.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_2d_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _2d_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "TVRD"},
        slices,
        last_px=px,
        tf="5m",
        strategy="2D (5M)",
        layout_id="2",
        structural=23.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_2c_2d_pack_targets():
    slices, px = _2c_slices()
    _stop, tgt, _frac = m._2c_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.08) < 1e-9
    s2, px2 = _2d_slices()
    _s2, tgt2, _f2 = m._2d_5m_pack_exits(s2, px2)
    assert abs(tgt2 / px2 - 1.08) < 1e-9


def _2a_5m_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.128, 1.098, 1.099, v=400)
    rows.append(last)
    return rows, float(last["c"])


def _1d_5m_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.112, 1.098, 1.101, v=400)
    rows.append(last)
    return rows, float(last["c"])


def _4a_5m_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.011, 6)
        rows.append(_bar(c, nxt * 1.002, c * 0.999, nxt, v=50))
        c = nxt
    last = _bar(c, c * 1.022, c * 0.999, c * 0.999, v=400)
    rows.append(last)
    return rows, float(last["c"])


def test_2a_1d_4a_5m_ids():
    assert m._is_2a_5m("2A (5M)", "5m") is True
    assert m._is_2a_5m("2A (1M)", "1m") is False
    assert m._is_1d_5m("1D (5M)", "5m") is True
    assert m._is_1d_5m("1D (15M)", "15m") is False
    assert m._is_4a_5m("4A (5M)", "5m") is True
    assert m._is_4a_5m("4A (1M)", "1m") is False


def test_2a_5m_gene_no_last_green_required():
    slices, _px = _2a_5m_slices()
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._2a_5m_gene_ok(slices) is True
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._2a_5m_gene_ok(quiet) is False


def test_1d_5m_gene_not_2c():
    slices, _px = _1d_5m_slices()
    assert m._1d_5m_gene_ok(slices) is True
    assert m._2c_5m_gene_ok(slices) is False
    assert m._2a_5m_gene_ok(slices) is False
    assert m._4a_5m_gene_ok(slices) is False


def test_4a_5m_gene_vel5_band():
    slices, _px = _4a_5m_slices()
    vel5 = m._window_velocity_pct(slices, 5)
    assert 3.0 <= vel5 < 8.0
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._4a_5m_gene_ok(slices) is True
    assert m._1d_5m_gene_ok(slices) is False
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is False


def test_2a_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _2a_5m_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "VTAK"},
        slices,
        last_px=px,
        tf="5m",
        strategy="2A (5M)",
        layout_id="2",
        structural=28.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_1d_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _1d_5m_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "CANF"},
        slices,
        last_px=px,
        tf="5m",
        strategy="1D (5M)",
        layout_id="1",
        structural=22.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_4a_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _4a_5m_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "LNKS"},
        slices,
        last_px=px,
        tf="5m",
        strategy="4A (5M)",
        layout_id="4",
        structural=18.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_2a_1d_4a_pack_targets():
    slices, px = _2a_5m_slices()
    _stop, tgt, _frac = m._2a_5m_pack_exits(slices, px)
    assert abs(tgt / px - 1.08) < 1e-9
    s1, px1 = _1d_5m_slices()
    _s1, tgt1, _f1 = m._1d_5m_pack_exits(s1, px1)
    assert abs(tgt1 / px1 - 1.08) < 1e-9
    s4, px4 = _4a_5m_slices()
    _s4, tgt4, _f4 = m._4a_5m_pack_exits(s4, px4)
    assert abs(tgt4 / px4 - 1.08) < 1e-9


def _remain_5m_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.128, 1.098, 1.099, v=400)
    rows.append(last)
    return rows, float(last["c"])


def _9b_5m_slices():
    rows = [_bar(1.10, 1.11, 1.09, 1.10, v=50)] * 6
    last = _bar(1.10, 1.150, 1.095, 1.098, v=400)
    rows.append(last)
    return rows, float(last["c"])


def _1a_15m_slices():
    rows = []
    c = 1.0
    for _ in range(4):
        nxt = round(c * 1.042, 6)
        rows.append(_bar(c, nxt * 1.005, c * 0.999, nxt, v=80))
        c = nxt
    last = _bar(c, c * 1.025, c * 0.999, c * 0.999, v=200)
    rows.append(last)
    return rows, float(last["c"])


def test_remain_5m_ids():
    assert m._is_6b_5m("6B (5M)", "5m") is True
    assert m._is_6b_5m("6B (1M)", "1m") is False
    assert m._is_8b_5m("8B (5M)", "5m") is True
    assert m._is_3a_5m("3A (5M)", "5m") is True
    assert m._is_3a_5m("3A (1M)", "1m") is False
    assert m._is_9b_5m("9B (5M)", "5m") is True
    assert m._is_1a_15m("1A (15M)", "15m") is True
    assert m._is_1a_15m("1A (5M)", "5m") is False
    assert m._is_15m_origin_letter("2A (15M)", "15m") == "2A"
    assert m._is_15m_origin_letter("8A (15M)", "15m") == ""


def test_remain_5m_gene_no_last_green():
    slices, _px = _remain_5m_slices()
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._6b_5m_gene_ok(slices) is True
    assert m._8b_5m_gene_ok(slices) is True
    assert m._3a_5m_gene_ok(slices) is True
    quiet = [_bar(1.0, 1.002, 0.999, 1.001, v=80)] * 10
    assert m._6b_5m_gene_ok(quiet) is False


def test_9b_5m_gene_fat_bar():
    slices, _px = _9b_5m_slices()
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._9b_5m_gene_ok(slices) is True
    thin, _ = _remain_5m_slices()
    assert m._9b_5m_gene_ok(thin) is False


def test_6b_5m_fill_now():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    slices, px = _remain_5m_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "NEXR"},
        slices,
        last_px=px,
        tf="5m",
        strategy="6B (5M)",
        layout_id="6",
        structural=20.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note


def test_9b_5m_skips_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    slices, px = _9b_5m_slices()
    ready, note = m._entry_trigger_ready(
        {"ticker": "JEM"},
        slices,
        last_px=px,
        tf="5m",
        strategy="9B (5M)",
        layout_id="9",
        structural=40.0,
        session_state=ss,
    )
    assert ready is False
    assert "9:30" in note


def test_remain_5m_pack_targets():
    slices, px = _remain_5m_slices()
    for fn in (m._6b_5m_pack_exits, m._8b_5m_pack_exits, m._3a_5m_pack_exits):
        _stop, tgt, _frac = fn(slices, px)
        assert abs(tgt / px - 1.08) < 1e-9
    s9, px9 = _9b_5m_slices()
    _s, tgt9, _f = m._9b_5m_pack_exits(s9, px9)
    assert abs(tgt9 / px9 - 1.08) < 1e-9


def test_1a_15m_gene_and_fill_now():
    slices, px = _1a_15m_slices()
    last = slices[-1]
    assert float(last["c"]) < float(last["o"])
    assert m._1a_15m_gene_ok(slices) is True
    assert m._15m_origin_gene_ok(slices) is False
    ss = _SS(_now_et=datetime(2026, 9, 11, 9, 35, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "FAMI"},
        slices,
        last_px=px,
        tf="15m",
        strategy="1A (15M)",
        layout_id="1",
        structural=50.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note
    _stop, tgt, _frac = m._1a_15m_pack_exits(slices, px)
    assert abs(tgt / px - 1.08) < 1e-9


def test_15m_origin_fill_now_12():
    slices = [_bar(1.0, 1.02, 0.99, 1.01, v=50)] * 4
    last = _bar(1.01, 1.05, 1.00, 1.02, v=200)
    slices.append(last)
    assert m._1a_15m_gene_ok(slices) is False
    assert m._15m_origin_gene_ok(slices) is True
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
    ready, note = m._entry_trigger_ready(
        {"ticker": "ZYBT"},
        slices,
        last_px=float(last["c"]),
        tf="15m",
        strategy="1B (15M)",
        layout_id="1",
        structural=80.0,
        session_state=ss,
    )
    assert ready is True
    assert "enter now" in note
    _s, tgt, _f = m._15m_origin_pack_exits(slices, float(last["c"]))
    assert abs(tgt / float(last["c"]) - 1.12) < 1e-9
