"""
Room 2 → Room 3 bridge (ONE WAY).

Rules:
- Room 3 may READ a small snapshot of matrix state.
- Room 3 must NOT import Room 2 modules (vault_bridge, core_quantum, app guts).
- Room 2 must NOT import room3_* modules.
- If Room 2 renames internals, update ONLY this file's readers — Room 3 UI/engine stay stable.
- Missing keys → empty snapshot (Room 3 still runs; handshake just says quiet).

Full signal bus (scan → entry/exit orders) is NOT established yet.
This file is the contract for what *is* shared today.
"""

from __future__ import annotations

from typing import Any


# Session keys Room 3 is allowed to observe (read-only).
# Do not reach into other Room 2 keys from room3_* code.
ROOM2_OBSERVE_KEYS = (
    "layout_master_matrix_index",
    "room2_deploy_registry",
    "matrix_active_pattern_count",
    "matrix_active_save_count",
    "market_weather_snapshot",
)


def matrix_snapshot(session_state: Any) -> dict[str, Any]:
    """Safe peek — never throws if Room 2 state is missing or reshaped."""
    try:
        get = session_state.get
    except Exception:
        return _empty_snapshot()

    layouts = get("layout_master_matrix_index") or []
    deploys = get("room2_deploy_registry") or []
    try:
        patterns = int(get("matrix_active_pattern_count") or 0)
    except (TypeError, ValueError):
        patterns = 0
    try:
        saves = int(get("matrix_active_save_count") or 0)
    except (TypeError, ValueError):
        saves = 0

    weather = get("market_weather_snapshot") or {}
    weather_name = ""
    if isinstance(weather, dict):
        weather_name = str(
            weather.get("label")
            or weather.get("regime")
            or weather.get("name")
            or ""
        ).strip()

    layout_n = len(layouts) if isinstance(layouts, list) else 0
    deploy_n = len(deploys) if isinstance(deploys, list) else 0
    return {
        "layout_count": layout_n,
        "deploy_count": deploy_n,
        "pattern_count": patterns,
        "save_count": saves,
        "weather": weather_name or "—",
        "ready": bool(layout_n or deploy_n or patterns or saves),
    }


def _empty_snapshot() -> dict[str, Any]:
    return {
        "layout_count": 0,
        "deploy_count": 0,
        "pattern_count": 0,
        "save_count": 0,
        "weather": "—",
        "ready": False,
    }
