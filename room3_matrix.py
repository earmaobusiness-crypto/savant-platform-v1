"""
Room 3 matrix DNA matching — live map slices vs saved layout vectors.

Self-contained (no Room 2 imports). Uses repertoire from room3_bridge.
"""

from __future__ import annotations

import math
from typing import Any

import room3_engine
import room3_recipes
import room3_review_learn

room3_lots = room3_engine.lots

MATCH_THRESHOLD_PCT = 85
CHILD_READY_PCT = 84  # show a strategy sub-lane; fire still waits for MATCH_THRESHOLD
EXIT_MATCH_FLOOR_PCT = 65
STOP_LOSS_PCT = 2.5
MIN_SLICES = {"1m": 5, "5m": 4, "15m": 3}
PLACEHOLDER_LAYOUTS = frozenset(
    {"NEW_LAYOUT", "PURGATORY_PENDING", "Purgatory", "PURGATORY", "—", "-", ""}
)

# Day book split — these three add to 100% of Trading today.
TF_BUCKET_FRAC: dict[str, float] = {"15m": 0.50, "5m": 0.30, "1m": 0.20}
# Expected fills (opening reservation). Caps stay under ~50 combined max.
TF_PROJECTED_PRIOR: dict[str, int] = {"15m": 3, "5m": 6, "1m": 5}
TF_PROJECTED_CAP: dict[str, int] = {"15m": 6, "5m": 12, "1m": 10}
SCALE_IN_MAX = 1  # one add onto a live winner
SCALE_IN_TARGET_FRAC = 0.50  # add only while P/L is still under half the layout move
SIZE_AT_THRESHOLD = 0.80  # 85% match → 80% of that TF's slot
WARMING_MATCH_PCT = 70  # sticky / warming Err floor (not an entry)


def size_explain(session_state: Any | None = None) -> str:
    snap = tf_budget_snapshot(session_state) if session_state is not None else None
    tradable = float((snap or {}).get("tradable") or 0)
    book_txt = (
        f"Trading today is ${tradable:,.0f}. "
        if tradable > 0
        else "Trading today is the day’s deployable cash. "
    )
    p = (snap or {}).get("projected") or TF_PROJECTED_PRIOR
    n15 = max(1, int(p.get("15m") or 4))
    slot_frac = 1.0 / n15
    return (
        f"{book_txt}"
        "That cash is split into timeframe buckets that add to 100%: "
        f"15m {TF_BUCKET_FRAC['15m']:.0%} · 5m {TF_BUCKET_FRAC['5m']:.0%} · "
        f"1m {TF_BUCKET_FRAC['1m']:.0%}. "
        f"Layouts project about {p.get('15m', 3)} fifteen-minute fills, "
        f"{p.get('5m', 6)} five-minute, {p.get('1m', 5)} one-minute today — "
        f"each full-match 15m therefore starts at 1/{n15} of the 15m bucket "
        f"({slot_frac:.0%} of that 50%). "
        "Those percents are the opening reservation, not walls. "
        "If a TF prints more than expected, it collects leftover from buckets that are "
        "not hot (live < projected). A live 15m that is still in the move can add once "
        "from that same idle cash. If 5m or 1m is the hot book, leftover flows there "
        "instead of sitting in 15m. "
        "Weaker match uses less of its slot. "
        "Uniqueness still cuts size when two strategies are almost equally close. "
        "Chart-wallpaper downweight is not in this formula yet. "
        "Watch-book Size $ is the planned amount, not a fill."
    )


SIZE_EXPLAIN = (
    "Trading today opens 50% 15m / 30% 5m / 20% 1m. "
    "Leftover is fluid: extra fills and a still-moving 15m collect idle cash "
    "from buckets that are not hot. A hot 5m/1m keeps its pot and can pull quiet 15m leftover."
)


def cosine_similarity(vec_a: list[float], vec_b: list[float], weights: list[float] | None = None) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    w = weights if weights and len(weights) == len(vec_a) else [1.0] * len(vec_a)
    dot = sum(wa * a * b for wa, a, b in zip(w, vec_a, vec_b))
    norm_a = math.sqrt(sum(wa * a * a for wa, a in zip(w, vec_a)))
    norm_b = math.sqrt(sum(wa * b * b for wa, b in zip(w, vec_b)))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _wallpaper_weights(layouts: list[dict[str, Any]], dim: int) -> list[float]:
    """
    Downweight dimensions that look the same in almost every saved pattern
    (wallpaper). Distinct / high-spread traits weigh more.
    """
    rows: list[list[float]] = []
    for entry in layouts or []:
        stored = entry.get("vector") or []
        if not stored or len(stored) != dim:
            continue
        rows.append([float(x) for x in stored])
    if len(rows) < 3:
        return [1.0] * dim
    n = float(len(rows))
    weights: list[float] = []
    for i in range(dim):
        vals = [r[i] for r in rows]
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / n
        std = math.sqrt(var)
        # High spread → distinctive. Near-zero spread → wallpaper.
        w = math.log(1.0 + (std / (abs(mean) + 0.12)))
        weights.append(max(0.20, min(2.4, 0.35 + w * 1.8)))
    return weights


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
    # Log-volume so share-count sigma cannot crush cosine vs Room 2 envelopes.
    vol_sigma_n = math.log10(1.0 + vol_sigma) if vol_sigma > 0 else 0.0

    return [
        round(session_velocity, 4),
        round(peak_bar, 4),
        round(mean_bar, 4),
        round(vol_sigma_n, 4),
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
    second_cosine = 0.0
    nearest = "—"
    nearest_strategy = ""
    structural_move = 0.0
    best_ticker = ""
    best_tf = ""
    watch_tf = _normalize_watch_tf(watch_timeframe or "")
    dim_ok = [
        e
        for e in (layouts or [])
        if (e.get("vector") or []) and len(e.get("vector") or []) == len(snapshot_vec)
    ]
    usable: list[dict[str, Any]] = []
    for e in dim_ok:
        entry_tf = _layout_dna_tf(e)
        if watch_tf and entry_tf and entry_tf != watch_tf:
            continue
        strat = str(e.get("strategy") or e.get("execution_strategy") or "")
        if room3_recipes.is_purgatory_letter(
            str(e.get("layout_id") or ""), strat
        ):
            continue
        if watch_tf and strat and not room3_recipes.strategy_tf_agrees(strat, watch_tf):
            continue
        usable.append(e)
    weights = _wallpaper_weights(usable, len(snapshot_vec))

    ranked_hits: list[dict[str, Any]] = []
    for entry in usable:
        stored = [float(x) for x in (entry.get("vector") or [])]
        cos = cosine_similarity(snapshot_vec, stored, weights)
        entry_tf = _layout_dna_tf(entry)
        ranked_hits.append(
            {
                "cosine": cos,
                "layout_id": str(entry.get("layout_id") or "—"),
                "strategy": str(entry.get("strategy") or ""),
                "structural_move_pct": float(entry.get("structural_move_pct") or 0.0),
                "ticker": str(entry.get("ticker") or ""),
                "timeframe": str(entry.get("timeframe_resolution") or entry_tf),
            }
        )
        if cos > best_cosine:
            second_cosine = best_cosine
            best_cosine = cos
            nearest = str(entry.get("layout_id") or "—")
            nearest_strategy = str(entry.get("strategy") or "")
            structural_move = float(entry.get("structural_move_pct") or 0.0)
            best_ticker = str(entry.get("ticker") or "")
            best_tf = str(entry.get("timeframe_resolution") or entry_tf)
        elif cos > second_cosine:
            second_cosine = cos
    ranked_hits.sort(key=lambda h: -float(h.get("cosine") or 0))
    ranked: list[dict[str, Any]] = []
    seen_letters: set[str] = set()
    for hit in ranked_hits:
        if float(hit.get("cosine") or 0) <= 0:
            continue
        token = room3_lots.letter_token(str(hit.get("layout_id") or ""), str(hit.get("strategy") or ""))
        if not token or token in seen_letters:
            continue
        seen_letters.add(token)
        ranked.append(
            {
                "layout_id": hit["layout_id"],
                "strategy": hit["strategy"] or token,
                "letter": token,
                "spatial_match_pct": int(round(float(hit["cosine"]) * 100)),
                "cosine_similarity": round(float(hit["cosine"]), 4),
                "structural_move_pct": float(hit.get("structural_move_pct") or 0),
            }
        )
        if len(ranked) >= 8:
            break
    # No positive hit → do not invent "NEW_LAYOUT" (Room 2 mint jargon). Show blank.
    if best_cosine <= 0:
        nearest = "—"
        nearest_strategy = ""
        structural_move = 0.0
        best_ticker = ""
        best_tf = ""
        ranked = []
    return {
        "spatial_match_pct": int(round(best_cosine * 100)),
        "cosine_similarity": round(best_cosine, 4),
        "second_cosine": round(second_cosine, 4),
        "nearest_layout_id": nearest,
        "nearest_strategy": nearest_strategy,
        "structural_move_pct": structural_move,
        "layout_ticker": best_ticker,
        "layout_timeframe": best_tf,
        "ranked": ranked,
    }


def _normalize_watch_tf(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    named = room3_recipes.strategy_tf_token(text)
    if named:
        return named
    t = text.lower()
    if t in ("1m", "5m", "15m"):
        return t
    return room3_recipes.recipe_timeframe(timeframe=text) or t


def _layout_dna_tf(entry: dict[str, Any]) -> str:
    return room3_recipes.recipe_timeframe(
        strategy=str(entry.get("strategy") or entry.get("execution_strategy") or ""),
        timeframe_norm=str(entry.get("timeframe_norm") or ""),
        timeframe=str(entry.get("timeframe") or ""),
        timeframe_resolution=str(entry.get("timeframe_resolution") or ""),
    )


def strategy_for_layout(
    layout_id: str,
    repertoire: dict[str, Any],
    *,
    timeframe: str = "",
) -> str:
    lid = str(layout_id or "").strip()
    if not lid or lid in PLACEHOLDER_LAYOUTS:
        return "matrix"
    if room3_recipes.is_purgatory_letter(lid, ""):
        return "matrix"
    want = _normalize_watch_tf(timeframe) if timeframe else ""

    def _ok(strat: str) -> bool:
        if not strat:
            return False
        if room3_recipes.is_purgatory_letter(lid, strat):
            return False
        return room3_recipes.strategy_tf_agrees(strat, want) if want else True

    for row in reversed(list(repertoire.get("deploy_registry") or [])):
        if str(row.get("layout") or row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if _ok(strat):
                return strat
    for row in repertoire.get("layouts") or []:
        if str(row.get("layout_id") or "") == lid:
            strat = str(row.get("strategy") or row.get("execution_strategy") or "").strip()
            if _ok(strat):
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
            "ranked": [],
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


def _approaching_day_close() -> bool:
    """Last ~20 minutes of post — take the second-best exit rather than hold overnight."""
    try:
        from datetime import datetime, time as dtime

        import room3_engine

        now = datetime.now(room3_engine.ET)
        if room3_engine.detect_session_window(now) != room3_engine.SESSION_POST:
            return False
        return now.time() >= dtime(19, 40)
    except Exception:
        return False


def _ticker_already_engaged(
    book: dict[str, Any],
    ticker: str,
    *,
    except_key: str = "",
    session_state: Any = None,
    letter: str = "",
) -> bool:
    """True if this letter is already in/queued. A different letter may add."""
    token = room3_lots.letter_token("", letter) if letter else ""
    if token and session_state is not None:
        if room3_lots.open_lots(session_state, ticker, letter=token):
            return True
    for key, line in (book.get("lines") or {}).items():
        if except_key and key == except_key:
            continue
        if str(line.get("ticker") or "").upper() != str(ticker).upper():
            continue
        queued = str((line.get("entry_signal") or {}).get("strategy") or "")
        if token and queued and room3_lots.letter_token("", queued) == token:
            return True
        if token:
            continue
        # No letter asked: only block a duplicate queue on this same line.
        if except_key and key == except_key:
            continue
    return False


def _sync_hot_children(
    line: dict[str, Any],
    ranked: list[dict[str, Any]],
    session_state: Any,
    ticker: str,
    tf: str,
) -> list[dict[str, Any]]:
    """Mint/keep fire-ready sub-lanes. Open lots stay even if Match% cools."""
    prev = {
        str(c.get("letter") or ""): dict(c)
        for c in (line.get("children") or [])
        if isinstance(c, dict) and str(c.get("letter") or "").strip()
    }
    open_tokens = {
        str(r.get("letter") or "")
        for r in room3_lots.open_lots(session_state, ticker, tf=tf)
        if str(r.get("letter") or "").strip()
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked or []:
        layout = str(row.get("layout_id") or "")
        strat = str(row.get("strategy") or "")
        if room3_recipes.is_purgatory_letter(layout, strat):
            continue
        letter = str(row.get("letter") or room3_lots.letter_token(layout, strat))
        if not letter or letter in seen:
            continue
        pct = int(row.get("spatial_match_pct") or 0)
        if pct < CHILD_READY_PCT and letter not in open_tokens:
            continue
        seen.add(letter)
        old = prev.get(letter) or {}
        child = {
            "letter": letter,
            "layout_id": layout,
            "strategy": strat or letter,
            "match_pct": pct,
            "structural_move_pct": float(row.get("structural_move_pct") or 0),
            "cosine_similarity": float(row.get("cosine_similarity") or 0),
            "family_armed_px": old.get("family_armed_px"),
            "family_armed_high": old.get("family_armed_high"),
            "pullback_low": old.get("pullback_low"),
            "trigger_phase": old.get("trigger_phase"),
            "entry_skipped_late": old.get("entry_skipped_late"),
            "patience_note": str(old.get("patience_note") or ""),
            "in_lot": letter in open_tokens,
        }
        if pct < WARMING_MATCH_PCT and letter not in open_tokens:
            _reset_entry_trigger(child)
        out.append(child)
    for letter in open_tokens:
        if letter in seen:
            continue
        old = prev.get(letter) or {}
        old["letter"] = letter
        old["in_lot"] = True
        out.append(old)
    line["children"] = out
    return out


def _child_match_floor(session_state: Any, child: dict[str, Any], tf: str) -> float:
    floor = float(MATCH_THRESHOLD_PCT)
    try:
        floor += float(
            room3_review_learn.overlay_match_floor_delta(
                session_state,
                str(child.get("layout_id") or ""),
                str(child.get("strategy") or ""),
                tf,
            )
        )
    except Exception:
        pass
    return max(70.0, min(95.0, floor))


def _try_queue_child_entry(
    book: dict[str, Any],
    line: dict[str, Any],
    *,
    session_state: Any,
    ticker: str,
    tf: str,
    last_px: float,
    slices: list[dict[str, Any]],
    layouts: list[dict[str, Any]],
    match: dict[str, Any],
) -> bool:
    """Queue one child that is fire-ready. Second letter on the pile is an add."""
    import room3_watcher

    if line.get("entry_signal"):
        return False
    children = list(line.get("children") or [])
    for child in children:
        if not isinstance(child, dict):
            continue
        letter = str(child.get("letter") or "")
        layout_id = str(child.get("layout_id") or "")
        strategy = str(child.get("strategy") or letter)
        if not letter or room3_recipes.is_purgatory_letter(layout_id, strategy):
            continue
        if child.get("in_lot"):
            continue
        if _ticker_already_engaged(
            book, ticker, except_key=room3_watcher.line_key(ticker, tf),
            session_state=session_state, letter=letter,
        ):
            continue
        pct = int(child.get("match_pct") or 0)
        floor = _child_match_floor(session_state, child, tf)
        if pct < floor:
            if pct >= WARMING_MATCH_PCT:
                child["patience_note"] = f"warming {pct}% · need ≥{int(floor)}%"
            continue
        structural = float(child.get("structural_move_pct") or 0)
        ready, trigger_note = _entry_trigger_ready(
            child,
            slices,
            last_px=last_px,
            tf=tf,
            strategy=strategy,
            layout_id=layout_id,
            structural=structural,
        )
        child["patience_note"] = trigger_note
        if not ready:
            continue
        add_lot = bool(room3_lots.open_lots(session_state, ticker) or _open_qty(session_state, ticker) > 0)
        if tf == "15m" and not _15m_can_open_lot(session_state, ticker, scale_in=False):
            child["patience_note"] = "15m add already used · wait exit"
            continue
        qty, notional = _compute_entry_qty(
            price=last_px,
            session_state=session_state,
            timeframe=tf,
            match_pct=pct,
            second_cosine=float(match.get("second_cosine") or 0),
            best_cosine=float(child.get("cosine_similarity") or match.get("cosine_similarity") or 0),
            layouts=layouts,
            exclude_ticker=ticker if add_lot else "",
        )
        if qty < 1 or notional <= 0:
            child["patience_note"] = "size $0 — not enough room or price too high"
            continue
        _claim_cash(session_state, notional)
        room3_watcher.queue_entry_signal(
            book,
            ticker,
            tf,
            side="buy",
            qty=qty,
            strategy=strategy,
            keep_in=add_lot and str(line.get("state") or "") == "in",
            scale_in=False,
            layout_id=layout_id,
        )
        key = room3_watcher.line_key(ticker, tf)
        stamped = (book.get("lines") or {}).get(key) or line
        stamped["entry_match_pct"] = pct
        stamped["entry_layout"] = layout_id
        stamped["entry_strategy"] = strategy
        stamped["entry_price"] = last_px
        stamped["entry_qty"] = qty
        stamped["entry_structural_move_pct"] = structural
        sig = stamped.get("entry_signal")
        if isinstance(sig, dict):
            sig["ref_price"] = last_px
            sig["notional"] = notional
            sig["match_pct"] = pct
            sig["layout_id"] = layout_id
            sig["strategy"] = strategy
            sig["add_lot"] = add_lot
            sig["letter"] = letter
            sig["trigger"] = trigger_note
            sig["order_style"] = room3_recipes.order_style_for(
                strategy,
                tf,
                layout_id=layout_id,
                structural_move_pct=structural,
            )
        line["nearest_strategy"] = strategy
        line["patience"] = False
        line.pop("patience_note", None)
        return True
    return False


def _lot_should_exit(
    lot: dict[str, Any],
    *,
    cur_match: int,
    last_px: float,
    patience: bool,
) -> str:
    entry_px = float(lot.get("entry_px") or 0)
    entry_match = int(lot.get("entry_match_pct") or MATCH_THRESHOLD_PCT)
    structural = float(lot.get("structural_move_pct") or 0)
    pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if entry_px > 0 and last_px > 0 else 0.0
    hard_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 15
    soft_fade = cur_match < EXIT_MATCH_FLOOR_PCT and cur_match < entry_match - 10
    if hard_fade:
        return f"match faded {cur_match}%"
    if soft_fade and not patience:
        return f"match faded {cur_match}%"
    if soft_fade and patience and structural > 0 and pnl_pct < structural * 0.25:
        return ""
    if soft_fade:
        return f"match faded {cur_match}%"
    if pnl_pct <= -STOP_LOSS_PCT:
        return f"stop {pnl_pct:.1f}%"
    if structural > 0 and pnl_pct >= structural * 0.5:
        return f"target {pnl_pct:.1f}%"
    if _approaching_day_close():
        return "day close · second-best exit"
    return ""


def _open_qty(session_state: Any, symbol: str) -> float:
    try:
        for row in session_state.get("room3_open_positions") or []:
            if str(row.get("ticker") or "").upper() == str(symbol).upper():
                return abs(float(row.get("qty") or 0))
    except Exception:
        pass
    return 0.0


def _15m_scale_in_used(session_state: Any, ticker: str) -> bool:
    try:
        book = session_state.get("room3_watch_book") or {}
        for line in (book.get("lines") or {}).values():
            if str(line.get("ticker") or "").upper() != str(ticker).upper():
                continue
            if str(line.get("timeframe") or "") != "15m":
                continue
            if int(line.get("scale_ins") or 0) >= SCALE_IN_MAX:
                return True
    except Exception:
        return False
    return False


def _15m_can_open_lot(
    session_state: Any,
    ticker: str,
    *,
    scale_in: bool = False,
) -> bool:
    """A live 15m can add once: initial lot + one add (scale-in or a second 15m letter)."""
    n15 = len(room3_lots.open_lots(session_state, ticker, tf="15m"))
    if n15 <= 0:
        return True
    if n15 >= 2:
        return False
    if scale_in:
        return not _15m_scale_in_used(session_state, ticker)
    if _15m_scale_in_used(session_state, ticker):
        return False
    return True


def _off_belt(line: dict[str, Any], book: dict[str, Any]) -> bool:
    """Open leftover maps (keep_tickers) that are not on the operator belt."""
    if line.get("in_filter") is False:
        return True
    ticker = str(line.get("ticker") or "").upper()
    uni = {str(t).upper() for t in (book.get("universe") or []) if str(t).strip()}
    return bool(ticker) and ticker not in uni


def _enter_on_print(
    strategy: str,
    tf: str,
    layout_id: str,
    structural_move_pct: float,
) -> bool:
    """1m pops: the start is the trigger. Everything else waits a first hold/pullback."""
    tf_n = room3_recipes.normalize_tf(tf)
    style = room3_recipes.order_style_for(
        strategy,
        tf_n,
        layout_id=layout_id,
        structural_move_pct=structural_move_pct,
    )
    return tf_n == "1m" and style == "market"


def _reset_entry_trigger(line: dict[str, Any]) -> None:
    line.pop("family_armed_px", None)
    line.pop("family_armed_high", None)
    line.pop("pullback_low", None)
    line.pop("trigger_phase", None)
    line.pop("entry_skipped_late", None)


def _entry_is_late(line: dict[str, Any], last_px: float, structural: float) -> bool:
    armed = float(line.get("family_armed_px") or 0)
    if armed <= 0 or last_px <= 0:
        return False
    run_pct = (last_px - armed) / armed * 100.0
    if run_pct >= 8.0:
        return True
    if structural > 0 and run_pct >= max(2.0, structural * 0.5):
        return True
    return False


def _entry_trigger_ready(
    line: dict[str, Any],
    slices: list[dict[str, Any]],
    *,
    last_px: float,
    tf: str,
    strategy: str,
    layout_id: str,
    structural: float,
) -> tuple[bool, str]:
    """
    ≥85% = family. Fill = letter style, else TF fallback.
    Late (half the expected move already in) = skip this shot.
    """
    if line.get("entry_skipped_late"):
        return False, "late · skipped · wait next pattern"
    if last_px <= 0:
        return False, "no last print"
    if not line.get("family_armed_px"):
        line["family_armed_px"] = last_px
        last_h = float((slices[-1] or {}).get("h") or last_px) if slices else last_px
        line["family_armed_high"] = last_h
        if _enter_on_print(strategy, tf, layout_id, structural):
            line["trigger_phase"] = "ready"
        else:
            line["trigger_phase"] = "wait_dip"
    if _entry_is_late(line, last_px, structural):
        line["entry_skipped_late"] = True
        line["trigger_phase"] = "skipped"
        return False, "late · move already gone · skip"
    if _enter_on_print(strategy, tf, layout_id, structural):
        return True, "pop · enter now"
    tf_n = room3_recipes.normalize_tf(tf)
    armed_px = float(line.get("family_armed_px") or last_px)
    last = slices[-1] if slices else {}
    last_c = float(last.get("c") or last_px)
    last_l = float(last.get("l") or last_c)
    dip_frac = 0.012 if tf_n == "15m" else 0.008 if tf_n == "5m" else 0.004
    phase = str(line.get("trigger_phase") or "wait_dip")
    if phase == "ready":
        return True, "trigger ready"
    if phase == "wait_dip":
        if last_l <= armed_px * (1.0 - dip_frac) or last_c < armed_px:
            line["trigger_phase"] = "wait_reclaim"
            line["pullback_low"] = last_l
            return False, "≥85% · first dip · waiting reclaim"
        return False, "≥85% · waiting first pullback"
    if phase == "wait_reclaim":
        pb = min(float(line.get("pullback_low") or last_l), last_l)
        line["pullback_low"] = pb
        if tf_n == "15m":
            if last_c > pb and last_c >= armed_px * 0.997:
                line["trigger_phase"] = "ready"
                return True, "15m hold after pullback"
            return False, "15m · waiting hold after dip"
        prior = slices[-2] if len(slices) >= 2 else last
        prior_high = float(prior.get("h") or prior.get("c") or 0)
        if last_c > pb and (prior_high <= 0 or last_c >= prior_high):
            line["trigger_phase"] = "ready"
            return True, "reclaim after pullback"
        return False, "waiting reclaim after dip"
    return False, "≥85% · waiting trigger"


def _ss_get(session_state: Any, key: str, default: Any = None) -> Any:
    if session_state is None:
        return default
    try:
        return session_state.get(key, default)
    except Exception:
        return default


def _tf_layout_counts(layouts: list[dict[str, Any]] | None) -> dict[str, int]:
    counts = {"1m": 0, "5m": 0, "15m": 0}
    seen: set[tuple[str, str, str]] = set()
    for entry in layouts or []:
        tf = _layout_dna_tf(entry)
        if tf not in counts:
            continue
        key = (
            str(entry.get("layout_id") or entry.get("layout") or "").strip(),
            str(entry.get("strategy") or "").strip(),
            tf,
        )
        if key in seen:
            continue
        seen.add(key)
        counts[tf] += 1
    return counts


def project_tf_counts(
    layouts: list[dict[str, Any]] | None,
    n_names: int | None = None,
) -> dict[str, int]:
    """
    Expected fills per TF today from layout richness + how many names are on the belt.
    sqrt(recipe_count / prior) so a fat 15m library does not claim 20 fills.
    Empty DNA uses the prior (3 / 6 / 5) until layouts hydrate.
    """
    n = _tf_layout_counts(layouts)
    name_scale = 1.0
    try:
        nn = int(n_names or 0)
    except (TypeError, ValueError):
        nn = 0
    if nn > 0:
        name_scale = min(1.5, max(0.75, math.sqrt(nn / 8.0)))
    out: dict[str, int] = {}
    for tf in ("15m", "5m", "1m"):
        prior = int(TF_PROJECTED_PRIOR[tf])
        cap = int(TF_PROJECTED_CAP[tf])
        layouts_n = int(n.get(tf) or 0)
        if layouts_n <= 0:
            est = prior
        else:
            richness = math.sqrt(max(1.0, layouts_n) / max(1.0, prior))
            est = int(round(prior * richness))
        out[tf] = max(1, min(cap, int(round(est * name_scale))))
    return out


def _row_notional(row: dict[str, Any]) -> float:
    try:
        qty = abs(float(row.get("qty") or 0))
        px = abs(float(row.get("last_price") or row.get("entry_price") or 0))
        if qty > 0 and px > 0:
            return qty * px
        return abs(float(row.get("position_usd") or row.get("notional") or 0))
    except (TypeError, ValueError):
        return 0.0


def _tf_live_usage(session_state: Any, *, exclude_ticker: str = "") -> dict[str, Any]:
    """Open + committed dollars and live count per TF (money still in the trade)."""
    spent = {"1m": 0.0, "5m": 0.0, "15m": 0.0}
    live = {"1m": 0, "5m": 0, "15m": 0}
    counted: set[str] = set()
    skip = str(exclude_ticker or "").upper()
    for row in list(_ss_get(session_state, "room3_open_positions") or []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if skip and ticker == skip:
            continue
        tf = _normalize_watch_tf(row.get("timeframe") or "")
        usd = _row_notional(row)
        if tf not in spent or usd <= 0:
            continue
        spent[tf] += usd
        live[tf] += 1
        if ticker:
            counted.add(ticker)
    book = _ss_get(session_state, "room3_watch_book") or {}
    for line in (book.get("lines") or {}).values():
        ticker = str(line.get("ticker") or "").upper()
        if skip and ticker == skip:
            continue
        tf = _normalize_watch_tf(line.get("timeframe") or "")
        if tf not in spent:
            continue
        if str(line.get("state") or "") not in ("in", "committed"):
            continue
        if ticker and ticker in counted:
            continue
        usd = 0.0
        sig = line.get("entry_signal")
        if isinstance(sig, dict):
            usd = float(sig.get("notional") or 0)
        if usd <= 0:
            usd = float(line.get("size_usd") or 0)
        if usd <= 0:
            continue
        spent[tf] += usd
        live[tf] += 1
        if ticker:
            counted.add(ticker)
    return {"spent": spent, "live": live}


def _heat(live: int, projected: int) -> float:
    return float(live) / float(max(1, projected))


def _idle_cash(
    remaining: dict[str, float],
    live: dict[str, int],
    projected: dict[str, int],
    *,
    taker: str,
) -> float:
    """
    Cash sitting in buckets that are not hot. A hot book (live ≥ projected)
    keeps its leftover for its own extras; a quiet book can donate.
    """
    idle = 0.0
    for tf, left in remaining.items():
        if tf == taker:
            continue
        donor_live = int(live.get(tf) or 0)
        donor_heat = _heat(donor_live, int(projected.get(tf) or 1))
        # Quiet / empty books donate. Keep leftover only if this TF is actually printing.
        if donor_live > 0 and donor_heat >= 0.5:
            continue
        idle += max(0.0, float(left or 0))
    return idle


def _claim_cash(session_state: Any, usd: float) -> None:
    if session_state is None or usd <= 0:
        return
    try:
        cur = float(session_state.get("room3_cash_claimed") or 0)
        session_state["room3_cash_claimed"] = cur + float(usd)
    except Exception:
        pass


def _layouts_from_session(session_state: Any) -> list[dict[str, Any]]:
    cache = _ss_get(session_state, "room3_repertoire_cache") or {}
    layouts = list(cache.get("layouts") or []) if isinstance(cache, dict) else []
    if layouts:
        return layouts
    try:
        import room3_bridge

        return list((room3_bridge.matrix_repertoire(session_state) or {}).get("layouts") or [])
    except Exception:
        return []


def _belt_name_count(session_state: Any) -> int:
    book = _ss_get(session_state, "room3_watch_book") or {}
    try:
        n = len(list(book.get("universe") or []))
        if n:
            return n
    except Exception:
        pass
    try:
        return len(list(_ss_get(session_state, "room3_filter_universe") or []))
    except Exception:
        return 0


def tf_budget_snapshot(session_state: Any | None = None) -> dict[str, Any]:
    tradable = 0.0
    try:
        tradable = float(_ss_get(session_state, "room3_tradable_today") or 0)
    except (TypeError, ValueError):
        tradable = 0.0
    layouts = _layouts_from_session(session_state)
    projected = project_tf_counts(layouts, n_names=_belt_name_count(session_state))
    usage = (
        _tf_live_usage(session_state)
        if session_state is not None
        else {"spent": {"1m": 0.0, "5m": 0.0, "15m": 0.0}, "live": {"1m": 0, "5m": 0, "15m": 0}}
    )
    spent = usage["spent"]
    live = usage["live"]
    buckets = {tf: tradable * TF_BUCKET_FRAC[tf] for tf in ("15m", "5m", "1m")}
    remaining = {tf: max(0.0, buckets[tf] - float(spent.get(tf) or 0)) for tf in buckets}
    slots = {tf: (buckets[tf] / float(projected[tf])) if projected[tf] else 0.0 for tf in buckets}
    layout_n = _tf_layout_counts(layouts)
    rows = []
    for tf in ("15m", "5m", "1m"):
        rows.append(
            {
                "TF": tf,
                "Bucket %": f"{TF_BUCKET_FRAC[tf]:.0%}",
                "Bucket $": round(buckets[tf], 2),
                "Projected": projected[tf],
                "Live": int(live.get(tf) or 0),
                "In use $": round(float(spent.get(tf) or 0), 2),
                "Left $": round(remaining[tf], 2),
                "Full-match slot $": round(slots[tf], 2),
                "Layouts": int(layout_n.get(tf) or 0),
                "Heat": (
                    "hot"
                    if _heat(int(live.get(tf) or 0), int(projected.get(tf) or 1)) >= 1.0
                    else (
                        "on pace"
                        if _heat(int(live.get(tf) or 0), int(projected.get(tf) or 1)) >= 0.5
                        else "quiet"
                    )
                ),
            }
        )
    return {
        "tradable": tradable,
        "projected": projected,
        "buckets": buckets,
        "spent": spent,
        "live": live,
        "remaining": remaining,
        "slots": slots,
        "layout_counts": layout_n,
        "rows": rows,
        "dna_empty": sum(layout_n.values()) <= 0,
    }


def _match_size_scale(match_pct: float) -> float:
    """85% (entry floor) → 55% of that TF's slot; 100% → full slot."""
    at_floor = 0.55
    try:
        at_floor = float(SIZE_AT_THRESHOLD)
    except (NameError, TypeError, ValueError):
        at_floor = 0.55
    pct = max(0.0, min(100.0, float(match_pct or 0)))
    floor = float(MATCH_THRESHOLD_PCT)
    if pct <= 0:
        return 0.0
    if pct < floor:
        return at_floor * (pct / floor)
    span = max(1.0, 100.0 - floor)
    return at_floor + (1.0 - at_floor) * ((pct - floor) / span)


def _distinctiveness(best_cosine: float, second_cosine: float) -> float:
    """
    Unique hit vs wallpaper: if runner-up is almost as close, this isn't a
    distinctive strategy read — pay it less. Gap of ~10% cosine → full size.
    """
    gap = max(0.0, float(best_cosine or 0) - float(second_cosine or 0))
    if float(second_cosine or 0) <= 0:
        return 1.0
    return max(0.50, min(1.0, 0.50 + gap / 0.10 * 0.50))


def stamp_line_size(
    line: dict[str, Any],
    session_state: Any,
    *,
    repertoire: dict[str, Any] | None = None,
    last_px: float | None = None,
    second_cosine: float | None = None,
    best_cosine: float | None = None,
) -> None:
    """Size $ follows Trading today now — do not wait for a 5m/15m tape pulse."""
    slices = list(line.get("slices") or [])
    if last_px is None:
        last_px = float(slices[-1].get("c") or 0) if slices else 0.0
    tf = str(line.get("timeframe") or "1m")
    ticker = str(line.get("ticker") or "").upper()
    exclude = ticker if str(line.get("state") or "") in ("in", "committed") else ""
    raw_match = float(line.get("match_pct") or 0)
    preview_match = (
        float(MATCH_THRESHOLD_PCT)
        if 0 < raw_match < MATCH_THRESHOLD_PCT
        else raw_match
    )
    layouts = list((repertoire or {}).get("layouts") or []) or _layouts_from_session(session_state)
    cos = float(best_cosine if best_cosine is not None else (raw_match / 100.0))
    preview = compute_entry_plan(
        price=float(last_px or 0),
        timeframe=tf,
        match_pct=preview_match,
        session_state=session_state,
        second_cosine=float(second_cosine if second_cosine is not None else line.get("second_cosine") or 0),
        best_cosine=cos,
        layouts=layouts,
        exclude_ticker=exclude,
    )
    line["size_usd"] = float(preview.get("notional") or 0)
    line["size_qty"] = float(preview.get("qty") or 0)
    line["size_note"] = str(preview.get("note") or "")


def compute_entry_plan(
    *,
    price: float,
    timeframe: str,
    match_pct: float,
    session_state: Any,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> dict[str, Any]:
    """
    Size from TF bucket → projected count slot → match → uniqueness → borrow.
    Never more than remaining Trading-today cash.
    """
    tf = _normalize_watch_tf(timeframe)
    if tf not in TF_BUCKET_FRAC:
        tf = "5m"
    match_scale = _match_size_scale(match_pct)
    best = float(best_cosine if best_cosine is not None else (float(match_pct or 0) / 100.0))
    distinct = _distinctiveness(best, second_cosine)
    try:
        tradable = float(session_state.get("room3_tradable_today") or 0)
    except (TypeError, ValueError):
        tradable = 0.0
    if layouts is None:
        layouts = _layouts_from_session(session_state)
    projected = project_tf_counts(layouts, n_names=_belt_name_count(session_state))
    usage = _tf_live_usage(session_state, exclude_ticker=exclude_ticker)
    spent = usage["spent"]
    live = usage["live"]
    buckets = {k: tradable * v for k, v in TF_BUCKET_FRAC.items()}
    remaining = {k: max(0.0, buckets[k] - float(spent.get(k) or 0)) for k in buckets}
    leftover_other = _idle_cash(remaining, live, projected, taker=tf)
    try:
        claimed = float(session_state.get("room3_cash_claimed") or 0)
    except (TypeError, ValueError):
        claimed = 0.0
    leftover_other = max(0.0, leftover_other - claimed)
    remaining_slots = max(1, int(projected[tf]) - int(live.get(tf) or 0))
    full_slot = buckets[tf] / float(max(1, projected[tf]))
    if remaining[tf] > 1e-6:
        slot = remaining[tf] / float(remaining_slots)
    else:
        slot = full_slot
    want = slot * match_scale * distinct
    from_own = min(want, remaining[tf])
    borrowed = 0.0
    taker_hot = int(live.get(tf) or 0) >= int(projected[tf])
    if (taker_hot or from_own + 1e-6 < want) and leftover_other > 0:
        borrowed = min(max(0.0, want - from_own), leftover_other)
    raw = from_own + borrowed
    deployed = 0.0
    try:
        import room3_engine

        deployed = room3_engine.deployed_notional(session_state.get("room3_open_positions"))
    except Exception:
        pass
    room = max(0.0, tradable - deployed - claimed)
    notional = min(raw, room)
    qty = 0.0
    if price > 0 and notional >= price:
        qty = math.floor(notional / price)
        notional = qty * price
    borrow_bit = f" · borrowed ${borrowed:,.0f}" if borrowed > 0 else ""
    note = (
        f"{tf} bucket {TF_BUCKET_FRAC[tf]:.0%} · slot ${slot:,.0f} of "
        f"{projected[tf]} projected · match {match_scale:.0%} · "
        f"unique {distinct:.0%}{borrow_bit} · ${notional:,.0f}"
    )
    return {
        "qty": qty,
        "notional": round(notional, 2),
        "tf_cap": TF_BUCKET_FRAC[tf],
        "match_scale": match_scale,
        "distinct": distinct,
        "slot": round(slot, 2),
        "projected": projected[tf],
        "borrowed": round(borrowed, 2),
        "note": note,
        "idle_cash": round(leftover_other, 2),
        "taker_hot": taker_hot,
    }


def _compute_entry_qty(
    *,
    price: float,
    session_state: Any,
    timeframe: str = "5m",
    match_pct: float = 0.0,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    max_positions: int = 5,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> tuple[float, float]:
    """Return (qty, notional). max_positions kept for call-site compat; unused."""
    _ = max_positions
    plan = compute_entry_plan(
        price=price,
        timeframe=timeframe,
        match_pct=match_pct,
        session_state=session_state,
        second_cosine=second_cosine,
        best_cosine=best_cosine,
        layouts=layouts,
        exclude_ticker=exclude_ticker,
    )
    return float(plan["qty"]), float(plan["notional"])


def compute_scale_in_plan(
    *,
    price: float,
    timeframe: str,
    match_pct: float,
    session_state: Any,
    second_cosine: float = 0.0,
    best_cosine: float | None = None,
    layouts: list[dict[str, Any]] | None = None,
    exclude_ticker: str = "",
) -> dict[str, Any]:
    """
    Add to a live winner using idle leftover from buckets that are not hot.
    Capped at one full-match slot. Does not spend a hot book's leftover.
    """
    plan = compute_entry_plan(
        price=price,
        timeframe=timeframe,
        match_pct=match_pct,
        session_state=session_state,
        second_cosine=second_cosine,
        best_cosine=best_cosine,
        layouts=layouts,
        exclude_ticker=exclude_ticker,
    )
    idle = float(plan.get("idle_cash") or 0)
    slot = float(plan.get("slot") or 0)
    add = min(idle, slot)
    qty = 0.0
    if price > 0 and add >= price:
        qty = math.floor(add / price)
        add = qty * price
    else:
        add = 0.0
        qty = 0.0
    return {
        **plan,
        "qty": qty,
        "notional": round(add, 2),
        "borrowed": round(add, 2),
        "note": f"add ${add:,.0f} from idle leftover · {plan.get('note') or ''}",
    }


def maybe_queue_matrix_signals(
    book: dict[str, Any],
    line: dict[str, Any],
    repertoire: dict[str, Any],
    session_state: Any,
    *,
    engine_armed: bool = False,
    entries_allowed: bool = True,
) -> None:
    """
    Stamp entry_signal or exit_signal on a line when DNA rules pass.
    One Alpaca pile per ticker. App lots are per letter; a second letter adds.
    """
    import room3_watcher

    match = score_line_against_repertoire(line, repertoire)
    line["match_pct"] = int(match.get("spatial_match_pct") or 0)
    layout_id = str(match.get("nearest_layout_id") or "—")
    line["nearest_layout"] = layout_id
    tf = str(line.get("timeframe") or "1m")
    nearest_strat = str(match.get("nearest_strategy") or "").strip()
    if (
        (not nearest_strat or nearest_strat in ("—", "-", "matrix"))
        and layout_id not in PLACEHOLDER_LAYOUTS
    ):
        nearest_strat = strategy_for_layout(layout_id, repertoire, timeframe=tf)
    if nearest_strat and not room3_recipes.strategy_tf_agrees(nearest_strat, tf):
        nearest_strat = "—"
        # Keep Match% / layout. Wrong-TF letter must not fire; do not blank the score.
    if room3_recipes.is_purgatory_letter(layout_id, nearest_strat):
        layout_id = "—"
        nearest_strat = "—"
        line["nearest_layout"] = "—"
        line["match_pct"] = 0
        match = {**match, "nearest_layout_id": "—", "nearest_strategy": "", "spatial_match_pct": 0, "ranked": []}
    line["nearest_strategy"] = nearest_strat or "—"
    line["score"] = float(match.get("display_score") or 0)
    line["second_cosine"] = float(match.get("second_cosine") or 0)

    ticker = str(line.get("ticker") or "").upper()
    slices = list(line.get("slices") or [])
    last_px = float(slices[-1].get("c") or 0) if slices else 0.0
    _sync_hot_children(
        line,
        list(match.get("ranked") or []),
        session_state,
        ticker,
        tf,
    )
    if _off_belt(line, book):
        line["children"] = []
    stamp_line_size(
        line,
        session_state,
        repertoire=repertoire,
        last_px=last_px,
        second_cosine=float(match.get("second_cosine") or 0),
        best_cosine=float(match.get("cosine_similarity") or 0),
    )

    layouts = list(repertoire.get("layouts") or [])
    if not layouts or not engine_armed:
        return

    if line.get("state") == "in":
        tf_lots = room3_lots.open_lots(session_state, ticker, tf=tf)
        children_by = {
            str(c.get("letter") or ""): c
            for c in (line.get("children") or [])
            if isinstance(c, dict)
        }
        if tf_lots:
            for lot in tf_lots:
                letter = str(lot.get("letter") or "")
                child = children_by.get(letter) or {}
                lot_match = int(child.get("match_pct") or line.get("match_pct") or 0)
                exit_reason = _lot_should_exit(
                    lot, cur_match=lot_match, last_px=last_px, patience=True
                )
                if not exit_reason or line.get("exit_signal"):
                    if not exit_reason and lot_match < EXIT_MATCH_FLOOR_PCT:
                        line["patience"] = True
                        line["patience_note"] = (
                            f"holding {letter} · match {lot_match}%"
                        )
                    continue
                qty = abs(float(lot.get("qty") or 0))
                if qty <= 0:
                    qty = _open_qty(session_state, ticker)
                if qty <= 0:
                    continue
                strat = str(lot.get("strategy") or line.get("entry_strategy") or "matrix")
                room3_watcher.queue_exit_signal(
                    book,
                    ticker,
                    tf,
                    side="sell",
                    qty=qty,
                    strategy=strat,
                    layout_id=str(lot.get("layout_id") or line.get("entry_layout") or ""),
                )
                line["last_exit_reason"] = exit_reason
                line["patience"] = False
                es = line.get("exit_signal")
                if isinstance(es, dict):
                    es["ref_price"] = last_px
                    es["lot_id"] = str(lot.get("id") or "")
                    es["letter"] = letter
                return
        else:
            entry_px = float(line.get("entry_price") or last_px or 0)
            entry_match = int(line.get("entry_match_pct") or MATCH_THRESHOLD_PCT)
            cur_match = int(line.get("match_pct") or 0)
            structural = float(line.get("entry_structural_move_pct") or 0.0)
            dummy = {
                "entry_px": entry_px,
                "entry_match_pct": entry_match,
                "structural_move_pct": structural,
            }
            exit_reason = _lot_should_exit(
                dummy, cur_match=cur_match, last_px=last_px, patience=True
            )
            if exit_reason and not line.get("exit_signal"):
                qty = _open_qty(session_state, ticker)
                if qty <= 0:
                    qty = float(line.get("entry_qty") or 0)
                if qty <= 0:
                    return
                strat = str(line.get("entry_strategy") or "matrix")
                room3_watcher.queue_exit_signal(
                    book,
                    ticker,
                    tf,
                    side="sell",
                    qty=qty,
                    strategy=strat,
                    layout_id=str(line.get("entry_layout") or ""),
                )
                line["last_exit_reason"] = exit_reason
                line["patience"] = False
                es = line.get("exit_signal")
                if isinstance(es, dict):
                    es["ref_price"] = last_px
                return

        entry_px = float(line.get("entry_price") or last_px or 0)
        cur_match = int(line.get("match_pct") or 0)
        structural = float(line.get("entry_structural_move_pct") or 0.0)
        pnl_pct = ((last_px - entry_px) / entry_px * 100.0) if entry_px > 0 and last_px > 0 else 0.0
        if (
            entries_allowed
            and not _off_belt(line, book)
            and not _approaching_day_close()
            and tf == "15m"
            and not line.get("entry_signal")
            and int(line.get("scale_ins") or 0) < SCALE_IN_MAX
            and _15m_can_open_lot(session_state, ticker, scale_in=True)
            and cur_match >= MATCH_THRESHOLD_PCT
            and structural > 0
            and pnl_pct > 0
            and pnl_pct < structural * SCALE_IN_TARGET_FRAC
        ):
            add = compute_scale_in_plan(
                price=last_px,
                timeframe=tf,
                match_pct=cur_match,
                session_state=session_state,
                second_cosine=float(match.get("second_cosine") or 0),
                best_cosine=float(match.get("cosine_similarity") or 0),
                layouts=layouts,
                exclude_ticker=ticker,
            )
            add_qty = float(add.get("qty") or 0)
            add_usd = float(add.get("notional") or 0)
            if add_qty >= 1 and add_usd > 0:
                strat = str(line.get("entry_strategy") or "matrix")
                room3_watcher.queue_entry_signal(
                    book,
                    ticker,
                    tf,
                    side="buy",
                    qty=add_qty,
                    strategy=strat,
                    keep_in=True,
                    scale_in=True,
                    layout_id=str(line.get("entry_layout") or ""),
                )
                _claim_cash(session_state, add_usd)
                line["scale_ins"] = int(line.get("scale_ins") or 0) + 1
                line["patience"] = True
                line["patience_note"] = (
                    f"add ${add_usd:,.0f} · match {cur_match}% · "
                    f"move {pnl_pct:.1f}% of ~{structural:.1f}%"
                )
                sig = (book.get("lines") or {}).get(room3_watcher.line_key(ticker, tf)) or line
                if isinstance(sig.get("entry_signal"), dict):
                    sig["entry_signal"]["notional"] = add_usd
                    sig["entry_signal"]["ref_price"] = last_px
                    sig["entry_signal"]["scale_in"] = True
                    sig["entry_signal"]["order_style"] = "limit"
                    sig["entry_signal"]["letter"] = room3_lots.letter_token(
                        str(line.get("entry_layout") or ""), strat
                    )
        if (
            entries_allowed
            and not _off_belt(line, book)
            and not _approaching_day_close()
            and not line.get("entry_signal")
            and not line.get("exit_signal")
        ):
            _try_queue_child_entry(
                book,
                line,
                session_state=session_state,
                ticker=ticker,
                tf=tf,
                last_px=last_px,
                slices=slices,
                layouts=layouts,
                match=match,
            )
        return

    if not entries_allowed:
        return
    if _off_belt(line, book):
        line["patience"] = True
        line["patience_note"] = "leftover · exit only · no new buy"
        line["children"] = []
        return
    if line.get("entry_signal"):
        return
    if line.get("state") not in ("watching", "committed"):
        return
    if not match.get("vector_ready"):
        if not line.get("children"):
            line["patience"] = False
            line.pop("patience_note", None)
        return
    queued = _try_queue_child_entry(
        book,
        line,
        session_state=session_state,
        ticker=ticker,
        tf=tf,
        last_px=last_px,
        slices=slices,
        layouts=layouts,
        match=match,
    )
    if queued:
        return
    if line.get("children"):
        line["patience"] = True
        notes = [
            str(c.get("patience_note") or "")
            for c in line["children"]
            if str(c.get("patience_note") or "").strip()
        ]
        line["patience_note"] = notes[0] if notes else "scanning live letters"
        return
    cur_match = int(match.get("spatial_match_pct") or 0)
    if cur_match < WARMING_MATCH_PCT:
        _reset_entry_trigger(line)
        line["patience"] = False
        line.pop("patience_note", None)
    else:
        line["patience"] = True
        line["patience_note"] = (
            f"warming {cur_match}% · need ≥{MATCH_THRESHOLD_PCT}%"
        )
