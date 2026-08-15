"""
Room 3 strategy recipes — lookback + sensors per layout·strategy·TF.

Room 2 used long nets to *discover* DNA. Room 3 only needs strategy-sized
lookback to *recognize* it, then 30s snapshots to finish the puzzle.

Shared sensors across strategies on a ticker are fetched once per tick.
"""

from __future__ import annotations

import math
from typing import Any

# Default lookback (minutes of tape) when vault doesn't spell it out.
DEFAULT_LOOKBACK_MIN: dict[str, int] = {
    "1m": 20,
    "5m": 60,
    "15m": 120,  # ~2h — typical 15m signal window, not Room 2's multi-day net
}
MAX_LOOKBACK_MIN: dict[str, int] = {
    "1m": 60,
    "5m": 180,
    "15m": 240,
}
# Chart always on; others are recipe flags (stubs ok until wired).
BASE_SENSORS = ("charts", "vwap")
OPTIONAL_SENSORS = ("sec", "news", "social")


def normalize_tf(raw: str) -> str:
    s = str(raw or "").strip().lower().replace(" ", "")
    if s in {"1", "1m", "1min", "1minute", "m1"}:
        return "1m"
    if s in {"5", "5m", "5min", "5minute", "m5"}:
        return "5m"
    if s in {"15", "15m", "15min", "15minute", "m15"}:
        return "15m"
    if "15" in s:
        return "15m"
    if s.startswith("5") or "5m" in s:
        return "5m"
    if s.startswith("1") or "1m" in s:
        return "1m"
    return "5m"


def minutes_to_bars(tf: str, minutes: int) -> int:
    tf = normalize_tf(tf)
    minutes = max(1, int(minutes or 1))
    if tf == "1m":
        return max(5, minutes)
    if tf == "5m":
        return max(4, int(math.ceil(minutes / 5.0)))
    return max(3, int(math.ceil(minutes / 15.0)))


def recipe_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
) -> dict[str, Any]:
    """
    Build a recipe for one layout·strategy·TF bucket.

    Heuristics until vault stores explicit recipes:
      - TF default lookback
      - strategy/layout name keywords unlock optional sensors
      - larger structural moves get a bit more tape + patience
    """
    tf = normalize_tf(timeframe)
    strat = str(strategy or "").strip()
    layout = str(layout_id or "").strip()
    blob = f"{strat} {layout}".lower()

    lookback = int(DEFAULT_LOOKBACK_MIN.get(tf, 60))
    sensors: list[str] = list(BASE_SENSORS)

    if any(k in blob for k in ("sec", "filing", "8-k", "8k", "10-q", "10q", "earnings")):
        if "sec" not in sensors:
            sensors.append("sec")
        lookback = max(lookback, int(DEFAULT_LOOKBACK_MIN.get(tf, 60) * 1.25))
    if any(k in blob for k in ("news", "headline", "press", "catalyst")):
        if "news" not in sensors:
            sensors.append("news")
    if any(k in blob for k in ("social", "sentiment", "reddit", "twitter", "x.com")):
        if "social" not in sensors:
            sensors.append("social")
    if any(k in blob for k in ("vwap", "volume profile", "anchor")):
        if "vwap" not in sensors:
            sensors.append("vwap")

    move = abs(float(structural_move_pct or 0))
    if move >= 8.0:
        lookback = int(lookback * 1.35)
    elif move >= 4.0:
        lookback = int(lookback * 1.15)

    cap = int(MAX_LOOKBACK_MIN.get(tf, 180))
    lookback = max(5, min(cap, lookback))
    bars = minutes_to_bars(tf, lookback)

    return {
        "layout_id": layout,
        "strategy": strat or "—",
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": bars,
        "sensors": sensors,
        # If DNA is warm but incomplete — keep watching; stock may lag the pattern.
        "patience": True,
        "patience_match_floor": 70,
    }


def attach_recipe(layout_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(layout_entry or {})
    entry["recipe"] = recipe_for(
        str(entry.get("strategy") or ""),
        str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "5m"),
        layout_id=str(entry.get("layout_id") or ""),
        structural_move_pct=float(entry.get("structural_move_pct") or 0),
    )
    return entry


def plan_for_timeframe(
    layouts: list[dict[str, Any]] | None,
    timeframe: str,
) -> dict[str, Any]:
    """
    Across all recipes on this TF: max lookback, union of sensors.
    Shared fetches run once; each strategy still scores its own window.
    """
    tf = normalize_tf(timeframe)
    recipes: list[dict[str, Any]] = []
    for entry in layouts or []:
        entry_tf = normalize_tf(
            str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "")
        )
        if entry_tf and entry_tf != tf:
            continue
        rec = entry.get("recipe")
        if not isinstance(rec, dict):
            rec = recipe_for(
                str(entry.get("strategy") or ""),
                tf,
                layout_id=str(entry.get("layout_id") or ""),
                structural_move_pct=float(entry.get("structural_move_pct") or 0),
            )
        recipes.append(rec)

    if not recipes:
        recipes = [recipe_for("", tf)]

    lookback = max(int(r.get("lookback_minutes") or 0) for r in recipes)
    bars = max(int(r.get("bars_keep") or 0) for r in recipes)
    sensors: list[str] = []
    seen: set[str] = set()
    for r in recipes:
        for s in r.get("sensors") or []:
            s = str(s).strip().lower()
            if s and s not in seen:
                seen.add(s)
                sensors.append(s)
    for s in BASE_SENSORS:
        if s not in seen:
            sensors.insert(0, s)
            seen.add(s)

    return {
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": max(bars, minutes_to_bars(tf, lookback)),
        "sensors": sensors,
        "recipes": recipes,
        "strategy_count": len(recipes),
    }


def empty_sensor_pack(ticker: str) -> dict[str, Any]:
    return {
        "ticker": str(ticker or "").upper(),
        "charts": {"ok": False, "note": "pending"},
        "vwap": {"ok": False, "note": "pending"},
        "sec": {"ok": None, "note": "stub — not wired yet"},
        "news": {"ok": None, "note": "stub — not wired yet"},
        "social": {"ok": None, "note": "stub — not wired yet"},
        "shared": True,
    }


def recipes_need_sensor(recipes: list[dict[str, Any]], sensor: str) -> bool:
    s = str(sensor or "").lower()
    return any(s in (r.get("sensors") or []) for r in recipes)
