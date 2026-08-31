"""
Precursor pack — tape DNA from lookback→start+peek, plus hyper-vol extras.

Used by replay (old windows) and Room 3 live sensors. Does not import Room 2.
"""

from __future__ import annotations

import json
import math
import re
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
SEC_HEADERS = {"User-Agent": "SavantApprentice earmaobusiness@gmail.com"}
MASSIVE_API_BASE = "https://api.massive.com"

LOOKBACK_BARS = {"1m": 5, "5m": 36, "15m": 48}
PEEK_BARS = {"1m": 1, "5m": 1, "15m": 2}
NEWS_DEPTH_DAYS = {"1m": 7, "5m": 14, "15m": 30}

OFFERING_FORMS = frozenset(
    {"S-1", "S-3", "F-1", "F-3", "424B3", "424B4", "424B5", "424B7", "424B8"}
)
DILUTION_FORMS = frozenset(OFFERING_FORMS | {"8-K", "S-8", "424B2"})
INSIDER_FORMS = frozenset({"4", "4/A", "3", "5"})
CATALYST_FORMS = frozenset(
    {"8-K", "8-K/A", "6-K", "SC 13D", "SC 13G", "SC 13D/A", "4", "S-3", "S-1", "424B5"}
)

_CIK_INDEX: dict[str, str] | None = None
_SUBMISSIONS: dict[str, dict[str, Any]] = {}
_INFO: dict[str, dict[str, Any]] = {}
_BARS: dict[str, Any] = {}
_MASSIVE_LAST = 0.0
_FEED_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="r3feed")
_LIVE_YF_TTL = 14.0
_LIVE_EMPTY_TTL = 20.0
_MASSIVE_LIVE_TICKER_TTL = 900.0
_LIVE_1M: dict[str, dict[str, Any]] = {}
_MASSIVE_LIVE_TICKER: dict[str, float] = {}


def tf_token(raw: str) -> str:
    t = str(raw or "").lower().replace("-", "").replace(" ", "")
    if "15" in t:
        return "15m"
    if t.startswith("5") or "5m" in t or "5min" in t:
        return "5m"
    if t.startswith("1") or "1m" in t or "1min" in t:
        return "1m"
    return "5m"


def _parse_clock(raw: str) -> tuple[int, int] | None:
    text = re.sub(r"\s+", " ", str(raw or "").strip().upper())
    if not text:
        return None
    text = re.sub(r"(?<=\d)(AM|PM)$", r" \1", text)
    match = re.search(
        r"(?:(\d{4}-\d{2}-\d{2})[T ])?(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?",
        text,
    )
    if not match:
        return None
    hour = int(match.group(2))
    minute = int(match.group(3))
    ampm = match.group(4) or ""
    if ampm == "PM" and hour < 12:
        hour += 12
    if ampm == "AM" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        blob = json.loads(raw)
        return blob if isinstance(blob, dict) else {}
    except Exception:
        return {}


def session_date_from_row(row: dict[str, Any]) -> date | None:
    et = str(row.get("entry_time") or "")
    stamped = re.search(r"(\d{4}-\d{2}-\d{2})", et)
    if stamped:
        return date.fromisoformat(stamped.group(1))
    day_ctx = _parse_json(row.get("day_context_json"))
    for key in ("session_date", "start_date", "end_date"):
        text = str(day_ctx.get(key) or "")[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
    ctx = str(row.get("operator_context") or "")
    if "DAY_CONTEXT:" in ctx:
        try:
            blob = ctx.split("DAY_CONTEXT:", 1)[1]
            if " | " in blob:
                blob = blob.split(" | ", 1)[0]
            parsed = json.loads(blob)
            text = str((parsed or {}).get("session_date") or "")[:10]
            if re.match(r"\d{4}-\d{2}-\d{2}", text):
                return date.fromisoformat(text)
        except Exception:
            pass
    for key in ("entry_time", "exit_time", "timestamp"):
        text = str(row.get(key) or "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
        if m:
            return date.fromisoformat(m.group(1))
    return None


def window_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(row.get("ticker") or "").strip().upper()
    if not ticker or ticker.startswith("_"):
        return None
    sess = session_date_from_row(row)
    if sess is None:
        return None
    start_hm = _parse_clock(str(row.get("entry_time") or ""))
    end_hm = _parse_clock(str(row.get("exit_time") or ""))
    if not start_hm:
        return None
    tf = tf_token(str(row.get("timeframe_resolution") or row.get("timeframe") or ""))
    start_dt = datetime(sess.year, sess.month, sess.day, start_hm[0], start_hm[1])
    end_sess = sess
    xt = str(row.get("exit_time") or "")
    xm = re.search(r"(\d{4}-\d{2}-\d{2})", xt)
    if xm:
        try:
            end_sess = date.fromisoformat(xm.group(1))
        except ValueError:
            end_sess = sess
    if end_hm:
        end_dt = datetime(end_sess.year, end_sess.month, end_sess.day, end_hm[0], end_hm[1])
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
    else:
        end_dt = start_dt + timedelta(minutes=30)
    return {
        "ticker": ticker,
        "tf": tf,
        "session_date": sess,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "row_id": row.get("id"),
    }


def _yahoo_info_pull(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    return dict(yf.Ticker(ticker).info or {})


def _yahoo_info(ticker: str) -> dict[str, Any]:
    tk = str(ticker or "").upper()
    if tk in _INFO:
        return _INFO[tk]
    info: dict[str, Any] = {}
    try:
        info = dict(_FEED_POOL.submit(_yahoo_info_pull, tk).result(timeout=8) or {})
    except Exception:
        info = {}
    _INFO[tk] = info
    return info


def _cik_for(ticker: str) -> str:
    global _CIK_INDEX
    tk = str(ticker or "").upper()
    if _CIK_INDEX is None:
        _CIK_INDEX = {}
        try:
            resp = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=SEC_HEADERS,
                timeout=8,
            )
            if resp.ok:
                for entry in (resp.json() or {}).values():
                    t = str(entry.get("ticker") or "").upper()
                    cik = str(entry.get("cik_str") or "").zfill(10)
                    if t and cik:
                        _CIK_INDEX[t] = cik
        except Exception:
            pass
    return (_CIK_INDEX or {}).get(tk, "")


def _sec_submissions(ticker: str) -> dict[str, Any]:
    tk = str(ticker or "").upper()
    if tk in _SUBMISSIONS:
        return _SUBMISSIONS[tk]
    cik = _cik_for(tk)
    blob: dict[str, Any] = {}
    if cik:
        try:
            resp = requests.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=SEC_HEADERS,
                timeout=8,
            )
            if resp.ok:
                blob = resp.json() if isinstance(resp.json(), dict) else {}
        except Exception:
            blob = {}
    _SUBMISSIONS[tk] = blob
    return blob


def filings_before(
    ticker: str,
    as_of: date,
    *,
    lookback_days: int,
) -> list[dict[str, str]]:
    recent = (_sec_submissions(ticker).get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    start = as_of - timedelta(days=max(1, int(lookback_days)))
    out: list[dict[str, str]] = []
    for form, filed in zip(forms, dates):
        form_s = str(form or "").strip()
        date_s = str(filed or "").strip()[:10]
        if not form_s or not re.match(r"\d{4}-\d{2}-\d{2}", date_s):
            continue
        d = date.fromisoformat(date_s)
        if start <= d <= as_of:
            out.append({"form": form_s, "date": date_s})
    return out


def _log10(x: float) -> float:
    return round(math.log10(1.0 + max(0.0, float(x))), 4)


def tape_vector(window) -> list[float]:
    """Same 8-dim shape Room 3 live uses (log volume so share-count cannot crush cosine)."""
    if window is None or getattr(window, "empty", True):
        return []
    closes = [float(x) for x in window["Close"].astype(float).tolist() if float(x) > 0]
    vols = [float(x) for x in window["Volume"].astype(float).fillna(0).tolist()]
    if len(closes) < 3:
        return []
    rets = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        rets.append(((closes[i] - prev) / prev) if prev else 0.0)
    session_velocity = ((closes[-1] - closes[0]) / closes[0] * 100.0) if closes[0] else 0.0
    peak_bar = (max(abs(r) for r in rets) * 100.0) if rets else 0.0
    mean_bar = ((sum(abs(r) for r in rets) / len(rets)) * 100.0) if rets else 0.0
    pos_vols = [v for v in vols if v > 0]
    vol_sigma = 0.0
    vol_z = 0.0
    if len(pos_vols) > 1:
        avg_v = sum(pos_vols) / len(pos_vols)
        var_v = sum((v - avg_v) ** 2 for v in pos_vols) / len(pos_vols)
        vol_sigma = math.sqrt(var_v)
        if vol_sigma > 0:
            vol_z = (pos_vols[-1] - avg_v) / vol_sigma
    highs = [float(x) for x in window["High"].astype(float).tolist()]
    lows = [float(x) for x in window["Low"].astype(float).tolist()]
    spreads = []
    for h, l, c in zip(highs, lows, closes):
        if c:
            spreads.append((h - l) / c * 100.0)
    mean_close = sum(closes) / len(closes)
    vwap_bias = ((closes[-1] - mean_close) / closes[-1] * 100.0) if closes[-1] else 0.0
    n = min(8, len(closes))
    tail = closes[-n:]
    mean = sum(tail) / n
    num = sum((x - mean) * (i - (n - 1) / 2.0) for i, x in enumerate(tail))
    den_x = math.sqrt(sum((i - (n - 1) / 2.0) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((x - mean) ** 2 for x in tail))
    pearson = (num / (den_x * den_y)) if den_x > 0 and den_y > 0 else 0.0
    return [
        round(session_velocity, 4),
        round(peak_bar, 4),
        round(mean_bar, 4),
        _log10(vol_sigma),
        round(vol_z, 4),
        round(vwap_bias, 4),
        0.0,
        round(max(-1.0, min(1.0, pearson)), 4),
    ]


def extra_pack(
    ticker: str,
    *,
    tf: str,
    as_of: date,
    window=None,
    full_day=None,
) -> dict[str, Any]:
    """Hyper-vol extras. Historical: SEC as-of date. Float/SI from Yahoo (current snapshot)."""
    def _f(val: Any, default: float = 0.0) -> float:
        try:
            if val in (None, "", "N/A", "None"):
                return default
            return float(val)
        except (TypeError, ValueError):
            return default

    info = _yahoo_info(ticker)
    float_shares = _f(info.get("floatShares") or info.get("sharesOutstanding"))
    short_pct = _f(info.get("shortPercentOfFloat"))
    if short_pct > 1.5:
        short_pct = short_pct / 100.0
    short_ratio = _f(info.get("shortRatio"))
    avg_vol = _f(info.get("averageVolume") or info.get("averageVolume10days"))
    bid = _f(info.get("bid"))
    ask = _f(info.get("ask"))
    spread_live = ((ask - bid) / ((ask + bid) / 2.0) * 100.0) if bid and ask and ask > bid else 0.0

    win_vol = 0.0
    spread_bar = 0.0
    rvol = 0.0
    pm_rvol = 0.0
    halt_gap = False
    if window is not None and not getattr(window, "empty", True):
        vols = window["Volume"].astype(float).fillna(0)
        win_vol = float(vols.sum())
        if avg_vol > 0:
            rvol = win_vol / max(avg_vol * (len(vols) / 78.0), 1.0)
        closes = window["Close"].astype(float)
        highs = window["High"].astype(float)
        lows = window["Low"].astype(float)
        spread_bar = float(((highs - lows) / closes.replace(0, float("nan")) * 100).mean() or 0)
        idx = list(window.index)
        if len(idx) >= 3:
            deltas = [(idx[i] - idx[i - 1]).total_seconds() for i in range(1, len(idx))]
            typical = sorted(deltas)[len(deltas) // 2] if deltas else 0
            halt_gap = bool(typical and max(deltas) > typical * 4)

    if full_day is not None and not getattr(full_day, "empty", True):
        try:
            pm = full_day[full_day.index.strftime("%H:%M") < "09:30"]
            rth = full_day[full_day.index.strftime("%H:%M") >= "09:30"]
            pm_vol = float(pm["Volume"].astype(float).fillna(0).sum()) if len(pm) else 0.0
            rth_avg = float(rth["Volume"].astype(float).fillna(0).mean() or 0) if len(rth) else 0.0
            if rth_avg > 0:
                pm_rvol = pm_vol / max(rth_avg * max(len(pm), 1), 1.0)
        except Exception:
            pm_rvol = 0.0

    depth = int(NEWS_DEPTH_DAYS.get(tf, 14))
    filings = filings_before(ticker, as_of, lookback_days=depth)
    bases = [f["form"].split("/")[0].upper() for f in filings]
    offering = any(b in OFFERING_FORMS for b in bases)
    dilution = any(b in DILUTION_FORMS for b in bases)
    insider = any(b in INSIDER_FORMS for b in bases)
    catalyst = any(b in CATALYST_FORMS for b in bases)
    rotation = (win_vol / float_shares) if float_shares > 0 else 0.0

    def _cell(ok: bool | None, note: str, **extra: Any) -> dict[str, Any]:
        cell = {"ok": ok, "note": note}
        cell.update(extra)
        return cell

    pack = {
        "charts": _cell(window is not None and not getattr(window, "empty", True), "precursor tape"),
        "vwap": _cell(True, "window close vs mean"),
        "rvol": _cell(rvol > 0, "window volume vs typical", value=round(rvol, 3)),
        "sec": _cell(catalyst, "EDGAR as-of window", filings=filings[:8]),
        "news": _cell(catalyst, "dated filings stand in for wires (RSS is current-only)"),
        "social": _cell(None, "historical social not archived — live only"),
        "float": _cell(float_shares > 0, "Yahoo float (current snapshot)", value=int(float_shares)),
        "short_interest": _cell(short_pct > 0, "Yahoo SI % of float", value=round(short_pct, 4)),
        "dilution": _cell(dilution, "S-3 / 424B / 8-K in lookback"),
        "halt": _cell(halt_gap, "bar-gap proxy in precursor window"),
        "spread": _cell(True, "bar range %", value=round(spread_bar or spread_live, 4)),
        "prints": _cell(tf == "1m", "aggressive tape (1m)"),
        "bid_ask": _cell(bool(bid and ask), "inside spread", value=round(spread_live, 4)),
        "premarket_rvol": _cell(tf in ("5m", "15m"), "pre-open vs RTH", value=round(pm_rvol, 3)),
        "float_rotation": _cell(rotation > 0, "window volume / float", value=round(rotation, 6)),
        "offering": _cell(offering, "shelf / 424B in lookback"),
        "insider": _cell(insider, "Form 4 in lookback"),
        "borrow": _cell(short_ratio > 0, "days-to-cover proxy", value=round(short_ratio, 3)),
        "sector": _cell(None, "peer tape not dated — live only"),
        "days_to_cover": _cell(short_ratio > 0, "Yahoo shortRatio", value=round(short_ratio, 3)),
    }
    return pack


def _to_et_naive(frame):
    if frame is None or getattr(frame, "empty", True):
        return frame
    try:
        idx = frame.index
        if getattr(idx, "tz", None) is not None:
            frame = frame.copy()
            frame.index = idx.tz_convert(ET).tz_localize(None)
    except Exception:
        pass
    return frame


def fetch_bars_yahoo(ticker: str, sess: date, tf: str):
    age = (date.today() - sess).days
    if tf == "1m" and age > 7:
        return None
    if tf in ("5m", "15m") and age > 55:
        return None
    key = f"yf|{ticker}|{sess.isoformat()}|{tf}"
    if key in _BARS:
        return _BARS[key]
    frame = None
    try:
        import yfinance as yf

        interval = {"1m": "1m", "5m": "5m", "15m": "15m"}[tf]
        start = sess - timedelta(days=5)
        end = sess + timedelta(days=2)
        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=interval,
            auto_adjust=False,
            prepost=True,
            progress=False,
            threads=False,
        )
        if hist is not None and not hist.empty:
            if getattr(hist.columns, "nlevels", 1) > 1:
                hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
            frame = _to_et_naive(hist)
    except Exception:
        frame = None
    _BARS[key] = frame
    return frame


def _market_key() -> str:
    try:
        import vault_bridge

        for name in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
            val = vault_bridge._secret_or_env(name)
            if val and "your-" not in val.lower():
                return val
    except Exception:
        pass
    return ""


def fetch_bars_massive(ticker: str, sess: date):
    """1m aggs for the session ±1 day, cached. Resample later."""
    key = f"ms|{ticker}|{sess.isoformat()}"
    if key in _BARS:
        return _BARS[key]
    api_key = _market_key()
    if not api_key:
        _BARS[key] = None
        return None
    import time as _time

    global _MASSIVE_LAST
    wait = 12.0 - (_time.monotonic() - _MASSIVE_LAST)
    if _MASSIVE_LAST > 0 and wait > 0:
        _time.sleep(wait)
    start = (sess - timedelta(days=2)).isoformat()
    end = (sess + timedelta(days=1)).isoformat()
    url = f"{MASSIVE_API_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{start}/{end}"
    frame = None
    try:
        resp = requests.get(
            url,
            params={"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": api_key},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=45,
        )
        _MASSIVE_LAST = _time.monotonic()
        payload = resp.json() if resp.ok else {}
        rows = payload.get("results") if isinstance(payload, dict) else None
        if rows:
            import pandas as pd

            idx = [
                datetime.fromtimestamp(int(r["t"]) / 1000.0, tz=timezone.utc)
                .astimezone(ET)
                .replace(tzinfo=None)
                for r in rows
            ]
            frame = pd.DataFrame(
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
        frame = None
        _MASSIVE_LAST = _time.monotonic()
    _BARS[key] = frame
    return frame


def _resample(frame, tf: str):
    if frame is None or getattr(frame, "empty", True) or tf == "1m":
        return frame
    rule = {"5m": "5min", "15m": "15min"}[tf]
    try:
        return (
            frame.resample(rule)
            .agg(
                {
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                }
            )
            .dropna(subset=["Close"])
        )
    except Exception:
        return frame


def load_session_bars(ticker: str, sess: date, tf: str):
    yf_frame = fetch_bars_yahoo(ticker, sess, tf)
    if yf_frame is not None and not getattr(yf_frame, "empty", True):
        day = yf_frame[yf_frame.index.date == sess]
        if day is not None and not day.empty:
            return yf_frame
    ms = fetch_bars_massive(ticker, sess)
    return _resample(ms, tf)


def _frame_empty(frame) -> bool:
    return frame is None or getattr(frame, "empty", True)


def _yahoo_1m_live(ticker: str):
    def _pull():
        import yfinance as yf

        hist = yf.Ticker(ticker).history(
            period="1d",
            interval="1m",
            auto_adjust=True,
            prepost=True,
        )
        if hist is None or getattr(hist, "empty", True):
            hist = yf.Ticker(ticker).history(
                period="5d",
                interval="1m",
                auto_adjust=True,
                prepost=True,
            )
        if hist is None or getattr(hist, "empty", True):
            return None
        return _to_et_naive(hist)

    try:
        return _FEED_POOL.submit(_pull).result(timeout=12)
    except Exception:
        return None


def _alpaca_1m_live(ticker: str):
    def _pull():
        import room3_alpaca

        return room3_alpaca.fetch_today_1m_bars(ticker, paper=True)

    try:
        frame = _FEED_POOL.submit(_pull).result(timeout=10)
    except Exception:
        return None
    return _to_et_naive(frame)


def _massive_live_ok(ticker: str) -> bool:
    now = _time.monotonic()
    if _MASSIVE_LAST > 0 and (now - _MASSIVE_LAST) < 12.0:
        return False
    last = float(_MASSIVE_LIVE_TICKER.get(ticker) or 0)
    if last and (now - last) < _MASSIVE_LIVE_TICKER_TTL:
        return False
    return bool(_market_key())


def _massive_today_1m(ticker: str):
    """Same-day 1m only. Never sleeps — skip if the 12s lock is held."""
    global _MASSIVE_LAST
    api_key = _market_key()
    if not api_key:
        return None
    today = datetime.now(ET).date().isoformat()
    url = f"{MASSIVE_API_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{today}/{today}"
    _MASSIVE_LIVE_TICKER[ticker] = _time.monotonic()
    try:
        resp = requests.get(
            url,
            params={"adjusted": "false", "sort": "asc", "limit": 5000, "apiKey": api_key},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8,
        )
        _MASSIVE_LAST = _time.monotonic()
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
        _MASSIVE_LAST = _time.monotonic()
        return None


def _live_1m_cached(ticker: str, *, allow_massive: bool) -> tuple[Any, str]:
    now = _time.monotonic()
    hit = _LIVE_1M.get(ticker)
    if isinstance(hit, dict):
        age = now - float(hit.get("t") or 0)
        empty = _frame_empty(hit.get("frame"))
        ttl = _LIVE_EMPTY_TTL if empty else _LIVE_YF_TTL
        if age < ttl:
            return hit.get("frame"), str(hit.get("source") or "yahoo")
    frame = _yahoo_1m_live(ticker)
    source = "yahoo"
    if _frame_empty(frame) and allow_massive and _massive_live_ok(ticker):
        ms = _massive_today_1m(ticker)
        if not _frame_empty(ms):
            frame = ms
            source = "massive"
    if _frame_empty(frame):
        ap = _alpaca_1m_live(ticker)
        if not _frame_empty(ap):
            frame = ap
            source = "alpaca"
    _LIVE_1M[ticker] = {"t": now, "frame": frame, "source": source}
    return frame, source


def _rows_from_1m(frame, tf: str, bars_keep: int) -> list[dict[str, Any]]:
    chopped = _resample(frame, tf)
    if _frame_empty(chopped):
        return []
    keep = max(3, min(120, int(bars_keep or 8)))
    tail = chopped.tail(keep)
    out: list[dict[str, Any]] = []
    for idx, row in tail.iterrows():
        out.append(
            {
                "ts": str(idx),
                "o": float(row["Open"]),
                "h": float(row["High"]),
                "l": float(row["Low"]),
                "c": float(row["Close"]),
                "v": float(row["Volume"]) if "Volume" in row else 0.0,
            }
        )
    return out


def peek_live_bar_rows(
    ticker: str, tf: str, *, bars_keep: int
) -> tuple[list[dict[str, Any]] | None, str]:
    """Reuse a fresh Yahoo 1m pull (resampled). None = cache miss, must fetch."""
    tk = str(ticker or "").upper()
    hit = _LIVE_1M.get(tk)
    if not isinstance(hit, dict):
        return None, ""
    if (_time.monotonic() - float(hit.get("t") or 0)) >= _LIVE_YF_TTL:
        return None, ""
    return _rows_from_1m(hit.get("frame"), tf, bars_keep), str(hit.get("source") or "yahoo")


def live_bar_rows(
    ticker: str,
    tf: str,
    *,
    bars_keep: int,
    allow_massive: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Yahoo 1m first. Massive only if Yahoo is empty and quota lock allows."""
    tk = str(ticker or "").upper()
    frame, source = _live_1m_cached(tk, allow_massive=allow_massive)
    return _rows_from_1m(frame, tf, bars_keep), source


def precursor_window(frame, start_dt: datetime, tf: str):
    if frame is None or getattr(frame, "empty", True):
        return None, None
    look = int(LOOKBACK_BARS.get(tf, 36))
    peek = int(PEEK_BARS.get(tf, 1))
    before = frame[frame.index < start_dt].tail(look)
    after = frame[frame.index >= start_dt].head(max(1, peek + 1))
    import pandas as pd

    parts = [p for p in (before, after) if p is not None and not p.empty]
    if not parts:
        return None, None
    window = pd.concat(parts)
    fence = after.index[-1] if after is not None and not after.empty else start_dt
    return window, fence


def already_replayed(row: dict[str, Any]) -> bool:
    blob = _parse_json(row.get("master_signature_json"))
    return bool(blob.get("precursor_replayed_at"))


def build_signature_blob(
    *,
    vector: list[float],
    pack: dict[str, Any],
    window_meta: dict[str, Any],
    existing: Any = None,
) -> str:
    prev = _parse_json(existing)
    body = {
        "master_signature": [float(x) for x in vector[:8]],
        "precursor_pack": pack,
        "precursor_window": {
            "ticker": window_meta.get("ticker"),
            "tf": window_meta.get("tf"),
            "session_date": str(window_meta.get("session_date") or ""),
            "start": window_meta["start_dt"].strftime("%Y-%m-%d %H:%M")
            if window_meta.get("start_dt")
            else "",
            "end": window_meta["end_dt"].strftime("%Y-%m-%d %H:%M")
            if window_meta.get("end_dt")
            else "",
        },
        "precursor_replayed_at": datetime.now(timezone.utc).isoformat(),
    }
    if prev.get("overlap_pct") is not None:
        body["overlap_pct"] = prev.get("overlap_pct")
    return json.dumps(body, default=str)


def live_sensor_overlay(ticker: str, tf: str = "15m") -> dict[str, Any]:
    """Current extras for the live watch book (as-of today)."""
    today = datetime.now(ET).date()
    return extra_pack(ticker, tf=tf, as_of=today)
