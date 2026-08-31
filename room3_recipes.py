"""
Room 3 strategy recipes — lookback + sensors per layout·strategy·TF.

Room 2 used long nets to *discover* DNA. Room 3 only needs strategy-sized
lookback to *recognize* it, then 30s snapshots to finish the puzzle.

Shared sensors across strategies on a ticker are fetched once per tick.
"""

from __future__ import annotations

import math
import re
from typing import Any

# 5A (15M) / 1D (15M) — the letter’s own TF token. Wins over a stale vault clock.
_STRATEGY_TF_TOKEN = re.compile(r"\(\s*(1|5|15)\s*M\s*\)", re.IGNORECASE)
_PURGATORY_LETTER = re.compile(r"^P\d+\b", re.IGNORECASE)

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
# Chart + VWAP always. Named catalysts plus hyper-vol extras (not keyword-gated).
# Operator names SEC/volume/price/news/social; we also pack what those names need.
BASE_SENSORS = ("charts", "vwap", "rvol")
SHARED_CATALYST_SENSORS = (
    "sec",
    "news",
    "social",
    "float",
    "short_interest",
    "dilution",
    "halt",
    "spread",
)
# Extra tells by TF — hyper-volatile names; 15m gets the deepest brew.
TF_EXTRA_SENSORS: dict[str, tuple[str, ...]] = {
    "1m": ("prints", "bid_ask"),
    "5m": ("premarket_rvol", "float_rotation"),
    "15m": ("offering", "insider", "borrow", "sector", "days_to_cover"),
}
OPTIONAL_SENSORS = SHARED_CATALYST_SENSORS + (
    "prints",
    "bid_ask",
    "premarket_rvol",
    "float_rotation",
    "offering",
    "insider",
    "borrow",
    "sector",
    "days_to_cover",
)
# Three similar packs before a letter is a live strategy (purgatory until then).
STRATEGY_MINT_MIN_SAVES = 3


def normalize_tf(raw: str) -> str:
    named = strategy_tf_token(raw)
    if named:
        return named
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


def strategy_tf_token(strategy: str) -> str:
    """TF printed on a matrix letter, e.g. 5A (15M) → 15m. Empty if unlabeled."""
    match = _STRATEGY_TF_TOKEN.search(str(strategy or ""))
    if not match:
        return ""
    return {"1": "1m", "5": "5m", "15": "15m"}[match.group(1)]


def recipe_timeframe(
    *,
    strategy: str = "",
    timeframe: str = "",
    timeframe_norm: str = "",
    timeframe_resolution: str = "",
) -> str:
    """
    Timeframe this DNA actually belongs to.

    The letter’s parenthetical (15M / 5M / 1M) wins over timeframe_norm.
    That stops a 1m watch from matching a bin whose clock says 1m but whose
    name is 5A (15M) — CRE Aug 26: 1m ticket, 15M sticker.
    """
    named = strategy_tf_token(strategy)
    if named:
        return named
    for raw in (timeframe_norm, timeframe, timeframe_resolution):
        text = str(raw or "").strip()
        if not text:
            continue
        tf = normalize_tf(text)
        if tf in ("1m", "5m", "15m"):
            return tf
    if str(strategy or "").strip():
        tf = normalize_tf(strategy)
        if tf in ("1m", "5m", "15m"):
            return tf
    return ""


def strategy_tf_agrees(strategy: str, watch_tf: str) -> bool:
    """False when the letter names a different TF than the live watch."""
    named = strategy_tf_token(strategy)
    want = normalize_tf(watch_tf) if str(watch_tf or "").strip() else ""
    if not named or want not in ("1m", "5m", "15m"):
        return True
    return named == want


def is_purgatory_letter(layout_id: str = "", strategy: str = "") -> bool:
    """Purgatory sits. It is not a live strategy and must not match or fire."""
    lid = str(layout_id or "").strip().lower()
    if lid == "purgatory" or lid.startswith("purgatory"):
        return True
    strat = str(strategy or "").strip()
    if _PURGATORY_LETTER.match(strat):
        return True
    return False


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
      - always pack catalyst + hyper-vol extras (not keyword-gated)
      - larger stored trips get a bit more tape + patience
    """
    tf = normalize_tf(timeframe)
    strat = str(strategy or "").strip()
    layout = str(layout_id or "").strip()
    blob = f"{strat} {layout}".lower()

    lookback = int(DEFAULT_LOOKBACK_MIN.get(tf, 60))
    sensors: list[str] = list(BASE_SENSORS)
    for s in SHARED_CATALYST_SENSORS:
        if s not in sensors:
            sensors.append(s)
    for s in TF_EXTRA_SENSORS.get(tf, ()):
        if s not in sensors:
            sensors.append(s)

    if any(k in blob for k in ("sec", "filing", "8-k", "8k", "10-q", "10q", "earnings")):
        lookback = max(lookback, int(DEFAULT_LOOKBACK_MIN.get(tf, 60) * 1.25))

    move = abs(float(structural_move_pct or 0))
    if move >= 8.0:
        lookback = int(lookback * 1.35)
    elif move >= 4.0:
        lookback = int(lookback * 1.15)

    cap = int(MAX_LOOKBACK_MIN.get(tf, 180))
    lookback = max(5, min(cap, lookback))
    bars = minutes_to_bars(tf, lookback)

    cadence = cadence_for(
        strat,
        tf,
        layout_id=layout,
        structural_move_pct=move,
    )
    return {
        "layout_id": layout,
        "strategy": strat or "—",
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": bars,
        "sensors": sensors,
        "pulse_seconds": cadence["pulse_seconds"],
        "extra_refresh_seconds": cadence["extra_refresh_seconds"],
        "order_style": order_style_for(
            strat, tf, layout_id=layout, structural_move_pct=move
        ),
        # If DNA is warm but incomplete — keep watching; stock may lag the pattern.
        "patience": True,
        "patience_match_floor": 70,
    }


def order_style_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
) -> str:
    """
    Market only when waiting would miss the print. Otherwise limit (less slippage,
    Yahoo/Alpaca lag). 1m is a prior for pops, not a hard rule — 5m/15m can pop too.
    Outside RTH the broker still forces a limit.
    """
    tf = normalize_tf(timeframe)
    blob = f"{strategy} {layout_id}".lower()
    patient = (
        "vwap",
        "pullback",
        "reversion",
        "mean rev",
        "fade",
        "swing",
        "range",
        "dip",
        "reclaim",
        "flag",
        "patient",
        "limit",
    )
    pop = (
        "scalp",
        "sniper",
        "pop",
        "spike",
        "burst",
        "chase",
        "impulse",
        "flush",
        "squeeze",
        "blast",
        "gap and go",
        "gap&go",
    )
    if any(k in blob for k in patient):
        return "limit"
    if any(k in blob for k in pop):
        return "market"
    if tf == "1m" and abs(float(structural_move_pct or 0)) < 4.0:
        return "market"
    return "limit"


def cadence_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
    in_trade: bool = False,
) -> dict[str, int]:
    """
    Revisit interval after the first lookback paint.
    15m lives on 5–10m checks (a closed bar), not a 15s clip.
    5m typical ~1–5m. 1m pops stay short.
    """
    tf = normalize_tf(timeframe)
    style = order_style_for(
        strategy,
        tf,
        layout_id=layout_id,
        structural_move_pct=structural_move_pct,
    )
    pop = style == "market"
    if tf == "1m":
        pulse = 15 if pop else 60
        extras = 120 if pop else 180
    elif tf == "5m":
        pulse = 60 if pop else 300
        extras = 180 if pop else 300
    else:
        pulse = 300 if pop else 600
        extras = 300 if pop else 600
    if in_trade:
        if tf == "1m":
            pulse = min(int(pulse), 15)
        elif tf == "5m":
            pulse = min(int(pulse), 60)
        else:
            pulse = min(int(pulse), 300)
    return {"pulse_seconds": int(pulse), "extra_refresh_seconds": int(extras)}


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

    pulses = [int(r.get("pulse_seconds") or 60) for r in recipes] or [60]
    extras = [int(r.get("extra_refresh_seconds") or 300) for r in recipes] or [300]
    return {
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": max(bars, minutes_to_bars(tf, lookback)),
        "sensors": sensors,
        "pulse_seconds": min(pulses),
        "extra_refresh_seconds": min(extras),
        "recipes": recipes,
        "strategy_count": len(recipes),
    }


def empty_sensor_pack(ticker: str) -> dict[str, Any]:
    pack: dict[str, Any] = {
        "ticker": str(ticker or "").upper(),
        "charts": {"ok": False, "note": "pending"},
        "vwap": {"ok": False, "note": "pending"},
        "shared": True,
    }
    for name in OPTIONAL_SENSORS:
        pack[name] = {"ok": None, "note": "pending — hyper-vol extra"}
    return pack


def recipes_need_sensor(recipes: list[dict[str, Any]], sensor: str) -> bool:
    s = str(sensor or "").lower()
    return any(s in (r.get("sensors") or []) for r in recipes)
