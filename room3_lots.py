"""
Room 3 lot ledger.

Alpaca is one share pile per ticker. The app keeps one lot per letter+TF
(qty, entry, exit). A second hot letter adds. That letter’s exit peels its qty.
"""

from __future__ import annotations

import time
from typing import Any


def letter_token(layout_id: str = "", strategy: str = "") -> str:
    strat = str(strategy or "").strip()
    if strat and strat not in ("—", "-", "matrix", "Alpaca"):
        return strat
    layout = str(layout_id or "").strip()
    if layout and layout not in ("—", "-", "NEW_LAYOUT"):
        return layout
    return ""


def _ss_lots(session_state: Any) -> list[dict[str, Any]]:
    if session_state is None:
        return []
    try:
        rows = session_state.get("room3_lots")
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    return rows


def save_lots(session_state: Any, rows: list[dict[str, Any]]) -> None:
    if session_state is None:
        return
    try:
        session_state.room3_lots = list(rows)[-80:]
    except Exception:
        pass


def open_lots(
    session_state: Any,
    ticker: str = "",
    *,
    tf: str = "",
    letter: str = "",
) -> list[dict[str, Any]]:
    sym = str(ticker or "").upper()
    want_tf = str(tf or "").strip()
    want_letter = str(letter or "").strip()
    out = []
    for row in _ss_lots(session_state):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open") != "open":
            continue
        if sym and str(row.get("ticker") or "").upper() != sym:
            continue
        if want_tf and str(row.get("tf") or "") != want_tf:
            continue
        if want_letter and str(row.get("letter") or "") != want_letter:
            continue
        out.append(row)
    return out


def lot_qty(
    session_state: Any,
    ticker: str,
    *,
    tf: str = "",
    letter: str = "",
) -> float:
    return sum(abs(float(r.get("qty") or 0)) for r in open_lots(session_state, ticker, tf=tf, letter=letter))


def find_lot(session_state: Any, lot_id: str) -> dict[str, Any] | None:
    lid = str(lot_id or "").strip()
    if not lid:
        return None
    for row in _ss_lots(session_state):
        if str(row.get("id") or "") == lid:
            return row
    return None


def append_lot(session_state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(payload.get("ticker") or "").upper()
    tf = str(payload.get("tf") or payload.get("timeframe") or "").strip()
    letter = letter_token(str(payload.get("layout_id") or ""), str(payload.get("strategy") or ""))
    qty = abs(float(payload.get("qty") or 0))
    existing = open_lots(session_state, ticker, tf=tf, letter=letter)
    if existing and qty > 0:
        row = existing[0]
        row["qty"] = abs(float(row.get("qty") or 0)) + qty
        save_lots(session_state, _ss_lots(session_state))
        return row
    row = {
        "id": str(payload.get("id") or f"{ticker}-{tf}-{letter}-{int(time.time() * 1000)}"),
        "ticker": ticker,
        "tf": tf,
        "letter": letter,
        "layout_id": str(payload.get("layout_id") or ""),
        "strategy": str(payload.get("strategy") or letter),
        "qty": qty,
        "entry_px": float(payload.get("entry_px") or payload.get("entry_price") or 0),
        "entry_match_pct": int(payload.get("entry_match_pct") or 0),
        "structural_move_pct": float(payload.get("structural_move_pct") or 0),
        "status": "open",
    }
    rows = _ss_lots(session_state)
    rows.append(row)
    save_lots(session_state, rows)
    return row


def close_lot(session_state: Any, lot_id: str) -> dict[str, Any] | None:
    row = find_lot(session_state, lot_id)
    if not row:
        return None
    row["status"] = "closed"
    return row


def close_lots_for_ticker(session_state: Any, ticker: str) -> int:
    n = 0
    for row in open_lots(session_state, ticker):
        row["status"] = "closed"
        n += 1
    return n


def peel_qty(
    session_state: Any,
    ticker: str,
    *,
    tf: str,
    letter: str,
    fallback: float = 0.0,
) -> float:
    qty = lot_qty(session_state, ticker, tf=tf, letter=letter)
    if qty > 0:
        return qty
    return abs(float(fallback or 0))
