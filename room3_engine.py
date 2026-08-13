"""
Room 3 execution core — gates + auto signal path.

Intended loop (filters/scan wire next):
  session window → matrix signal → gated Alpaca entry → hold → exit signal → Alpaca exit

You supervise. The engine fires. No manual ticket desk.
"""

from __future__ import annotations

import os
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import room3_alpaca
import room3_bridge

ET = ZoneInfo("America/New_York")

SESSION_PRE = "premarket"
SESSION_RTH = "rth"
SESSION_POST = "postmarket"
SESSION_CLOSED = "closed"

# Hard fence: live Alpaca/IBKR orders stay off until you deliberately enable.
LIVE_ORDERS_ENABLED = False


def is_cloud_host() -> bool:
    """True on Streamlit Community Cloud (and similar) — Mac stays cooler when you use this URL."""
    if str(os.environ.get("STREAMLIT_RUNTIME_ENVIRONMENT") or "").lower() == "cloud":
        return True
    if str(os.environ.get("STREAMLIT_SHARING_MODE") or "").strip():
        return True
    try:
        from pathlib import Path

        if Path("/mount/src").exists():
            return True
    except Exception:
        pass
    return False


def hosting_label() -> str:
    return "Cloud host" if is_cloud_host() else "Local Mac"


def detect_session_window(now: datetime | None = None) -> str:
    """US equity session bucket in Eastern time."""
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    if now.weekday() >= 5:
        return SESSION_CLOSED
    t = now.time()
    if time(4, 0) <= t < time(9, 30):
        return SESSION_PRE
    if time(9, 30) <= t < time(16, 0):
        return SESSION_RTH
    if time(16, 0) <= t < time(20, 0):
        return SESSION_POST
    return SESSION_CLOSED


def session_label(window: str) -> str:
    return {
        SESSION_PRE: "Pre-market",
        SESSION_RTH: "Market hours",
        SESSION_POST: "Post-market",
        SESSION_CLOSED: "Closed",
    }.get(window, window)


def matrix_handshake(session_state: Any) -> dict[str, Any]:
    """Delegate to room3_bridge — only approved Room 2 keys, read-only."""
    return room3_bridge.matrix_snapshot(session_state)


def deployed_notional(open_positions: list[dict] | None) -> float:
    total = 0.0
    for row in open_positions or []:
        qty = abs(float(row.get("qty") or 0))
        px = float(row.get("last_price") or row.get("entry_price") or 0)
        if qty and px:
            total += qty * px
            continue
        # fallback if dollar value already present
        total += abs(float(row.get("position_usd") or 0))
    return round(total, 2)


def evaluate_execution_gates(
    *,
    mode: str,
    broker: str,
    broker_connected: bool,
    engine_armed: bool,
    kill_flat: bool,
    pause_entries: bool,
    intent: str,
    session_window: str,
    allowed_sessions: set[str] | list[str],
    tradable_today: float,
    deployed: float,
    order_notional: float = 0.0,
    live_orders_enabled: bool = LIVE_ORDERS_ENABLED,
) -> dict[str, Any]:
    """
    Absolute checks before any auto order.
    intent: entry | exit
    """
    reasons: list[str] = []
    intent_l = str(intent or "").strip().lower()
    if intent_l not in ("entry", "exit"):
        return {"ok": False, "reasons": ["intent must be entry or exit"]}

    if not broker_connected:
        reasons.append("broker not connected")
    if broker != "alpaca":
        reasons.append("auto hose is Alpaca-only for now (IBKR idle)")
    if not engine_armed:
        reasons.append("engine disarmed — arm auto execution")
    if kill_flat:
        reasons.append("kill switch FLAT — all auto orders blocked")

    if str(mode or "") == "live":
        if not live_orders_enabled:
            reasons.append("live orders hard-disabled (paper-only path)")
    elif str(mode or "") != "paper":
        reasons.append("unknown execution mode")

    allowed = set(allowed_sessions or [])
    if session_window == SESSION_CLOSED:
        reasons.append("market session closed")
    elif session_window not in allowed:
        reasons.append(f"{session_label(session_window)} filter is off")

    if intent_l == "entry":
        if pause_entries:
            reasons.append("entries paused")
        room = max(0.0, float(tradable_today) - float(deployed))
        if float(order_notional or 0) > 0 and float(order_notional) > room + 1e-6:
            reasons.append(
                f"notional ${float(order_notional):,.2f} exceeds remaining tradable ${room:,.2f}"
            )
        if float(tradable_today) <= 0:
            reasons.append("tradable today is $0")

    return {"ok": not reasons, "reasons": reasons, "session": session_window}


def execute_matrix_signal(
    signal: dict[str, Any],
    *,
    paper: bool = True,
    gates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fire one matrix signal through Alpaca after gates pass.

    signal keys:
      intent: entry|exit
      side: buy|sell  (exit long → sell; exit short → buy)
      symbol / ticker
      qty
      strategy (optional)
      timeframe (optional)
      notional (optional — for entry capital check)
    """
    if gates is not None and not gates.get("ok"):
        return {
            "ok": False,
            "blocked": True,
            "error": "; ".join(gates.get("reasons") or ["blocked by gates"]),
            "gates": gates,
        }

    symbol = str(signal.get("symbol") or signal.get("ticker") or "").strip().upper()
    side = str(signal.get("side") or "").strip().lower()
    intent = str(signal.get("intent") or "").strip().lower()
    try:
        qty = float(signal.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0.0

    if intent == "exit" and not side:
        # default: flatten long
        side = "sell"
    if intent == "entry" and not side:
        side = "buy"

    result = room3_alpaca.place_market_order(symbol, side, qty, paper=paper)
    result = dict(result)
    result["intent"] = intent
    result["strategy"] = str(signal.get("strategy") or "matrix")
    result["timeframe"] = str(signal.get("timeframe") or "—")
    result["blocked"] = False
    return result


def runtime_health() -> dict[str, Any]:
    """Boring startup checks so Room 3 fails loudly, not mysteriously."""
    issues: list[str] = []
    try:
        import alpaca.trading.client  # noqa: F401
    except ImportError:
        issues.append("alpaca-py missing in this Python — use TradingApprentice/.venv")
    creds = room3_alpaca.load_alpaca_credentials(paper=True)
    if not creds.get("key") or not creds.get("secret"):
        issues.append("Alpaca paper keys missing in .streamlit/secrets.toml")
    return {
        "ok": not issues,
        "issues": issues,
        "endpoint": creds.get("endpoint") or "",
        "key_prefix": (creds.get("key") or "")[:4],
    }
