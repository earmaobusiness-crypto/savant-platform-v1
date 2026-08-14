"""
Room 3 built-in screener — Job 1 (FILTER ONLY).

Architecture:
  Job 1 · Screener  → cheap yes/no on full universe → small belt (~5–15)
  Job 2 · Watcher   → 1m/5m/15m maps + matrix compare (survivors only)
  Job 3 · Execution → Alpaca when armed + match

This module must NOT do map/matrix work. Deep daily history is only for
filter fields (HMA / vol) on a short liquid shortlist — never on all ~8k.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import room3_alpaca

ET = ZoneInfo("America/New_York")

SCAN_INTERVAL_MINUTES = 18
BATCH_SIZE = 120
UNIVERSE_CAP = 20000  # safety ceiling only — do NOT truncate mid-list (drops WETO/CAPR/etc.)
YF_PERIOD = "2mo"  # deep history for HMA + 30d vol (Pass B shortlist only)
YF_PRESCREEN_PERIOD = "5d"  # Pass A — cheap liquidity on the full list
YF_BATCH_WORKERS = 8
DEEP_SCAN_CAP = 200  # Pass B: max names that get full 2mo HMA/vol (not Job 2 maps)
BELT_MAX = 15  # Job 1 output cap → Job 2 maps only these

# Alpaca lists leveraged single-stock products as us_equity — strip by name.
_ETF_NAME_MARKERS = (
    " ETF",
    "ETN",
    "2X",
    "3X",
    "1X",
    " BULL ",
    " BEAR ",
    "DIREXION",
    "GRANITESHARES",
    "PROSHARES",
    "DEFIANCE",
    "LEVERAGE SHARES",
    "ULTRAPRO",
    "ULTRASHORT",
    "DAILY TARGET",
    "INVERSE",
)

DEFAULT_RULES: dict[str, Any] = {
    "min_volatility_pct": 30.0,  # 30-day hist vol annualized
    "require_price_above_hma9": True,
    "min_dollar_volume": 10_000_000.0,  # price × today's volume
    "min_dollar_avg_vol_10d": 10_000_000.0,  # price × 10d avg volume
    "max_market_cap": 1_000_000_000.0,  # exclude above $1B
    "require_volume_vs_float": True,
    "high_float_shares": 90_000_000.0,  # mega-float: time-of-day ratio instead of vol > float
    "low_float_shares": 2_000_000.0,  # tiny float: stricter headroom above float
    "min_price": 0.01,  # match TV-style sub-$1 names (was $1 and killed them)
    # Yahoo vs TV HMA can disagree by a hair (STKH was ~0.5% under). Allow tiny slack.
    "hma_tolerance_pct": 1.0,
    "exclude_etfs": True,
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


def _adjust_close_splits(closes: list[float]) -> list[float]:
    """
    TradingView adjusts history for splits; Yahoo sometimes leaves a raw jump
    (e.g. ONFO 0.04 → 2.40). Re-scale older closes across big gaps so HMA matches TV.
    """
    if len(closes) < 2:
        return list(closes)
    out = [float(x) for x in closes]
    for i in range(1, len(out)):
        prev, cur = out[i - 1], out[i]
        if prev <= 0 or cur <= 0:
            continue
        ratio = cur / prev
        # Reverse split (price jumps up) or forward split (price gaps down)
        if ratio >= 8.0:
            for j in range(i):
                out[j] *= ratio
        elif ratio <= 0.125:
            for j in range(i):
                out[j] *= ratio
    return out


def hull_ma9(closes: list[float]) -> float | None:
    """
    TradingView-style Hull MA(9):
    wma(2 * wma(src, length/2) - wma(src, length), round(sqrt(length)))
    """
    n = 9
    if len(closes) < n:
        return None
    half = max(1, n // 2)
    sqrt_n = max(1, int(round(math.sqrt(n))))
    series: list[float] = []
    for i in range(n, len(closes) + 1):
        chunk = closes[:i]
        wh = _wma(chunk, half)
        wf = _wma(chunk, n)
        if wh is None or wf is None:
            continue
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


def _asset_field_str(value: Any) -> str:
    """Alpaca enums stringify as 'AssetExchange.NASDAQ' — use .value when present."""
    if value is None:
        return ""
    raw = getattr(value, "value", None)
    if raw is not None:
        return str(raw).strip()
    return str(value).strip()


def _looks_like_etf_name(name: str) -> bool:
    n = f" {str(name or '').upper()} "
    if "ETF" in n or " ETN" in n:
        return True
    return any(m in n for m in _ETF_NAME_MARKERS)


def fetch_nyse_nasdaq_universe(
    *, paper: bool = True, cap: int = UNIVERSE_CAP
) -> tuple[list[str], str]:
    """
    Alpaca tradable US equities on major exchanges (ETFs stripped by name).
    Returns (symbols, error). error is empty on success.
    """
    try:
        from alpaca.trading.enums import AssetClass, AssetStatus
        from alpaca.trading.requests import GetAssetsRequest

        client = room3_alpaca._trading_client(paper=paper)
        req = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY,
        )
        assets = client.get_all_assets(req) or []
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        return [], f"Alpaca assets failed: {msg}"

    allowed = {str(x).upper() for x in DEFAULT_RULES.get("exchanges") or ("NASDAQ", "NYSE")}
    out: list[str] = []
    seen: set[str] = set()
    etf_skipped = 0
    for a in assets:
        try:
            status = _asset_field_str(getattr(a, "status", "")).lower()
            if status and status != "active":
                continue
            if not bool(getattr(a, "tradable", False)):
                continue
            name = str(getattr(a, "name", "") or "")
            if _looks_like_etf_name(name):
                etf_skipped += 1
                continue
            sym = _asset_field_str(getattr(a, "symbol", "")).upper()
            if not sym or sym in seen or "." in sym:
                continue
            exch = _asset_field_str(getattr(a, "exchange", "")).upper()
            if exch not in allowed:
                continue
            seen.add(sym)
            out.append(sym)
        except Exception:
            continue
    # Cap only AFTER full pass — early break dropped late symbols (WETO, CAPR, …)
    # that still pass filters, while earlier alphabet/API order filled the quota.
    out = sorted(out)[: max(1, int(cap))]
    if not out:
        return [], (
            f"Alpaca returned {len(assets)} assets but 0 matched "
            f"active/tradable stocks on {sorted(allowed)} "
            f"(skipped {etf_skipped} ETF-like names)"
        )
    return out, ""


def _flatten_ohlcv(hist) -> Any | None:
    """
    Normalize Yahoo frames to simple Close/Volume columns.
    yfinance flips between flat columns and MultiIndex (Ticker, Price) /
    (Price, Ticker) depending on version and batch size.
    """
    try:
        if hist is None or getattr(hist, "empty", True):
            return None
        cols = hist.columns
        if getattr(cols, "nlevels", 1) > 1:
            # Prefer selecting the Price level so we get Open/High/Low/Close/Volume
            names = [str(n).lower() if n is not None else "" for n in (cols.names or [])]
            frame = hist
            if "price" in names:
                price_lvl = names.index("price")
                try:
                    frame = hist.droplevel(0 if price_lvl else 1, axis=1)
                except Exception:
                    # Fall back: take first ticker slice if present
                    try:
                        top = cols.get_level_values(0)[0]
                        frame = hist[top]
                    except Exception:
                        return None
            else:
                # No named levels — try common patterns
                try:
                    lvl0 = set(map(str, cols.get_level_values(0)))
                    if {"Open", "High", "Low", "Close", "Volume"} & lvl0:
                        # (Price, Ticker) → pick first ticker under Close etc.
                        tickers = list(dict.fromkeys(cols.get_level_values(1)))
                        if not tickers:
                            return None
                        frame = hist.xs(tickers[0], axis=1, level=1)
                    else:
                        top = cols.get_level_values(0)[0]
                        frame = hist[top]
                except Exception:
                    return None
            hist = frame
        # After MultiIndex collapse, columns should be flat strings
        have = {str(c) for c in hist.columns}
        if "Close" not in have or "Volume" not in have:
            # Sometimes still tuples
            try:
                hist.columns = [
                    c[0] if isinstance(c, tuple) else c for c in hist.columns
                ]
            except Exception:
                return None
            have = {str(c) for c in hist.columns}
        if "Close" not in have or "Volume" not in have:
            return None
        return hist
    except Exception:
        return None


def _series_floats(frame, col: str) -> list[float]:
    try:
        raw = frame[col]
        if hasattr(raw, "columns"):
            # Still a DataFrame — take first column
            raw = raw.iloc[:, 0]
        out: list[float] = []
        for x in raw.dropna().tolist():
            try:
                if hasattr(x, "iloc"):
                    x = x.iloc[0]
                v = float(x)
            except (TypeError, ValueError):
                continue
            if v == v:  # not NaN
                out.append(v)
        return out
    except Exception:
        return []


def _last_positive_volume_idx(vols: list[float]) -> int | None:
    for i in range(len(vols) - 1, -1, -1):
        if vols[i] > 0:
            return i
    return None


def _metrics_from_history(hist) -> dict[str, float] | None:
    try:
        hist = _flatten_ohlcv(hist)
        if hist is None:
            return None
        closes_raw = _series_floats(hist, "Close")
        vols = _series_floats(hist, "Volume")
        if len(closes_raw) < 12 or len(vols) < 10:
            return None
        # Align lengths if Yahoo drops a volume cell
        n = min(len(closes_raw), len(vols))
        closes_raw = closes_raw[-n:]
        vols = vols[-n:]
        # Split-adjust closes for HMA / hist-vol (TV does this; raw Yahoo often doesn't)
        closes = _adjust_close_splits(closes_raw)
        close = closes[-1]
        # After hours Yahoo sometimes posts today's volume as 0 until settled —
        # walk back to the last positive-volume session print.
        v_idx = _last_positive_volume_idx(vols)
        if v_idx is None:
            return None
        vol_today = vols[v_idx]
        vol_window = [v for v in vols[-10:] if v > 0] or vols[-10:]
        avg_vol_10 = sum(vol_window) / max(1, len(vol_window))
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
    """Stage 1 — daily price/vol/HMA/dollar-volume (TV-style 1D HMA9)."""
    if metrics["close"] < float(rules.get("min_price") or 0):
        return False
    if metrics["vol_pct"] < float(rules.get("min_volatility_pct") or 0):
        return False
    if rules.get("require_price_above_hma9") and metrics["hma9"] > 0:
        tol = max(0.0, float(rules.get("hma_tolerance_pct") or 0.0)) / 100.0
        # close >= HMA * (1 - tol). tol=0 → strict above; 1% keeps STKH-type near-misses.
        floor = float(metrics["hma9"]) * (1.0 - tol)
        if metrics["close"] < floor:
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
    # Unknown / missing float (common on TV too) → keep the name; other rules still apply.
    if float_shares is None or float_shares <= 0:
        return True
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
    """Float + market cap + quote type (stage-2 only — called on survivors)."""
    import yfinance as yf

    try:
        info = yf.Ticker(sym).info or {}
        quote_type = str(info.get("quoteType") or info.get("quote_type") or "").upper()
        # Prefer real float only — sharesOutstanding can be absurd vs tiny mcap.
        raw_float = info.get("floatShares")
        if raw_float is None:
            raw_float = info.get("sharesOutstanding")
        raw_cap = info.get("marketCap")
        float_shares = float(raw_float) if raw_float else None
        market_cap = float(raw_cap) if raw_cap else None
        if float_shares is not None and float_shares <= 0:
            float_shares = None
        if market_cap is not None and market_cap <= 0:
            market_cap = None
        # Sanity: absurd float vs tiny mcap (bad Yahoo sharesOutstanding) → treat as unknown
        if (
            float_shares
            and market_cap
            and float_shares > 0
            and market_cap / float_shares < 0.01
        ):
            float_shares = None
        # Also drop floats that are impossibly large vs price×shares for microcaps
        if float_shares and float_shares >= 1_000_000_000 and (not market_cap or market_cap < 50_000_000):
            float_shares = None
        return {
            "float_shares": float_shares,
            "market_cap": market_cap,
            "quote_type": quote_type or None,  # type: ignore[dict-item]
        }
    except Exception:
        return {"float_shares": None, "market_cap": None, "quote_type": None}


def passes_structure_rules(
    metrics: dict[str, float],
    share_stats: dict[str, float | None],
    rules: dict[str, Any],
    *,
    now_et: datetime | None = None,
) -> bool:
    """Stage 2 — equities only, market cap ceiling + volume vs float."""
    if rules.get("exclude_etfs", True):
        qt = str(share_stats.get("quote_type") or "").upper()
        if qt in {"ETF", "ETN", "MUTUALFUND", "FUND"}:
            return False
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


def _download_daily_batches(
    symbols: list[str],
    *,
    period: str,
) -> tuple[dict[str, Any], int, int]:
    """Parallel Yahoo daily download. Returns (sym→history, scanned, errors)."""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, as_completed

    by_sym: dict[str, Any] = {}
    scanned = 0
    errors = 0
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    batches = [syms[i : i + BATCH_SIZE] for i in range(0, len(syms), BATCH_SIZE)]

    def _one(batch: list[str]):
        data = yf.download(
            " ".join(batch),
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        return batch, data

    with ThreadPoolExecutor(max_workers=YF_BATCH_WORKERS) as pool:
        futures = [pool.submit(_one, b) for b in batches]
        for fut in as_completed(futures):
            try:
                batch, data = fut.result()
            except Exception:
                errors += BATCH_SIZE
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
                        try:
                            hist = (
                                data[sym]
                                if sym in data.columns.get_level_values(0)
                                else None
                            )
                        except Exception:
                            hist = None
                    if hist is not None and not getattr(hist, "empty", True):
                        by_sym[sym] = hist
                except Exception:
                    errors += 1
    return by_sym, scanned, errors


def _liquidity_score(hist) -> float:
    """Rough today dollar volume from a short daily window (prescreen)."""
    try:
        if hist is None or getattr(hist, "empty", True):
            return 0.0
        if "Close" not in hist.columns or "Volume" not in hist.columns:
            return 0.0
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        vols = [float(x) for x in hist["Volume"].dropna().tolist()]
        if not closes or not vols:
            return 0.0
        return max(0.0, closes[-1] * vols[-1])
    except Exception:
        return 0.0


def scan_universe(
    symbols: list[str],
    *,
    rules: dict[str, Any] | None = None,
    max_pass: int = BELT_MAX,
) -> dict[str, Any]:
    """
    Job 1 cascade (filter only — no maps / no matrix):
      Pass A — short daily bars on full list → liquidity kill
      Pass B — 2mo history only on top liquid shortlist → HMA / vol / float / mcap
      Output  — small belt for Job 2
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    rules = rules or default_rules()
    started = datetime.now(ET)
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    min_dv = float(rules.get("min_dollar_volume") or 0)
    # Slightly loose on prescreen so borderline names still get a deep look.
    pre_floor = max(0.0, min_dv * 0.5) if min_dv > 0 else 0.0

    pre_hist, scanned, errors = _download_daily_batches(syms, period=YF_PRESCREEN_PERIOD)
    liquid: list[tuple[str, float]] = []
    for sym, hist in pre_hist.items():
        score = _liquidity_score(hist)
        if score >= pre_floor:
            # Also respect min price from last close when available
            try:
                closes = [float(x) for x in hist["Close"].dropna().tolist()]
                if closes and closes[-1] < float(rules.get("min_price") or 0):
                    continue
            except Exception:
                pass
            liquid.append((sym, score))
    liquid.sort(key=lambda x: x[1], reverse=True)
    deep_syms = [s for s, _ in liquid[:DEEP_SCAN_CAP]]

    stage1: list[tuple[str, dict[str, float]]] = []
    deep_scanned = 0
    if deep_syms:
        deep_hist, deep_scanned, deep_err = _download_daily_batches(
            deep_syms, period=YF_PERIOD
        )
        errors += deep_err
        for sym in deep_syms:
            hist = deep_hist.get(sym)
            if hist is None:
                continue
            try:
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
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(fetch_share_stats, sym): sym for sym, _ in stage1}
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    stats_by_sym[sym] = fut.result()
                except Exception:
                    stats_by_sym[sym] = {
                        "float_shares": None,
                        "market_cap": None,
                        "quote_type": None,
                    }

        for sym, m in stage1:
            stats = stats_by_sym.get(sym) or {
                "float_shares": None,
                "market_cap": None,
                "quote_type": None,
            }
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
        "deep_scanned": deep_scanned,
        "prescreen_liquid": len(liquid),
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "at": started.strftime("%H:%M:%S ET"),
    }


def run_rth_scan(
    *, paper: bool = True, rules: dict[str, Any] | None = None, max_pass: int = BELT_MAX
) -> dict[str, Any]:
    universe, uni_err = fetch_nyse_nasdaq_universe(paper=paper)
    if not universe:
        return {
            "ok": False,
            "tickers": [],
            "error": uni_err or "universe empty — Alpaca connection or assets unavailable",
            "scanned": 0,
            "passed": 0,
            "universe_size": 0,
        }
    result = scan_universe(universe, rules=rules, max_pass=max_pass)
    result["universe_size"] = len(universe)
    return result
