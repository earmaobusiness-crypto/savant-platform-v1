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
    rows = [_bar(1.12, 1.13, 1.11, 1.12, v=220)] * 6
    rows.append(_bar(1.12, 1.12, 1.06, 1.07, v=60))
    rows.append(_bar(1.07, 1.08, 1.03, 1.04, v=55))
    last = _bar(1.04, 1.075, 1.03, 1.065, v=50)
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
    assert m._1a_5m_gene_ok(slices) is False
    assert m._1b_5m_gene_ok(slices) is False


def test_1a_5m_fill_now_after_open():
    ss = _SS(_now_et=datetime(2026, 9, 11, 12, 0, tzinfo=ET))
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
