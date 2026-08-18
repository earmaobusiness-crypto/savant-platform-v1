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

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import room3_alpaca

ET = ZoneInfo("America/New_York")

_SNAPSHOT_PATH = Path(__file__).resolve().parent / "room3_data" / "screener_snapshot.json"

SCAN_INTERVAL_MINUTES = 18
# Parked: set True to restore Yahoo universe Job 1 UI + ~18 min auto-scan.
# Code paths in room3_screener / _run_screener_pass stay intact for bring-back.
BUILTIN_SCREENER_ENABLED = False
BATCH_SIZE = 120
UNIVERSE_CAP = 20000  # safety ceiling only — do NOT truncate mid-list (drops WETO/CAPR/etc.)
YF_PERIOD = "2mo"  # deep history for HMA + 30d vol (Pass B shortlist only)
YF_PRESCREEN_PERIOD = "5d"  # Pass A — cheap liquidity on the full list
YF_BATCH_WORKERS = 4  # Streamlit Cloud has a tight thread ceiling
SHARE_STATS_WORKERS = 4
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
            names = [str(n).lower() if n is not None else "" for n in (cols.names or [])]
            lvl0 = list(map(str, cols.get_level_values(0)))
            ohlcv = {"Open", "High", "Low", "Close", "Volume"}
            if ohlcv & set(lvl0):
                # Already price-on-level-0 (single ticker wrapped) — drop ticker level
                try:
                    hist = hist.droplevel(1, axis=1)
                except Exception:
                    hist = hist.copy()
                    hist.columns = lvl0
            elif "ticker" in names and names.index("ticker") == 0:
                top = str(cols.get_level_values(0)[0])
                hist = hist[top]
            else:
                try:
                    top = str(cols.get_level_values(0)[0])
                    hist = hist[top]
                except Exception:
                    return None
        # Collapse any leftover tuple column labels
        flat_cols = []
        for c in hist.columns:
            if isinstance(c, tuple):
                # Prefer the price name inside the tuple
                picked = next((str(x) for x in c if str(x) in {"Open", "High", "Low", "Close", "Volume"}), str(c[0]))
                flat_cols.append(picked)
            else:
                flat_cols.append(str(c))
        hist = hist.copy()
        hist.columns = flat_cols
        have = set(hist.columns)
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
    # Ceiling is on → must have a usable mcap. Unknown used to "keep" and let
    # NVDA/AAPL onto the belt whenever Yahoo omitted marketCap.
    if market_cap is None or market_cap <= 0:
        return False
    return market_cap <= cap_max


def fetch_share_stats(sym: str) -> dict[str, float | None]:
    """Float + market cap + quote type (used for deep-pick + structure)."""
    import yfinance as yf

    try:
        t = yf.Ticker(sym)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        quote_type = str(info.get("quoteType") or info.get("quote_type") or "").upper()
        # Prefer real float only — sharesOutstanding can be absurd vs tiny mcap.
        raw_float = info.get("floatShares")
        if raw_float is None:
            raw_float = info.get("sharesOutstanding")
        raw_cap = info.get("marketCap")
        # fast_info often has market_cap when .info is rate-limited / empty
        if not raw_cap:
            try:
                fi = getattr(t, "fast_info", None)
                if fi is not None:
                    raw_cap = getattr(fi, "market_cap", None) or (fi.get("market_cap") if hasattr(fi, "get") else None)
                    if not quote_type:
                        quote_type = str(
                            getattr(fi, "quote_type", None)
                            or (fi.get("quote_type") if hasattr(fi, "get") else "")
                            or ""
                        ).upper()
            except Exception:
                pass
        float_shares = float(raw_float) if raw_float else None
        market_cap = float(raw_cap) if raw_cap else None
        # Proxy mcap from price × shares when Yahoo omits marketCap
        if market_cap is None or market_cap <= 0:
            price = (
                info.get("regularMarketPrice")
                or info.get("currentPrice")
                or info.get("previousClose")
                or info.get("lastPrice")
            )
            shares = info.get("sharesOutstanding") or raw_float
            try:
                if price and shares and float(price) > 0 and float(shares) > 0:
                    market_cap = float(price) * float(shares)
            except (TypeError, ValueError):
                market_cap = None
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


def _map_share_stats(
    symbols: list[str],
) -> dict[str, dict[str, float | None]]:
    """
    Fetch float/mcap for many symbols without blowing Streamlit Cloud's thread limit.
    Tries a small pool; falls back to sequential on RuntimeError (can't start new thread).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out: dict[str, dict[str, float | None]] = {}
    syms = [str(s).upper() for s in symbols if str(s).strip()]
    if not syms:
        return out

    def _one(sym: str) -> tuple[str, dict[str, float | None]]:
        try:
            return sym, fetch_share_stats(sym)
        except Exception:
            return sym, {
                "float_shares": None,
                "market_cap": None,
                "quote_type": None,
            }

    try:
        with ThreadPoolExecutor(max_workers=SHARE_STATS_WORKERS) as pool:
            futs = [pool.submit(_one, sym) for sym in syms]
            for fut in as_completed(futs):
                try:
                    sym, stats = fut.result()
                except Exception:
                    continue
                out[sym] = stats
        return out
    except RuntimeError:
        # Cloud / container thread exhaustion — finish sequentially
        for sym in syms:
            if sym in out:
                continue
            _, stats = _one(sym)
            out[sym] = stats
        return out


def _pick_deep_symbols(
    liquid: list[tuple[str, float]],
    *,
    rules: dict[str, Any],
    cap: int = DEEP_SCAN_CAP,
) -> tuple[list[str], dict[str, dict[str, float | None]], int]:
    """
    Walk liquid names (highest DV first), keep only known sub-ceiling mcaps / non-ETFs.

    Must NOT keep unknown mcap — that refilled the belt with NVDA/AAPL whenever Yahoo
    omitted marketCap on the mega-liquid names.
    """
    if cap <= 0:
        return [], {}, 0
    max_mcap = float(rules.get("max_market_cap") or 0)
    exclude_etfs = bool(rules.get("exclude_etfs", True))
    # No mcap ceiling → old behavior (top liquid by DV)
    if max_mcap <= 0 and not exclude_etfs:
        return [s for s, _ in liquid[:cap]], {}, 0

    selected: list[str] = []
    stats_cache: dict[str, dict[str, float | None]] = {}
    mcap_skipped = 0
    wave = 40
    i = 0
    # Bound how far we walk so a broken Yahoo session can't spin forever
    max_inspect = min(len(liquid), max(cap * 25, 800))
    while len(selected) < cap and i < max_inspect:
        chunk = liquid[i : i + wave]
        i += wave
        batch_stats = _map_share_stats([sym for sym, _ in chunk])
        stats_cache.update(batch_stats)
        kept: list[tuple[str, float]] = []
        for sym, score in chunk:
            stats = batch_stats.get(sym) or {
                "float_shares": None,
                "market_cap": None,
                "quote_type": None,
            }
            qt = str(stats.get("quote_type") or "").upper()
            if exclude_etfs and qt in {"ETF", "ETN", "MUTUALFUND", "FUND"}:
                mcap_skipped += 1
                continue
            mcap = stats.get("market_cap")
            if max_mcap > 0:
                # Strict: need a known mcap under the ceiling
                if mcap is None or float(mcap) <= 0 or float(mcap) > max_mcap:
                    mcap_skipped += 1
                    continue
            kept.append((sym, score))
        kept.sort(key=lambda x: x[1], reverse=True)
        for sym, _score in kept:
            if len(selected) >= cap:
                break
            selected.append(sym)
    return selected, stats_cache, mcap_skipped


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


def _extract_symbol_frame(data, sym: str, *, batch_len: int):
    """Pull one symbol's OHLCV out of a yfinance download result."""
    if data is None or getattr(data, "empty", True):
        return None
    cols = data.columns
    nlevels = int(getattr(cols, "nlevels", 1) or 1)
    hist = None
    try:
        if nlevels == 1:
            # Single-ticker flat frame (rare with group_by=ticker)
            hist = data
        else:
            names = [str(n).lower() if n is not None else "" for n in (cols.names or [])]
            lvl0 = cols.get_level_values(0)
            lvl1 = cols.get_level_values(1) if nlevels > 1 else None
            # Common: (Ticker, Price) — symbol on level 0
            if sym in set(map(str, lvl0)):
                hist = data[sym]
            # Alternate: (Price, Ticker) — symbol on level 1
            elif lvl1 is not None and sym in set(map(str, lvl1)):
                hist = data.xs(sym, axis=1, level=1)
            elif batch_len == 1:
                # Lone ticker still MultiIndex-wrapped as (SYM, Price)
                try:
                    top = str(lvl0[0])
                    hist = data[top]
                except Exception:
                    hist = data
    except Exception:
        return None
    return _flatten_ohlcv(hist)


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
            threads=False,  # we already parallelize batches; Cloud thread limit is tight
        )
        return batch, data

    def _ingest(batch: list[str], data) -> None:
        nonlocal scanned, errors
        if data is None or getattr(data, "empty", True):
            errors += len(batch)
            return
        for sym in batch:
            scanned += 1
            try:
                hist = _extract_symbol_frame(data, sym, batch_len=len(batch))
                if hist is not None and not getattr(hist, "empty", True):
                    by_sym[sym] = hist
            except Exception:
                errors += 1

    try:
        with ThreadPoolExecutor(max_workers=YF_BATCH_WORKERS) as pool:
            futures = [pool.submit(_one, b) for b in batches]
            for fut in as_completed(futures):
                try:
                    batch, data = fut.result()
                except Exception:
                    errors += BATCH_SIZE
                    continue
                _ingest(batch, data)
    except RuntimeError:
        # Streamlit Cloud: can't start new thread — run batches one-by-one
        for batch in batches:
            try:
                batch, data = _one(batch)
            except Exception:
                errors += len(batch)
                continue
            _ingest(batch, data)
    return by_sym, scanned, errors


def _liquidity_score(hist) -> float:
    """Best recent dollar volume from a short daily window (prescreen)."""
    try:
        hist = _flatten_ohlcv(hist)
        if hist is None:
            return 0.0
        closes = _series_floats(hist, "Close")
        vols = _series_floats(hist, "Volume")
        if not closes or not vols:
            return 0.0
        n = min(len(closes), len(vols), 5)
        best = 0.0
        for i in range(1, n + 1):
            c, v = closes[-i], vols[-i]
            if c > 0 and v > 0:
                best = max(best, c * v)
        return best
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
    rules = {**default_rules(), **(rules or {})}
    # Guard: 0 / missing ceiling must not disable the $1B small-cap belt
    if float(rules.get("max_market_cap") or 0) <= 0:
        rules["max_market_cap"] = float(DEFAULT_RULES["max_market_cap"])
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
                flat = _flatten_ohlcv(hist)
                closes = _series_floats(flat, "Close") if flat is not None else []
                if closes and closes[-1] < float(rules.get("min_price") or 0):
                    continue
            except Exception:
                pass
            liquid.append((sym, score))
    liquid.sort(key=lambda x: x[1], reverse=True)
    deep_syms, stats_cache, mcap_skipped = _pick_deep_symbols(
        liquid, rules=rules, cap=DEEP_SCAN_CAP
    )

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
        stats_by_sym: dict[str, dict[str, float | None]] = dict(stats_cache)
        need = [sym for sym, _ in stage1 if sym not in stats_by_sym]
        if need:
            stats_by_sym.update(_map_share_stats(need))

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
    note = ""
    if not tickers and len(pre_hist) == 0 and scanned > 0:
        note = "Yahoo bars unreadable (column layout) — retry; parser was updated"
    elif not tickers and not liquid and scanned > 0:
        note = "Liquidity prescreen empty — check min dollar volume / Yahoo volume"
    elif not tickers and stage1 and structure_rejected:
        note = "Stage1 names failed float/mcap — tune structure rules"
    return {
        "ok": True,
        "tickers": tickers,
        "passed": len(passed),
        "stage1_passed": len(stage1),
        "structure_rejected": structure_rejected,
        "scanned": scanned,
        "hist_ok": len(pre_hist),
        "deep_scanned": deep_scanned,
        "prescreen_liquid": len(liquid),
        "mcap_skipped": mcap_skipped,
        "errors": errors,
        "elapsed_sec": round(elapsed, 1),
        "at": started.strftime("%H:%M:%S ET"),
        "error": note,
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


def save_screener_snapshot(payload: dict[str, Any]) -> None:
    """Disk backup so Streamlit refresh / tab sleep does not wipe the last list."""
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        blob = dict(payload or {})
        blob["saved_at"] = datetime.now(ET).isoformat()
        _SNAPSHOT_PATH.write_text(json.dumps(blob, default=str), encoding="utf-8")
    except Exception:
        pass


def load_screener_snapshot() -> dict[str, Any]:
    try:
        if not _SNAPSHOT_PATH.is_file():
            return {}
        raw = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def merge_screener_snapshot(updates: dict[str, Any]) -> None:
    blob = load_screener_snapshot()
    blob.update(dict(updates or {}))
    save_screener_snapshot(blob)
