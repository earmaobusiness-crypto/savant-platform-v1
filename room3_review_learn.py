"""
Room 3 operator-review → matrix DNA compile loop.

Votes bank first. Extra good/bad traits sit in a compile pile.
A pattern only hardens into DNA after TF thresholds:
  15m ≥ 2 · 5m ≥ 3 · 1m ≥ 4
(near-misses that came close count).

Before any DNA rewrite we snapshot the prior layout entry so revert
can put it back. Vault / Supabase stay read-only — session overlays only.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "room3_data"
LEARN_PATH = DATA_DIR / "review_learn.json"

LAYOUT_INDEX_KEY = "layout_master_matrix_index"

# Operator-stated harden bars (same pattern / near-misses).
TF_HARDEN_THRESHOLDS: dict[str, int] = {
    "15m": 2,
    "5m": 3,
    "1m": 4,
}

_PLACEHOLDER_STRAT = frozenset(
    {"", "—", "-", "Alpaca", "matrix", "unknown", "Alpaca BUY", "Alpaca SELL"}
)
_PLACEHOLDER_LAYOUT = frozenset({"", "—", "-", "NEW_LAYOUT", "PURGATORY_PENDING"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_tf(raw: str) -> str:
    t = str(raw or "").strip().lower().replace(" ", "")
    aliases = {
        "1": "1m",
        "1m": "1m",
        "1min": "1m",
        "1-minute": "1m",
        "1minute": "1m",
        "5": "5m",
        "5m": "5m",
        "5min": "5m",
        "5-minute": "5m",
        "5minute": "5m",
        "15": "15m",
        "15m": "15m",
        "15min": "15m",
        "15-minute": "15m",
        "15minute": "15m",
    }
    return aliases.get(t, t if t in TF_HARDEN_THRESHOLDS else "")


def threshold_for_tf(tf: str) -> int:
    return int(TF_HARDEN_THRESHOLDS.get(normalize_tf(tf), 0))


def empty_state() -> dict[str, Any]:
    return {
        "observations": [],
        "versions": [],
        "overlays": {},
        "applied_pattern_keys": [],
    }


def load_state() -> dict[str, Any]:
    try:
        if LEARN_PATH.is_file():
            raw = json.loads(LEARN_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                base = empty_state()
                for k in base:
                    if k in raw:
                        base[k] = raw[k]
                return base
    except Exception:
        pass
    return empty_state()


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    blob = empty_state()
    blob.update(dict(state or {}))
    LEARN_PATH.write_text(json.dumps(blob, indent=2, default=str), encoding="utf-8")


def pattern_key(*, strategy: str, layout_id: str, timeframe: str, trait: str = "") -> str:
    strat = str(strategy or "").strip() or "unknown"
    layout = str(layout_id or "").strip() or "—"
    tf = normalize_tf(timeframe) or "—"
    trait_bit = str(trait or "").strip()
    if trait_bit:
        return f"{strat}|{layout}|{tf}|trait:{trait_bit}"
    return f"{strat}|{layout}|{tf}"


def bucket_key(*, layout_id: str, strategy: str, timeframe: str) -> str:
    lid = str(layout_id or "").strip() or "—"
    strat = str(strategy or "").strip() or "—"
    tf = normalize_tf(timeframe) or "—"
    return f"{lid}|{strat}|{tf}"


def _is_placeholder_strat(raw: str) -> bool:
    s = str(raw or "").strip()
    return s in _PLACEHOLDER_STRAT or s.upper().startswith("ALPACA")


def _is_placeholder_layout(raw: str) -> bool:
    return str(raw or "").strip() in _PLACEHOLDER_LAYOUT


def resolve_trade_context(trade: dict[str, Any], session_state: Any | None = None) -> dict[str, str]:
    """Pull strategy / TF / layout from the closed trade + watch book / fill cache."""
    t = dict(trade or {})
    ticker = str(t.get("ticker") or t.get("symbol") or "").upper()
    strat = str(
        t.get("matrix_strategy")
        or t.get("strategy")
        or t.get("entry_strategy")
        or ""
    ).strip()
    tf = str(
        t.get("matrix_timeframe")
        or t.get("timeframe")
        or t.get("entry_timeframe")
        or ""
    ).strip()
    layout = str(
        t.get("matrix_layout")
        or t.get("layout_id")
        or t.get("entry_layout")
        or t.get("layout")
        or ""
    ).strip()

    fill: dict[str, Any] = {}
    book_lines: list[dict] = []
    if session_state is not None:
        try:
            fill = dict((session_state.get("room3_fill_meta_by_ticker") or {}).get(ticker) or {})
        except Exception:
            fill = {}
        try:
            book = session_state.get("room3_watch_book") or {}
            book_lines = list((book.get("lines") or {}).values())
        except Exception:
            book_lines = []

    if _is_placeholder_strat(strat) and fill.get("strategy"):
        strat = str(fill.get("strategy") or "").strip()
    if not normalize_tf(tf) and fill.get("timeframe"):
        tf = str(fill.get("timeframe") or "").strip()
    if _is_placeholder_layout(layout) and fill.get("layout_id"):
        layout = str(fill.get("layout_id") or "").strip()

    for line in book_lines:
        if str(line.get("ticker") or "").upper() != ticker:
            continue
        if _is_placeholder_layout(layout):
            cand = str(line.get("entry_layout") or line.get("nearest_layout") or "").strip()
            if cand and not _is_placeholder_layout(cand):
                layout = cand
        if _is_placeholder_strat(strat):
            cand = str(
                line.get("entry_strategy") or line.get("nearest_strategy") or ""
            ).strip()
            if cand and not _is_placeholder_strat(cand):
                strat = cand
        if not normalize_tf(tf):
            cand = str(line.get("timeframe") or "").strip()
            if normalize_tf(cand):
                tf = cand
        if layout and strat and normalize_tf(tf):
            break

    tf_n = normalize_tf(tf)
    if _is_placeholder_strat(strat):
        strat = "unknown"
    if _is_placeholder_layout(layout):
        layout = "—"
    return {
        "ticker": ticker,
        "strategy": strat,
        "timeframe": tf_n or str(tf or "—"),
        "layout_id": layout,
    }


def _layouts_from_session(session_state: Any) -> list[dict[str, Any]]:
    try:
        raw = session_state.get(LAYOUT_INDEX_KEY) or []
        if isinstance(raw, list):
            return [dict(x) for x in raw if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _set_layouts(session_state: Any, layouts: list[dict[str, Any]]) -> None:
    try:
        session_state[LAYOUT_INDEX_KEY] = layouts
        session_state.pop("room3_repertoire_cache", None)
    except Exception:
        try:
            setattr(session_state, LAYOUT_INDEX_KEY, layouts)
            if hasattr(session_state, "pop"):
                session_state.pop("room3_repertoire_cache", None)
        except Exception:
            pass


def _layout_vector_for(
    session_state: Any,
    *,
    layout_id: str,
    strategy: str,
    timeframe: str,
) -> list[float]:
    tf = normalize_tf(timeframe)
    want_b = bucket_key(layout_id=layout_id, strategy=strategy, timeframe=tf)
    for entry in _layouts_from_session(session_state):
        b = str(entry.get("bucket_key") or "")
        if b == want_b:
            vec = entry.get("vector") or []
            if isinstance(vec, list) and vec:
                return [float(x) for x in vec]
        if (
            str(entry.get("layout_id") or "") == str(layout_id)
            and str(entry.get("strategy") or "") == str(strategy)
            and normalize_tf(
                str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "")
            )
            == tf
        ):
            vec = entry.get("vector") or []
            if isinstance(vec, list) and vec:
                return [float(x) for x in vec]
    return []


def ingest_review(
    state: dict[str, Any],
    trade: dict[str, Any],
    vote: str,
    *,
    session_state: Any | None = None,
    near_miss: bool = False,
    traits: list[str] | None = None,
) -> dict[str, Any]:
    """
    Bank the operator vote + optional side traits into the compile pile.
    Does not mutate DNA yet — call compile_ready_patterns afterward.
    """
    vote_clean = "good" if str(vote).lower().startswith("g") else "bad"
    ctx = resolve_trade_context(trade, session_state)
    trade_id = str(trade.get("id") or "").strip()
    vec: list[float] = []
    if session_state is not None:
        vec = _layout_vector_for(
            session_state,
            layout_id=ctx["layout_id"],
            strategy=ctx["strategy"],
            timeframe=ctx["timeframe"],
        )
    live = trade.get("live_vector") or trade.get("match_vector")
    if isinstance(live, list) and live:
        try:
            vec = [float(x) for x in live]
        except (TypeError, ValueError):
            pass

    observations = list(state.get("observations") or [])
    observations = [
        o
        for o in observations
        if not (
            str(o.get("trade_id") or "") == trade_id
            and not str(o.get("trait") or "").strip()
            and str(o.get("status") or "") == "pending"
        )
    ]
    primary = {
        "id": f"obs-{uuid.uuid4().hex[:12]}",
        "trade_id": trade_id,
        "ticker": ctx["ticker"],
        "strategy": ctx["strategy"],
        "layout_id": ctx["layout_id"],
        "timeframe": ctx["timeframe"],
        "vote": vote_clean,
        "near_miss": bool(near_miss),
        "trait": "",
        "pattern_key": pattern_key(
            strategy=ctx["strategy"],
            layout_id=ctx["layout_id"],
            timeframe=ctx["timeframe"],
        ),
        "bucket_key": bucket_key(
            layout_id=ctx["layout_id"],
            strategy=ctx["strategy"],
            timeframe=ctx["timeframe"],
        ),
        "vector": vec,
        "status": "pending",
        "created_at": _utc_now(),
    }
    observations.append(primary)

    for trait in traits or []:
        trait_s = str(trait or "").strip()
        if not trait_s:
            continue
        observations.append(
            {
                "id": f"obs-{uuid.uuid4().hex[:12]}",
                "trade_id": trade_id,
                "ticker": ctx["ticker"],
                "strategy": ctx["strategy"],
                "layout_id": ctx["layout_id"],
                "timeframe": ctx["timeframe"],
                "vote": vote_clean,
                "near_miss": bool(near_miss),
                "trait": trait_s,
                "pattern_key": pattern_key(
                    strategy=ctx["strategy"],
                    layout_id=ctx["layout_id"],
                    timeframe=ctx["timeframe"],
                    trait=trait_s,
                ),
                "bucket_key": bucket_key(
                    layout_id=ctx["layout_id"],
                    strategy=ctx["strategy"],
                    timeframe=ctx["timeframe"],
                ),
                "vector": vec,
                "status": "pending",
                "created_at": _utc_now(),
            }
        )

    state["observations"] = observations[-2000:]
    return primary


def remove_observations_for_trade(state: dict[str, Any], trade_id: str) -> int:
    """Drop pending observations for an undone vote. Applied ones stay."""
    tid = str(trade_id or "").strip()
    if not tid:
        return 0
    before = list(state.get("observations") or [])
    kept = [
        o
        for o in before
        if not (
            str(o.get("trade_id") or "") == tid
            and str(o.get("status") or "") == "pending"
        )
    ]
    state["observations"] = kept
    return len(before) - len(kept)


def _count_pattern(obs: list[dict[str, Any]], pkey: str) -> dict[str, Any]:
    hits = [
        o
        for o in obs
        if str(o.get("pattern_key") or "") == pkey and str(o.get("status") or "") == "pending"
    ]
    tickers = sorted({str(o.get("ticker") or "").upper() for o in hits if o.get("ticker")})
    goods = sum(1 for o in hits if o.get("vote") == "good")
    bads = sum(1 for o in hits if o.get("vote") == "bad")
    near = sum(1 for o in hits if o.get("near_miss"))
    tf = normalize_tf(str(hits[0].get("timeframe") if hits else "") or "")
    return {
        "count": len(hits),
        "goods": goods,
        "bads": bads,
        "near_misses": near,
        "tickers": tickers,
        "ticker_count": len(tickers),
        "timeframe": tf,
        "threshold": threshold_for_tf(tf),
        "ready": bool(tf and len(hits) >= threshold_for_tf(tf)),
        "pending": hits,
    }


def pending_pattern_stats(state: dict[str, Any]) -> list[dict[str, Any]]:
    obs = [o for o in (state.get("observations") or []) if str(o.get("status") or "") == "pending"]
    keys = sorted({str(o.get("pattern_key") or "") for o in obs if o.get("pattern_key")})
    out: list[dict[str, Any]] = []
    for k in keys:
        stats = _count_pattern(obs, k)
        sample = stats["pending"][0] if stats["pending"] else {}
        out.append(
            {
                "pattern_key": k,
                "strategy": sample.get("strategy"),
                "layout_id": sample.get("layout_id"),
                "timeframe": stats["timeframe"],
                "trait": sample.get("trait") or "",
                "count": stats["count"],
                "goods": stats["goods"],
                "bads": stats["bads"],
                "near_misses": stats["near_misses"],
                "tickers": stats["tickers"],
                "ticker_count": stats["ticker_count"],
                "threshold": stats["threshold"],
                "ready": stats["ready"],
            }
        )
    out.sort(key=lambda r: (-int(r.get("ready") or 0), -int(r.get("count") or 0)))
    return out


def _blend_vectors(base: list[float], samples: list[list[float]], *, toward: bool) -> list[float]:
    usable = [v for v in samples if v and len(v) == len(base)]
    if not base or not usable:
        return list(base)
    mean = []
    for i in range(len(base)):
        vals = [v[i] for v in usable]
        mean.append(sum(vals) / len(vals))
    alpha = 0.18
    out = []
    for b, m in zip(base, mean):
        if toward:
            out.append(b * (1.0 - alpha) + m * alpha)
        else:
            out.append(b + alpha * (b - m))
    return out


def _find_layout_index(
    layouts: list[dict[str, Any]],
    bkey: str,
    layout_id: str,
    strategy: str,
    tf: str,
) -> int:
    for i, entry in enumerate(layouts):
        if not isinstance(entry, dict):
            continue
        if str(entry.get("bucket_key") or "") == bkey:
            return i
        if (
            str(entry.get("layout_id") or "") == layout_id
            and str(entry.get("strategy") or "") == strategy
            and normalize_tf(
                str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "")
            )
            == tf
        ):
            return i
    return -1


def _snapshot_version(
    state: dict[str, Any],
    *,
    bucket: str,
    entry_before: dict[str, Any],
    reason: str,
    pattern_key_s: str,
    vote_majority: str,
) -> dict[str, Any]:
    versions = list(state.get("versions") or [])
    ver = {
        "id": f"ver-{uuid.uuid4().hex[:12]}",
        "bucket_key": bucket,
        "pattern_key": pattern_key_s,
        "reason": reason,
        "vote_majority": vote_majority,
        "created_at": _utc_now(),
        "reverted": False,
        "entry_before": copy.deepcopy(entry_before),
    }
    versions.append(ver)
    state["versions"] = versions[-200:]
    return ver


def apply_pattern(
    state: dict[str, Any],
    session_state: Any,
    pattern_key_s: str,
) -> dict[str, Any]:
    """Harden one ready pattern into session DNA. Snapshots prior entry first."""
    obs = list(state.get("observations") or [])
    stats = _count_pattern(obs, pattern_key_s)
    if not stats.get("ready"):
        return {"ok": False, "error": "pattern not ready", "stats": stats}

    pending = stats["pending"]
    sample = pending[0]
    layout_id = str(sample.get("layout_id") or "—")
    strategy = str(sample.get("strategy") or "unknown")
    tf = normalize_tf(str(sample.get("timeframe") or ""))
    bkey = str(
        sample.get("bucket_key")
        or bucket_key(layout_id=layout_id, strategy=strategy, timeframe=tf)
    )
    majority = "good" if int(stats["goods"]) >= int(stats["bads"]) else "bad"
    trait = str(sample.get("trait") or "").strip()

    layouts = _layouts_from_session(session_state)
    idx = _find_layout_index(layouts, bkey, layout_id, strategy, tf)
    if idx < 0:
        entry_before = {
            "layout_id": layout_id,
            "strategy": strategy,
            "timeframe_norm": tf,
            "bucket_key": bkey,
            "vector": [],
            "operator_overlay": dict((state.get("overlays") or {}).get(bkey) or {}),
        }
    else:
        entry_before = copy.deepcopy(layouts[idx])

    ver = _snapshot_version(
        state,
        bucket=bkey,
        entry_before=entry_before,
        reason="trait-compile" if trait else "strategy-compile",
        pattern_key_s=pattern_key_s,
        vote_majority=majority,
    )

    overlay = dict((state.get("overlays") or {}).get(bkey) or {})
    overlay.setdefault("reinforce", 0)
    overlay.setdefault("trim", 0)
    overlay.setdefault("match_floor_delta", 0)
    overlay.setdefault("traits_good", [])
    overlay.setdefault("traits_bad", [])
    overlay["updated_at"] = _utc_now()
    overlay["last_version_id"] = ver["id"]

    if majority == "good":
        overlay["reinforce"] = int(overlay.get("reinforce") or 0) + 1
        overlay["match_floor_delta"] = max(-5, int(overlay.get("match_floor_delta") or 0) - 1)
        if trait and trait not in (overlay.get("traits_good") or []):
            overlay["traits_good"] = list(overlay.get("traits_good") or []) + [trait]
    else:
        overlay["trim"] = int(overlay.get("trim") or 0) + 1
        overlay["match_floor_delta"] = min(10, int(overlay.get("match_floor_delta") or 0) + 2)
        if trait and trait not in (overlay.get("traits_bad") or []):
            overlay["traits_bad"] = list(overlay.get("traits_bad") or []) + [trait]

    samples = [list(o.get("vector") or []) for o in pending if o.get("vector")]
    new_entry = copy.deepcopy(entry_before)
    base_vec = list(new_entry.get("vector") or [])
    if base_vec and samples:
        new_entry["vector"] = _blend_vectors(base_vec, samples, toward=(majority == "good"))
        new_entry["vector_source"] = "operator_compile"
    new_entry["operator_overlay"] = overlay
    new_entry["bucket_key"] = bkey
    new_entry["layout_id"] = layout_id
    new_entry["strategy"] = strategy
    new_entry["timeframe_norm"] = tf

    if idx >= 0:
        layouts[idx] = new_entry
    else:
        layouts.append(new_entry)
    _set_layouts(session_state, layouts)

    overlays = dict(state.get("overlays") or {})
    overlays[bkey] = overlay
    state["overlays"] = overlays

    applied = set(state.get("applied_pattern_keys") or [])
    applied.add(pattern_key_s)
    state["applied_pattern_keys"] = sorted(applied)[-500:]

    for o in state.get("observations") or []:
        if str(o.get("pattern_key") or "") == pattern_key_s and str(o.get("status") or "") == "pending":
            o["status"] = "applied"
            o["applied_version_id"] = ver["id"]
            o["applied_at"] = _utc_now()

    return {
        "ok": True,
        "version_id": ver["id"],
        "bucket_key": bkey,
        "majority": majority,
        "stats": stats,
        "overlay": overlay,
        "trait": trait,
    }


def compile_ready_patterns(state: dict[str, Any], session_state: Any) -> list[dict[str, Any]]:
    """Apply every pattern that has crossed its TF threshold."""
    results = []
    for row in pending_pattern_stats(state):
        if not row.get("ready"):
            continue
        res = apply_pattern(state, session_state, str(row.get("pattern_key") or ""))
        results.append(res)
    return results


def revert_version(state: dict[str, Any], session_state: Any, version_id: str) -> dict[str, Any]:
    """Restore the layout entry / overlay from before a compile apply."""
    vid = str(version_id or "").strip()
    versions = list(state.get("versions") or [])
    ver = next((v for v in versions if str(v.get("id") or "") == vid), None)
    if not ver:
        return {"ok": False, "error": "version not found"}
    if ver.get("reverted"):
        return {"ok": False, "error": "already reverted"}

    before = dict(ver.get("entry_before") or {})
    bkey = str(ver.get("bucket_key") or before.get("bucket_key") or "")
    layouts = _layouts_from_session(session_state)
    idx = _find_layout_index(
        layouts,
        bkey,
        str(before.get("layout_id") or ""),
        str(before.get("strategy") or ""),
        normalize_tf(str(before.get("timeframe_norm") or "")),
    )
    if idx >= 0:
        if before.get("vector") or before.get("layout_id"):
            layouts[idx] = copy.deepcopy(before)
        else:
            layouts.pop(idx)
    elif before.get("vector") or before.get("operator_overlay"):
        layouts.append(copy.deepcopy(before))
    _set_layouts(session_state, layouts)

    overlays = dict(state.get("overlays") or {})
    prior_overlay = dict(before.get("operator_overlay") or {})
    if prior_overlay:
        overlays[bkey] = prior_overlay
    else:
        overlays.pop(bkey, None)
    state["overlays"] = overlays

    for v in versions:
        if str(v.get("id") or "") == vid:
            v["reverted"] = True
            v["reverted_at"] = _utc_now()
    state["versions"] = versions

    for o in state.get("observations") or []:
        if str(o.get("applied_version_id") or "") == vid:
            o["status"] = "pending"
            o.pop("applied_version_id", None)
            o.pop("applied_at", None)

    applied = set(state.get("applied_pattern_keys") or [])
    applied.discard(str(ver.get("pattern_key") or ""))
    state["applied_pattern_keys"] = sorted(applied)

    save_state(state)
    sync_state_to_session(session_state, state)
    return {"ok": True, "version_id": vid, "bucket_key": bkey}


def overlay_match_floor_delta(
    session_state: Any, layout_id: str, strategy: str, timeframe: str
) -> int:
    """Delta applied on top of MATCH_THRESHOLD_PCT for this DNA bucket."""
    bkey = bucket_key(layout_id=layout_id, strategy=strategy, timeframe=timeframe)
    for entry in _layouts_from_session(session_state):
        if str(entry.get("bucket_key") or "") == bkey or (
            str(entry.get("layout_id") or "") == str(layout_id)
            and str(entry.get("strategy") or "") == str(strategy)
            and normalize_tf(
                str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "")
            )
            == normalize_tf(timeframe)
        ):
            ov = entry.get("operator_overlay") or {}
            try:
                return int(ov.get("match_floor_delta") or 0)
            except (TypeError, ValueError):
                return 0
    try:
        st = load_state()
        ov = (st.get("overlays") or {}).get(bkey) or {}
        return int(ov.get("match_floor_delta") or 0)
    except Exception:
        return 0


def sync_state_to_session(session_state: Any, state: dict[str, Any] | None = None) -> dict[str, Any]:
    blob = state if state is not None else load_state()
    try:
        session_state["room3_review_learn"] = blob
    except Exception:
        try:
            setattr(session_state, "room3_review_learn", blob)
        except Exception:
            pass
    return blob


def state_from_session(session_state: Any) -> dict[str, Any]:
    try:
        raw = session_state.get("room3_review_learn")
        if isinstance(raw, dict) and ("observations" in raw or "versions" in raw):
            base = empty_state()
            base.update(raw)
            return base
    except Exception:
        pass
    return load_state()


def process_operator_vote(
    session_state: Any,
    trade: dict[str, Any],
    vote: str,
    *,
    near_miss: bool = False,
    traits: list[str] | None = None,
) -> dict[str, Any]:
    """Bank vote, auto-compile anything that crossed the TF bar, persist."""
    state = state_from_session(session_state)
    primary = ingest_review(
        state,
        trade,
        vote,
        session_state=session_state,
        near_miss=near_miss,
        traits=traits,
    )
    applied = compile_ready_patterns(state, session_state)
    save_state(state)
    sync_state_to_session(session_state, state)
    return {
        "observation": primary,
        "applied": applied,
        "pending": pending_pattern_stats(state),
        "versions": list(state.get("versions") or [])[-8:],
    }
