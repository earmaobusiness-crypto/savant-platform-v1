"""
Room 3 watcher — the eyes.

One stock in the filter → three maps (1m / 5m / 15m), different data diets.
Heartbeat appends a slice (not "trade on 30s alone").
Filter drop → purge map unless sticky (close to repertoire).
Day end / no trade → delete maps.
Filter feed plugs in via set_filter_universe() — TradingView filters next.

Does NOT import Room 2 modules. Uses room3_bridge snapshot only for repertoire hints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import room3_bridge
import room3_engine

ET = ZoneInfo("America/New_York")

TIMEFRAMES = ("1m", "5m", "15m")
MAX_NAMES = 10
STICKY_MIN_SCORE = 0.72  # keep after filter drop if map this close to repertoire
STICKY_MAX_MINUTES = 90

# Picture budget — lean 1m, richer 15m
TF_DIET: dict[str, dict[str, Any]] = {
    "1m": {
        "max_slices": 24,  # ~last ~12–24 min of pulse memory
        "yf_interval": "1m",
        "yf_period": "1d",
        "bars_keep": 12,  # thin chart memory
        "extras": "chart",  # almost chart-only
    },
    "5m": {
        "max_slices": 36,
        "yf_interval": "5m",
        "yf_period": "5d",
        "bars_keep": 36,
        "extras": "light",
    },
    "15m": {
        "max_slices": 48,
        "yf_interval": "15m",
        "yf_period": "10d",
        "bars_keep": 64,
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
    else:
        book["last_note"] = "Awaiting TradingView / session filter feed."
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
        if line.get("state") == "in":
            # still in a trade — keep until exit path closes it
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
    }


def _sticky_alive(line: dict[str, Any]) -> bool:
    until = str(line.get("sticky_until") or "")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now(ET)
    except Exception:
        return False


def _fetch_bar_snapshot(ticker: str, tf: str) -> dict[str, Any] | None:
    """Pull a lean closed-bar fingerprint for this TF diet."""
    diet = TF_DIET.get(tf) or TF_DIET["1m"]
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(
            period=str(diet["yf_period"]),
            interval=str(diet["yf_interval"]),
            auto_adjust=True,
        )
        if hist is None or hist.empty:
            return None
        keep = int(diet["bars_keep"])
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
    line["slices"] = slices[-max_n:]
    line["last_bar_ts"] = ts
    line["last_error"] = ""
    return True


def _score_against_repertoire(line: dict[str, Any], matrix: dict[str, Any]) -> float:
    """
    Soft proximity score until full matrix DNA matching is plugged in.
    Uses map warmth + Room 2 handshake presence — does NOT invent fake entries.
    """
    slices = list(line.get("slices") or [])
    if not slices:
        return 0.0
    warmth = min(1.0, len(slices) / float(TF_DIET.get(line.get("timeframe") or "1m", {}).get("max_slices") or 24))
    # Recent motion energy (chart-led, especially 1m)
    last = slices[-1]
    energy = min(1.0, abs(float(last.get("ret") or 0)) * 40.0 + abs(float(last.get("range") or 0)) * 8.0)
    matrix_boost = 0.15 if matrix.get("ready") else 0.0
    # Heavier TFs lean a bit more on accumulated map than instant energy
    tf = str(line.get("timeframe") or "1m")
    if tf == "1m":
        score = 0.55 * energy + 0.30 * warmth + matrix_boost
    elif tf == "5m":
        score = 0.40 * energy + 0.45 * warmth + matrix_boost
    else:
        score = 0.30 * energy + 0.55 * warmth + matrix_boost
    return round(min(1.0, score), 4)


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
    """
    Produce an entry/exit intent only when rules say so.

    Until TradingView filters + matrix DNA are plugged in, this stays conservative:
    no automatic entries from warmup alone. Exit still returns if state==in and
    an exit_signal was stamped (future path).
    """
    if line.get("state") == "in" and line.get("exit_signal"):
        sig = dict(line["exit_signal"])
        line["exit_signal"] = None
        return sig
    # Optional queued entry from filter/matrix adapter
    if line.get("state") in ("watching", "committed") and line.get("entry_signal"):
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
    }
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    One heartbeat:
      - sync lines to filter universe
      - append TF slices (diets)
      - score sticky proximity
      - emit queued signals (from filter/matrix adapter)
    Returns (book, signals_to_fire).
    """
    book = dict(book or empty_book())
    signals: list[dict[str, Any]] = []
    book["ticks"] = int(book.get("ticks") or 0) + 1
    book["last_tick"] = datetime.now(ET).strftime("%H:%M:%S ET")

    if not session_allowed:
        book["last_note"] = "Session filter closed / not armed for this window — maps held, no new scan."
        return book, signals

    if book.get("awaiting_filters") or not (book.get("universe") or []):
        book["last_note"] = "Eyes ready · waiting for TradingView filter names."
        return book, signals

    _ensure_lines_for_universe(book)
    matrix = room3_bridge.matrix_snapshot(session_state)

    # Cap work: universe already capped; scan lines
    for key, line in list((book.get("lines") or {}).items()):
        if line.get("state") == "flat_day":
            continue
        # Still scan sticky / in-filter / in-trade
        if not line.get("in_filter") and not line.get("sticky") and line.get("state") != "in":
            continue
        snap = _fetch_bar_snapshot(str(line["ticker"]), str(line["timeframe"]))
        _append_slice(line, snap or {})
        line["score"] = _score_against_repertoire(line, matrix)
        if line.get("in_filter") is False:
            _maybe_mark_sticky(line)
        elif float(line.get("score") or 0) >= STICKY_MIN_SCORE:
            _maybe_mark_sticky(line)

        if engine_armed:
            sig = evaluate_line_signals(line)
            if sig:
                signals.append(sig)

    n_lines = len(book.get("lines") or {})
    book["last_note"] = (
        f"Scanned {n_lines} TF maps · universe {len(book.get('universe') or [])} · "
        f"matrix={'ready' if matrix.get('ready') else 'quiet'}"
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
                "Slices": len(line.get("slices") or []),
                "Score": f"{float(line.get('score') or 0):.2f}",
                "Filter": "in" if line.get("in_filter") else ("sticky" if line.get("sticky") else "out"),
                "Last bar": str(line.get("last_bar_ts") or "—")[-19:],
                "Err": (line.get("last_error") or "")[:40],
            }
        )
    return rows
