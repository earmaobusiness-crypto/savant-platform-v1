"""
Room 2 → Room 3 bridge (ONE WAY).

Rules:
- Room 3 may READ a small snapshot of matrix state.
- Room 3 must NOT import Room 2 modules (vault_bridge, core_quantum, app guts).
- Room 2 must NOT import room3_* modules.
- If Room 2 renames internals, update ONLY this file's readers — Room 3 UI/engine stay stable.
- Missing keys → empty snapshot (Room 3 still runs; handshake just says quiet).
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests

REPERTOIRE_CACHE_TTL_SEC = 900  # refresh vault library every 15 min max

ROOM2_OBSERVE_KEYS = (
    "layout_master_matrix_index",
    "room2_deploy_registry",
    "room2_master_signature",
    "room2_last_successful_deploy",
    "matrix_active_pattern_count",
    "matrix_active_save_count",
    "market_weather_snapshot",
)

PLACEHOLDER_LAYOUT_IDS = frozenset({"NEW_LAYOUT", "PURGATORY_PENDING", "—", "-", ""})
PROJECT_ROOT = Path(__file__).resolve().parent
CACHE_PATH = PROJECT_ROOT / ".streamlit" / "matrix_vault_cache.json"
LAYOUT_CAP = 256
VAULT_FETCH_LIMIT = 5000
VECTOR_DIM = 8


def _session_get(session_state: Any, key: str, default: Any = None) -> Any:
    try:
        return session_state.get(key, default)
    except Exception:
        return default


def _load_secrets() -> dict[str, str]:
    out: dict[str, str] = {}
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    try:
        if secrets_path.is_file():
            for line in secrets_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                name, value = stripped.split("=", 1)
                out[name.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    try:
        import streamlit as st

        for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY", "SUPABASE_PATTERN_TABLE"):
            val = st.secrets.get(key, "")
            if val not in (None, ""):
                out[key] = str(val).strip()
    except Exception:
        pass
    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY", "SUPABASE_PATTERN_TABLE"):
        if not out.get(key):
            env = os.environ.get(key, "")
            if env:
                out[key] = str(env).strip()
    return out


def _supabase_headers(secrets: dict[str, str]) -> dict[str, str]:
    key = secrets.get("SUPABASE_SERVICE_KEY") or secrets.get("SUPABASE_KEY") or ""
    if not key:
        return {}
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _parse_json_field(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            blob = json.loads(raw)
            return blob if isinstance(blob, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_master_signature(raw: Any) -> list[float]:
    blob = raw
    if isinstance(raw, str):
        blob = _parse_json_field(raw) or raw
    if isinstance(blob, dict):
        vec = blob.get("master_signature") or blob.get("master_signature_preview") or []
        if isinstance(vec, list) and vec:
            try:
                return [float(x) for x in vec[:VECTOR_DIM]]
            except (TypeError, ValueError):
                return []
    return []


def _parse_signature_from_row(row: dict[str, Any]) -> list[float]:
    if not isinstance(row, dict):
        return []
    raw = row.get("master_signature_json") or row.get("master_signature") or row.get("signature")
    if isinstance(raw, list):
        try:
            return [float(x) for x in raw[:VECTOR_DIM]]
        except (TypeError, ValueError):
            return []
    if isinstance(raw, dict):
        return _parse_master_signature(raw)
    sig = _parse_master_signature(raw)
    if sig:
        return sig
    env = _parse_json_field(row.get("metric_envelopes_json"))
    if env:
        return _vector_from_metric_envelopes(env, row)
    return _vector_from_row_metadata(row)


def _vector_from_metric_envelopes(env: dict[str, Any], row: dict[str, Any]) -> list[float]:
    vol = env.get("volume") or env.get("Volume") or {}
    vel = env.get("velocity_pct") or {}
    spread = env.get("spread_pct") or {}
    lm = float(row.get("layout_match_pct") or 0)
    return [
        float(vel.get("mid") or vel.get("high") or 0),
        float(vel.get("high") or vel.get("mid") or 0),
        float(vel.get("low") or vel.get("mid") or 0),
        float(vol.get("sigma") or spread.get("sigma") or 0),
        float(vol.get("z_score") or vol.get("z") or 0),
        float(spread.get("mid") or 0),
        0.0,
        lm / 100.0 if lm else 0.0,
    ]


def _vector_from_row_metadata(row: dict[str, Any]) -> list[float]:
    """Collective fingerprint proxy when vault row has no master_signature_json."""
    sm = float(row.get("structural_move_pct") or 0)
    lm = float(row.get("layout_match_pct") or 0)
    bars = float(row.get("bar_count") or 0)
    return [
        round(sm, 4),
        round(sm * 1.25, 4),
        round(sm * 0.65, 4),
        round(min(10.0, bars / 50.0), 4),
        round(lm / 100.0, 4),
        round(sm * 0.15, 4),
        0.0,
        round(lm / 100.0, 4),
    ]


def _average_vectors(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = VECTOR_DIM
    out: list[float] = []
    for i in range(dim):
        vals = [v[i] for v in vectors if len(v) > i]
        out.append(round(sum(vals) / len(vals), 4) if vals else 0.0)
    return out


def _normalize_tf(raw: str) -> str:
    """Map vault strings (15-Minute, 1A (5M)) and watcher keys (1m) to 1m/5m/15m."""
    t = str(raw or "").lower().replace("-", "").replace(" ", "")
    if ("15" in t and "min" in t) or t.endswith("15m") or "(15m)" in t:
        return "15m"
    if ("5" in t and "min" in t) or t.endswith("5m") or "(5m)" in t:
        return "5m"
    if ("1" in t and "min" in t) or t.endswith("1m") or "(1m)" in t:
        return "1m"
    if t in ("1m", "5m", "15m"):
        return t
    return t


def _bucket_key_from_row(row: dict[str, Any]) -> tuple[str, str, str] | None:
    layout_id = str(row.get("macro_weather_layout") or row.get("layout") or "").strip()
    if not layout_id or layout_id in PLACEHOLDER_LAYOUT_IDS:
        return None
    strategy = str(row.get("execution_strategy") or row.get("strategy") or "").strip() or "—"
    raw_tf = str(row.get("timeframe_resolution") or "").strip()
    try:
        import room3_recipes

        tf = room3_recipes.recipe_timeframe(
            strategy=strategy,
            timeframe_resolution=raw_tf,
        ) or _normalize_tf(raw_tf or strategy)
    except Exception:
        tf = _normalize_tf(raw_tf or strategy)
    return (layout_id, strategy, tf)


def _layout_entry(
    *,
    layout_id: str,
    vector: list[float],
    ticker: str = "",
    timeframe_resolution: str = "",
    structural_move_pct: float = 0.0,
    strategy: str = "",
    pattern_count: int = 0,
    source: str = "",
    bucket_key: str = "",
) -> dict[str, Any] | None:
    if not layout_id or layout_id in PLACEHOLDER_LAYOUT_IDS or not vector:
        return None
    try:
        import room3_recipes

        tf_norm = room3_recipes.recipe_timeframe(
            strategy=strategy,
            timeframe_resolution=timeframe_resolution,
        ) or _normalize_tf(timeframe_resolution or strategy)
        mint_n = int(room3_recipes.STRATEGY_MINT_MIN_SAVES)
    except Exception:
        tf_norm = _normalize_tf(timeframe_resolution or strategy)
        mint_n = 3
    bkey = bucket_key or f"{layout_id}|{strategy}|{tf_norm}"
    entry = {
        "layout_id": layout_id,
        "bucket_key": bkey,
        "vector": vector[:VECTOR_DIM],
        "ticker": str(ticker or "").upper(),
        "timeframe_resolution": str(timeframe_resolution or tf_norm),
        "timeframe_norm": tf_norm,
        "structural_move_pct": float(structural_move_pct or 0.0),
        "strategy": str(strategy or ""),
        "pattern_count": int(pattern_count or 0),
        "vector_source": source or "unknown",
        # A bucket we already built a vector for is matchable. Envelopes are
        # Room 2 DNA; only skip trip-size (those never become a bucket).
        "tradeable": bool(
            int(pattern_count or 0) >= mint_n
            and str(source or "") in ("vault_genetic", "vault_envelopes", "session")
            and bool(vector)
        ),
    }
    try:
        import room3_recipes

        return room3_recipes.attach_recipe(entry)
    except Exception:
        return entry


def _aggregate_rows_into_layouts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Collapse pattern saves into layout + strategy + timeframe buckets.
    Many stocks → Layout 1 / 1A (5M) / 5m is its own DNA bucket, separate from 1B (1M), etc.
    """
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _bucket_key_from_row(row)
        if key:
            buckets[key].append(row)

    out: list[dict[str, Any]] = []
    for (layout_id, strategy, tf_norm), group in sorted(buckets.items()):
        genetic: list[list[float]] = []
        envelopes: list[list[float]] = []
        raw_tfs: list[str] = []
        moves: list[float] = []
        for row in group:
            raw_sig = _parse_master_signature(row.get("master_signature_json"))
            if raw_sig:
                genetic.append(raw_sig)
            else:
                env = _parse_json_field(row.get("metric_envelopes_json"))
                if env:
                    vec = _vector_from_metric_envelopes(env, row)
                    if vec and any(abs(float(x or 0)) > 1e-9 for x in vec):
                        envelopes.append(vec)
            raw_tf = str(row.get("timeframe_resolution") or "").strip()
            if raw_tf:
                raw_tfs.append(raw_tf)
            moves.append(float(row.get("structural_move_pct") or 0))

        if genetic:
            canon = _average_vectors(genetic)
            source = "vault_genetic"
        elif envelopes:
            canon = _average_vectors(envelopes)
            source = "vault_envelopes"
        else:
            # Trip-size proxy is not DNA — do not mint a fake live letter.
            continue
        display_tf = Counter(raw_tfs).most_common(1)[0][0] if raw_tfs else tf_norm
        sm = sum(moves) / len(moves) if moves else 0.0
        entry = _layout_entry(
            layout_id=layout_id,
            vector=canon,
            timeframe_resolution=display_tf,
            structural_move_pct=sm,
            strategy=strategy,
            pattern_count=len(group),
            source=source,
            bucket_key=f"{layout_id}|{strategy}|{tf_norm}",
        )
        if entry:
            out.append(entry)
    return out[:LAYOUT_CAP]


def _fetch_vault_rows() -> list[dict[str, Any]]:
    secrets = _load_secrets()
    headers = _supabase_headers(secrets)
    url = secrets.get("SUPABASE_URL", "").rstrip("/")
    if not headers or not url:
        return []
    table = secrets.get("SUPABASE_PATTERN_TABLE") or "forensic_patterns"
    select = (
        "macro_weather_layout,ticker,timeframe_resolution,master_signature_json,"
        "metric_envelopes_json,structural_move_pct,execution_strategy,layout_match_pct,"
        "bar_count,vault_track,state"
    )
    try:
        resp = requests.get(
            f"{url}/rest/v1/{table}"
            f"?select={select}"
            "&macro_weather_layout=not.is.null"
            "&or=(state.is.null,state.eq.active,state.eq.incubation)"
            f"&order=timestamp.desc&limit={VAULT_FETCH_LIMIT}",
            headers=headers,
            timeout=45,
        )
        if not resp.ok:
            return []
        body = resp.json()
        return body if isinstance(body, list) else []
    except Exception:
        return []


def _layouts_from_session_vectors(session_state: Any) -> list[dict[str, Any]]:
    raw = _session_get(session_state, "layout_master_matrix_index") or []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        layout_id = str(entry.get("layout_id") or entry.get("macro_weather_layout") or "").strip()
        vec = entry.get("vector") or _parse_signature_from_row(entry)
        if not isinstance(vec, list):
            vec = []
        row = _layout_entry(
            layout_id=layout_id,
            vector=[float(x) for x in vec[:VECTOR_DIM]] if vec else [],
            ticker=str(entry.get("ticker") or ""),
            timeframe_resolution=str(entry.get("timeframe_resolution") or ""),
            structural_move_pct=float(entry.get("structural_move_pct") or 0.0),
            strategy=str(entry.get("execution_strategy") or entry.get("strategy") or ""),
            source="session",
        )
        if row:
            out.append(row)
    return out


def _layouts_from_local_cache() -> list[dict[str, Any]]:
    try:
        if not CACHE_PATH.is_file():
            return []
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = [r for r in (cache.get("patterns") or []) if isinstance(r, dict)]
    return _aggregate_rows_into_layouts(rows)


def _layouts_from_supabase() -> list[dict[str, Any]]:
    return _aggregate_rows_into_layouts(_fetch_vault_rows())


def _merge_layout_libraries(*parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per layout+strategy+timeframe bucket."""
    rank = {
        "session": 3,
        "vault_genetic": 2,
        "vault_envelopes": 1,
        "vault_collective": 1,
        "unknown": 0,
    }
    merged: dict[str, dict[str, Any]] = {}
    for layouts in parts:
        for entry in layouts or []:
            bkey = str(
                entry.get("bucket_key")
                or f"{entry.get('layout_id')}|{entry.get('strategy')}|{entry.get('timeframe_norm') or _normalize_tf(entry.get('timeframe_resolution') or '')}"
            )
            if not bkey:
                continue
            prev = merged.get(bkey)
            if not prev:
                merged[bkey] = entry
                continue
            prev_rank = rank.get(str(prev.get("vector_source") or ""), 0)
            cur_rank = rank.get(str(entry.get("vector_source") or ""), 0)
            if cur_rank > prev_rank or (
                cur_rank == prev_rank
                and int(entry.get("pattern_count") or 0) > int(prev.get("pattern_count") or 0)
            ):
                merged[bkey] = entry
    return list(merged.values())[:LAYOUT_CAP]


def _deploy_registry_from_vault(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        layout = str(row.get("macro_weather_layout") or "").strip()
        strategy = str(row.get("execution_strategy") or "").strip()
        if not layout or not strategy:
            continue
        key = (layout, strategy)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "layout": layout,
                "strategy": strategy,
                "ticker": str(row.get("ticker") or "").upper(),
                "timeframe": str(row.get("timeframe_resolution") or ""),
                "structural_move": float(row.get("structural_move_pct") or 0.0),
            }
        )
    return out[-256:]


def _deploy_registry(session_state: Any, vault_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    reg = _session_get(session_state, "room2_deploy_registry") or []
    if isinstance(reg, list) and reg:
        return [dict(x) for x in reg if isinstance(x, dict)]
    vault_reg = _deploy_registry_from_vault(vault_rows or _fetch_vault_rows())
    if vault_reg:
        return vault_reg
    try:
        if CACHE_PATH.is_file():
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            local = cache.get("deploy_registry") or []
            if isinstance(local, list):
                return [dict(x) for x in local if isinstance(x, dict)]
    except Exception:
        pass
    return []


def ensure_layout_library(session_state: Any) -> int:
    """
    Always hydrate the full collective layout library from vault + session.
    Many pattern saves → few layout buckets (Layout 1–4, etc.).
    """
    vault_rows = _fetch_vault_rows()
    vault_layouts = _aggregate_rows_into_layouts(vault_rows)
    session_layouts = _layouts_from_session_vectors(session_state)
    cache_layouts = _layouts_from_local_cache()
    merged = _merge_layout_libraries(session_layouts, vault_layouts, cache_layouts)
    if merged:
        try:
            session_state.layout_master_matrix_index = merged
            session_state.layout_library_hydrated = True
            session_state.room3_layout_hydrated = True
            session_state.room3_vault_pattern_rows = len(vault_rows)
        except Exception:
            pass
    return len(merged)


def matrix_repertoire(session_state: Any) -> dict[str, Any]:
    """Full collective repertoire — all layout buckets from vault + session."""
    try:
        cache = _session_get(session_state, "room3_repertoire_cache") or {}
        if (
            isinstance(cache, dict)
            and cache.get("layouts")
            and (time.time() - float(cache.get("_cached_at") or 0)) < REPERTOIRE_CACHE_TTL_SEC
        ):
            return cache
    except Exception:
        cache = {}

    vault_rows = _fetch_vault_rows()
    vault_layouts = _aggregate_rows_into_layouts(vault_rows)
    session_layouts = _layouts_from_session_vectors(session_state)
    cache_layouts = _layouts_from_local_cache()
    layouts = _merge_layout_libraries(session_layouts, vault_layouts, cache_layouts)
    if not layouts:
        ensure_layout_library(session_state)
        layouts = _merge_layout_libraries(
            _layouts_from_session_vectors(session_state),
            _aggregate_rows_into_layouts(_fetch_vault_rows()),
            _layouts_from_local_cache(),
        )

    deploy_registry = _deploy_registry(session_state, vault_rows)
    genetic_n = sum(1 for x in layouts if str(x.get("vector_source") or "") == "vault_genetic")
    collective_n = sum(1 for x in layouts if str(x.get("vector_source") or "") == "vault_collective")
    tradeable_n = sum(1 for x in layouts if x.get("tradeable"))

    weather = _session_get(session_state, "market_weather_snapshot") or {}
    weather_name = ""
    if isinstance(weather, dict):
        weather_name = str(
            weather.get("label") or weather.get("regime") or weather.get("name") or ""
        ).strip()

    try:
        pattern_count = int(_session_get(session_state, "matrix_active_pattern_count") or 0)
    except (TypeError, ValueError):
        pattern_count = 0
    if not pattern_count:
        pattern_count = len(vault_rows)
    try:
        save_count = int(_session_get(session_state, "matrix_active_save_count") or 0)
    except (TypeError, ValueError):
        save_count = 0

    layout_n = len(layouts)
    deploy_n = len(deploy_registry)
    dna_ready = tradeable_n > 0
    if layout_n:
        dna_note = (
            f"Live strategies: {tradeable_n} (≥3 saves + real DNA). "
            f"{layout_n} bucket(s) from {pattern_count or len(vault_rows)} save(s). "
            "Purgatory / trip-size proxies do not fire."
        )
    else:
        dna_note = "Vault connected but no layout buckets found."
    rep = {
        "layouts": layouts,
        "deploy_registry": deploy_registry,
        "layout_count": layout_n,
        "tradeable_count": tradeable_n,
        "deploy_count": deploy_n,
        "pattern_count": pattern_count,
        "save_count": save_count,
        "vault_rows": len(vault_rows),
        "genetic_layouts": genetic_n,
        "collective_layouts": collective_n,
        "weather": weather_name or "—",
        "ready": dna_ready,
        "source": "vault_collective" if vault_layouts else ("session" if session_layouts else "empty"),
        "dna_note": dna_note,
    }
    rep["_cached_at"] = time.time()
    try:
        session_state.room3_repertoire_cache = rep
        session_state.layout_master_matrix_index = layouts
    except Exception:
        pass
    return rep


def matrix_snapshot(session_state: Any) -> dict[str, Any]:
    """Safe peek — never throws if Room 2 state is missing or reshaped."""
    rep = matrix_repertoire(session_state)
    return {
        "layout_count": rep.get("layout_count", 0),
        "deploy_count": rep.get("deploy_count", 0),
        "pattern_count": rep.get("pattern_count", 0),
        "save_count": rep.get("save_count", 0),
        "vault_rows": rep.get("vault_rows", 0),
        "genetic_layouts": rep.get("genetic_layouts", 0),
        "collective_layouts": rep.get("collective_layouts", 0),
        "weather": rep.get("weather") or "—",
        "ready": bool(rep.get("ready")),
        "source": rep.get("source") or "empty",
        "dna_note": rep.get("dna_note") or "",
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "layout_count": 0,
        "deploy_count": 0,
        "pattern_count": 0,
        "save_count": 0,
        "vault_rows": 0,
        "genetic_layouts": 0,
        "collective_layouts": 0,
        "weather": "—",
        "ready": False,
        "source": "empty",
        "dna_note": "",
    }
