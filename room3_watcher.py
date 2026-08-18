"""
Room 3 watcher — Job 2 (the eyes / middleman).

Job 1 (screener) hands a small belt. This module:
  - builds 1m / 5m / 15m maps only for those survivors
  - lookback = max needed for that TF's strategy compare (not forever)
  - matrix match vs repertoire
Job 3 (execution) fires only when armed + gates open.

Does NOT import Room 2 modules. Uses room3_bridge snapshot only for repertoire hints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import room3_bridge
import room3_engine
import room3_matrix
import room3_recipes

ET = ZoneInfo("America/New_York")

TIMEFRAMES = ("1m", "5m", "15m")
# Job 2 only maps Job 1 survivors — keep this tight (operator: ~5–10 typical)
MAX_NAMES = 15
STICKY_MIN_SCORE = 0.72  # keep after filter drop if map this close to repertoire
STICKY_MAX_MINUTES = 90

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
    else:
        book["last_note"] = "Awaiting TradingView / session filter feed."
        book["lines"] = {}
    return book


def ensure_maps(book: dict[str, Any]) -> dict[str, Any]:
    """Open 1m/5m/15m lines as soon as names land — don't wait for a heartbeat."""
    _ensure_lines_for_universe(book)
    return book


def _ensure_lines_for_universe(book: dict[str, Any]) -> None:
    lines = book.setdefault("lines", {})
    universe = set(book.get("universe") or [])
    # Open three TF maps for each filtered name
    for ticker in list(universe)[:MAX_NAMES]:
        for tf in TIMEFRAMES:
            key = line_key(ticker, tf)
            if key not in lines:
                lines[key] = _new_line(ticker, tf)

    # Drop non-sticky lines whose ticker left the filter
    drop_keys = []
    for key, line in lines.items():
        t = str(line.get("ticker") or "")
        if t in universe:
            line["in_filter"] = True
            continue
        line["in_filter"] = False
        if line.get("state") in ("in", "committed"):
            # still in a trade or entry queued — keep until exit path closes it
            continue
        if line.get("sticky") and _sticky_alive(line):
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


def _fetch_bar_snapshot(
    ticker: str,
    tf: str,
    *,
    bars_keep: int | None = None,
) -> dict[str, Any] | None:
    """Pull a lean closed-bar fingerprint for this TF diet / strategy plan."""
    diet = TF_DIET.get(tf) or TF_DIET["1m"]
    keep = int(bars_keep if bars_keep is not None else diet["bars_keep"])
    keep = max(3, min(120, keep))
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(
            period=str(diet["yf_period"]),
            interval=str(diet["yf_interval"]),
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            return None
        tail = hist.tail(keep)
        last = tail.iloc[-1]
        prev = tail.iloc[-2] if len(tail) > 1 else last
        ts = str(tail.index[-1])
        o = float(last["Open"])
        h = float(last["High"])
        l = float(last["Low"])
        c = float(last["Close"])
        v = float(last["Volume"]) if "Volume" in last else 0.0
        prev_c = float(prev["Close"])
        ret = ((c - prev_c) / prev_c) if prev_c else 0.0
        rng = ((h - l) / c) if c else 0.0
        # Session VWAP proxy from the lookback window (shared sensor).
        typ = (tail["High"] + tail["Low"] + tail["Close"]) / 3.0
        vol_s = tail["Volume"] if "Volume" in tail.columns else None
        vwap = None
        if vol_s is not None and float(vol_s.sum() or 0) > 0:
            vwap = float((typ * vol_s).sum() / vol_s.sum())
        slice_body: dict[str, Any] = {
            "ts": ts,
            "o": round(o, 4),
            "h": round(h, 4),
            "l": round(l, 4),
            "c": round(c, 4),
            "v": round(v, 2),
            "ret": round(ret, 6),
            "range": round(rng, 6),
            "extras": diet["extras"],
            "vwap": round(vwap, 4) if vwap is not None else None,
            "lookback_bars": keep,
        }
        # Richer TFs get a little more context without dumping full history
        if diet["extras"] in ("light", "rich"):
            closes = [float(x) for x in tail["Close"].tolist()]
            vols = [float(x) for x in tail["Volume"].tolist()] if "Volume" in tail else []
            slice_body["close_trail"] = [round(x, 4) for x in closes[-8:]]
            if vols:
                avg_v = sum(vols) / len(vols)
                slice_body["vol_z"] = round((v - avg_v) / avg_v, 4) if avg_v else 0.0
        if diet["extras"] == "rich":
            slice_body["high_trail"] = [round(float(x), 4) for x in tail["High"].tolist()[-6:]]
            slice_body["low_trail"] = [round(float(x), 4) for x in tail["Low"].tolist()[-6:]]
        return slice_body
    except Exception as exc:
        return {"error": str(exc).strip() or type(exc).__name__}


def _seed_line_from_history(line: dict[str, Any], *, bars_keep: int) -> int:
    """
    On first touch: load strategy-sized lookback as slices so the puzzle can
    complete immediately if DNA already matches — then 30s snaps continue.
    """
    if line.get("seeded"):
        return 0
    ticker = str(line.get("ticker") or "")
    tf = str(line.get("timeframe") or "1m")
    diet = TF_DIET.get(tf) or TF_DIET["1m"]
    keep = max(3, min(120, int(bars_keep)))
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(
            period=str(diet["yf_period"]),
            interval=str(diet["yf_interval"]),
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            line["seeded"] = True
            return 0
        tail = hist.tail(keep)
        added = 0
        prev_c = None
        for idx, row in tail.iterrows():
            c = float(row["Close"])
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            v = float(row["Volume"]) if "Volume" in row else 0.0
            ret = ((c - prev_c) / prev_c) if prev_c and prev_c > 0 else 0.0
            prev_c = c
            snap = {
                "ts": str(idx),
                "o": round(o, 4),
                "h": round(h, 4),
                "l": round(l, 4),
                "c": round(c, 4),
                "v": round(v, 2),
                "ret": round(ret, 6),
                "range": round(((h - l) / c) if c else 0.0, 6),
                "extras": diet["extras"],
                "seed": True,
            }
            if _append_slice(line, snap):
                added += 1
        line["seeded"] = True
        line["seed_bars"] = added
        line["recipe_bars_keep"] = keep
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
) -> dict[str, Any]:
    """One shared sensor pack per ticker — recipes reuse it."""
    packs = book.setdefault("sensor_packs", {})
    pack = packs.get(ticker) or room3_recipes.empty_sensor_pack(ticker)
    sensors = list(plan.get("sensors") or ["charts", "vwap"])
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
    # Optional sensors: stubs until wired (structure ready for SEC/news/social).
    for name in ("sec", "news", "social"):
        if name in sensors:
            cur = pack.get(name) or {}
            if cur.get("ok") is None:
                pack[name] = {
                    "ok": None,
                    "note": "stub — recipe asked for it; feed not wired yet",
                    "required": True,
                }
        elif name in pack and not (pack.get(name) or {}).get("required"):
            pack[name] = {"ok": None, "note": "not required by active recipes"}
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


def _maybe_mark_sticky(line: dict[str, Any]) -> None:
    score = float(line.get("score") or 0)
    if score >= STICKY_MIN_SCORE and line.get("state") in ("watching", "committed"):
        from datetime import timedelta

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
) -> bool:
    """External adapter (filters/matrix) stamps an entry onto a TF line."""
    key = line_key(ticker, timeframe)
    line = (book.get("lines") or {}).get(key)
    if not line:
        return False
    line["entry_signal"] = {
        "intent": "entry",
        "symbol": str(ticker).upper(),
        "side": side,
        "qty": float(qty),
        "strategy": strategy,
        "timeframe": timeframe,
        "scale_in": bool(scale_in),
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
) -> bool:
    key = line_key(ticker, timeframe)
    line = (book.get("lines") or {}).get(key)
    if not line:
        return False
    line["exit_signal"] = {
        "intent": "exit",
        "symbol": str(ticker).upper(),
        "side": side,
        "qty": float(qty),
        "strategy": strategy,
        "timeframe": timeframe,
    }
    return True


def tick_watcher(
    book: dict[str, Any],
    *,
    session_state: Any,
    session_allowed: bool,
    engine_armed: bool,
    scan_allowed: bool = True,
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

    if book.get("awaiting_filters") or not (book.get("universe") or []):
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

    for key, line in list((book.get("lines") or {}).items()):
        if line.get("state") == "flat_day":
            continue
        # Still scan sticky / in-filter / in-trade
        if not line.get("in_filter") and not line.get("sticky") and line.get("state") != "in":
            continue
        tf = str(line.get("timeframe") or "1m")
        ticker = str(line.get("ticker") or "").upper()
        plan = tf_plans.get(tf) or room3_recipes.plan_for_timeframe(layouts, tf)
        bars_keep = int(plan.get("bars_keep") or (TF_DIET.get(tf) or {}).get("bars_keep") or 8)
        line["recipe_bars_keep"] = bars_keep
        line["recipe_lookback_min"] = int(plan.get("lookback_minutes") or 0)
        line["recipe_sensors"] = list(plan.get("sensors") or [])

        # First touch: seed strategy-sized lookback, then 30s snaps continue.
        if not line.get("seeded"):
            _seed_line_from_history(line, bars_keep=bars_keep)

        snap = _fetch_bar_snapshot(ticker, tf, bars_keep=bars_keep)
        _append_slice(line, snap or {})
        _update_shared_sensors(book, ticker, plan=plan, last_snap=snap if isinstance(snap, dict) else None)
        line["sensor_pack"] = (book.get("sensor_packs") or {}).get(ticker) or {}

        room3_matrix.maybe_queue_matrix_signals(
            book,
            line,
            repertoire,
            session_state,
            engine_armed=trade_ok,
        )
        if line.get("in_filter") is False:
            _maybe_mark_sticky(line)
        elif float(line.get("score") or 0) >= STICKY_MIN_SCORE:
            _maybe_mark_sticky(line)

        if trade_ok:
            sig = evaluate_line_signals(line)
            if sig:
                signals.append(sig)

    n_lines = len(book.get("lines") or {})
    n_layouts = int(repertoire.get("layout_count") or 0)
    trade_note = "trading ON" if trade_ok else "maps on · arm engine to trade"
    lb_note = ", ".join(
        f"{tf}≤{tf_plans[tf].get('lookback_minutes')}m" for tf in TIMEFRAMES
    )
    book["last_note"] = (
        f"Scanned {n_lines} TF maps · universe {len(book.get('universe') or [])} · "
        f"{n_layouts} matrix buckets · recipes [{lb_note}] · {trade_note} · "
        f"DNA ≥{room3_matrix.MATCH_THRESHOLD_PCT}%"
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


def book_status_rows(book: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for key, line in sorted((book.get("lines") or {}).items()):
        rows.append(
            {
                "Line": key,
                "State": line.get("state"),
                "Match%": int(line.get("match_pct") or 0),
                "Layout": str(line.get("nearest_layout") or "—")[:16],
                "Strategy": str(line.get("nearest_strategy") or "—")[:12],
                "Lookback": f"{int(line.get('recipe_lookback_min') or 0)}m"
                if line.get("recipe_lookback_min")
                else "—",
                "Size $": (
                    f"${float(line.get('size_usd') or 0):,.0f}"
                    if float(line.get("size_usd") or 0) > 0
                    else "—"
                ),
                "Slices": len(line.get("slices") or []),
                "Patience": "yes" if line.get("patience") else "",
                "Score": f"{float(line.get('score') or 0):.2f}",
                "Filter": "in" if line.get("in_filter") else ("sticky" if line.get("sticky") else "out"),
                "Last bar": str(line.get("last_bar_ts") or "—")[-19:],
                "Err": (line.get("last_error") or line.get("patience_note") or "")[:40],
            }
        )
    return rows
