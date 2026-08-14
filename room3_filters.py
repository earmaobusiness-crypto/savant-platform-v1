"""
Room 3 session filter slots.

Built-in screener (room3_screener) is the primary RTH feed.
Optional paste backup + dormant TV webhook inbox remain for fallback.
"""

from __future__ import annotations

import re
from typing import Any

import room3_engine
import room3_watcher

SLOT_PRE = room3_engine.SESSION_PRE
SLOT_RTH = room3_engine.SESSION_RTH
SLOT_POST = room3_engine.SESSION_POST
SLOTS = (SLOT_PRE, SLOT_RTH, SLOT_POST)

_EXCHANGE_PREFIX = re.compile(
    r"^(NASDAQ|NYSE|AMEX|CBOE|OTC|OTCMKTS|ARCA|BATS|NYSEARCA|NYSEAMERICAN|NASDAQGS|NASDAQGM|NASDAQCM):",
    re.IGNORECASE,
)
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")
_SKIP_TOKENS = {
    "SYMBOL",
    "TICKER",
    "NAME",
    "PRICE",
    "VOLUME",
    "CHANGE",
    "CHG",
    "CHG%",
    "VOL",
    "MARKET",
    "CAP",
    "SECTOR",
    "INDUSTRY",
    "RATING",
    "DESC",
    "DESCRIPTION",
    "CLOSE",
    "OPEN",
    "HIGH",
    "LOW",
    "TIME",
    "DATE",
    "STOCK",
    "STOCKS",
    "FILTER",
    "INC",
    "CORP",
    "LTD",
    "PLC",
    "CLASS",
    "ETF",
    "FUND",
}


def empty_slots() -> dict[str, list[str]]:
    return {SLOT_PRE: [], SLOT_RTH: [], SLOT_POST: []}


def parse_screener_paste(raw: str, *, cap: int | None = None) -> dict[str, Any]:
    """
    Accept TradingView screener copy: commas, newlines, tabs, NASDAQ:AAPL, table rows.
    Returns parsed names plus how many were dropped as junk / over cap.
    """
    limit = int(cap if cap is not None else room3_watcher.MAX_NAMES)
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    found: list[str] = []
    seen: set[str] = set()
    junk = 0
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            cells = [line.split("\t")[0]]
        else:
            cells = [c.strip() for c in re.split(r"[,;|]+", line) if c.strip()]
        for cell in cells:
            # Table leftover like "AAPL Apple Inc" → first word
            token = cell.split()[0] if cell.split() else cell
            ticker = _normalize_token(token)
            if not ticker:
                if token and _normalize_token(token) == "":
                    junk += 1
                continue
            if ticker in seen:
                continue
            seen.add(ticker)
            found.append(ticker)
    kept = found[:limit]
    return {
        "tickers": kept,
        "parsed": len(found),
        "kept": len(kept),
        "junk": junk,
        "truncated": max(0, len(found) - len(kept)),
    }


def _normalize_token(raw: str) -> str:
    token = str(raw or "").strip().strip('"').strip("'").upper()
    if not token:
        return ""
    token = token.lstrip("$")
    token = _EXCHANGE_PREFIX.sub("", token)
    token = token.strip()
    if token in _SKIP_TOKENS:
        return ""
    if not _TICKER_RE.match(token):
        return ""
    return token


def set_slot(slots: dict[str, list[str]] | None, slot: str, tickers: list[str]) -> dict[str, list[str]]:
    out = dict(empty_slots())
    if isinstance(slots, dict):
        for key in SLOTS:
            out[key] = list(slots.get(key) or [])
    if slot not in SLOTS:
        return out
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tickers or []:
        t = _normalize_token(str(raw))
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
    out[slot] = cleaned
    return out


HIT_TTL_MINUTES = 90
HITS_TABLE = "room3_screener_hits"


def fetch_live_hits(*, session: str, ttl_minutes: int = HIT_TTL_MINUTES) -> dict[str, Any]:
    """Tickers TradingView pushed in the last ttl_minutes for this session slot."""
    from datetime import datetime, timedelta, timezone

    import requests

    import vault_bridge

    if session not in SLOTS:
        return {"tickers": [], "error": "", "hits": 0}
    cfg = vault_bridge.supabase_settings()
    if not cfg.get("ready"):
        return {"tickers": [], "error": "supabase_not_configured", "hits": 0}
    since = (datetime.now(timezone.utc) - timedelta(minutes=int(ttl_minutes))).isoformat()
    url = f"{cfg['url']}/rest/v1/{HITS_TABLE}"
    try:
        resp = requests.get(
            url,
            headers=vault_bridge.supabase_headers(cfg["key"]),
            params={
                "select": "ticker,seen_at",
                "session": f"eq.{session}",
                "seen_at": f"gte.{since}",
                "order": "seen_at.desc",
                "limit": "200",
            },
            timeout=12,
        )
    except Exception as exc:
        return {"tickers": [], "error": str(exc), "hits": 0}
    if not resp.ok:
        return {
            "tickers": [],
            "error": f"HTTP {resp.status_code}: {resp.text[:180]}",
            "hits": 0,
        }
    rows = resp.json() if resp.text else []
    found: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        t = _normalize_token(str((row or {}).get("ticker") or ""))
        if not t or t in seen:
            continue
        seen.add(t)
        found.append(t)
        if len(found) >= room3_watcher.MAX_NAMES:
            break
    return {"tickers": found, "error": "", "hits": len(found)}


def webhook_url() -> str:
    import vault_bridge

    cfg = vault_bridge.supabase_settings()
    base = str(cfg.get("url") or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/functions/v1/tv-screener"


def active_universe(
    slots: dict[str, list[str]] | None,
    *,
    window: str,
    allowed: list[str] | None,
    screener: list[str] | None = None,
) -> list[str]:
    """Built-in screener first; manual paste slot is backup."""
    if window not in SLOTS:
        return []
    if window not in set(allowed or []):
        return []
    cap = room3_watcher.MAX_NAMES
    if screener:
        out: list[str] = []
        seen: set[str] = set()
        for raw in screener:
            t = _normalize_token(str(raw))
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= cap:
                return out
        if out:
            return out
    names = list((slots or {}).get(window) or [])
    return names[:cap]


def slot_label(slot: str) -> str:
    return {
        SLOT_PRE: "Pre-market",
        SLOT_RTH: "Market hours",
        SLOT_POST: "Post-market",
    }.get(slot, slot)
