"""
Room 3 built-in RTH screener — Job 1.

Periodic light scan on liquid NASDAQ + NYSE (Alpaca tradable universe).
Survivors feed the watch book for 1m / 5m / 15m maps + matrix path.

Thresholds are tunable; operator refines to match their TradingView screener.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import room3_alpaca

ET = ZoneInfo("America/New_York")

SCAN_INTERVAL_MINUTES = 18
BATCH_SIZE = 80
UNIVERSE_CAP = 3500  # safety cap on symbols per pass

DEFAULT_RULES: dict[str, Any] = {
    "min_volatility_pct": 30.0,  # 30-day hist vol annualized
    "require_price_above_hma9": True,
    "min_dollar_volume": 10_000_000.0,  # price × today's volume
    "min_dollar_avg_vol_10d": 10_000_000.0,  # price × 10d avg volume
    "max_market_cap": 1_000_000_000.0,  # exclude above $1B
    "require_volume_vs_float": True,
    "high_float_shares": 90_000_000.0,  # mega-float: time-of-day ratio instead of vol > float
    "low_float_shares": 2_000_000.0,  # tiny float: stricter headroom above float
    "min_price": 1.0,
    "exchanges": ("NASDAQ", "NYSE", "AMEX"),
}


def default_rules() -> dict[str, Any]:
    return dict(DEFAULT_RULES)


def _wma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    tail = values[-period:]
    weights = list(range(1, period + 1))
    denom = sum(weights)
    if denom <= 0:
        return None
    return sum(v * w for v, w in zip(tail, weights)) / denom


def hull_ma9(closes: list[float]) -> float | None:
    n = 9
    if len(closes) < n:
        return None
    half = max(1, n // 2)
    sqrt_n = max(1, int(math.sqrt(n)))
    wma_half = _wma(closes, half)
    wma_full = _wma(closes, n)
    if wma_half is None or wma_full is None:
        return None
    raw = [2.0 * wma_half - wma_full]
    # Need sqrt_n points of intermediate series — approximate with last close stream
    # Standard HMA: WMA(sqrt(n)) of (2*WMA(n/2) - WMA(n))
    series: list[float] = []
    for i in range(len(closes) - n + 1, len(closes) + 1):
        chunk = closes[:i]
        wh = _wma(chunk, half)
        wf = _wma(chunk, n)
        if wh is not None and wf is not None:
            series.append(2.0 * wh - wf)
    if len(series) < sqrt_n:
        return series[-1] if series else None
    return _wma(series, sqrt_n)


def historical_vol_pct(closes: list[float], lookback: int = 30) -> float | None:
    if len(closes) < lookback + 1:
        return None
    rets: list[float] = []
    tail = closes[-(lookback + 1) :]
    for i in range(1, len(tail)):
        prev = tail[i - 1]
        cur = tail[i]
        if prev > 0:
            rets.append(math.log(cur / prev))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return math.sqrt(var) * math.sqrt(252.0) * 100.0


def fetch_nyse_nasdaq_universe(*, paper: bool = True, cap: int = UNIVERSE_CAP) -> list[str]:
    """Alpaca tradable US equities on major exchanges."""
    try:
        client = room3_alpaca._trading_client(paper=paper)
        assets = client.get_all_assets() or []
    except Exception:
        return []
    allowed = {str(x).upper() for x in DEFAULT_RULES.get("exchanges") or ("NASDAQ", "NYSE")}
    out: list[str] = []
    seen: set[str] = set()
    for a in assets:
        try:
            if str(getattr(a, "status", "") or "").lower() != "active":
                continue
            if not bool(getattr(a, "tradable", False)):
                continue
            sym = str(getattr(a, "symbol", "") or "").upper()
            if not sym or sym in seen or "." in sym:
                continue
            exch = str(getattr(a, "exchange", "") or "").upper()
            if exch not in allowed:
                continue
            seen.add(sym)
            out.append(sym)
            if len(out) >= cap:
                break
        except Exception:
            continue
    return sorted(out)


def _metrics_from_history(hist) -> dict[str, float] | None:
    try:
        if hist is None or hist.empty:
            return None
        if "Close" not in hist.columns or "Volume" not in hist.columns:
            return None
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        vols = [float(x) for x in hist["Volume"].dropna().tolist()]
        if len(closes) < 12 or len(vols) < 10:
            return None
        close = closes[-1]
        vol_today = vols[-1]
        avg_vol_10 = sum(vols[-10:]) / min(10, len(vols[-10:]))
        hma = hull_ma9(closes)
        vol_pct = historical_vol_pct(closes)
        if close <= 0:
            return None
        return {
            "close": close,
            "vol_pct": float(vol_pct or 0),
            "hma9": float(hma or 0),
            "volume_shares": vol_today,
            "dollar_volume": close * vol_today,
            "dollar_avg_vol_10d": close * avg_vol_10,
        }
    except Exception:
        return None


def passes_rules(metrics: dict[str, float], rules: dict[str, Any]) -> bool:
    """Stage 1 — price/vol/HMA/dollar-volume only (no float or market cap yet)."""
    if metrics["close"] < float(rules.get("min_price") or 0):
        return False
    if metrics["vol_pct"] < float(rules.get("min_volatility_pct") or 0):
        return False
    if rules.get("require_price_above_hma9") and metrics["hma9"] > 0:
        if metrics["close"] <= metrics["hma9"]:
            return False
    if metrics["dollar_volume"] < float(rules.get("min_dollar_volume") or 0):
        return False
    if metrics["dollar_avg_vol_10d"] < float(rules.get("min_dollar_avg_vol_10d") or 0):
        return False
    return True


def required_volume_float_ratio(
    float_shares: float,
    *,
    now_et: datetime | None = None,
    rules: dict[str, Any] | None = None,
) -> float:
    """
    Minimum volume / float ratio for a name to pass.

    Default (mid float): volume must exceed float (> 1.0).
    Mega-float (~90M+): 50% pre-9:30 → 60% → 75% → 80% by noon (ET).
    Low float (≤2M): stricter headroom — closer to or above full float.
    """
    rules = rules or default_rules()
    now_et = now_et or datetime.now(ET)
    high = float(rules.get("high_float_shares") or 90_000_000)
    low = float(rules.get("low_float_shares") or 2_000_000)

    if float_shares >= high:
        minutes = now_et.hour * 60 + now_et.minute
        if minutes < 9 * 60 + 30:  # 4:00–9:30 ET
            return 0.50
        if minutes < 10 * 60:  # 9:30–10:00
            return 0.60
        if minutes < 12 * 60:  # 10:00–12:00
            return 0.75
        return 0.80

    if float_shares <= 500_000:
        return 1.50
    if float_shares <= 1_000_000:
        return 1.25
    if float_shares <= low:
        return 1.05

    return 1.001  # volume strictly above float


def passes_volume_vs_float(
    volume_shares: float,
    float_shares: float | None,
    *,
    now_et: datetime | None = None,
    rules: dict[str, Any] | None = None,
) -> bool:
    if float_shares is None or float_shares <= 0:
        return False
    ratio = required_volume_float_ratio(float_shares, now_et=now_et, rules=rules)
    return volume_shares >= float_shares * ratio


def passes_market_cap(market_cap: float | None, rules: dict[str, Any] | None = None) -> bool:
    rules = rules or default_rules()
    cap_max = float(rules.get("max_market_cap") or 0)
    if cap_max <= 0:
        return True
    if market_cap is None or market_cap <= 0:
        return False
    return market_cap <= cap_max


def fetch_share_stats(sym: str) -> dict[str, float | None]:
    """Float + market cap from yfinance (stage-2 only — called on survivors)."""
    import yfinance as yf

    try:
        info = yf.Ticker(sym).info or {}
        raw_float = info.get("floatShares") or info.get("sharesOutstanding")
        raw_cap = info.get("marketCap")
        float_shares = float(raw_float) if raw_float else None
        market_cap = float(raw_cap) if raw_cap else None
        if float_shares is not None and float_shares <= 0:
            float_shares = None
        if market_cap is not None and market_cap <= 0:
            market_cap = None
        return {"float_shares": float_shares, "market_cap": market_cap}
    except Exception:
        return {"float_shares": None, "market_cap": None}


def passes_structure_rules(
    metrics: dict[str, float],
    share_stats: dict[str, float | None],
    rules: dict[str, Any],
    *,
    now_et: datetime | None = None,
) -> bool:
    """Stage 2 — market cap ceiling + volume vs float."""
    if not passes_market_cap(share_stats.get("market_cap"), rules):
        return False
    if not rules.get("require_volume_vs_float", True):
        return True
    return passes_volume_vs_float(
        metrics.get("volume_shares") or 0,
        share_stats.get("float_shares"),
        now_et=now_et,
        rules=rules,
    )


def scan_universe(
    symbols: list[str],
    *,
    rules: dict[str, Any] | None = None,
    max_pass: int = 40,
) -> dict[str, Any]:
    """
    Two-stage light pass — daily history, then float/market-cap on survivors.
    Returns tickers sorted by dollar volume desc.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rules = rules or default_rules()
    started = datetime.now(ET)
    stage1: list[tuple[str, dict[str, float]]] = []
    scanned = 0
    errors = 0
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    for i in range(0, len(syms), BATCH_SIZE):
        batch = syms[i : i + BATCH_SIZE]
        tickers_str = " ".join(batch)
        try:
            data = yf.download(
                tickers_str,
                period="3mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception:
            errors += len(batch)
            continue
        if data is None or getattr(data, "empty", True):
            errors += len(batch)
            continue
        for sym in batch:
            scanned += 1
            try:
                if len(batch) == 1:
                    hist = data
                else:
                    hist = data[sym] if sym in data.columns.get_level_values(0) else None
                m = _metrics_from_history(hist)
                if not m:
                    continue
                if passes_rules(m, rules):
                    stage1.append((sym, m))
            except Exception:
                errors += 1

    passed: list[tuple[str, float]] = []
    structure_rejected = 0
    if stage1:
        stats_by_sym: dict[str, dict[str, float | None]] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_share_stats, sym): sym for sym, _ in stage1}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    stats_by_sym[sym] = fut.result()
                except Exception:
                    stats_by_sym[sym] = {"float_shares": None, "market_cap": None}

        for sym, m in stage1:
            stats = stats_by_sym.get(sym) or {"float_shares": None, "market_cap": None}
            if passes_structure_rules(m, stats, rules, now_et=started):
                passed.append((sym, m["dollar_volume"]))
            else:
                structure_rejected += 1

    passed.sort(key=lambda x: x[1], reverse=True)
    tickers = [t for t, _ in passed[: int(max_pass)]]
    elapsed = (datetime.now(ET) - started).total_seconds()
    return {
        "ok": True,
        "tickers": tickers,
        "passed": len(passed),
        "stage1_passed": len(stage1),
        "structure_rejected": structure_rejected,
        "scanned": scanned,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "at": started.strftime("%H:%M:%S ET"),
    }


def run_rth_scan(*, paper: bool = True, rules: dict[str, Any] | None = None, max_pass: int = 40) -> dict[str, Any]:
    universe = fetch_nyse_nasdaq_universe(paper=paper)
    if not universe:
        return {
            "ok": False,
            "tickers": [],
            "error": "universe empty — Alpaca connection or assets unavailable",
            "scanned": 0,
            "passed": 0,
        }
    result = scan_universe(universe, rules=rules, max_pass=max_pass)
    result["universe_size"] = len(universe)
    return result
