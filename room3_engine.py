"""
Room 3 execution core — gates + auto signal path.

Intended loop:
  session filter → screener → maps → matrix DNA match → gated Alpaca entry → hold → exit → log

You supervise. The engine fires. No manual ticket desk.
"""

from __future__ import annotations

import os
import time as _time
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
    elif intent_l == "entry" and session_window not in allowed:
        reasons.append(f"{session_label(session_window)} filter is off")
    # Exits: a live trade may continue pre → RTH → post the same day.
    # Overnight (closed) still blocks.

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

    def _opt_float(key: str) -> float | None:
        raw = signal.get(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    alpaca_px = room3_alpaca.fetch_latest_price(symbol, paper=paper)
    ref = alpaca_px or _opt_float("ref_price") or _opt_float("entry_price")
    tf = str(signal.get("timeframe") or "")
    style = str(signal.get("order_style") or "").strip().lower()
    if style not in ("market", "limit"):
        import room3_recipes

        style = room3_recipes.order_style_for(
            str(signal.get("strategy") or ""),
            tf,
            layout_id=str(signal.get("layout_id") or ""),
        )
    prefer_limit = style == "limit"
    result = room3_alpaca.place_market_order(
        symbol,
        side,
        qty,
        paper=paper,
        limit_price=_opt_float("limit_price"),
        ref_price=ref,
        prefer_limit=prefer_limit,
    )
    result = dict(result)
    result["intent"] = intent
    result["strategy"] = str(signal.get("strategy") or "matrix")
    result["timeframe"] = str(signal.get("timeframe") or "—")
    result["layout_id"] = str(signal.get("layout_id") or "")
    result["letter"] = str(signal.get("letter") or "")
    result["lot_id"] = str(signal.get("lot_id") or "")
    result["add_lot"] = bool(signal.get("add_lot"))
    result["scale_in"] = bool(signal.get("scale_in"))
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


class lots:
    """Alpaca is one pile per ticker. App lots are per letter+TF so a second letter can add and peel."""

    @staticmethod
    def letter_token(layout_id: str = "", strategy: str = "") -> str:
        strat = str(strategy or "").strip()
        if strat and strat not in ("—", "-", "matrix", "Alpaca"):
            return strat
        layout = str(layout_id or "").strip()
        if layout and layout not in ("—", "-", "NEW_LAYOUT"):
            return layout
        return ""

    @staticmethod
    def _rows(session_state: Any) -> list[dict[str, Any]]:
        if session_state is None:
            return []
        try:
            rows = session_state.get("room3_lots")
        except Exception:
            return []
        if not isinstance(rows, list):
            return []
        return rows

    @staticmethod
    def save_lots(session_state: Any, rows: list[dict[str, Any]]) -> None:
        if session_state is None:
            return
        try:
            session_state.room3_lots = list(rows)[-80:]
        except Exception:
            pass

    @staticmethod
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
        for row in lots._rows(session_state):
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "open") != "open":
                continue
            try:
                if abs(float(row.get("qty") or 0)) < 1:
                    continue
            except (TypeError, ValueError):
                continue
            if sym and str(row.get("ticker") or "").upper() != sym:
                continue
            if want_tf and str(row.get("tf") or "") != want_tf:
                continue
            if want_letter and str(row.get("letter") or "") != want_letter:
                continue
            out.append(row)
        return out

    @staticmethod
    def lot_qty(
        session_state: Any,
        ticker: str,
        *,
        tf: str = "",
        letter: str = "",
    ) -> float:
        return sum(
            abs(float(r.get("qty") or 0))
            for r in lots.open_lots(session_state, ticker, tf=tf, letter=letter)
        )

    @staticmethod
    def find_lot(session_state: Any, lot_id: str) -> dict[str, Any] | None:
        lid = str(lot_id or "").strip()
        if not lid:
            return None
        for row in lots._rows(session_state):
            if str(row.get("id") or "") == lid:
                return row
        return None

    @staticmethod
    def append_lot(session_state: Any, payload: dict[str, Any]) -> dict[str, Any]:
        ticker = str(payload.get("ticker") or "").upper()
        tf = str(payload.get("tf") or payload.get("timeframe") or "").strip()
        letter = lots.letter_token(
            str(payload.get("layout_id") or ""),
            str(payload.get("strategy") or ""),
        )
        qty = abs(float(payload.get("qty") or 0))
        existing = lots.open_lots(session_state, ticker, tf=tf, letter=letter)
        if existing and qty > 0:
            row = existing[0]
            row["qty"] = abs(float(row.get("qty") or 0)) + qty
            lots.save_lots(session_state, lots._rows(session_state))
            return row
        row = {
            "id": str(payload.get("id") or f"{ticker}-{tf}-{letter}-{int(_time.time() * 1000)}"),
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
        rows = lots._rows(session_state)
        rows.append(row)
        lots.save_lots(session_state, rows)
        return row

    @staticmethod
    def _label_queue(session_state: Any) -> list[dict[str, Any]]:
        if session_state is None:
            return []
        try:
            rows = session_state.get("room3_lot_close_labels")
        except Exception:
            return []
        if not isinstance(rows, list):
            return []
        return rows

    @staticmethod
    def queue_close_label(session_state: Any, lot_row: dict[str, Any] | None) -> None:
        """Keep TF+letter after a peel/flatten so review/log do not inherit the live stamp."""
        if session_state is None or not isinstance(lot_row, dict):
            return
        ticker = str(lot_row.get("ticker") or "").upper()
        if not ticker:
            return
        letter = str(lot_row.get("letter") or lot_row.get("strategy") or "").strip()
        tf = str(lot_row.get("tf") or lot_row.get("timeframe") or "").strip()
        payload = {
            "ticker": ticker,
            "tf": tf,
            "letter": letter,
            "layout_id": str(lot_row.get("layout_id") or ""),
            "strategy": str(lot_row.get("strategy") or letter),
            "qty": abs(float(lot_row.get("qty") or 0)),
            "entry_px": float(lot_row.get("entry_px") or lot_row.get("entry_price") or 0),
            "lot_id": str(lot_row.get("id") or ""),
            "entry_match_pct": int(lot_row.get("entry_match_pct") or 0),
            "used": False,
        }
        q = lots._label_queue(session_state)
        q.append(payload)
        try:
            session_state.room3_lot_close_labels = q[-80:]
        except Exception:
            pass

    @staticmethod
    def take_close_label(
        session_state: Any,
        ticker: str,
        *,
        qty: float = 0.0,
        lot_id: str = "",
        letter: str = "",
        tf: str = "",
    ) -> dict[str, Any] | None:
        """Pop the unused close-label that best matches this broker/FIFO row."""
        if session_state is None:
            return None
        sym = str(ticker or "").upper()
        want_id = str(lot_id or "").strip()
        want_letter = str(letter or "").strip()
        want_tf = str(tf or "").strip()
        if want_letter in ("", "—", "-", "Alpaca", "matrix") or want_letter.upper().startswith(
            "ALPACA"
        ):
            want_letter = ""
        if want_tf in ("", "—", "-", "MKT") or want_tf.upper().startswith("ALPACA"):
            want_tf = ""
        want_qty = abs(float(qty or 0))
        q = lots._label_queue(session_state)
        best_i = -1
        best_score = -1
        for i, row in enumerate(q):
            if not isinstance(row, dict) or row.get("used"):
                continue
            if str(row.get("ticker") or "").upper() != sym:
                continue
            score = 0
            if want_id and str(row.get("lot_id") or "") == want_id:
                score += 8
            if want_letter and str(row.get("letter") or "") == want_letter:
                score += 4
            if want_tf and str(row.get("tf") or "") == want_tf:
                score += 2
            row_qty = abs(float(row.get("qty") or 0))
            if want_qty > 0 and row_qty > 0 and abs(row_qty - want_qty) <= max(1.0, 0.05 * want_qty):
                score += 3
            # Ticker-only so an Alpaca FIFO close still gets the next unused letter.
            score += 1
            if score > best_score:
                best_score = score
                best_i = i
        if best_i < 0 or best_score < 1:
            return None
        q[best_i]["used"] = True
        try:
            session_state.room3_lot_close_labels = q[-80:]
        except Exception:
            pass
        return dict(q[best_i])

    @staticmethod
    def _placeholder_tf(raw: str) -> bool:
        t = str(raw or "").strip()
        return t in ("", "—", "-", "MKT", "Alpaca") or t.upper().startswith("ALPACA")

    @staticmethod
    def _placeholder_strat(raw: str) -> bool:
        s = str(raw or "").strip()
        return s in ("", "—", "-", "Alpaca", "matrix", "Alpaca BUY", "Alpaca SELL") or s.upper().startswith(
            "ALPACA"
        )

    @staticmethod
    def row_needs_identity(row: dict[str, Any] | None) -> bool:
        if not isinstance(row, dict):
            return False
        tf = str(row.get("matrix_timeframe") or row.get("timeframe") or "").strip()
        strat = str(row.get("matrix_strategy") or row.get("strategy") or "").strip()
        return lots._placeholder_tf(tf) or lots._placeholder_strat(strat)

    @staticmethod
    def _exit_is_fresh(row: dict[str, Any], window_sec: int = 180) -> bool:
        text = str(row.get("exit_time") or "").strip()
        if not text or text in ("—", "-"):
            return False
        try:
            parts = text.replace(".", ":").split(":")
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
        except (TypeError, ValueError, IndexError):
            return False
        now = datetime.now(ET)
        then = now.replace(hour=h, minute=m, second=s, microsecond=0)
        return abs((now - then).total_seconds()) <= window_sec

    @staticmethod
    def _apply_label(row: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(row or {})
        if not isinstance(label, dict):
            return out
        letter = str(label.get("letter") or label.get("strategy") or "").strip()
        tf = str(label.get("tf") or label.get("timeframe") or "").strip()
        layout = str(label.get("layout_id") or "").strip()
        if letter and not lots._placeholder_strat(letter):
            out["strategy"] = letter
            out["matrix_strategy"] = letter
            out["letter"] = letter
        if tf and not lots._placeholder_tf(tf):
            out["timeframe"] = tf
            out["matrix_timeframe"] = tf
        if layout and layout not in ("—", "-", "NEW_LAYOUT", "PURGATORY_PENDING"):
            out["layout_id"] = layout
            out["matrix_layout"] = layout
        if label.get("lot_id") and not out.get("lot_id"):
            out["lot_id"] = label.get("lot_id")
        if not lots.row_needs_identity(out):
            out["identity_frozen"] = True
        return out

    @staticmethod
    def remember_entry_fill(session_state: Any, payload: dict[str, Any] | None) -> None:
        """Keep buy TF/letter so a later Alpaca FIFO close can stamp the same lot."""
        if session_state is None or not isinstance(payload, dict):
            return
        ticker = str(payload.get("ticker") or payload.get("symbol") or "").upper()
        if not ticker:
            return
        try:
            cache = dict(session_state.get("room3_fill_meta_by_ticker") or {})
        except Exception:
            cache = {}
        entry = dict(cache.get(ticker) or {})
        letter = lots.letter_token(
            str(payload.get("layout_id") or ""),
            str(payload.get("strategy") or payload.get("letter") or ""),
        )
        tf = str(payload.get("tf") or payload.get("timeframe") or "").strip()
        try:
            qty = abs(float(payload.get("qty") or 0))
        except (TypeError, ValueError):
            qty = 0.0
        fills = list(entry.get("fills") or [])
        fills.append(
            {
                "strategy": letter,
                "letter": letter,
                "timeframe": tf,
                "tf": tf,
                "qty": qty,
                "entry_order_id": str(payload.get("order_id") or payload.get("entry_order_id") or ""),
                "lot_id": str(payload.get("lot_id") or ""),
                "layout_id": str(payload.get("layout_id") or ""),
            }
        )
        entry["fills"] = fills[-24:]
        if letter:
            entry["strategy"] = letter
        if tf:
            entry["timeframe"] = tf
        cache[ticker] = entry
        try:
            session_state.room3_fill_meta_by_ticker = cache
        except Exception:
            pass

    @staticmethod
    def _label_from_fill_cache(session_state: Any, row: dict[str, Any]) -> dict[str, Any] | None:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or session_state is None:
            return None
        try:
            cache = (session_state.get("room3_fill_meta_by_ticker") or {}).get(ticker) or {}
        except Exception:
            cache = {}
        fills = list(cache.get("fills") or [])
        oid = str(row.get("entry_order_id") or "").strip()
        if oid:
            for fill in reversed(fills):
                if not isinstance(fill, dict):
                    continue
                if str(fill.get("entry_order_id") or "").strip() == oid:
                    return fill
        try:
            want_qty = abs(float(row.get("qty") or 0))
        except (TypeError, ValueError):
            want_qty = 0.0
        for fill in reversed(fills):
            if not isinstance(fill, dict) or fill.get("applied_close_id"):
                continue
            try:
                fq = abs(float(fill.get("qty") or 0))
            except (TypeError, ValueError):
                fq = 0.0
            letter = str(fill.get("letter") or fill.get("strategy") or "").strip()
            tf = str(fill.get("timeframe") or fill.get("tf") or "").strip()
            if want_qty > 0 and fq > 0 and abs(fq - want_qty) <= max(1.0, 0.05 * want_qty):
                if letter and not lots._placeholder_strat(letter) and tf and not lots._placeholder_tf(tf):
                    fill["applied_close_id"] = str(row.get("id") or "")
                    try:
                        full = dict(session_state.get("room3_fill_meta_by_ticker") or {})
                        full[ticker] = dict(cache)
                        full[ticker]["fills"] = fills
                        session_state.room3_fill_meta_by_ticker = full
                    except Exception:
                        pass
                    return fill
        return None

    @staticmethod
    def _peel_open_lot_label(
        session_state: Any, ticker: str, qty: float
    ) -> dict[str, Any] | None:
        opens = lots.open_lots(session_state, ticker)
        if not opens:
            return None
        pick = None
        want = abs(float(qty or 0))
        for lot in opens:
            try:
                lq = abs(float(lot.get("qty") or 0))
            except (TypeError, ValueError):
                lq = 0.0
            if want > 0 and lq > 0 and abs(lq - want) <= max(1.0, 0.05 * want):
                pick = lot
                break
        if pick is None:
            pick = opens[0]
        closed = lots.close_lot(session_state, str(pick.get("id") or ""))
        if not closed:
            return None
        return lots.take_close_label(
            session_state,
            ticker,
            qty=abs(float(pick.get("qty") or qty or 0)),
            lot_id=str(pick.get("id") or ""),
            letter=str(pick.get("letter") or pick.get("strategy") or ""),
            tf=str(pick.get("tf") or ""),
        )

    @staticmethod
    def stamp_close_row(
        session_state: Any,
        row: dict[str, Any] | None,
        *,
        peel_open: bool = False,
    ) -> dict[str, Any]:
        """Put TF + letter on an Alpaca FIFO close. Never inherit the live watch-book stamp."""
        out = dict(row or {})
        if not lots.row_needs_identity(out):
            return out
        fill = lots._label_from_fill_cache(session_state, out)
        if fill:
            out = lots._apply_label(out, fill)
            if not lots.row_needs_identity(out):
                return out
        ticker = str(out.get("ticker") or "").upper()
        try:
            qty = abs(float(out.get("qty") or 0))
        except (TypeError, ValueError):
            qty = 0.0
        letter = str(out.get("letter") or "").strip()
        if lots._placeholder_strat(letter):
            letter = ""
        tf = str(out.get("timeframe") or "").strip()
        if lots._placeholder_tf(tf):
            tf = ""
        label = lots.take_close_label(
            session_state,
            ticker,
            qty=qty,
            lot_id=str(out.get("lot_id") or ""),
            letter=letter,
            tf=tf,
        )
        if label is None and peel_open and lots._exit_is_fresh(out):
            label = lots._peel_open_lot_label(session_state, ticker, qty)
        if label:
            out = lots._apply_label(out, label)
        return out

    @staticmethod
    def stamp_unlabeled_closes(session_state: Any, *, peel_open: bool = False) -> int:
        """Retry unlabeled history after close_lot queues labels. Pulse must do this — UI paint is not enough."""
        if session_state is None:
            return 0
        try:
            hist = list(session_state.get("room3_trade_history") or [])
        except Exception:
            return 0
        n = 0
        for row in hist:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "").lower()
            closed = "closed" in status or "closing" in status or bool(row.get("exit_price") is not None)
            if not closed:
                continue
            if not lots.row_needs_identity(row):
                continue
            stamped = lots.stamp_close_row(session_state, row, peel_open=peel_open)
            if not lots.row_needs_identity(stamped):
                row.update(stamped)
                n += 1
        if n:
            try:
                session_state.room3_trade_history = hist
            except Exception:
                pass
        return n

    @staticmethod
    def unused_close_labels(session_state: Any, ticker: str = "") -> list[dict[str, Any]]:
        sym = str(ticker or "").upper()
        out = []
        for row in lots._label_queue(session_state):
            if not isinstance(row, dict) or row.get("used"):
                continue
            if sym and str(row.get("ticker") or "").upper() != sym:
                continue
            out.append(dict(row))
        return out

    @staticmethod
    def close_lot(session_state: Any, lot_id: str) -> dict[str, Any] | None:
        row = lots.find_lot(session_state, lot_id)
        if not row:
            return None
        if str(row.get("status") or "open") == "open":
            lots.queue_close_label(session_state, row)
        row["status"] = "closed"
        return row

    @staticmethod
    def close_lots_for_ticker(session_state: Any, ticker: str) -> int:
        n = 0
        for row in lots.open_lots(session_state, ticker):
            lots.queue_close_label(session_state, row)
            row["status"] = "closed"
            n += 1
        return n

    @staticmethod
    def reconcile_to_broker(session_state: Any, positions: list | None) -> int:
        """Broker pile is truth. Ghost lots (qty 0 or leftover after exits) leave the open book."""
        broker: dict[str, float] = {}
        for pos in positions or []:
            if not isinstance(pos, dict):
                continue
            ticker = str(pos.get("ticker") or pos.get("symbol") or "").upper()
            if not ticker:
                continue
            try:
                qty = abs(float(pos.get("qty") or 0))
            except (TypeError, ValueError):
                qty = 0.0
            broker[ticker] = broker.get(ticker, 0.0) + qty
        n = 0
        seen: set[str] = set()
        for row in list(lots.open_lots(session_state)):
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                seen.add(ticker)
        for ticker in seen | set(broker):
            want = float(broker.get(ticker) or 0)
            opens = lots.open_lots(session_state, ticker)
            if want < 1:
                if opens:
                    n += lots.close_lots_for_ticker(session_state, ticker)
                continue
            lot_sum = sum(abs(float(r.get("qty") or 0)) for r in opens)
            if lot_sum <= want + 1e-9:
                continue
            # Oldest lots first — those should already have exited.
            for row in opens:
                lot_sum = sum(
                    abs(float(r.get("qty") or 0))
                    for r in lots.open_lots(session_state, ticker)
                )
                if lot_sum <= want + 1e-9:
                    break
                try:
                    q = abs(float(row.get("qty") or 0))
                except (TypeError, ValueError):
                    q = 0.0
                extra = lot_sum - want
                if q <= extra + 1e-9:
                    lots.close_lot(session_state, str(row.get("id") or ""))
                    n += 1
                else:
                    row["qty"] = max(0.0, q - extra)
                    n += 1
                    break
            lots.save_lots(session_state, lots._rows(session_state))
        return n

    @staticmethod
    def peel_qty(
        session_state: Any,
        ticker: str,
        *,
        tf: str,
        letter: str,
        fallback: float = 0.0,
    ) -> float:
        qty = lots.lot_qty(session_state, ticker, tf=tf, letter=letter)
        if qty > 0:
            return qty
        return abs(float(fallback or 0))
