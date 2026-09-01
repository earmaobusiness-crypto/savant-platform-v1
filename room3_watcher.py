"""
Room 3 watcher — Job 2 (the eyes / middleman).

Job 1 (screener) hands a small belt. This module:
  - builds 1m / 5m / 15m maps only for those survivors
  - lookback = max needed for that TF's strategy compare (not forever)
  - after first paint, each letter revisits on its own cadence
  - tape is Yahoo-first; Massive only if Yahoo is empty
  - matrix match vs repertoire
Job 3 (execution) fires only when armed + gates open.

Does NOT import Room 2 modules. Uses room3_bridge snapshot only for repertoire hints.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
import time

import room3_bridge
import room3_engine
import room3_matrix
import room3_precursor
import room3_recipes

ET = ZoneInfo("America/New_York")

TIMEFRAMES = ("1m", "5m", "15m")
# Job 2 only maps Job 1 survivors — keep this tight (operator: ~5–10 typical)
MAX_NAMES = 15
STICKY_MIN_SCORE = 0.72  # keep after filter drop if map this close to repertoire
STICKY_MIN_MATCH_PCT = 70  # must also be warming+ DNA — never sticky on a 6% Match%
STICKY_MAX_MINUTES = 45
HEARTBEAT_SEC = 15
# Yahoo/SEC calls per heartbeat — more than this in one gulp whites Cloud.
MAX_HEAVY_PER_TICK = 3
_TF_WORK_RANK = {"1m": 0, "5m": 1, "15m": 2}

# Picture budget — lean where strategies are short; richer only on 15m
# bars_keep ≈ max lookback strategies on that TF need (not full-day dumps)
TF_DIET: dict[str, dict[str, Any]] = {
    "1m": {
        "max_slices": 12,  # ~last 12 minutes of pulse memory
        "yf_interval": "1m",
        "yf_period": "1d",
        "bars_keep": 8,  # most 1m strategies need ≤ ~5–8 minutes
        "extras": "chart",
    },
    "5m": {
        "max_slices": 18,
        "yf_interval": "5m",
        "yf_period": "1d",
        "bars_keep": 12,  # ~1 hour of 5m bars
        "extras": "light",
    },
    "15m": {
        "max_slices": 24,
        "yf_interval": "15m",
        "yf_period": "5d",
        "bars_keep": 24,  # richer but not 10d of everything
        "extras": "rich",
    },
}


def empty_book() -> dict[str, Any]:
    return {
        "universe": [],  # tickers from filter feed
        "lines": {},  # key "AAPL:1m" → line dict
        "last_tick": "",
        "last_note": "Awaiting TradingView / session filter feed.",
        "ticks": 0,
        "awaiting_filters": True,
    }


def line_key(ticker: str, tf: str) -> str:
    return f"{str(ticker).upper()}:{tf}"


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return 0.0
        return float(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    try:
        return _plain(float(value))
    except (TypeError, ValueError):
        return str(value)


def _overlay_fresh(book: dict[str, Any], ticker: str, *, ttl_sec: int) -> dict[str, Any] | None:
    hit = (book.get("_overlay_cache") or {}).get(ticker)
    if not isinstance(hit, dict):
        return None
    ttl = max(30, int(ttl_sec or 180))
    if (time.monotonic() - float(hit.get("t") or 0)) < ttl:
        return hit.get("pack") or {}
    return None


def _snap_fresh(
    book: dict[str, Any],
    ticker: str,
    tf: str,
    *,
    bars_keep: int,
    ttl_sec: int,
) -> dict[str, Any] | None:
    key = f"{ticker}|{tf}|{int(bars_keep)}"
    hit = (book.get("_snap_cache") or {}).get(key)
    if not isinstance(hit, dict):
        return None
    ttl = max(8, int(ttl_sec or 15) - 2)
    if (time.monotonic() - float(hit.get("t") or 0)) < ttl:
        return hit.get("snap")
    return None


def _cached_overlay(
    book: dict[str, Any],
    ticker: str,
    tf: str,
    *,
    ttl_sec: int,
) -> dict[str, Any]:
    cache = book.setdefault("_overlay_cache", {})
    hit = cache.get(ticker)
    now = time.monotonic()
    ttl = max(30, int(ttl_sec or 180))
    if isinstance(hit, dict) and (now - float(hit.get("t") or 0)) < ttl:
        return hit.get("pack") or {}
    pack: dict[str, Any] = {}
    try:
        pack = _plain(room3_precursor.live_sensor_overlay(ticker, tf=tf) or {})
    except Exception:
        pack = {}
    cache[ticker] = {"t": now, "pack": pack}
    return pack


def _cached_snap(
    book: dict[str, Any],
    ticker: str,
    tf: str,
    *,
    bars_keep: int,
    ttl_sec: int,
) -> dict[str, Any] | None:
    cache = book.setdefault("_snap_cache", {})
    key = f"{ticker}|{tf}|{int(bars_keep)}"
    hit = cache.get(key)
    now = time.monotonic()
    ttl = max(8, int(ttl_sec or 15) - 2)
    if isinstance(hit, dict) and (now - float(hit.get("t") or 0)) < ttl:
        return hit.get("snap")
    snap = _fetch_bar_snapshot(ticker, tf, bars_keep=bars_keep)
    cache[key] = {"t": now, "snap": snap}
    return snap


def set_filter_universe(book: dict[str, Any], tickers: list[str] | None) -> dict[str, Any]:
    """
    Hook for TradingView / session filters.
    Pass the names currently inside the active filter.
    """
    book = dict(book or empty_book())
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tickers or []:
        t = str(raw or "").strip().upper()
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
        if len(cleaned) >= MAX_NAMES:
            break
    book["universe"] = cleaned
    book["awaiting_filters"] = len(cleaned) == 0
    if cleaned:
        book["last_note"] = f"Filter feed · {len(cleaned)} name(s) · tracking 1m/5m/15m"
        ensure_maps(book)
    elif _keep_tickers_for_book(book):
        book["last_note"] = "Belt empty · still mapping open broker names."
        ensure_maps(book)
    else:
        book["last_note"] = "Awaiting TradingView / session filter feed."
        book["lines"] = {}
    return book


def ensure_maps(book: dict[str, Any], keep_tickers: list[str] | None = None) -> dict[str, Any]:
    """Open 1m/5m/15m lines as soon as names land — don't wait for a heartbeat."""
    if keep_tickers is not None:
        book["keep_tickers"] = [
            str(t).strip().upper() for t in keep_tickers if str(t).strip()
        ]
    _ensure_lines_for_universe(book)
    return book


def ensure_ticker_maps(book: dict[str, Any], ticker: str) -> None:
    """Make sure one name has 1m/5m/15m lines (broker leftovers, not the belt)."""
    sym = str(ticker or "").strip().upper()
    if not sym:
        return
    lines = book.setdefault("lines", {})
    universe = set(book.get("universe") or [])
    for tf in TIMEFRAMES:
        key = line_key(sym, tf)
        if key not in lines:
            lines[key] = _new_line(sym, tf)
        lines[key]["in_filter"] = sym in universe


def _keep_tickers_for_book(book: dict[str, Any]) -> set[str]:
    keep = {str(t).strip().upper() for t in (book.get("keep_tickers") or []) if str(t).strip()}
    return keep


def _ensure_lines_for_universe(book: dict[str, Any]) -> None:
    lines = book.setdefault("lines", {})
    universe = set(book.get("universe") or [])
    keep = set(universe) | _keep_tickers_for_book(book)
    # Open three TF maps for each filtered name
    for ticker in list(universe)[:MAX_NAMES]:
        for tf in TIMEFRAMES:
            key = line_key(ticker, tf)
            if key not in lines:
                lines[key] = _new_line(ticker, tf)
    # Broker-open names that left the belt still need maps to manage the pile.
    for ticker in sorted(keep - universe):
        ensure_ticker_maps(book, ticker)

    # Drop ghosts whose ticker left the filter (sticky-only does not keep them).
    drop_keys = []
    for key, line in lines.items():
        t = str(line.get("ticker") or "")
        if t in universe:
            line["in_filter"] = True
            continue
        line["in_filter"] = False
        if t in keep:
            continue
        if line.get("state") == "in":
            continue
        if line.get("state") == "committed" and _entry_stamped(line):
            continue
        drop_keys.append(key)
    for key in drop_keys:
        lines.pop(key, None)


def _new_line(ticker: str, tf: str) -> dict[str, Any]:
    return {
        "ticker": ticker.upper(),
        "timeframe": tf,
        "state": "watching",  # watching | committed | in | flat_day
        "sticky": False,
        "in_filter": True,
        "slices": [],
        "score": 0.0,
        "last_bar_ts": "",
        "opened_at": datetime.now(ET).isoformat(),
        "sticky_until": "",
        "entry_signal": None,
        "exit_signal": None,
        "last_error": "",
        "trades_today": 0,
        "scale_ins": 0,
    }


def _sticky_alive(line: dict[str, Any]) -> bool:
    until = str(line.get("sticky_until") or "")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now(ET)
    except Exception:
        return False


def _rows_to_snap(
    rows: list[dict[str, Any]],
    diet: dict[str, Any],
    keep: int,
) -> dict[str, Any] | None:
    if not rows:
        return None
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last
    o = float(last.get("o") or 0)
    h = float(last.get("h") or 0)
    l = float(last.get("l") or 0)
    c = float(last.get("c") or 0)
    v = float(last.get("v") or 0)
    prev_c = float(prev.get("c") or 0)
    ret = ((c - prev_c) / prev_c) if prev_c else 0.0
    rng = ((h - l) / c) if c else 0.0
    typ_vol = 0.0
    vol_sum = 0.0
    for row in rows:
        rc = float(row.get("c") or 0)
        rh = float(row.get("h") or 0)
        rl = float(row.get("l") or 0)
        rv = float(row.get("v") or 0)
        typ_vol += ((rh + rl + rc) / 3.0) * rv
        vol_sum += rv
    vwap = (typ_vol / vol_sum) if vol_sum > 0 else None
    slice_body: dict[str, Any] = {
        "ts": str(last.get("ts") or ""),
        "o": round(o, 4),
        "h": round(h, 4),
        "l": round(l, 4),
        "c": round(c, 4),
        "v": round(v, 2),
        "ret": round(ret, 6),
        "range": round(rng, 6),
        "extras": diet.get("extras"),
        "vwap": round(vwap, 4) if vwap is not None else None,
        "lookback_bars": keep,
    }
    if diet.get("extras") in ("light", "rich"):
        closes = [float(x.get("c") or 0) for x in rows]
        vols = [float(x.get("v") or 0) for x in rows]
        slice_body["close_trail"] = [round(x, 4) for x in closes[-8:]]
        if vols:
            avg_v = sum(vols) / len(vols)
            slice_body["vol_z"] = round((v - avg_v) / avg_v, 4) if avg_v else 0.0
    if diet.get("extras") == "rich":
        slice_body["high_trail"] = [round(float(x.get("h") or 0), 4) for x in rows[-6:]]
        slice_body["low_trail"] = [round(float(x.get("l") or 0), 4) for x in rows[-6:]]
    return slice_body


def _fetch_bar_snapshot(
    ticker: str,
    tf: str,
    *,
    bars_keep: int | None = None,
) -> dict[str, Any] | None:
    """Yahoo 1m (resampled to TF). Massive only if Yahoo is empty."""
    diet = TF_DIET.get(tf) or TF_DIET["1m"]
    keep = int(bars_keep if bars_keep is not None else diet["bars_keep"])
    keep = max(3, min(120, keep))
    try:
        rows, source = room3_precursor.live_bar_rows(ticker, tf, bars_keep=keep)
        snap = _rows_to_snap(rows, diet, keep)
        if snap:
            snap["feed"] = source
        return snap
    except Exception as exc:
        return {"error": str(exc).strip() or type(exc).__name__}


def _seed_line_from_history(
    line: dict[str, Any],
    *,
    bars_keep: int,
    rows: list[dict[str, Any]] | None = None,
    source: str = "",
) -> int:
    """
    On first touch: load strategy-sized lookback so the puzzle can score.
    Yahoo 1m is shared across 1m/5m/15m on the same name for ~one heartbeat.
    """
    if line.get("seeded"):
        return 0
    ticker = str(line.get("ticker") or "")
    tf = str(line.get("timeframe") or "1m")
    diet = TF_DIET.get(tf) or TF_DIET["1m"]
    keep = max(3, min(120, int(bars_keep)))
    try:
        if rows is None:
            rows, source = room3_precursor.live_bar_rows(ticker, tf, bars_keep=keep)
        if not rows:
            line["seeded"] = False
            line["seed_bars"] = 0
            line["feed"] = source or "yahoo"
            line["last_error"] = "no tape · Yahoo/Massive/Alpaca empty"
            return 0
        added = 0
        prev_c = None
        for row in rows:
            c = float(row.get("c") or 0)
            o = float(row.get("o") or 0)
            h = float(row.get("h") or 0)
            l = float(row.get("l") or 0)
            v = float(row.get("v") or 0)
            ret = ((c - prev_c) / prev_c) if prev_c and prev_c > 0 else 0.0
            prev_c = c
            snap = {
                "ts": str(row.get("ts") or ""),
                "o": round(o, 4),
                "h": round(h, 4),
                "l": round(l, 4),
                "c": round(c, 4),
                "v": round(v, 2),
                "ret": round(ret, 6),
                "range": round(((h - l) / c) if c else 0.0, 6),
                "extras": diet["extras"],
                "seed": True,
                "feed": source or "yahoo",
            }
            if _append_slice(line, snap):
                added += 1
        line["seeded"] = True
        line["seed_bars"] = added
        line["recipe_bars_keep"] = keep
        line["feed"] = source or "yahoo"
        line["last_error"] = ""
        return added
    except Exception as exc:
        line["seeded"] = True
        line["last_error"] = str(exc).strip() or type(exc).__name__
        return 0


def _update_shared_sensors(
    book: dict[str, Any],
    ticker: str,
    *,
    plan: dict[str, Any],
    last_snap: dict[str, Any] | None,
    extra_ttl: int = 180,
) -> dict[str, Any]:
    """One shared sensor pack per ticker — recipes reuse it."""
    packs = book.setdefault("sensor_packs", {})
    pack = packs.get(ticker) or room3_recipes.empty_sensor_pack(ticker)
    sensors = list(plan.get("sensors") or ["charts", "vwap"])
    live: dict[str, Any] = {}
    if last_snap and not last_snap.get("error"):
        pack["charts"] = {
            "ok": True,
            "note": f"lookback {plan.get('lookback_minutes')}m · bars {plan.get('bars_keep')}",
            "last_ts": str(last_snap.get("ts") or ""),
            "last_c": last_snap.get("c"),
        }
        vwap = last_snap.get("vwap")
        pack["vwap"] = {
            "ok": vwap is not None,
            "value": vwap,
            "note": "from lookback window" if vwap is not None else "unavailable",
        }
        live = _cached_overlay(
            book,
            ticker,
            str(plan.get("timeframe") or "15m"),
            ttl_sec=int(extra_ttl or plan.get("extra_refresh_seconds") or 180),
        )
    extra_notes = {
        "sec": "filings / 8-K / S-3",
        "news": "wires / headlines",
        "social": "retail buzz",
        "float": "tradable supply",
        "short_interest": "squeeze pressure",
        "dilution": "ATM / PIPE / toxic",
        "halt": "LULD / halt history",
        "spread": "bid-ask friction",
        "rvol": "relative volume vs typical",
        "prints": "aggressive tape (1m)",
        "bid_ask": "inside spread (1m)",
        "premarket_rvol": "pre-open volume vs typical (5m)",
        "float_rotation": "volume vs float (5m)",
        "offering": "shelf / 424B (15m)",
        "insider": "Form 4 (15m)",
        "borrow": "locate / HTB (15m)",
        "sector": "peer / ETF tape (15m)",
        "days_to_cover": "short ratio (15m)",
    }
    for name in sensors:
        if name in ("charts", "vwap"):
            continue
        found = live.get(name) if isinstance(live.get(name), dict) else None
        if found and found.get("ok") is not None:
            cell = dict(found)
            cell["required"] = True
            pack[name] = cell
            continue
        cur = pack.get(name) or {}
        if cur.get("ok") is None or not cur:
            pack[name] = {
                "ok": None,
                "note": extra_notes.get(name, "hyper-vol extra") + " — feed filling in",
                "required": True,
            }
    packs[ticker] = pack
    return pack


def _append_slice(line: dict[str, Any], snap: dict[str, Any]) -> bool:
    """Append only if this is a new bar fingerprint (avoid duplicate half-bars)."""
    if not snap or snap.get("error"):
        if snap and snap.get("error"):
            line["last_error"] = str(snap["error"])
        return False
    ts = str(snap.get("ts") or "")
    if ts and ts == str(line.get("last_bar_ts") or ""):
        return False
    diet = TF_DIET.get(str(line.get("timeframe") or "1m")) or TF_DIET["1m"]
    slices = list(line.get("slices") or [])
    slices.append(
        {
            "saved_at": datetime.now(ET).strftime("%H:%M:%S"),
            **snap,
        }
    )
    max_n = int(diet["max_slices"])
    recipe_n = int(line.get("recipe_bars_keep") or 0)
    if recipe_n > max_n:
        max_n = recipe_n
    line["slices"] = slices[-max_n:]
    line["last_bar_ts"] = ts
    line["last_error"] = ""
    return True


def _entry_stamped(line: dict[str, Any]) -> bool:
    """True when committed means a real queued/filled entry, not sticky-only."""
    return bool(
        line.get("entry_signal")
        or line.get("entry_layout")
        or line.get("entry_qty")
        or line.get("entry_match_pct")
    )


def _clear_sticky_watch(line: dict[str, Any]) -> None:
    """Demote sticky-only committed → watching. Leaves real entry stamps alone."""
    if line.get("state") == "in" or _entry_stamped(line):
        return
    if line.get("state") == "committed" or line.get("sticky"):
        line["state"] = "watching"
    line["sticky"] = False
    line.pop("sticky_until", None)


def _maybe_mark_sticky(line: dict[str, Any]) -> None:
    score = float(line.get("score") or 0)
    match_pct = int(line.get("match_pct") or 0)
    # Match% collapsed after a warm read → drop sticky so UI doesn't lie.
    if match_pct < STICKY_MIN_MATCH_PCT or score < STICKY_MIN_SCORE:
        _clear_sticky_watch(line)
        return
    if line.get("state") in ("watching", "committed"):
        line["sticky"] = True
        line["state"] = "committed"
        line["sticky_until"] = (
            datetime.now(ET) + timedelta(minutes=STICKY_MAX_MINUTES)
        ).isoformat()


def evaluate_line_signals(line: dict[str, Any]) -> dict[str, Any] | None:
    """Emit queued entry/exit intents stamped by matrix DNA matching."""
    if line.get("state") == "in" and line.get("exit_signal"):
        sig = dict(line["exit_signal"])
        line["exit_signal"] = None
        return sig
    if line.get("entry_signal") and (
        line.get("state") in ("watching", "committed")
        or (line.get("state") == "in" and (line.get("entry_signal") or {}).get("scale_in"))
    ):
        sig = dict(line["entry_signal"])
        line["entry_signal"] = None
        return sig
    return None


def queue_entry_signal(
    book: dict[str, Any],
    ticker: str,
    timeframe: str,
    *,
    side: str = "buy",
    qty: float = 1.0,
    strategy: str = "matrix",
    keep_in: bool = False,
    scale_in: bool = False,
    order_style: str | None = None,
    layout_id: str = "",
) -> bool:
    """External adapter (filters/matrix) stamps an entry onto a TF line."""
    key = line_key(ticker, timeframe)
    line = (book.get("lines") or {}).get(key)
    if not line:
        return False
    style = str(order_style or "").strip().lower()
    if style not in ("market", "limit"):
        style = room3_recipes.order_style_for(
            strategy, timeframe, layout_id=layout_id
        )
    line["entry_signal"] = {
        "intent": "entry",
        "symbol": str(ticker).upper(),
        "side": side,
        "qty": float(qty),
        "strategy": strategy,
        "timeframe": timeframe,
        "scale_in": bool(scale_in),
        "order_style": style,
    }
    if not keep_in:
        line["state"] = "committed"
    return True


def queue_exit_signal(
    book: dict[str, Any],
    ticker: str,
    timeframe: str,
    *,
    side: str = "sell",
    qty: float = 1.0,
    strategy: str = "matrix",
    order_style: str | None = None,
    layout_id: str = "",
) -> bool:
    key = line_key(ticker, timeframe)
    line = (book.get("lines") or {}).get(key)
    if not line:
        return False
    style = str(order_style or "").strip().lower()
    if style not in ("market", "limit"):
        style = room3_recipes.order_style_for(
            strategy, timeframe, layout_id=layout_id
        )
    line["exit_signal"] = {
        "intent": "exit",
        "symbol": str(ticker).upper(),
        "side": side,
        "qty": float(qty),
        "strategy": strategy,
        "timeframe": timeframe,
        "order_style": style,
    }
    return True


def tick_watcher(
    book: dict[str, Any],
    *,
    session_state: Any,
    session_allowed: bool,
    engine_armed: bool,
    scan_allowed: bool = True,
    entries_allowed: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    One heartbeat:
      - sync lines to filter universe
      - append TF slices (diets)
      - score vs full matrix library (layout · strategy · TF buckets)
      - emit queued signals only when scan + session + armed allow trading
    Returns (book, signals_to_fire).
    """
    book = dict(book or empty_book())
    signals: list[dict[str, Any]] = []
    book["ticks"] = int(book.get("ticks") or 0) + 1
    try:
        session_state["room3_cash_claimed"] = 0.0
    except Exception:
        pass
    book["last_tick"] = datetime.now(ET).strftime("%H:%M:%S ET")

    if not scan_allowed:
        book["last_note"] = "Scan paused — no ticker universe."
        return book, signals

    # Outside an enabled trade window: Job 1 list only — no 1m/5m/15m maps,
    # no matrix compare, no orders (e.g. Market hours only after the close).
    if not session_allowed:
        book["last_note"] = (
            "Session not tradeable — filter list only; maps / compare / orders paused."
        )
        return book, signals

    keep: list[str] = []
    try:
        for row in session_state.get("room3_open_positions") or []:
            t = str(row.get("ticker") or row.get("symbol") or "").upper()
            if t:
                keep.append(t)
    except Exception:
        pass
    book["keep_tickers"] = keep
    for line in (book.get("lines") or {}).values():
        if isinstance(line, dict):
            room3_recipes.scrub_purgatory_line(line)

    if book.get("awaiting_filters") or not (book.get("universe") or []):
        if not keep:
            book["last_note"] = "Eyes ready · waiting for filter names (screener or paste)."
            return book, signals

    trade_ok = bool(session_allowed and engine_armed)

    _ensure_lines_for_universe(book)
    repertoire = room3_bridge.matrix_repertoire(session_state)
    layouts = list(repertoire.get("layouts") or [])
    # Precompute TF plans once — max lookback + shared sensors across strategies.
    tf_plans = {
        tf: room3_recipes.plan_for_timeframe(layouts, tf) for tf in TIMEFRAMES
    }

    now_m = time.monotonic()
    heavy = 0

    def _take_heavy() -> bool:
        nonlocal heavy
        if heavy >= MAX_HEAVY_PER_TICK:
            return False
        heavy += 1
        return True

    work: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for key, line in list((book.get("lines") or {}).items()):
        if line.get("state") == "flat_day":
            continue
        keep_set = set(book.get("keep_tickers") or [])
        if (
            not line.get("in_filter")
            and str(line.get("ticker") or "").upper() not in keep_set
            and line.get("state") != "in"
        ):
            continue
        tf = str(line.get("timeframe") or "1m")
        in_trade = 0 if str(line.get("state") or "") == "in" else 1
        unseeded = 0 if not line.get("seeded") else 1
        work.append((_TF_WORK_RANK.get(tf, 9), unseeded, in_trade, key, line))
    work.sort(key=lambda row: (row[0], row[1], row[2], row[3]))

    for _rank, _unseeded, _in, key, line in work:
        tf = str(line.get("timeframe") or "1m")
        ticker = str(line.get("ticker") or "").upper()
        plan = tf_plans.get(tf) or room3_recipes.plan_for_timeframe(layouts, tf)
        letter = room3_recipes.recipe_for(
            str(line.get("nearest_strategy") or line.get("strategy") or ""),
            tf,
            layout_id=str(line.get("nearest_layout") or line.get("entry_layout") or ""),
            structural_move_pct=float(line.get("structural_move_pct") or 0),
        )
        in_trade = str(line.get("state") or "") == "in"
        cadence = room3_recipes.cadence_for(
            str(line.get("nearest_strategy") or line.get("strategy") or ""),
            tf,
            layout_id=str(line.get("nearest_layout") or line.get("entry_layout") or ""),
            structural_move_pct=float(line.get("structural_move_pct") or 0),
            in_trade=in_trade,
        )
        pulse = int(cadence.get("pulse_seconds") or letter.get("pulse_seconds") or 60)
        extra_ttl = int(
            cadence.get("extra_refresh_seconds") or letter.get("extra_refresh_seconds") or 300
        )
        bars_keep = int(
            letter.get("bars_keep")
            or plan.get("bars_keep")
            or (TF_DIET.get(tf) or {}).get("bars_keep")
            or 8
        )
        line["recipe_bars_keep"] = bars_keep
        line["recipe_lookback_min"] = int(
            letter.get("lookback_minutes") or plan.get("lookback_minutes") or 0
        )
        line["recipe_sensors"] = list(letter.get("sensors") or plan.get("sensors") or [])
        line["pulse_seconds"] = pulse

        due = (not line.get("seeded")) or now_m >= float(line.get("next_pulse_at") or 0)
        # Armed + already ≥85% must not wait out a 5m/15m clock. 1m is first in rank.
        if (
            trade_ok
            and entries_allowed
            and line.get("seeded")
            and (line.get("slices") or [])
            and int(line.get("match_pct") or 0) >= room3_matrix.MATCH_THRESHOLD_PCT
            and str(line.get("state") or "") in ("watching", "committed")
            and not line.get("entry_signal")
        ):
            due = True
        if due:
            just_seeded = False
            if not line.get("seeded"):
                peek_rows, peek_src = room3_precursor.peek_live_bar_rows(
                    ticker, tf, bars_keep=bars_keep
                )
                if peek_rows is None:
                    if not _take_heavy():
                        continue
                    _seed_line_from_history(line, bars_keep=bars_keep)
                else:
                    _seed_line_from_history(
                        line, bars_keep=bars_keep, rows=peek_rows, source=peek_src
                    )
                just_seeded = True
            snap = None
            if just_seeded:
                slices = list(line.get("slices") or [])
                snap = slices[-1] if slices else None
            else:
                snap = _snap_fresh(
                    book, ticker, tf, bars_keep=bars_keep, ttl_sec=pulse
                )
                if snap is None:
                    peek_rows, peek_src = room3_precursor.peek_live_bar_rows(
                        ticker, tf, bars_keep=bars_keep
                    )
                    if peek_rows:
                        diet = TF_DIET.get(tf) or TF_DIET["1m"]
                        snap = _rows_to_snap(peek_rows, diet, bars_keep)
                        if snap:
                            snap["feed"] = peek_src
                    else:
                        if not _take_heavy():
                            continue
                        snap = _cached_snap(
                            book, ticker, tf, bars_keep=bars_keep, ttl_sec=pulse
                        )
            if snap and not just_seeded:
                _append_slice(line, snap or {})
            overlay_ok = True
            if _overlay_fresh(book, ticker, ttl_sec=extra_ttl) is None:
                if not _take_heavy():
                    overlay_ok = False
                else:
                    _update_shared_sensors(
                        book,
                        ticker,
                        plan=letter if letter.get("sensors") else plan,
                        last_snap=snap if isinstance(snap, dict) else None,
                        extra_ttl=extra_ttl,
                    )
            else:
                _update_shared_sensors(
                    book,
                    ticker,
                    plan=letter if letter.get("sensors") else plan,
                    last_snap=snap if isinstance(snap, dict) else None,
                    extra_ttl=extra_ttl,
                )
            line["sensor_pack"] = (book.get("sensor_packs") or {}).get(ticker) or {}
            room3_matrix.maybe_queue_matrix_signals(
                book,
                line,
                repertoire,
                session_state,
                engine_armed=trade_ok,
                entries_allowed=bool(entries_allowed),
            )
            # Extras skipped this tick: retry next heartbeat. Don't sleep 5–10m
            # on a first paint that never got the sensor pack.
            line["next_pulse_at"] = (now_m + pulse) if overlay_ok else 0.0
            if line.get("in_filter") is False:
                # Off-belt leftovers stay only if the broker still holds them.
                if str(line.get("state") or "") != "in":
                    _clear_sticky_watch(line)
            elif float(line.get("score") or 0) >= STICKY_MIN_SCORE:
                _maybe_mark_sticky(line)
            else:
                _clear_sticky_watch(line)

        if trade_ok:
            sig = evaluate_line_signals(line)
            if sig:
                signals.append(sig)

    n_lines = len(book.get("lines") or {})
    n_layouts = int(repertoire.get("layout_count") or 0)
    trade_note = (
        "armed · scanning"
        if trade_ok
        else "maps on · arm engine to trade"
    )
    book["engine_armed"] = bool(trade_ok)
    book["entries_allowed"] = bool(entries_allowed)
    try:
        book["pause_entries"] = bool(session_state.get("room3_pause_entries"))
    except Exception:
        book["pause_entries"] = False
    pulse_note = ", ".join(
        f"{tf}@{int(tf_plans[tf].get('pulse_seconds') or 60)}s"
        for tf in TIMEFRAMES
    )
    lb_note = ", ".join(
        f"{tf}≤{tf_plans[tf].get('lookback_minutes')}m" for tf in TIMEFRAMES
    )
    book["last_note"] = (
        f"Scanned {n_lines} TF maps · universe {len(book.get('universe') or [])} · "
        f"{n_layouts} matrix buckets · pulse [{pulse_note}] · recipes [{lb_note}] · "
        f"{trade_note} · DNA ≥{room3_matrix.MATCH_THRESHOLD_PCT}%"
    )
    return book, signals


def purge_untouched_maps(book: dict[str, Any]) -> dict[str, Any]:
    """
    End of day / session roll:
    If it scanned all day, saved slices, never traded → delete.
    Keep lines that traded today only in summary sense — clear watching maps.
    """
    book = dict(book or empty_book())
    lines = book.get("lines") or {}
    kept = {}
    purged = 0
    for key, line in lines.items():
        if int(line.get("trades_today") or 0) > 0 or line.get("state") == "in":
            # reset watching memory but keep a stub if still in
            if line.get("state") == "in":
                kept[key] = line
            else:
                purged += 1
            continue
        purged += 1
    book["lines"] = kept
    book["last_note"] = f"EOD purge · removed {purged} unused TF maps"
    return book


def _line_owns_seat(line: dict[str, Any]) -> bool:
    """True when this TF is the live pile (in) or has a real entry stamped (queued)."""
    raw = str(line.get("state") or "")
    if raw == "in":
        return True
    return raw == "committed" and _entry_stamped(line)


def _display_state(line: dict[str, Any], book: dict[str, Any] | None = None) -> str:
    """Operator-facing: scanning · warming · ready · queued · in."""
    raw = str(line.get("state") or "watching")
    if raw == "in":
        return "in"
    if raw == "committed" and _entry_stamped(line):
        return "queued"
    match = int(line.get("match_pct") or 0)
    seat = _sibling_seat_tf(book or {}, line) if book else ""
    if seat:
        if match >= room3_matrix.MATCH_THRESHOLD_PCT:
            return "ready"
        if match >= STICKY_MIN_MATCH_PCT:
            return "warming"
        return "scanning"
    if match >= room3_matrix.MATCH_THRESHOLD_PCT:
        return "ready"
    if match >= STICKY_MIN_MATCH_PCT:
        return "warming"
    return "scanning"


def _sibling_seat_tf(book: dict[str, Any], line: dict[str, Any]) -> str:
    """If another TF on this ticker is already in/queued, return that TF."""
    ticker = str(line.get("ticker") or "").upper()
    mine = line_key(ticker, str(line.get("timeframe") or ""))
    for key, other in (book.get("lines") or {}).items():
        if key == mine or not isinstance(other, dict):
            continue
        if str(other.get("ticker") or "").upper() != ticker:
            continue
        if _line_owns_seat(other):
            return str(other.get("timeframe") or "")
    return ""


def _why_not_firing(line: dict[str, Any], book: dict[str, Any] | None = None) -> str:
    """Short reason when DNA is hot but no order is in flight."""
    seat = _sibling_seat_tf(book or {}, line) if book else ""
    match = int(line.get("match_pct") or 0)
    state = _display_state(line, book)
    if state == "in":
        return "live trade"
    if state == "queued":
        return "order stamped · waiting fill"
    if line.get("in_filter") is False and state not in ("in", "queued"):
        return "leftover · exit only · no new buy"
    if seat:
        if match >= room3_matrix.MATCH_THRESHOLD_PCT:
            return f"promise · {seat} has the seat"
        if match >= STICKY_MIN_MATCH_PCT:
            return f"warming {match}% · {seat} is in"
        return f"scanning · {seat} is in"
    if not (line.get("slices") or []):
        err = str(line.get("last_error") or "").strip()
        return (err or "no tape · retrying")[:48]
    note = str(line.get("patience_note") or "").strip()
    if note:
        return note[:48]
    if match >= room3_matrix.MATCH_THRESHOLD_PCT:
        if book and book.get("engine_armed"):
            if book.get("pause_entries"):
                return "≥85% · Pause is on — no new entries"
            if book.get("entries_allowed") is False:
                return "≥85% · session gate off"
            return "≥85% · firing"
        return "≥85% · ready · Arm is OFF — flip Arm to send"
    if match >= STICKY_MIN_MATCH_PCT:
        return f"warming {match}% · need ≥{room3_matrix.MATCH_THRESHOLD_PCT}%"
    return "scanning"


def book_status_rows(book: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, line in sorted((book.get("lines") or {}).items()):
        layout = str(line.get("nearest_layout") or "—")
        strat = str(line.get("nearest_strategy") or "—")
        match_pct = int(line.get("match_pct") or 0)
        if room3_recipes.is_purgatory_letter(layout, strat):
            layout, strat, match_pct = "—", "—", 0
        rows.append(
            {
                "Line": key,
                "State": _display_state(line, book),
                "Match%": match_pct,
                "Layout": layout[:16],
                "Strategy": strat[:20],
                "Lookback": f"{int(line.get('recipe_lookback_min') or 0)}m"
                if line.get("recipe_lookback_min")
                else "—",
                "Size $": (
                    f"${float(line.get('size_usd') or 0):,.0f}"
                    if float(line.get("size_usd") or 0) > 0
                    else "—"
                ),
                "Note": _why_not_firing(line, book)[:52],
                "Slices": len(line.get("slices") or []),
                "Patience": "yes" if line.get("patience") else "",
                "Score": f"{float(line.get('score') or 0):.2f}",
                "Last bar": str(line.get("last_bar_ts") or "—")[-19:],
            }
        )
    return rows
