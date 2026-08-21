"""
Room 3 matrix DNA matching — live map slices vs saved layout vectors.

Self-contained (no Room 2 imports). Uses repertoire from room3_bridge.
"""

from __future__ import annotations

import math
from typing import Any

import room3_recipes

MATCH_THRESHOLD_PCT = 85
EXIT_MATCH_FLOOR_PCT = 65
STOP_LOSS_PCT = 2.5
MIN_SLICES = {"1m": 5, "5m": 4, "15m": 3}
PLACEHOLDER_LAYOUTS = frozenset({"NEW_LAYOUT", "PURGATORY_PENDING", "—", "-", ""})

# Day book split — these three add to 100% of Trading today.
TF_BUCKET_FRAC: dict[str, float] = {"15m": 0.50, "5m": 0.30, "1m": 0.20}
# Layout-based fill estimate starts here, then scales with how many recipes exist.
TF_PROJECTED_PRIOR: dict[str, int] = {"15m": 4, "5m": 8, "1m": 6}
TF_PROJECTED_CAP: dict[str, int] = {"15m": 8, "5m": 16, "1m": 12}
SCALE_IN_MAX = 1  # one add onto a live winner
SCALE_IN_TARGET_FRAC = 0.50  # add only while P/L is still under half the layout move
SIZE_AT_THRESHOLD = 0.55  # 85% match → 55% of that TF's slot


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
        f"Layouts project about {p.get('15m', 4)} fifteen-minute fills, "
        f"{p.get('5m', 8)} five-minute, {p.get('1m', 6)} one-minute today — "
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
    second_cosine = 0.0
    nearest = "—"
    nearest_strategy = ""
    structural_move = 0.0
    best_ticker = ""
    best_tf = ""
    watch_tf = _normalize_watch_tf(watch_timeframe or "")
    usable = [
        e
        for e in (layouts or [])
        if (e.get("vector") or []) and len(e.get("vector") or []) == len(snapshot_vec)
    ]
    weights = _wallpaper_weights(usable, len(snapshot_vec))

    for entry in usable:
        stored = [float(x) for x in (entry.get("vector") or [])]
        cos = cosine_similarity(snapshot_vec, stored, weights)
        entry_tf = str(entry.get("timeframe_norm") or _normalize_watch_tf(entry.get("timeframe_resolution") or entry.get("strategy") or ""))
        if watch_tf and entry_tf:
            if entry_tf == watch_tf:
                cos = min(1.0, cos * 1.04)
            else:
                cos *= 0.90
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
    # No positive hit → do not invent "NEW_LAYOUT" (Room 2 mint jargon). Show blank.
    if best_cosine <= 0:
        nearest = "—"
        nearest_strategy = ""
        structural_move = 0.0
        best_ticker = ""
        best_tf = ""
    return {
        "spatial_match_pct": int(round(best_cosine * 100)),
        "cosine_similarity": round(best_cosine, 4),
        "second_cosine": round(second_cosine, 4),
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
) -> bool:
    """True if another line already owns this ticker (open or real entry queued).

    Sticky watch also uses state=committed — that alone must NOT block the
    line that is trying to stamp an entry, or ≥85% never fires.
    """
    sym = str(ticker).upper()
    for key, line in (book.get("lines") or {}).items():
        if except_key and key == except_key:
            continue
        if str(line.get("ticker") or "").upper() != sym:
            continue
        if line.get("state") == "in" or line.get("entry_signal"):
            return True
        # Real matrix commitment (sized/layout stamped), not sticky-only.
        if line.get("state") == "committed" and (
            line.get("entry_layout")
            or line.get("entry_qty")
            or line.get("entry_match_pct")
        ):
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
        tf = _normalize_watch_tf(
            entry.get("timeframe_norm")
            or entry.get("timeframe_resolution")
            or entry.get("timeframe")
            or ""
        )
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
    Empty DNA uses the prior (4 / 8 / 6) until layouts hydrate.
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
    One entry per ticker across all TF lines.
    """
    import room3_watcher

    match = score_line_against_repertoire(line, repertoire)
    line["match_pct"] = int(match.get("spatial_match_pct") or 0)
    line["nearest_layout"] = str(match.get("nearest_layout_id") or "—")
    line["nearest_strategy"] = str(match.get("nearest_strategy") or "—")
    line["score"] = float(match.get("display_score") or 0)
    line["second_cosine"] = float(match.get("second_cosine") or 0)

    ticker = str(line.get("ticker") or "").upper()
    tf = str(line.get("timeframe") or "1m")
    slices = list(line.get("slices") or [])
    last_px = float(slices[-1].get("c") or 0) if slices else 0.0
    exclude = ticker if str(line.get("state") or "") in ("in", "committed") else ""
    preview = compute_entry_plan(
        price=last_px,
        timeframe=tf,
        match_pct=float(line.get("match_pct") or 0),
        session_state=session_state,
        second_cosine=float(match.get("second_cosine") or 0),
        best_cosine=float(match.get("cosine_similarity") or 0),
        layouts=list(repertoire.get("layouts") or []),
        exclude_ticker=exclude,
    )
    line["size_usd"] = float(preview.get("notional") or 0)
    line["size_qty"] = float(preview.get("qty") or 0)
    line["size_note"] = str(preview.get("note") or "")

    layouts = list(repertoire.get("layouts") or [])
    if not layouts or not engine_armed:
        return

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
        elif _approaching_day_close():
            exit_reason = "day close · second-best exit"

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
                layout_id=str(line.get("entry_layout") or ""),
            )
            line["last_exit_reason"] = exit_reason
            line["patience"] = False
            es = line.get("exit_signal")
            if isinstance(es, dict):
                es["ref_price"] = last_px
            return

        if (
            entries_allowed
            and not _approaching_day_close()
            and tf == "15m"
            and not line.get("entry_signal")
            and int(line.get("scale_ins") or 0) < SCALE_IN_MAX
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
                    sig["entry_signal"]["order_style"] = "limit"  # add-on, not a pop
        return

    if not entries_allowed:
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
    if _ticker_already_engaged(
        book, ticker, except_key=room3_watcher.line_key(ticker, tf)
    ):
        return

    layout_id = str(match.get("nearest_layout_id") or "")
    if layout_id in PLACEHOLDER_LAYOUTS:
        return

    strategy = str(match.get("nearest_strategy") or "") or strategy_for_layout(layout_id, repertoire)
    qty, notional = _compute_entry_qty(
        price=last_px,
        session_state=session_state,
        timeframe=tf,
        match_pct=cur_match,
        second_cosine=float(match.get("second_cosine") or 0),
        best_cosine=float(match.get("cosine_similarity") or 0),
        layouts=list(repertoire.get("layouts") or []),
    )
    if qty < 1 or notional <= 0:
        line["size_note"] = "size $0 — not enough room or price too high"
        return
    _claim_cash(session_state, notional)
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
    stamped["entry_signal"]["order_style"] = room3_recipes.order_style_for(
        strategy,
        tf,
        layout_id=layout_id,
        structural_move_pct=float(match.get("structural_move_pct") or 0.0),
    )
    line["nearest_strategy"] = strategy
