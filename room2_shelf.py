"""Dated S1 release of the current purgatory shelf (operator 2026-10-06).

One-time lock: vault incubation + chat packs that sat on this date fire as
own-letter S1, same TF, as-of discovery. They do not bolt onto 2A / 2C / 1B.
Purgatory-named rows stay untradeable. Future captures stay on the shelf
until the operator changes that rule.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import room3_bridge as br

ET = ZoneInfo("America/New_York")
RELEASE_PATH = Path(__file__).resolve().parent / "room2_s1_release.json"
LETTER = {
    "1m": ("S", "S1 (1M)"),
    "5m": ("S", "S1 (5M)"),
    "15m": ("S", "S1 (15M)"),
}


def _today() -> date:
    return datetime.now(ET).date()


def dated_entries() -> list[dict[str, Any]]:
    if not RELEASE_PATH.is_file():
        return []
    try:
        body = json.loads(RELEASE_PATH.read_text())
    except Exception:
        return []
    rows = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            day = date.fromisoformat(str(row.get("discovery") or ""))
        except ValueError:
            continue
        item = dict(row)
        item["_discovery"] = day
        out.append(item)
    return out


def packs_before(day: date) -> list[dict[str, Any]]:
    """Visible when discovery is on or before this session. No future peek."""
    return [p for p in dated_entries() if p["_discovery"] <= day]


def _entry(row: dict[str, Any]) -> dict[str, Any] | None:
    tf = str(row.get("tf") or "")
    vec = list(row.get("vector") or [])
    if tf not in LETTER or len(vec) < 6:
        return None
    lid, strat = LETTER[tf]
    return br._layout_entry(
        layout_id=lid,
        vector=vec,
        ticker=str(row.get("ticker") or ""),
        timeframe_resolution=tf,
        structural_move_pct=float(row.get("move") or 0),
        strategy=strat,
        pattern_count=3,
        source="s1_release_2026_10_06",
    )


def layouts_as_of(day: date | None = None) -> list[dict[str, Any]]:
    """Live/sim library extras for session `day` (default today ET)."""
    sess = day or _today()
    extra: list[dict[str, Any]] = []
    for row in packs_before(sess):
        entry = _entry(row)
        if entry:
            extra.append(entry)
    return extra


def packs_before_open(day: date) -> list[dict[str, Any]]:
    """Older as-of helper: session strictly before `day`."""
    return [p for p in dated_entries() if p["_discovery"] < day]
