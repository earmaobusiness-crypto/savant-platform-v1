"""
Room 3 matrix DNA matching — live map slices vs saved layout vectors.

Self-contained (no Room 2 imports). Uses repertoire from room3_bridge.
"""

from __future__ import annotations

import math
from typing import Any

MATCH_THRESHOLD_PCT = 85
EXIT_MATCH_FLOOR_PCT = 65
STOP_LOSS_PCT = 2.5
MIN_SLICES = {"1m": 5, "5m": 4, "15m": 3}
PLACEHOLDER_LAYOUTS = frozenset({"NEW_LAYOUT", "PURGATORY_PENDING", "—", "-", ""})


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _pearson_r(values: list[float]) -> float:
    n = len(values)
    if n < 3:
        return 0.0
    mean = sum(values) / n
    num = sum((x - mean) * (i - (n - 1) / 2.0) for i, x in enumerate(values))
    den_x = math.sqrt(sum((i - (n - 1) / 2.0) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((x - mean) ** 2 for x in values))
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return max(-1.0, min(1.0, num / (den_x * den_y)))


def build_live_feature_vector(line: dict[str, Any]) -> list[float] | None:
    """Approximate Room 2 eight-dim DNA vector from watcher bar slices."""
    slices = list(line.get("slices") or [])
    tf = str(line.get("timeframe") or "1m")
    if len(slices) < int(MIN_SLICES.get(tf, 4)):
        return None

    rets = [float(s.get("ret") or 0) for s in slices]
    vols = [float(s.get("v") or 0) for s in slices]
    closes = [float(s.get("c") or 0) for s in slices if float(s.get("c") or 0) > 0]
    if not closes:
        return None

    session_velocity = sum(rets) * 100.0
    peak_bar = max(abs(r) for r in rets) * 100.0
    mean_bar = (sum(abs(r) for r in rets) / len(rets)) * 100.0

    vol_sigma = 0.0
    vol_z = 0.0
    pos_vols = [v for v in vols if v > 0]
    if len(pos_vols) > 1:
        avg_v = sum(pos_vols) / len(pos_vols)
        var_v = sum((v - avg_v) ** 2 for v in pos_vols) / len(pos_vols)
        vol_sigma = math.sqrt(var_v)
        if vol_sigma > 0:
            vol_z = (pos_vols[-1] - avg_v) / vol_sigma

    mean_close = sum(closes) / len(closes)
    vwap_bias = ((closes[-1] - mean_close) / closes[-1] * 100.0) if closes[-1] else 0.0
    pearson = _pearson_r(closes[-8:])

    return [
        round(session_velocity, 4),
        round(peak_bar, 4),
        round(mean_bar, 4),
        round(vol_sigma, 4),
        round(vol_z, 4),
        round(vwap_bias, 4),
        0.0,
        round(pearson, 4),
    ]


def match_spatial(
    snapshot_vec: list[float],
    layouts: list[dict[str, Any]],
    *,
    watch_timeframe: str | None = None,
) -> dict[str, Any]:
    best_cosine = 0.0
    nearest = "NEW_LAYOUT"
    nearest_strategy = ""
    structural_move = 0.0
    best_ticker = ""
    best_tf = ""
    watch_tf = _normalize_watch_tf(watch_timeframe or "")

    for entry in layouts or []:
        stored = entry.get("vector") or []
        if not stored or len(stored) != len(snapshot_vec):
            continue
        cos = cosine_similarity(snapshot_vec, [float(x) for x in stored])
        entry_tf = str(entry.get("timeframe_norm") or _normalize_watch_tf(entry.get("timeframe_resolution") or entry.get("strategy") or ""))
        if watch_tf and entry_tf:
            if entry_tf == watch_tf:
                cos = min(1.0, cos * 1.04)
            else:
                cos *= 0.90
        if cos > best_cosine:
            best_cosine = cos
            nearest = str(entry.get("layout_id") or "LAYOUT")
            nearest_strategy = str(entry.get("strategy") or "")
            structural_move = float(entry.get("structural_move_pct") or 0.0)
            best_ticker = str(entry.get("ticker") or "")
            best_tf = str(entry.get("timeframe_resolution") or entry_tf)
    return {
        "spatial_match_pct": int(round(best_cosine * 100)),
        "cosine_similarity": round(best_cosine, 4),
        "nearest_layout_id": nearest,
        "nearest_strategy": nearest_strategy,
        "structural_move_pct": structural_move,
        "layout_ticker": best_ticker,
        "layout_timeframe": best_tf,
    }


def _normalize_watch_tf(raw: str) -> str:
    t = str(raw or "").lower()
    if t in ("1m", "5m", "15m"):
        return t
    if "15" in t:
        return "15m"
    if "5" in t:
        return "5m"
    if "1" in t:
        return "1m"
    return t


def strategy_for_layout(layout_id: str, repertoire: dict[str, Any]) -> str:
    lid = str(layout_id or "").strip()
    if not lid or lid in PLACEHOLDER_LAYOUTS:
        return "matrix"
    for row in reversed(list(repertoire.get("deploy_registry") or [])):
        if str(row.get("layout") or row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if strat:
                return strat
    for row in repertoire.get("layouts") or []:
        if str(row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if strat:
                return strat
    return "matrix"


def score_line_against_repertoire(
    line: dict[str, Any],
    repertoire: dict[str, Any],
) -> dict[str, Any]:
    """DNA match result + blended display score for the watch book."""
    layouts = list(repertoire.get("layouts") or [])
    vec = build_live_feature_vector(line)
    if not vec or not layouts:
        warmth = min(
            1.0,
            len(line.get("slices") or [])
            / float({"1m": 24, "5m": 36, "15m": 48}.get(str(line.get("timeframe") or "1m"), 24)),
        )
        boost = 0.15 if repertoire.get("ready") else 0.0
        return {
            "display_score": round(min(1.0, warmth * 0.6 + boost), 4),
            "spatial_match_pct": 0,
            "nearest_layout_id": "—",
            "vector_ready": False,
        }

    spatial = match_spatial(vec, layouts, watch_timeframe=str(line.get("timeframe") or "1m"))
    pct = int(spatial.get("spatial_match_pct") or 0)
    warmth = min(1.0, len(line.get("slices") or []) / 24.0)
    display = min(1.0, (pct / 100.0) * 0.75 + warmth * 0.15 + (0.10 if repertoire.get("ready") else 0))
    return {
        **spatial,
        "display_score": round(display, 4),
        "vector_ready": True,
    }


def _ticker_already_engaged(book: dict[str, Any], ticker: str) -> bool:
    sym = str(ticker).upper()
    for line in (book.get("lines") or {}).values():
        if str(line.get("ticker") or "").upper() != sym:
            continue
        if line.get("state") in ("in", "committed") or line.get("entry_signal"):
            return True
    return False


def _open_qty(session_state: Any, symbol: str) -> float:
    try:
        for row in session_state.get("room3_open_positions") or []:
            if str(row.get("ticker") or "").upper() == str(symbol).upper():
                return abs(float(row.get("qty") or 0))
    except Exception:
        pass
    return 0.0


def _compute_entry_qty(
    *,
    price: float,
    session_state: Any,
    max_positions: int = 5,
) -> tuple[float, float]:
    """Return (qty, notional) from tradable budget."""
    if price <= 0:
        return 1.0, 0.0
    try:
        tradable = float(session_state.get("room3_tradable_today") or 0)
    except (TypeError, ValueError):
        tradable = 0.0
    deployed = 0.0
    try:
        import room3_engine

        deployed = room3_engine.deployed_notional(session_state.get("room3_open_positions"))
    except Exception:
        pass
    open_n = len(list(session_state.get("room3_open_positions") or []))
    room = max(0.0, tradable - deployed)
    slots_left = max(1, int(max_positions) - open_n)
    slot = room / slots_left if room > 0 else 0.0
    if slot <= 0 and tradable > 0:
        slot = tradable * 0.1
    notional = min(slot, room if room > 0 else slot)
    if notional <= 0:
        return 1.0, price
    qty = max(1.0, math.floor(notional / price))
    return qty, qty * price


def maybe_queue_matrix_signals(
    book: dict[str, Any],
    line: dict[str, Any],
    repertoire: dict[str, Any],
    session_state: Any,
    *,
    engine_armed: bool = False,
) -> None:
    """
    Stamp entry_signal or exit_signal on a line when DNA rules pass.
    One entry per ticker across all TF lines.
    """
    import room3_watcher

    match = score_line_against_repertoire(line, repertoire)
    line["match_pct"] = int(match.get("spatial_match_pct") or 0)
    line["nearest_layout"] = str(match.get("nearest_layout_id") or "—")
    line["nearest_strategy"] = str(match.get("nearest_strategy") or "—")
    line["score"] = float(match.get("display_score") or 0)

    layouts = list(repertoire.get("layouts") or [])
    if not layouts or not engine_armed:
        return

    ticker = str(line.get("ticker") or "").upper()
    tf = str(line.get("timeframe") or "1m")
    slices = list(line.get("slices") or [])
    last_px = float(slices[-1].get("c") or 0) if slices else 0.0

    if line.get("state") == "in":
        entry_px = float(line.get("entry_price") or last_px or 0)
        entry_match = int(line.get("entry_match_pct") or MATCH_THRESHOLD_PCT)
        cur_match = int(line.get("match_pct") or 0)
        structural = float(line.get("entry_structural_move_pct") or 0.0)
        pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if entry_px > 0 and last_px > 0 else 0.0

        # Patience: stock may lag the pattern — don't panic-exit on mild fade
        # while DNA still warm and structural target not yet reached.
        patience = True
        exit_reason = ""
        hard_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 15
        soft_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 10
        if hard_fade:
            exit_reason = f"match faded {cur_match}%"
        elif soft_fade and not patience:
            exit_reason = f"match faded {cur_match}%"
        elif soft_fade and patience and structural > 0 and pnl_pct < structural * 0.25:
            line["patience"] = True
            line["patience_note"] = (
                f"holding · match {cur_match}% · waiting for move "
                f"(target ~{structural:.1f}%)"
            )
            exit_reason = ""
        elif soft_fade:
            exit_reason = f"match faded {cur_match}%"
        elif pnl_pct <= -STOP_LOSS_PCT:
            exit_reason = f"stop {pnl_pct:.1f}%"
        elif structural > 0 and pnl_pct >= structural * 0.5:
            exit_reason = f"target {pnl_pct:.1f}%"

        if exit_reason and not line.get("exit_signal"):
            qty = _open_qty(session_state, ticker)
            if qty <= 0:
                qty = float(line.get("entry_qty") or 1.0)
            strat = str(line.get("entry_strategy") or "matrix")
            room3_watcher.queue_exit_signal(
                book,
                ticker,
                tf,
                side="sell",
                qty=qty,
                strategy=strat,
            )
            line["last_exit_reason"] = exit_reason
            line["patience"] = False
        return

    if line.get("entry_signal") or line.get("state") not in ("watching", "committed"):
        return
    if not match.get("vector_ready"):
        return

    cur_match = int(match.get("spatial_match_pct") or 0)
    # Warm DNA but not full signal yet — keep mapping; stock may still fill the puzzle.
    if cur_match < MATCH_THRESHOLD_PCT:
        if cur_match >= 70:
            line["patience"] = True
            line["patience_note"] = (
                f"warming {cur_match}% · need ≥{MATCH_THRESHOLD_PCT}% · "
                f"30s snaps continue"
            )
        return
    line["patience"] = False
    line.pop("patience_note", None)
    if _ticker_already_engaged(book, ticker):
        return

    layout_id = str(match.get("nearest_layout_id") or "")
    if layout_id in PLACEHOLDER_LAYOUTS:
        return

    strategy = str(match.get("nearest_strategy") or "") or strategy_for_layout(layout_id, repertoire)
    qty, notional = _compute_entry_qty(price=last_px, session_state=session_state)
    room3_watcher.queue_entry_signal(
        book,
        ticker,
        tf,
        side="buy",
        qty=qty,
        strategy=strategy,
    )
    key = room3_watcher.line_key(ticker, tf)
    stamped = (book.get("lines") or {}).get(key) or line
    stamped["entry_match_pct"] = int(match.get("spatial_match_pct") or 0)
    stamped["entry_layout"] = layout_id
    stamped["entry_strategy"] = strategy
    stamped["entry_price"] = last_px
    stamped["entry_qty"] = qty
    stamped["entry_structural_move_pct"] = float(match.get("structural_move_pct") or 0.0)
    stamped["entry_signal"]["ref_price"] = last_px
    stamped["entry_signal"]["notional"] = notional
    stamped["entry_signal"]["match_pct"] = stamped["entry_match_pct"]
    stamped["entry_signal"]["layout_id"] = layout_id
    stamped["entry_signal"]["strategy"] = strategy
    line["nearest_strategy"] = strategy
