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
import re
from pathlib import Path
from typing import Any

import requests

# Session keys Room 3 is allowed to observe (read-only).
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


def _parse_master_signature(raw: Any) -> list[float]:
    blob = raw
    if isinstance(raw, str):
        try:
            blob = json.loads(raw)
        except Exception:
            return []
    if not isinstance(blob, dict):
        return []
    vec = blob.get("master_signature") or blob.get("master_signature_preview") or []
    if isinstance(vec, list) and vec:
        try:
            return [float(x) for x in vec]
        except (TypeError, ValueError):
            return []
    return []


def _parse_signature_from_row(row: dict[str, Any]) -> list[float]:
    if not isinstance(row, dict):
        return []
    raw = row.get("master_signature_json") or row.get("master_signature") or row.get("signature")
    if isinstance(raw, list):
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            return []
    if isinstance(raw, dict):
        return _parse_master_signature(raw)
    return _parse_master_signature(raw)


def _layout_entry(
    *,
    layout_id: str,
    vector: list[float],
    ticker: str = "",
    timeframe_resolution: str = "",
    structural_move_pct: float = 0.0,
    strategy: str = "",
) -> dict[str, Any] | None:
    if not layout_id or layout_id in PLACEHOLDER_LAYOUT_IDS or not vector:
        return None
    return {
        "layout_id": layout_id,
        "vector": vector,
        "ticker": str(ticker or "").upper(),
        "timeframe_resolution": str(timeframe_resolution or ""),
        "structural_move_pct": float(structural_move_pct or 0.0),
        "strategy": str(strategy or ""),
    }


def _layouts_from_last_deploy(session_state: Any) -> list[dict[str, Any]]:
    """Fallback — DNA minted on the most recent Room 2 deploy in this session."""
    sig = _session_get(session_state, "room2_master_signature") or {}
    vec = sig.get("master_signature") or []
    if not isinstance(vec, list) or len(vec) < 8:
        return []
    layout_id = str(sig.get("layout_id") or "").strip()
    last = _session_get(session_state, "room2_last_successful_deploy") or {}
    if not layout_id or layout_id in PLACEHOLDER_LAYOUT_IDS:
        layout_id = str(last.get("layout") or last.get("macro_weather_layout") or "").strip()
    if not layout_id or layout_id in PLACEHOLDER_LAYOUT_IDS:
        return []
    strategy = ""
    for row in reversed(list(_session_get(session_state, "room2_deploy_registry") or [])):
        if str(row.get("layout") or "") == layout_id:
            strategy = str(row.get("strategy") or "")
            break
    entry = _layout_entry(
        layout_id=layout_id,
        vector=[float(x) for x in vec[:8]],
        ticker=str(last.get("ticker") or ""),
        timeframe_resolution=str(last.get("timeframe") or ""),
        structural_move_pct=float(last.get("structural_move") or 0.0),
        strategy=strategy,
    )
    return [entry] if entry else []


def _layouts_from_session(session_state: Any) -> list[dict[str, Any]]:
    raw = _session_get(session_state, "layout_master_matrix_index") or []
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        layout_id = str(entry.get("layout_id") or entry.get("macro_weather_layout") or "").strip()
        vec = entry.get("vector") or _parse_signature_from_row(entry)
        row = _layout_entry(
            layout_id=layout_id,
            vector=list(vec) if isinstance(vec, list) else [],
            ticker=str(entry.get("ticker") or ""),
            timeframe_resolution=str(entry.get("timeframe_resolution") or ""),
            structural_move_pct=float(entry.get("structural_move_pct") or 0.0),
            strategy=str(entry.get("execution_strategy") or entry.get("strategy") or ""),
        )
        if row:
            out.append(row)
    if out:
        return out
    return _layouts_from_last_deploy(session_state)


def _layouts_from_local_cache() -> list[dict[str, Any]]:
    try:
        if not CACHE_PATH.is_file():
            return []
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cache.get("patterns") or []:
        if not isinstance(row, dict):
            continue
        layout_id = str(
            row.get("macro_weather_layout") or row.get("layout") or row.get("layout_id") or ""
        ).strip()
        vec = _parse_signature_from_row(row)
        dedupe = f"{layout_id}|{row.get('timeframe_resolution')}|{row.get('ticker')}"
        if dedupe in seen:
            continue
        entry = _layout_entry(
            layout_id=layout_id,
            vector=vec,
            ticker=str(row.get("ticker") or ""),
            timeframe_resolution=str(row.get("timeframe_resolution") or ""),
            structural_move_pct=float(row.get("structural_move_pct") or row.get("structural_move") or 0.0),
            strategy=str(row.get("execution_strategy") or row.get("strategy") or ""),
        )
        if entry:
            seen.add(dedupe)
            out.append(entry)
    return out


def _layouts_from_supabase() -> list[dict[str, Any]]:
    secrets = _load_secrets()
    headers = _supabase_headers(secrets)
    url = secrets.get("SUPABASE_URL", "").rstrip("/")
    if not headers or not url:
        return []
    table = secrets.get("SUPABASE_PATTERN_TABLE") or "forensic_patterns"
    try:
        resp = requests.get(
            f"{url}/rest/v1/{table}"
            "?select=macro_weather_layout,ticker,timeframe_resolution,master_signature_json,"
            "structural_move_pct,execution_strategy,vault_track,state"
            "&macro_weather_layout=not.is.null"
            "&or=(state.is.null,state.eq.active,state.eq.incubation)"
            "&order=timestamp.desc&limit=500",
            headers=headers,
            timeout=20,
        )
        if not resp.ok:
            return []
        rows = resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        layout_id = str(row.get("macro_weather_layout") or "").strip()
        vec = _parse_signature_from_row(row)
        dedupe = f"{layout_id}|{row.get('timeframe_resolution')}|{row.get('ticker')}"
        if dedupe in seen:
            continue
        entry = _layout_entry(
            layout_id=layout_id,
            vector=vec,
            ticker=str(row.get("ticker") or ""),
            timeframe_resolution=str(row.get("timeframe_resolution") or ""),
            structural_move_pct=float(row.get("structural_move_pct") or 0.0),
            strategy=str(row.get("execution_strategy") or ""),
        )
        if entry:
            seen.add(dedupe)
            out.append(entry)
    return out


def _deploy_registry(session_state: Any) -> list[dict[str, Any]]:
    reg = _session_get(session_state, "room2_deploy_registry") or []
    if isinstance(reg, list) and reg:
        return [dict(x) for x in reg if isinstance(x, dict)]
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
    Hydrate layout_master_matrix_index for Room 3 when Room 2 hasn't this session.
    Session → local cache → Supabase. Writes back to session when possible.
    """
    existing = _layouts_from_session(session_state)
    if existing:
        try:
            session_state.layout_library_hydrated = True
        except Exception:
            pass
        return len(existing)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in (_layouts_from_local_cache(), _layouts_from_supabase()):
        for entry in source:
            key = f"{entry.get('layout_id')}|{entry.get('timeframe_resolution')}|{entry.get('ticker')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)

    if merged:
        merged = merged[:LAYOUT_CAP]
        try:
            session_state.layout_master_matrix_index = merged
            session_state.layout_library_hydrated = True
            session_state.room3_layout_hydrated = True
        except Exception:
            pass
    return len(merged)


def matrix_repertoire(session_state: Any) -> dict[str, Any]:
    """Full read-only repertoire for DNA matching."""
    ensure_layout_library(session_state)
    layouts = _layouts_from_session(session_state)
    if not layouts:
        layouts = _layouts_from_local_cache() or _layouts_from_supabase()
    deploy_registry = _deploy_registry(session_state)

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
    try:
        save_count = int(_session_get(session_state, "matrix_active_save_count") or 0)
    except (TypeError, ValueError):
        save_count = 0

    layout_n = len(layouts)
    deploy_n = len(deploy_registry)
    dna_ready = layout_n > 0
    return {
        "layouts": layouts,
        "deploy_registry": deploy_registry,
        "layout_count": layout_n,
        "deploy_count": deploy_n,
        "pattern_count": pattern_count or deploy_n,
        "save_count": save_count,
        "weather": weather_name or "—",
        "ready": dna_ready,
        "source": (
            "session"
            if _layouts_from_session(session_state)
            else ("last_deploy" if layouts else ("cache/cloud" if layout_n else "empty"))
        ),
        "dna_note": (
            "DNA vectors loaded — matching enabled."
            if dna_ready
            else f"{pattern_count or deploy_n} vault pattern(s) but 0 DNA vectors — "
            "Archive once in Room 2 (same tab, no refresh) then return here."
        ),
    }


def matrix_snapshot(session_state: Any) -> dict[str, Any]:
    """Safe peek — never throws if Room 2 state is missing or reshaped."""
    rep = matrix_repertoire(session_state)
    return {
        "layout_count": rep.get("layout_count", 0),
        "deploy_count": rep.get("deploy_count", 0),
        "pattern_count": rep.get("pattern_count", 0),
        "save_count": rep.get("save_count", 0),
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
        "weather": "—",
        "ready": False,
        "source": "empty",
    }
