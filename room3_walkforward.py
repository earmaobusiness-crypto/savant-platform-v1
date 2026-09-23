"""
Walk-forward replay of locked 1m letters on the Sep 2–11 2026 belt tape.

Not live Alpaca. Not Cloud. Hunt extras stand in for ≥85% nearest
(Yahoo/Massive 1m has no vault Match%). Fill-now Handle: skip / first-of-day /
15m cool / 3A noon cut / locked stops and targets. Dip does not block.
2D match ≥91 is not scored (no DNA). Purgatory never fires.

Sim exits (not live Cloud): 1m stays the locked letter book. Trailing stops
are off on 1m / 5m / 15m — lookback stop and hard targets only. 5m hard clip
+15%. 15m hard clip +20%. Live 1A trip trail and 5m placeholder trail stay
on Cloud. Sim size tests: iceberg clips and loud-stretch entries.

  python3 room3_walkforward.py
"""

from __future__ import annotations

import argparse
import sys
import time as _time
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

import room3_matrix as m
import room3_precursor as precursor
import room3_recipes

ET = ZoneInfo("America/New_York")

LOCKED_1M = ("5B", "2A", "1A", "2D", "2B", "2C", "3A", "4A", "3B", "5A", "7A", "3C", "4D", "4B", "6A", "4C", "4E", "6B", "3D", "7B", "3G", "3F", "8A", "7C", "3E", "6C")
LOCKED_5M = ("1A", "1B", "5A", "1C", "9A", "5B", "2B", "5C", "8A", "6A", "2C", "2D", "2A", "1D", "4A", "6B", "8B", "3A", "9B")
# All live 5m letters (recluster). All 19 have Hunt extras.
LOCKED_5M_LIVE = (
    "1A",
    "1B",
    "1C",
    "1D",
    "2A",
    "2B",
    "2C",
    "2D",
    "3A",
    "4A",
    "5A",
    "5B",
    "5C",
    "6A",
    "6B",
    "8A",
    "8B",
    "9A",
    "9B",
)
# Live 15m letters (recluster). 1A leftover Hunt extras; 1B/1C/1D/2A/2B/6A/9A origin extras.
# 8A/8B stay placeholder dip-hold.
LOCKED_15M = ("1A", "1B", "1C", "1D", "2A", "2B", "6A", "9A")
LOCKED_15M_LIVE = ("1A", "1B", "1C", "1D", "2A", "2B", "6A", "8A", "8B", "9A")
SIM_5M_TARGET_FRAC = 0.15
SIM_5M_TRAIL_FRAC = 0.08  # unused in sim — trails off (2026-09-21)
SIM_5M_EXIT_STYLE = "sim_5m_trail"
SIM_NO_TRAIL = True
SIM_15M_TARGET_FRAC = 0.20
SIM_ICEBERG_FRAC = 0.02
SIM_LOUD_PCT = 90.0
SIM_LOUD_MIN_PRIOR = 15
SESS_START = date(2026, 9, 2)
SESS_END = date(2026, 9, 11)
# Sep 7 2026 is Labor Day — RTH closed. Not a missing-tape day.
MARKET_HOLIDAYS = frozenset({date(2026, 9, 7)})
TRAIN_N = 5
TEST_N = 1
STEP = 1
START_BOOK = 1000.0
TICKET_FRAC = 0.80

# Sep 2 belt + Sep 3 belt. Later weekdays in this stretch were not ticker-logged;
# the letter WR cards swept this union on Yahoo 1m every session.
BELT_UNION = (
    "FAMI",
    "BIAF",
    "PPBT",
    "VIOT",
    "NCPL",
    "MIMI",
    "GELS",
    "GIPR",
    "SPWR",
)
BELT_BY_DAY: dict[date, tuple[str, ...]] = {
    date(2026, 9, 2): ("FAMI", "BIAF", "PPBT", "VIOT", "NCPL"),
    date(2026, 9, 3): ("MIMI", "GELS", "GIPR", "SPWR"),
}

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


class _SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as exc:
            raise AttributeError(k) from exc

    def __setattr__(self, k, v):
        self[k] = v


def weekday_sessions(start: date = SESS_START, end: date = SESS_END) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur not in MARKET_HOLIDAYS:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def rolling_folds(
    sessions: list[date] | None = None,
    *,
    train_n: int = TRAIN_N,
    test_n: int = TEST_N,
    step: int = STEP,
) -> list[dict[str, list[date]]]:
    days = list(sessions or weekday_sessions())
    folds: list[dict[str, list[date]]] = []
    i = 0
    while i + train_n + test_n <= len(days):
        folds.append(
            {
                "train": days[i : i + train_n],
                "test": days[i + train_n : i + train_n + test_n],
            }
        )
        i += step
    return folds


def belt_for(sess: date) -> tuple[str, ...]:
    return BELT_BY_DAY.get(sess) or BELT_UNION


def _letter_token(letter: str, tf: str = "1m") -> str:
    tf_n = str(tf or "1m").strip().lower()
    tag = "5M" if tf_n == "5m" else ("15M" if tf_n == "15m" else "1M")
    return f"{letter} ({tag})"


def gene_ok(letter: str, slices: list[dict[str, Any]], tf: str = "1m") -> bool:
    """Hunt extras as detect. Wallpaper does not fire.

    15m 8A/8B may reach the placeholder Handle (dip then hold). That is not a Match% ≥85% claim.
    """
    tf_n = str(tf or "1m").strip().lower()
    if tf_n == "15m":
        if letter == "1A":
            return bool(m._1a_15m_gene_ok(slices))
        if letter in ("1B", "1C", "1D", "2A", "2B", "6A", "9A"):
            return bool(m._15m_origin_gene_ok(slices))
        return letter in LOCKED_15M_LIVE
    if tf_n == "5m":
        if letter == "1A":
            return bool(m._1a_5m_gene_ok(slices))
        if letter == "1B":
            return bool(m._1b_5m_gene_ok(slices))
        if letter == "5A":
            return bool(m._5a_5m_gene_ok(slices))
        if letter == "1C":
            return bool(m._1c_5m_gene_ok(slices))
        if letter == "9A":
            return bool(m._9a_5m_gene_ok(slices))
        if letter == "5B":
            return bool(m._5b_5m_gene_ok(slices))
        if letter == "2B":
            return bool(m._2b_5m_gene_ok(slices))
        if letter == "5C":
            return bool(m._5c_5m_gene_ok(slices))
        if letter == "8A":
            return bool(m._8a_5m_gene_ok(slices))
        if letter == "6A":
            return bool(m._6a_5m_gene_ok(slices))
        if letter == "2C":
            return bool(m._2c_5m_gene_ok(slices))
        if letter == "2D":
            return bool(m._2d_5m_gene_ok(slices))
        if letter == "2A":
            return bool(m._2a_5m_gene_ok(slices))
        if letter == "1D":
            return bool(m._1d_5m_gene_ok(slices))
        if letter == "4A":
            return bool(m._4a_5m_gene_ok(slices))
        if letter == "6B":
            return bool(m._6b_5m_gene_ok(slices))
        if letter == "8B":
            return bool(m._8b_5m_gene_ok(slices))
        if letter == "3A":
            return bool(m._3a_5m_gene_ok(slices))
        if letter == "9B":
            return bool(m._9b_5m_gene_ok(slices))
        return letter in LOCKED_5M_LIVE
    if letter == "5B":
        return bool(m._5b_gene_ok(slices))
    if letter == "2A":
        return bool(m._2a_gene_ok(slices))
    if letter == "1A":
        return bool(m._1a_classify(slices))
    if letter == "2D":
        return bool(m._2d_gene_ok(slices))
    if letter == "2B":
        return bool(m._2b_gene_ok(slices))
    if letter == "2C":
        return bool(m._2c_gene_ok(slices))
    if letter == "3A":
        return bool(m._3a_gene_ok(slices))
    if letter == "4A":
        return bool(m._4a_gene_ok(slices))
    if letter == "3B":
        return bool(m._3b_gene_ok(slices))
    if letter == "5A":
        return bool(m._5a_gene_ok(slices))
    if letter == "7A":
        return bool(m._7a_gene_ok(slices))
    if letter == "3C":
        return bool(m._3c_gene_ok(slices))
    if letter == "4D":
        return bool(m._4d_gene_ok(slices))
    if letter == "4B":
        return bool(m._4b_gene_ok(slices))
    if letter == "6A":
        return bool(m._6a_gene_ok(slices))
    if letter == "4C":
        return bool(m._4c_gene_ok(slices))
    if letter == "4E":
        return bool(m._4e_gene_ok(slices))
    if letter == "6B":
        return bool(m._6b_gene_ok(slices))
    if letter == "3D":
        return bool(m._3d_gene_ok(slices))
    if letter == "7B":
        return bool(m._7b_gene_ok(slices))
    if letter == "3G":
        return bool(m._3g_gene_ok(slices))
    if letter == "3F":
        return bool(m._3f_gene_ok(slices))
    if letter == "8A":
        return bool(m._8a_gene_ok(slices))
    if letter == "7C":
        return bool(m._7c_gene_ok(slices))
    if letter == "3E":
        return bool(m._3e_gene_ok(slices))
    if letter == "6C":
        return bool(m._6c_gene_ok(slices))
    return False


def _exit_style(letter: str, handle: str = "") -> str:
    if letter == "5B":
        return m.FIVE_B_EXIT_STYLE
    if letter == "2A":
        return m.TWO_A_EXIT_STYLE
    if letter == "2B":
        return m.TWO_B_EXIT_STYLE
    if letter == "2C":
        return m.TWO_C_EXIT_STYLE
    if letter == "3A":
        return m.THREE_A_EXIT_STYLE
    if letter == "4A":
        return m.FOUR_A_EXIT_STYLE
    if letter == "3B":
        return m.THREE_B_EXIT_STYLE
    if letter == "5A":
        return m.FIVE_A_EXIT_STYLE
    if letter == "7A":
        return m.SEVEN_A_EXIT_STYLE
    if letter == "3C":
        return m.THREE_C_EXIT_STYLE
    if letter == "4D":
        return m.FOUR_D_EXIT_STYLE
    if letter == "4B":
        return m.FOUR_B_EXIT_STYLE
    if letter == "6A":
        return m.SIX_A_EXIT_STYLE
    if letter == "4C":
        return m.FOUR_C_EXIT_STYLE
    if letter == "4E":
        return m.FOUR_E_EXIT_STYLE
    if letter == "6B":
        return m.SIX_B_EXIT_STYLE
    if letter == "3D":
        return m.THREE_D_EXIT_STYLE
    if letter == "7B":
        return m.SEVEN_B_EXIT_STYLE
    if letter == "3G":
        return m.THREE_G_EXIT_STYLE
    if letter == "3F":
        return m.THREE_F_EXIT_STYLE
    if letter == "8A":
        return m.EIGHT_A_EXIT_STYLE
    if letter == "7C":
        return m.SEVEN_C_EXIT_STYLE
    if letter == "3E":
        return m.THREE_E_EXIT_STYLE
    if letter == "6C":
        return m.SIX_C_EXIT_STYLE
    if letter == "2D":
        return m.TWO_D_EXIT_STYLE
    if letter == "1A":
        return m._1a_style_for(handle)
    return m.PH_EXIT_STYLE


def _pack_exits(
    letter: str,
    slices: list[dict[str, Any]],
    fill: float,
    handle: str = "",
) -> tuple[float, float, float]:
    if letter == "5B":
        return m._5b_pack_exits(slices, fill, 0.0)
    if letter == "2A":
        return m._2a_pack_exits(slices, fill, 0.0)
    if letter == "2B":
        return m._2b_pack_exits(slices, fill, 0.0)
    if letter == "2C":
        return m._2c_pack_exits(slices, fill, 0.0)
    if letter == "3A":
        return m._3a_pack_exits(slices, fill, 0.0)
    if letter == "4A":
        return m._4a_pack_exits(slices, fill, 0.0)
    if letter == "3B":
        return m._3b_pack_exits(slices, fill, 0.0)
    if letter == "5A":
        return m._5a_pack_exits(slices, fill, 0.0)
    if letter == "7A":
        return m._7a_pack_exits(slices, fill, 0.0)
    if letter == "3C":
        return m._3c_pack_exits(slices, fill, 0.0)
    if letter == "4D":
        return m._4d_pack_exits(slices, fill, 0.0)
    if letter == "4B":
        return m._4b_pack_exits(slices, fill, 0.0)
    if letter == "6A":
        return m._6a_pack_exits(slices, fill, 0.0)
    if letter == "4C":
        return m._4c_pack_exits(slices, fill, 0.0)
    if letter == "4E":
        return m._4e_pack_exits(slices, fill, 0.0)
    if letter == "6B":
        return m._6b_pack_exits(slices, fill, 0.0)
    if letter == "3D":
        return m._3d_pack_exits(slices, fill, 0.0)
    if letter == "7B":
        return m._7b_pack_exits(slices, fill, 0.0)
    if letter == "3G":
        return m._3g_pack_exits(slices, fill, 0.0)
    if letter == "3F":
        return m._3f_pack_exits(slices, fill, 0.0)
    if letter == "8A":
        return m._8a_pack_exits(slices, fill, 0.0)
    if letter == "7C":
        return m._7c_pack_exits(slices, fill, 0.0)
    if letter == "3E":
        return m._3e_pack_exits(slices, fill, 0.0)
    if letter == "6C":
        return m._6c_pack_exits(slices, fill, 0.0)
    if letter == "2D":
        return m._2d_pack_exits(slices, fill, 0.0)
    if letter == "1A":
        return m._1a_pack_exits(slices, fill, handle)
    return m._ph_pack_exits(slices, fill, 0.0, "1m")


def five_m_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    letter: str = "1A",
) -> tuple[float, float, float]:
    """Sim 5m: lookback-low stop (letter floor, no 3.5 cap), +15% hard clip. No trail."""
    floor = {"1A": 2.0, "1B": 3.5, "5A": 3.5, "1C": 2.0, "9A": 2.0, "5B": 2.0, "2B": 2.0, "5C": 3.5, "8A": 2.0, "6A": 3.5, "2C": 2.0, "2D": 2.0, "2A": 2.0, "1D": 2.0, "4A": 2.0, "6B": 2.0, "8B": 2.0, "3A": 2.0, "9B": 2.0}.get(
        str(letter or ""), 2.0
    )
    tgt = {"1C": 0.14, "9A": 0.075, "5B": 0.08, "2B": 0.10, "5C": 0.08, "8A": 0.08, "6A": 0.09, "2C": 0.08, "2D": 0.08, "2A": 0.08, "1D": 0.08, "4A": 0.08, "6B": 0.08, "8B": 0.08, "3A": 0.08, "9B": 0.08}.get(str(letter or ""), SIM_5M_TARGET_FRAC)
    return m._5m_spec_pack_exits(
        slices, fill, floor_pct=floor, tgt_frac=tgt
    )


def fifteen_m_pack_exits(
    slices: list[dict[str, Any]],
    fill: float,
    structural_move_pct: float = 0.0,
    letter: str = "",
) -> tuple[float, float, float]:
    """Sim 15m: lookback-low stop. Specialized 1A clips 8%; other specialized 12%; leftover sim 20%."""
    _ = structural_move_pct
    px = float(fill or 0)
    if px <= 0:
        return 0.0, 0.0, 0.02
    stop_px, stop_frac = m._lookback_stop_px(px, slices, 3, 2.0, cap_pct=None)
    if letter == "1A":
        tgt = 0.08
    elif letter in ("1B", "1C", "1D", "2A", "2B", "6A", "9A"):
        tgt = 0.12
    else:
        tgt = SIM_15M_TARGET_FRAC
    return stop_px, px * (1.0 + tgt), stop_frac


def _mark_fill(ss: _SS, letter: str, ticker: str, tf: str = "1m") -> None:
    tf_n = str(tf or "1m").strip().lower()
    if tf_n == "15m":
        if letter in LOCKED_15M:
            m._15m_spec_mark_used(ss, letter, ticker)
        else:
            m._ph_mark_used(ss, ticker, _letter_token(letter, "15m"))
        return
    if tf_n == "5m":
        if letter in ("1A", "1B", "5A", "1C", "9A", "5B", "2B", "5C", "8A", "6A", "2C", "2D", "2A", "1D", "4A", "6B", "8B", "3A", "9B"):
            m._5m_spec_mark_used(ss, letter, ticker)
        else:
            m._ph_mark_used(ss, ticker, _letter_token(letter, "5m"))
        return
    if letter == "5B":
        m._5b_mark_used(ss, ticker)
    elif letter == "2A":
        m._2a_mark_used(ss, ticker)
    elif letter == "2B":
        m._2b_mark_used(ss, ticker)
    elif letter == "2C":
        m._2c_mark_used(ss, ticker)
    elif letter == "3A":
        m._3a_mark_used(ss, ticker)
    elif letter == "4A":
        m._4a_mark_used(ss, ticker)
    elif letter == "3B":
        m._3b_mark_used(ss, ticker)
    elif letter == "5A":
        m._5a_mark_used(ss, ticker)
    elif letter == "7A":
        m._7a_mark_used(ss, ticker)
    elif letter == "3C":
        m._3c_mark_used(ss, ticker)
    elif letter == "4D":
        m._4d_mark_used(ss, ticker)
    elif letter == "4B":
        m._4b_mark_used(ss, ticker)
    elif letter == "6A":
        m._6a_mark_used(ss, ticker)
    elif letter == "4C":
        m._4c_mark_used(ss, ticker)
    elif letter == "4E":
        m._4e_mark_used(ss, ticker)
    elif letter == "6B":
        m._6b_mark_used(ss, ticker)
    elif letter == "3D":
        m._3d_mark_used(ss, ticker)
    elif letter == "7B":
        m._7b_mark_used(ss, ticker)
    elif letter == "3G":
        m._3g_mark_used(ss, ticker)
    elif letter == "3F":
        m._3f_mark_used(ss, ticker)
    elif letter == "8A":
        m._8a_mark_used(ss, ticker)
    elif letter == "7C":
        m._7c_mark_used(ss, ticker)
    elif letter == "3E":
        m._3e_mark_used(ss, ticker)
    elif letter == "6C":
        m._6c_mark_used(ss, ticker)
    elif letter == "1A":
        m._1a_mark_used(ss, ticker)
    elif letter == "2D":
        m._2d_mark_shot(ss, ticker)
    m._1m_mark_name_shot(ss, ticker)


def _mark_target(ss: _SS, letter: str, ticker: str) -> None:
    if letter == "2D":
        m._2d_mark_used(ss, ticker)


def bars_from_frame(frame: Any, sess: date) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    try:
        day = frame[frame.index.date == sess]
    except Exception:
        return []
    if day is None or getattr(day, "empty", True):
        return []
    out: list[dict[str, Any]] = []
    for ts, row in day.iterrows():
        raw = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if not isinstance(raw, datetime):
            continue
        if raw.tzinfo is None:
            stamp = raw.replace(tzinfo=ET)
        else:
            stamp = raw.astimezone(ET)
        if stamp.time() < RTH_OPEN or stamp.time() >= RTH_CLOSE:
            continue
        try:
            o = float(row["Open"])
            h = float(row["High"])
            lo = float(row["Low"])
            c = float(row["Close"])
            v = float(row["Volume"]) if "Volume" in row else 0.0
        except Exception:
            continue
        if c <= 0:
            continue
        out.append({"ts": stamp, "o": o, "h": h, "l": lo, "c": c, "v": v})
    out.sort(key=lambda b: b["ts"])
    return out


def resample_bars(bars: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Bucket 1m prints into 5m / 15m RTH bars."""
    if minutes < 2 or not bars:
        return list(bars)
    buckets: dict[datetime, dict[str, Any]] = {}
    order: list[datetime] = []
    for bar in bars:
        ts = bar.get("ts")
        if not isinstance(ts, datetime):
            continue
        minute = (ts.minute // minutes) * minutes
        key = ts.replace(minute=minute, second=0, microsecond=0)
        o = float(bar.get("o") or 0)
        h = float(bar.get("h") or 0)
        lo = float(bar.get("l") or 0)
        c = float(bar.get("c") or 0)
        v = float(bar.get("v") or 0)
        if key not in buckets:
            buckets[key] = {"ts": key, "o": o, "h": h, "l": lo, "c": c, "v": v}
            order.append(key)
            continue
        agg = buckets[key]
        if h > float(agg["h"]):
            agg["h"] = h
        if lo > 0 and (float(agg["l"]) <= 0 or lo < float(agg["l"])):
            agg["l"] = lo
        if c > 0:
            agg["c"] = c
        agg["v"] = float(agg["v"]) + v
    return [buckets[k] for k in order]


def load_day_bars(ticker: str, sess: date) -> list[dict[str, Any]]:
    frame = precursor.load_session_bars(ticker, sess, "1m")
    return bars_from_frame(frame, sess)


def _yahoo_range_1m(ticker: str, start: date, end: date):
    # Yahoo 1m only serves ~7–8 calendar days. Skip the long Sep 2–11 window.
    if (end - start).days > 7:
        return None
    try:
        import yfinance as yf

        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1m",
            auto_adjust=False,
            prepost=True,
            progress=False,
            threads=False,
        )
        if hist is None or hist.empty:
            return None
        if getattr(hist.columns, "nlevels", 1) > 1:
            hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
        return precursor._to_et_naive(hist)
    except Exception:
        return None


def _massive_range_1m(ticker: str, start: date, end: date):
    api_key = precursor._market_key()
    if not api_key:
        return None
    wait = 12.0 - (_time.monotonic() - float(precursor._MASSIVE_LAST or 0))
    if precursor._MASSIVE_LAST > 0 and wait > 0:
        _time.sleep(wait)
    url = (
        f"{precursor.MASSIVE_API_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    try:
        resp = requests.get(
            url,
            params={"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": api_key},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=45,
        )
        precursor._MASSIVE_LAST = _time.monotonic()
        payload = resp.json() if resp.ok else {}
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not rows:
            return None
        import pandas as pd

        idx = [
            datetime.fromtimestamp(int(r["t"]) / 1000.0, tz=timezone.utc)
            .astimezone(ET)
            .replace(tzinfo=None)
            for r in rows
        ]
        return pd.DataFrame(
            {
                "Open": [float(r.get("o") or 0) for r in rows],
                "High": [float(r.get("h") or 0) for r in rows],
                "Low": [float(r.get("l") or 0) for r in rows],
                "Close": [float(r.get("c") or 0) for r in rows],
                "Volume": [float(r.get("v") or 0) for r in rows],
            },
            index=idx,
        )
    except Exception:
        precursor._MASSIVE_LAST = _time.monotonic()
        return None


def prefetch_ticker_bars(ticker: str, sessions: list[date]) -> dict[date, list[dict[str, Any]]]:
    """One Yahoo pull + one Massive pull per name, then slice RTH days."""
    start = min(sessions) - timedelta(days=1)
    end = max(sessions) + timedelta(days=1)
    yf_frame = _yahoo_range_1m(ticker, start, end)
    ms_frame = _massive_range_1m(ticker, start, end)
    out: dict[date, list[dict[str, Any]]] = {}
    for sess in sessions:
        bars = bars_from_frame(yf_frame, sess)
        if not bars:
            bars = bars_from_frame(ms_frame, sess)
        out[sess] = bars
    return out


def _lot_exit(
    lot: dict[str, Any],
    bar: dict[str, Any],
    last_px: float,
    *,
    trails: bool = False,
) -> tuple[str, float]:
    """Lookback stop and hard target. Trails only if `trails` (sim search).
    Fat tape: stop only, 20-minute hold, letter flip — no +20% take."""
    entry = float(lot.get("entry_px") or 0)
    if entry <= 0:
        return "", 0.0
    if lot.get("fat_tape") or str(lot.get("exit_source") or "") == "fat_tape":
        stop_px = float(lot.get("exit_stop_px") or 0)
        lo = float(bar.get("l") or last_px or 0)
        if lo > 0 and stop_px > 0 and lo <= stop_px:
            return "stop", stop_px
        live = str(lot.get("_now_letter") or "")
        if room3_recipes.letter_flipped(str(lot.get("letter") or ""), live):
            return "letter flipped", last_px or lo
        raw = lot.get("entry_ts")
        ts = bar.get("ts")
        if raw and ts:
            try:
                et = datetime.fromisoformat(str(raw))
                now = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
                if et.tzinfo is None:
                    et = et.replace(tzinfo=ET)
                if getattr(now, "tzinfo", None) is None:
                    now = now.replace(tzinfo=ET)
                hold = float(lot.get("hold_minutes") or room3_recipes.FAT_HOLD_MINUTES)
                if (now - et).total_seconds() >= hold * 60.0:
                    return "time box", last_px or lo
            except (TypeError, ValueError):
                pass
        return "", 0.0
    stop_px = float(lot.get("exit_stop_px") or 0)
    tgt_px = float(lot.get("exit_tgt_px") or 0)
    style = str(lot.get("exit_style") or "")
    lo = float(bar.get("l") or last_px or 0)
    hi = float(bar.get("h") or last_px or 0)
    if trails and style == SIM_5M_EXIT_STYLE:
        peak = max(float(lot.get("exit_high_px") or entry), hi if hi > 0 else 0.0, last_px or 0.0)
        lot["exit_high_px"] = peak
        arm_px = tgt_px if tgt_px > 0 else entry * (1.0 + SIM_5M_TARGET_FRAC)
        if arm_px > 0 and peak >= arm_px:
            lot["exit_runner_on"] = True
        if lot.get("exit_runner_on"):
            trail = peak * (1.0 - SIM_5M_TRAIL_FRAC)
            if trail > stop_px:
                stop_px = trail
                lot["exit_stop_px"] = stop_px
        if lo > 0 and lo <= stop_px:
            return ("runner" if lot.get("exit_runner_on") else "stop"), stop_px
        return "", 0.0
    if trails and style == m.ONE_A_EXIT_TRIP:
        peak = max(float(lot.get("exit_high_px") or entry), hi if hi > 0 else 0.0, last_px or 0.0)
        lot["exit_high_px"] = peak
        if peak >= entry * (1.0 + m.ONE_A_TRIP_ARM_FRAC):
            lot["exit_runner_on"] = True
        if lot.get("exit_runner_on"):
            trail = peak * (1.0 - m.ONE_A_TRIP_TRAIL_FRAC)
            if trail > stop_px:
                stop_px = trail
                lot["exit_stop_px"] = stop_px
        if lo > 0 and lo <= stop_px:
            return ("runner" if lot.get("exit_runner_on") else "stop"), stop_px
        return "", 0.0
    if lo > 0 and stop_px > 0 and lo <= stop_px:
        return "stop", stop_px
    if tgt_px > 0 and hi >= tgt_px:
        return "target", tgt_px
    return "", 0.0


def _open_letters(lots: list[dict[str, Any]], ticker: str) -> set[str]:
    return {
        str(lot.get("letter") or "")
        for lot in lots
        if str(lot.get("ticker") or "") == ticker
    }


def _bar_dollar(bar: dict[str, Any]) -> float:
    c = float(bar.get("c") or 0)
    v = float(bar.get("v") or 0)
    if c <= 0 or v <= 0:
        return 0.0
    return c * v


def _is_loud_stretch(
    printed: list[dict[str, Any]],
    pct: float = SIM_LOUD_PCT,
    min_prior: int = SIM_LOUD_MIN_PRIOR,
) -> bool:
    """True if this bar's $ volume is at/above `pct` of prior bars this session."""
    if len(printed) < min_prior + 1:
        return False
    prior = [_bar_dollar(b) for b in printed[:-1]]
    prior = [x for x in prior if x > 0]
    if len(prior) < min_prior:
        return False
    last = _bar_dollar(printed[-1])
    if last <= 0:
        return False
    prior.sort()
    i = min(len(prior) - 1, max(0, int(float(pct) / 100.0 * (len(prior) - 1))))
    return last + 1e-9 >= prior[i]


def _impact_px(px: float, qty: int, bar_v: float, side: str, *, k: float, cap: float) -> float:
    if px <= 0 or qty < 1 or bar_v <= 0 or k <= 0:
        return px
    slip = min(float(cap), float(k) * min(1.0, qty / bar_v))
    if side == "buy":
        return px * (1.0 + slip)
    return px * (1.0 - slip)


def replay_session(
    sess: date,
    bars_by_ticker: dict[str, list[dict[str, Any]]],
    *,
    book: float = START_BOOK,
    letters: tuple[str, ...] | None = None,
    tf: str = "1m",
    part_frac: float | None = None,
    impact_k: float = 0.0,
    impact_cap: float = 0.03,
    iceberg_frac: float | None = None,
    loud_pct: float | None = None,
    trails: bool = False,
    ticket_frac: float | None = None,
    min_bar_usd: float | None = None,
    entry_after: time | None = None,
    leftover_cut: time | None = None,
    leftover_all_day: tuple[str, ...] | None = None,
    no_leftover_after: str | None = None,
    tf_name_shots_max: int | None = None,
    tf_name_shots_exempt: tuple[str, ...] | None = None,
    max_iceberg_clips: int | None = None,
    name_loss_stop_usd: float | None = None,
    name_stop_streak: int | None = None,
    day_loss_stop_usd: float | None = None,
) -> dict[str, Any]:
    """One ET session. Book resets to `book`. Overnight flat at the last RTH print.

    Optional size layer: `part_frac` of this bar's shares, plus linear impact
    `impact_k * (qty/bar vol)` capped at `impact_cap` on buy and sell.
    `iceberg_frac`: work a full ticket in clips of that fraction of each bar.
    `loud_pct`: new entries only if this bar's $ vol is at/above that percentile
    of prior bars (needs SIM_LOUD_MIN_PRIOR). Sim only — not live icebergs.
    Optional prove-gates (all off by default): `entry_after`, leftover clock,
    name-shot cap, max iceberg clips.
    """
    tf_n = str(tf or "1m").strip().lower()
    if letters is None:
        if tf_n == "5m":
            letters = LOCKED_5M
        elif tf_n == "15m":
            letters = LOCKED_15M
        else:
            letters = LOCKED_1M
    ss = _SS(
        _now_et=datetime(sess.year, sess.month, sess.day, 9, 30, tzinfo=ET),
        _fat_bar_complete=True,
    )
    cash = float(book)
    ticket_cap = float(book) * float(TICKET_FRAC if ticket_frac is None else ticket_frac)
    open_lots: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    name_pnl: dict[str, float] = {}
    name_stops: dict[str, int] = {}
    slices: dict[str, list[dict[str, Any]]] = {t: [] for t in bars_by_ticker}
    armed_lines: dict[tuple[str, str], dict[str, Any]] = {}

    events: list[tuple[datetime, str, dict[str, Any]]] = []
    for ticker, bars in bars_by_ticker.items():
        for bar in bars:
            events.append((bar["ts"], ticker, bar))
    events.sort(key=lambda e: (e[0], e[1]))

    def close_lot(
        lot: dict[str, Any], reason: str, px: float, when: datetime, bar_v: float = 0.0
    ) -> None:
        qty = int(lot.get("qty") or 0)
        entry = float(lot.get("entry_px") or 0)
        exit_px = _impact_px(float(px or 0), qty, bar_v, "sell", k=impact_k, cap=impact_cap)
        pnl = (exit_px - entry) * qty if qty and entry and exit_px else 0.0
        nonlocal cash
        cash += exit_px * qty
        row = {
            **lot,
            "exit_px": exit_px,
            "exit_reason": reason,
            "exit_ts": when.isoformat(),
            "pnl_usd": pnl,
            "pnl_pct": ((exit_px - entry) / entry * 100.0) if entry else 0.0,
        }
        closed.append(row)
        ticker = str(lot.get("ticker") or "")
        name_pnl[ticker] = float(name_pnl.get(ticker) or 0.0) + pnl
        if reason.startswith("stop") or reason == "runner":
            name_stops[ticker] = int(name_stops.get(ticker) or 0) + 1
        elif reason.startswith("target"):
            name_stops[ticker] = 0
        if reason.startswith("stop") or reason == "runner":
            m._pack_mark_stop_cool(ss, ticker, lot)
        elif reason.startswith("target"):
            _mark_target(ss, str(lot.get("letter") or ""), ticker)

    for ts, ticker, bar in events:
        ss._now_et = ts
        last_px = float(bar.get("c") or 0)
        still: list[dict[str, Any]] = []
        for lot in open_lots:
            if str(lot.get("ticker") or "") != ticker:
                still.append(lot)
                continue
            reason, px = _lot_exit(lot, bar, last_px, trails=trails)
            if reason:
                close_lot(lot, reason, px, ts, float(bar.get("v") or 0))
            else:
                still.append(lot)
        open_lots = still

        slice_bar = {k: bar[k] for k in ("o", "h", "l", "c", "v")}
        slices[ticker].append(slice_bar)
        printed = slices[ticker]
        last_px = float(bar.get("c") or 0)
        bar_v = float(bar.get("v") or 0)
        live = _open_letters(open_lots, ticker)

        def clip_buy(size_usd: float) -> tuple[int, float]:
            cap = float(size_usd)
            if last_px <= 0:
                return 0, 0.0
            if iceberg_frac is not None and bar_v > 0:
                cap = min(cap, float(iceberg_frac) * bar_v * last_px)
            elif part_frac is not None and bar_v > 0:
                cap = min(cap, float(part_frac) * bar_v * last_px)
            qty = int(cap / last_px)
            if qty < 1:
                return 0, 0.0
            fill_px = _impact_px(last_px, qty, bar_v, "buy", k=impact_k, cap=impact_cap)
            if qty * fill_px > cash + 1e-9:
                return 0, 0.0
            return qty, fill_px

        if iceberg_frac is not None:
            for lot in open_lots:
                if str(lot.get("ticker") or "") != ticker:
                    continue
                if (
                    max_iceberg_clips is not None
                    and int(lot.get("iceberg_clips") or 0) >= int(max_iceberg_clips)
                ):
                    lot["remain_usd"] = 0.0
                    continue
                remain = float(lot.get("remain_usd") or 0)
                if remain <= last_px or last_px <= 0:
                    continue
                add_qty, add_px = clip_buy(min(remain, cash))
                if add_qty < 1:
                    continue
                old_qty = int(lot.get("qty") or 0)
                old_px = float(lot.get("entry_px") or add_px)
                cost = add_qty * add_px
                cash -= cost
                new_qty = old_qty + add_qty
                lot["entry_px"] = (
                    (old_px * old_qty + add_px * add_qty) / new_qty if new_qty else add_px
                )
                lot["qty"] = new_qty
                lot["remain_usd"] = max(0.0, remain - cost)
                lot["iceberg_clips"] = int(lot.get("iceberg_clips") or 1) + 1
                hi = float(bar.get("h") or last_px or 0)
                lot["exit_high_px"] = max(float(lot.get("exit_high_px") or 0), hi, last_px)

        for letter in letters:
            if letter in live:
                continue
            if tf_n == "15m":
                n15 = sum(
                    1
                    for lot in list(open_lots) + closed
                    if str(lot.get("ticker") or "") == ticker
                )
                if n15 >= 2:
                    continue
            if not gene_ok(letter, printed, tf=tf_n):
                continue
            line = armed_lines.setdefault((ticker, letter), {"ticker": ticker})
            handle = ""
            if tf_n == "1m" and letter == "1A":
                handle = m._1a_classify(printed)
                if not handle:
                    continue
                line["1a_handle"] = handle
            ready, note = m._entry_trigger_ready(
                line,
                printed,
                last_px=last_px,
                tf=tf_n,
                strategy=_letter_token(letter, tf_n),
                layout_id="WALKFORWARD",
                structural=0.0,
                session_state=ss,
            )
            if not ready:
                continue
            if last_px <= 0:
                continue
            if loud_pct is not None and not _is_loud_stretch(printed, loud_pct):
                continue
            if min_bar_usd is not None and _bar_dollar(bar) < float(min_bar_usd):
                continue
            if entry_after is not None and ts.time() < entry_after:
                continue
            if name_loss_stop_usd is not None and float(name_pnl.get(ticker) or 0.0) <= -abs(
                float(name_loss_stop_usd)
            ):
                continue
            if name_stop_streak is not None and int(name_stops.get(ticker) or 0) >= int(
                name_stop_streak
            ):
                continue
            if day_loss_stop_usd is not None:
                booked = sum(float(t.get("pnl_usd") or 0) for t in closed)
                if booked <= -abs(float(day_loss_stop_usd)):
                    continue
            all_day = frozenset(leftover_all_day or ())
            if leftover_cut is not None and letter not in all_day and ts.time() >= leftover_cut:
                continue
            if no_leftover_after and letter not in all_day:
                stacked = any(
                    str(lot.get("ticker") or "") == ticker
                    and str(lot.get("letter") or "") == no_leftover_after
                    for lot in list(open_lots) + closed
                )
                if stacked:
                    continue
            if tf_name_shots_max is not None:
                exempt = frozenset(tf_name_shots_exempt or ())
                if letter not in exempt:
                    n_shots = sum(
                        1
                        for lot in list(open_lots) + closed
                        if str(lot.get("ticker") or "") == ticker
                        and str(lot.get("letter") or "") not in exempt
                    )
                    if n_shots >= int(tf_name_shots_max):
                        continue
            parent = min(ticket_cap, cash)
            letter_cap = room3_recipes.letter_max_ticket_usd(tf_n, letter)
            if letter_cap is not None:
                if float(letter_cap) <= 0:
                    continue
                parent = min(parent, float(letter_cap))
            if (
                max_iceberg_clips is not None
                and iceberg_frac is not None
                and bar_v > 0
                and last_px > 0
            ):
                clip_usd = float(iceberg_frac) * bar_v * last_px
                if clip_usd > 0 and parent > clip_usd * float(max_iceberg_clips) + 1e-9:
                    continue
            qty, fill_px = clip_buy(parent)
            if qty < 1:
                continue
            handle = str(line.get("1a_handle") or "")
            fat = room3_recipes.tape_is_fat(printed)
            if fat:
                wick = room3_recipes.wick_fill_px(printed, fill_px)
                if wick > 0:
                    fill_px = wick
            if tf_n == "5m":
                stop_px, tgt_px, stop_frac = five_m_pack_exits(printed, fill_px, letter)
                style = SIM_5M_EXIT_STYLE
            elif tf_n == "15m":
                stop_px, tgt_px, stop_frac = fifteen_m_pack_exits(
                    printed, fill_px, letter=letter
                )
                style = m.PH_EXIT_STYLE
            else:
                stop_px, tgt_px, stop_frac = _pack_exits(letter, printed, fill_px, handle)
                style = _exit_style(letter, handle)
            if fat:
                stop_pct = room3_recipes.fat_stop_pct(printed)
                stop_px = fill_px * (1.0 - stop_pct / 100.0) if fill_px > 0 else 0.0
                tgt_px = 0.0
                stop_frac = stop_pct / 100.0
            cost = qty * fill_px
            cash -= cost
            remain = max(0.0, parent - cost) if iceberg_frac is not None else 0.0
            armed_lines.pop((ticker, letter), None)
            lot = {
                "ticker": ticker,
                "letter": letter,
                "strategy": _letter_token(letter, tf_n),
                "tf": tf_n,
                "qty": qty,
                "entry_px": fill_px,
                "entry_ts": ts.isoformat(),
                "entry_note": note,
                "exit_stop_px": stop_px,
                "exit_tgt_px": tgt_px,
                "exit_r_frac": stop_frac,
                "exit_style": style,
                "1a_handle": handle,
                "exit_high_px": fill_px,
                "exit_runner_on": False,
                "session": sess.isoformat(),
                "remain_usd": remain,
                "iceberg_clips": 1 if iceberg_frac is not None else 0,
                "fat_tape": fat,
                "exit_source": "fat_tape" if fat else "",
                "hold_minutes": room3_recipes.FAT_HOLD_MINUTES if fat else 0,
                "exit_on_letter_flip": bool(fat),
            }
            open_lots.append(lot)
            _mark_fill(ss, letter, ticker, tf=tf_n)
            live.add(letter)

    if events:
        last_ts = events[-1][0]
        ss._now_et = last_ts
    for lot in list(open_lots):
        ticker = str(lot.get("ticker") or "")
        bars = bars_by_ticker.get(ticker) or []
        last = bars[-1] if bars else {}
        px = float((last.get("c") if last else 0) or lot.get("entry_px") or 0)
        close_lot(lot, "eod flatten", px, ss._now_et, float(last.get("v") or 0))
    open_lots = []

    wins = [t for t in closed if float(t.get("pnl_usd") or 0) > 0]
    scratches = [t for t in closed if abs(float(t.get("pnl_usd") or 0)) < 1e-9]
    pnl = sum(float(t.get("pnl_usd") or 0) for t in closed)
    n = len(closed)
    return {
        "session": sess.isoformat(),
        "book": book,
        "cash": cash,
        "pnl_usd": pnl,
        "pnl_pct": (pnl / book * 100.0) if book else 0.0,
        "fills": n,
        "wins": len(wins),
        "scratches": len(scratches),
        "win_rate": (len(wins) / n) if n else None,
        "trades": closed,
        "letters": dict(Counter(str(t.get("letter") or "") for t in closed)),
        "names": sorted({str(t.get("ticker") or "") for t in closed}),
        "missing": [t for t, bars in bars_by_ticker.items() if not bars],
        "tape": {t: len(bars) for t, bars in bars_by_ticker.items()},
    }


def _win_line(pnl_pct: float, wins: int, fills: int, scratches: int) -> str:
    if fills <= 0:
        return "quiet · 0 fills"
    wr = wins / fills * 100.0
    scratch = f" · {scratches} scratch" if scratches else ""
    return f"{pnl_pct:+.1f}% on $1,000 · win rate {wr:.0f}% ({wins} of {fills}){scratch}"


def summarize_days(days: list[dict[str, Any]], book: float = START_BOOK) -> dict[str, Any]:
    trades = [t for d in days for t in (d.get("trades") or [])]
    wins = [t for t in trades if float(t.get("pnl_usd") or 0) > 0]
    scratches = [t for t in trades if abs(float(t.get("pnl_usd") or 0)) < 1e-9]
    pnl = sum(float(d.get("pnl_usd") or 0) for d in days)
    n = len(trades)
    firing = [d for d in days if int(d.get("fills") or 0) > 0]
    mean_fire = (
        sum(float(d.get("pnl_pct") or 0) for d in firing) / len(firing) if firing else 0.0
    )
    return {
        "days": len(days),
        "firing_days": len(firing),
        "fills": n,
        "wins": len(wins),
        "scratches": len(scratches),
        "win_rate": (len(wins) / n) if n else None,
        "pnl_usd": pnl,
        "pnl_pct": (pnl / book * 100.0) if book else 0.0,
        "firing_day_mean_pct": mean_fire,
        "line": _win_line(
            mean_fire if firing else 0.0,
            len(wins),
            n,
            len(scratches),
        )
        if firing
        else "quiet · 0 fills",
    }


def walk_forward(
    *,
    book: float = START_BOOK,
    letters: tuple[str, ...] = LOCKED_1M,
    bars_cache: dict[tuple[str, str], list[dict[str, Any]]] | None = None,
    sessions: list[date] | None = None,
    load_bars=None,
    prefetch: bool = False,
) -> dict[str, Any]:
    days = list(sessions or weekday_sessions())
    loader = load_bars or load_day_bars
    cache = bars_cache if bars_cache is not None else {}
    if prefetch and load_bars is None:
        names = sorted({n for sess in days for n in belt_for(sess)})
        for ticker in names:
            print(f"  tape {ticker} …", flush=True)
            by_day = prefetch_ticker_bars(ticker, days)
            for sess, bars in by_day.items():
                cache[(ticker, sess.isoformat())] = bars
    session_rows: list[dict[str, Any]] = []
    for sess in days:
        names = belt_for(sess)
        bars_by_ticker: dict[str, list[dict[str, Any]]] = {}
        for ticker in names:
            key = (ticker, sess.isoformat())
            if key not in cache:
                cache[key] = loader(ticker, sess)
            bars_by_ticker[ticker] = cache[key]
        session_rows.append(replay_session(sess, bars_by_ticker, book=book, letters=letters))
    by_date = {row["session"]: row for row in session_rows}
    folds_out = []
    for fold in rolling_folds(days):
        train_rows = [by_date[d.isoformat()] for d in fold["train"]]
        test_rows = [by_date[d.isoformat()] for d in fold["test"]]
        folds_out.append(
            {
                "train_dates": [d.isoformat() for d in fold["train"]],
                "test_dates": [d.isoformat() for d in fold["test"]],
                "train": summarize_days(train_rows, book),
                "test": summarize_days(test_rows, book),
            }
        )
    oos = [by_date[d] for fold in folds_out for d in fold["test_dates"]]
    blob = {
        "letters": list(letters),
        "book": book,
        "split": {"train": TRAIN_N, "test": TEST_N, "step": STEP},
        "sessions": session_rows,
        "folds": folds_out,
        "oos": summarize_days(oos, book) if oos else summarize_days([], book),
        "all": summarize_days(session_rows, book),
    }
    blob["validation"] = validate_run(blob)
    return blob


def run_self_tests() -> dict[str, Any]:
    import test_room3_walkforward as t

    names = [n for n in sorted(dir(t)) if n.startswith("test_")]
    failed: list[str] = []
    for name in names:
        try:
            getattr(t, name)()
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    return {"ran": len(names), "failed": failed, "ok": not failed}


def validate_run(blob: dict[str, Any]) -> dict[str, Any]:
    checks: list[tuple[str, bool, str]] = []
    letters = tuple(blob.get("letters") or ())
    checks.append(
        (
            "locked_1m_only",
            letters == LOCKED_1M,
            ",".join(letters),
        )
    )
    book = float(blob.get("book") or 0)
    checks.append(("book_1000", abs(book - START_BOOK) < 1e-9, f"${book:.0f}"))
    days = [date.fromisoformat(r["session"]) for r in blob.get("sessions") or []]
    want = weekday_sessions()
    checks.append(
        (
            "sessions_sep_2_to_11",
            days == want,
            ",".join(d.isoformat() for d in days),
        )
    )
    split = blob.get("split") or {}
    checks.append(
        (
            "rolling_5_1_1",
            split.get("train") == TRAIN_N
            and split.get("test") == TEST_N
            and split.get("step") == STEP,
            str(split),
        )
    )
    folds = blob.get("folds") or []
    oos_dates = [d for fold in folds for d in fold.get("test_dates") or []]
    checks.append(
        (
            "oos_dates",
            oos_dates == [d.isoformat() for fold in rolling_folds() for d in fold["test"]],
            ",".join(oos_dates),
        )
    )
    bad_letter = []
    bad_tf = []
    purg = []
    fat = []
    for row in blob.get("sessions") or []:
        for trade in row.get("trades") or []:
            letter = str(trade.get("letter") or "")
            if letter not in LOCKED_1M:
                bad_letter.append(letter)
            if str(trade.get("tf") or "") != "1m":
                bad_tf.append(str(trade.get("tf") or ""))
            if letter.upper().startswith("P") and letter[1:2].isdigit():
                purg.append(letter)
            notional = float(trade.get("qty") or 0) * float(trade.get("entry_px") or 0)
            if notional > book * TICKET_FRAC + 0.02:
                fat.append(f"{trade.get('ticker')} {letter} ${notional:.0f}")
    checks.append(("fills_locked_letters", not bad_letter, ",".join(bad_letter) or "none"))
    checks.append(("fills_1m_tf", not bad_tf, ",".join(bad_tf) or "none"))
    checks.append(("no_purgatory", not purg, ",".join(purg) or "none"))
    checks.append(("ticket_cap_80pct", not fat, "; ".join(fat) or "ok"))
    missing = [f"{r['session']}:{','.join(r.get('missing') or [])}" for r in blob.get("sessions") or [] if r.get("missing")]
    checks.append(
        (
            "tape_present",
            not missing,
            "; ".join(missing) or "all belt names had 1m bars",
        )
    )
    ok = all(item[1] for item in checks)
    return {
        "ok": ok,
        "checks": [{"name": n, "ok": p, "detail": d} for n, p, d in checks],
    }


def _session_line(row: dict[str, Any]) -> str:
    wr = row.get("win_rate")
    if wr is None:
        wr_s = "+0.0% on $1,000 · quiet · 0 fills"
    else:
        wr_s = f"{row['pnl_pct']:+.1f}% on $1,000 · win rate {wr * 100:.0f}% ({row['wins']} of {row['fills']})"
        if row.get("scratches"):
            wr_s += f" · {row['scratches']} scratch"
    letters = row.get("letters") or {}
    mix = " ".join(f"{k}×{v}" for k, v in letters.items()) if letters else "—"
    miss = row.get("missing") or []
    miss_s = f"  missing tape {','.join(miss)}" if miss else ""
    names = ",".join(row.get("names") or []) or "—"
    return (
        f"{row['session']}  {wr_s}  closed ${row['pnl_usd']:+.2f}  "
        f"letters {mix}  names {names}{miss_s}"
    )


def _print_report(blob: dict[str, Any], tests: dict[str, Any] | None = None) -> None:
    print()
    print("=== SESSION BY SESSION ===")
    print("Locked 1M: " + ", ".join(blob["letters"]))
    print("Tape: Yahoo/Massive 1m  2026-09-02 .. 2026-09-11 weekdays")
    print(f"Book: ${blob['book']:.0f} 1m-only · ticket ≤ {TICKET_FRAC:.0%} of book")
    print("Handle: fill-now. Detect proxy: Hunt extras (no vault Match%). Not live Alpaca.")
    print()
    for row in blob["sessions"]:
        print(_session_line(row))
        for trade in row.get("trades") or []:
            print(
                f"    {trade['ticker']} {trade['letter']}  "
                f"{trade['pnl_pct']:+.1f}%  ${float(trade['pnl_usd']):+.2f}  "
                f"{trade.get('exit_reason')}"
            )

    print()
    print("=== VALIDATIONS ===")
    if tests is not None:
        if tests.get("ok"):
            print(f"PASS  self-tests  {tests['ran']} of {tests['ran']}")
        else:
            print(f"FAIL  self-tests  {tests['ran'] - len(tests['failed'])} of {tests['ran']}")
            for item in tests.get("failed") or []:
                print(f"      {item}")
    val = blob.get("validation") or {}
    for check in val.get("checks") or []:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"{mark}  {check['name']}  {check['detail']}")
    if tests is not None and tests.get("ok") and val.get("ok"):
        print("All validations passed.")
    elif not val.get("ok") or (tests is not None and not tests.get("ok")):
        print("Validation failed — do not use the walk-forward claim.")

    print()
    print("=== WALK-FORWARD CLAIM (OOS TEST FOLDS ONLY) ===")
    print("Rolling split: train 5 / test 1 / step 1 on RTH sessions (Labor Day 2026-09-07 skipped).")
    print("Test days: " + ", ".join(d for fold in blob["folds"] for d in fold["test_dates"]) + ".")
    print("Train numbers below are in-sample only. They are not the claim.")
    print()
    for i, fold in enumerate(blob["folds"], 1):
        te = fold["test"]
        tr = fold["train"]
        print(
            f"Fold {i}  test {', '.join(fold['test_dates'])}  {te['line']}"
            f"  closed ${te['pnl_usd']:+.2f}"
        )
        print(f"         train {fold['train_dates'][0]}..{fold['train_dates'][-1]}  {tr['line']}  ← not the claim")
    print()
    oos = blob["oos"]
    wr = oos.get("win_rate")
    if wr is None:
        claim = "quiet · 0 OOS fills"
    else:
        claim = (
            f"{oos['firing_day_mean_pct']:+.1f}% on $1,000 · "
            f"win rate {wr * 100:.0f}% ({oos['wins']} of {oos['fills']})"
        )
        if oos.get("scratches"):
            claim += f" · {oos['scratches']} scratch"
    print(f"OOS CLAIM  {claim}  closed ${oos['pnl_usd']:+.2f}  ({oos['firing_days']} firing of {oos['days']} test days)")
    print()
    print("=== NOT THE CLAIM ===")
    n_sess = len(blob.get("sessions") or [])
    print(f"All {n_sess} RTH sessions pooled  {blob['all']['line']}  closed ${blob['all']['pnl_usd']:+.2f}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Locked 1m walk-forward on Sep 2–11 belt tape")
    p.add_argument("--book", type=float, default=START_BOOK)
    args = p.parse_args(argv)
    tests = run_self_tests()
    print("Loading 1m bars (one Yahoo + one Massive pull per name)…", flush=True)
    blob = walk_forward(book=float(args.book), prefetch=True)
    _print_report(blob, tests)
    if not tests.get("ok") or not (blob.get("validation") or {}).get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
