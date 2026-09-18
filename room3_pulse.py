"""
Room 3 Cloud pulse — keeps detect/fire/hold/exit running after the operator tab dies.

Streamlit fragments stop when the laptop closes. This process-level loop does not.
Arm + belt + size are read from the last operator write. Kill / Disarm stops it.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import room3_alpaca
import room3_bridge
import room3_engine
import room3_screener
import room3_watcher

ET = ZoneInfo("America/New_York")
PULSE_SEC = 15
FILL_PULSE_SEC = 60.0

OPERATOR_KEYS = (
    "room3_engine_armed",
    "room3_unattended_armed",
    "room3_kill_flat",
    "room3_pause_entries",
    "room3_filter_universe",
    "room3_tradable_today",
    "room3_tradable_pct_ui",
    "room3_tradable_operator_set",
    "room3_allowed_sessions",
    "room3_execution_mode",
    "room3_broker",
)

RUNTIME_KEYS = (
    "room3_watch_book",
    "room3_lots",
    "room3_lot_close_labels",
    "room3_open_positions",
    "room3_trade_history",
    "room3_fill_meta_by_ticker",
    "room3_account_equity",
    "room3_broker_equity",
    "room3_broker_truth",
    "room3_alpaca_status",
    "room3_last_broker_sync",
    "room3_worker_note",
    "room3_worker_error",
    "room3_cash_claimed",
)

_BAG: "PulseState | None" = None
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()


class PulseState:
    """Duck-types Streamlit session_state enough for watcher / lots / engine."""

    def __init__(self, data: dict[str, Any] | None = None):
        object.__setattr__(self, "_d", dict(data or {}))

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        return self._d.pop(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._d

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._d[key] = value

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self._d[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        if key == "_d":
            object.__setattr__(self, key, value)
            return
        self._d[key] = value

    def as_dict(self) -> dict[str, Any]:
        return self._d


def bag() -> PulseState:
    global _BAG
    if _BAG is None:
        _BAG = PulseState()
        _hydrate_bag_from_disk(_BAG)
    return _BAG


def worker_is_running() -> bool:
    t = _THREAD
    return bool(t is not None and t.is_alive())


def worker_owns_execution() -> bool:
    return room3_engine.is_cloud_host() and worker_is_running()


def unattended_armed_from_disk() -> bool:
    snap = room3_screener.load_screener_snapshot() or {}
    return bool(snap.get("unattended_armed"))


def mark_unattended(ss: Any) -> None:
    """Arm + names on the belt = keep going if the tab dies. Disarm/Kill clears it."""
    armed = bool(ss.get("room3_engine_armed"))
    killed = bool(ss.get("room3_kill_flat"))
    belt = [str(t).upper() for t in (ss.get("room3_filter_universe") or []) if str(t).strip()]
    flag = bool(armed and not killed and belt)
    b = bag()
    bag_live = bool(
        b.get("room3_unattended_armed")
        or (b.get("room3_engine_armed") and (b.get("room3_filter_universe") or []))
    )
    # A brand-new Streamlit session defaults DISARMED. Do not let that
    # kill a Cloud pulse the operator already left running.
    session_fresh_disarm = (
        (not armed) and (not killed) and (not bool(ss.get("room3_unattended_armed")))
    )
    if bag_live and session_fresh_disarm:
        return
    try:
        ss.room3_unattended_armed = flag
    except Exception:
        ss["room3_unattended_armed"] = flag
    for k in OPERATOR_KEYS:
        try:
            if k in ss:
                b[k] = ss.get(k)
        except Exception:
            val = getattr(ss, k, None)
            if val is not None:
                b[k] = val
    b.room3_unattended_armed = flag
    b.room3_engine_armed = armed and not killed


def _pulse_day_key() -> str:
    now = datetime.now(ET)
    return (now - timedelta(days=1) if now.hour < 4 else now).strftime("%Y-%m-%d")


def stamp_belt_and_maps(ss: Any, *, force: bool = False) -> None:
    """× chips and white map rows stay the same set. Worker must not keep one without the other."""
    uni = [str(t).upper() for t in (ss.get("room3_filter_universe") or []) if str(t).strip()]
    b = bag()
    today = _pulse_day_key()
    worker_uni = [str(t).upper() for t in (b.get("room3_filter_universe") or []) if str(t).strip()]
    worker_snap = {
        "filter_universe": worker_uni,
        "filter_universe_day_key": str(b.get("filter_universe_day_key") or ""),
        "watch_book": b.get("room3_watch_book") or {},
        "tradable_day_key": str(b.get("tradable_day_key") or ""),
        "session_day_key": str(b.get("session_day_key") or ""),
    }
    armed = bool(ss.get("room3_engine_armed"))
    killed = bool(ss.get("room3_kill_flat"))
    session_fresh_disarm = (
        (not armed) and (not killed) and (not bool(ss.get("room3_unattended_armed")))
    )
    bag_live = bool(
        b.get("room3_unattended_armed")
        or (b.get("room3_engine_armed") and worker_uni)
    )
    stale_worker = room3_watcher.belt_snapshot_is_stale(worker_snap, today)
    if not force and bag_live and session_fresh_disarm and not stale_worker:
        return
    book = dict(ss.get("room3_watch_book") or room3_watcher.empty_book())
    book["keep_tickers"] = sorted(_open_syms(ss))
    book = room3_watcher.set_filter_universe(book, uni)
    try:
        ss.room3_watch_book = book
    except Exception:
        try:
            ss["room3_watch_book"] = book
        except Exception:
            pass
    b.room3_filter_universe = uni
    b.room3_watch_book = book
    b.filter_universe_day_key = today
    # Heartbeat must not rewrite the snapshot every 15s — that froze the whole Cloud app.
    # Drop / Clear / day-roll pass force=True so Friday maps actually leave disk.
    if force and worker_owns_execution():
        persist_bag(b)


def sync_operator_into_worker(ss: Any) -> None:
    mark_unattended(ss)
    if not worker_owns_execution():
        return
    b = bag()
    for k in RUNTIME_KEYS:
        if k in b._d:
            try:
                setattr(ss, k, b.get(k))
            except Exception:
                pass


def ensure_worker() -> None:
    """One process-level loop on Cloud. Local Mac still uses the Streamlit fragment."""
    global _THREAD
    if not room3_engine.is_cloud_host():
        return
    bag()
    t = _THREAD
    if t is not None and t.is_alive():
        return
    t = threading.Thread(target=_loop, name="room3-pulse", daemon=True)
    _THREAD = t
    t.start()


def _hydrate_bag_from_disk(ss: PulseState) -> None:
    snap = room3_screener.load_screener_snapshot() or {}
    ss.room3_execution_mode = "paper"
    ss.room3_broker = "alpaca"
    ss.room3_engine_armed = bool(snap.get("unattended_armed"))
    ss.room3_unattended_armed = bool(snap.get("unattended_armed"))
    ss.room3_kill_flat = False
    ss.room3_pause_entries = False
    today_key = _pulse_day_key()
    ss.room3_filter_universe = list(snap.get("filter_universe") or [])
    ss.room3_allowed_sessions = list(
        snap.get("allowed_sessions") or [room3_engine.SESSION_RTH]
    )
    try:
        ss.room3_tradable_today = float(snap.get("tradable_today") or 0)
    except (TypeError, ValueError):
        ss.room3_tradable_today = 0.0
    ss.room3_tradable_operator_set = bool(snap.get("tradable_operator_set"))
    snap_day = str(snap.get("tradable_day_key") or "")
    if snap_day and snap_day != today_key:
        ss.room3_tradable_today = 0.0
        ss.room3_tradable_operator_set = False
    ss.room3_lots = list(snap.get("lots") or [])
    ss.room3_lot_close_labels = list(snap.get("lot_close_labels") or [])
    ss.room3_trade_history = list(snap.get("trade_history") or [])
    ss.room3_fill_meta_by_ticker = dict(snap.get("fill_meta_by_ticker") or {})
    if room3_watcher.belt_snapshot_is_stale(snap, today_key):
        ss.room3_filter_universe = []
        ss.room3_watch_book = room3_watcher.empty_book()
        ss.filter_universe_day_key = today_key
    else:
        book = snap.get("watch_book") if isinstance(snap.get("watch_book"), dict) else {}
        book = dict(book or room3_watcher.empty_book())
        book["keep_tickers"] = []
        uni = list(ss.room3_filter_universe)
        ss.room3_watch_book = room3_watcher.set_filter_universe(book, uni)
        ss.filter_universe_day_key = str(snap.get("filter_universe_day_key") or today_key)
    ss.room3_open_positions = []
    ss.room3_cash_claimed = 0.0
    room3_bridge.ensure_layout_library(ss)


def persist_bag(ss: PulseState) -> None:
    room3_screener.merge_screener_snapshot(
        {
            "filter_universe": list(ss.get("room3_filter_universe") or []),
            "watch_book": room3_watcher.watch_book_for_disk(ss.get("room3_watch_book")),
            "lots": list(ss.get("room3_lots") or []),
            "lot_close_labels": list(ss.get("room3_lot_close_labels") or []),
            "trade_history": list(ss.get("room3_trade_history") or [])[-500:],
            "fill_meta_by_ticker": dict(ss.get("room3_fill_meta_by_ticker") or {}),
            "tradable_today": float(ss.get("room3_tradable_today") or 0),
            "tradable_operator_set": bool(ss.get("room3_tradable_operator_set")),
            "tradable_day_key": _pulse_day_key(),
            "filter_universe_day_key": str(
                ss.get("filter_universe_day_key") or _pulse_day_key()
            ),
            "session_day_key": str(ss.get("session_day_key") or _pulse_day_key()),
            "allowed_sessions": list(ss.get("room3_allowed_sessions") or []),
            "unattended_armed": bool(ss.get("room3_unattended_armed")),
            "engine_armed": bool(ss.get("room3_engine_armed")),
            "last_broker_sync": str(ss.get("room3_last_broker_sync") or ""),
            "broker_closed_sync": ss.get("room3_broker_closed_sync") or {},
        }
    )


def _session_must_be_flat(ss: PulseState) -> bool:
    window = room3_engine.detect_session_window()
    if window == room3_engine.SESSION_CLOSED:
        return True
    allowed = set(ss.get("room3_allowed_sessions") or [])
    return (
        window == room3_engine.SESSION_POST
        and room3_engine.SESSION_POST not in allowed
    )


def _session_trading_allowed(ss: PulseState) -> bool:
    window = room3_engine.detect_session_window()
    if window == room3_engine.SESSION_CLOSED:
        return False
    return window in set(ss.get("room3_allowed_sessions") or [])


def _open_syms(ss: Any) -> set[str]:
    out: set[str] = set()
    for pos in ss.get("room3_open_positions") or []:
        if not isinstance(pos, dict):
            continue
        sym = str(pos.get("symbol") or pos.get("ticker") or "").upper()
        try:
            qty = abs(float(pos.get("qty") or 0))
        except (TypeError, ValueError):
            qty = 0.0
        if sym and qty > 0:
            out.add(sym)
    return out


def _fills_due(ss: PulseState) -> bool:
    last = float(ss.get("_fills_mono") or 0)
    now = time.monotonic()
    if not last:
        ss._fills_mono = now
        return False
    return (now - last) >= FILL_PULSE_SEC


def _sync_alpaca(ss: PulseState, *, paper: bool, include_fills: bool = True) -> dict[str, Any]:
    result = room3_alpaca.probe_alpaca_connection(paper=paper)
    if not result.get("ok"):
        ss.room3_broker_truth = False
        ss.room3_alpaca_status = "waiting"
        return result
    equity = float(result.get("equity") or 0)
    ss.room3_broker_equity = equity
    ss.room3_account_equity = equity
    ss.room3_broker_truth = True
    ss.room3_alpaca_status = "connected"
    ss.room3_open_positions = [
        p
        for p in (room3_alpaca.fetch_open_positions(paper=paper) or [])
        if isinstance(p, dict) and abs(float(p.get("qty") or 0)) >= 1e-9
    ]
    room3_engine.lots.reconcile_to_broker(ss, ss.room3_open_positions)
    room3_engine.lots.heal_lots_from_watch(
        ss, ss.get("room3_watch_book"), ss.room3_open_positions
    )
    if not include_fills:
        now_s = datetime.now(ET).strftime("%H:%M:%S ET")
        ss.room3_last_broker_sync = now_s
        return result
    dbg = room3_alpaca.fetch_closed_trades_today_debug(paper=paper)
    hist = list(ss.get("room3_trade_history") or [])
    seen = {str(r.get("id") or "") for r in hist if isinstance(r, dict)}
    lots = room3_engine.lots
    for row in dbg.get("closed") or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        if rid and rid in seen:
            continue
        stamped = lots.stamp_close_row(ss, dict(row), peel_open=True)
        hist.append(stamped)
        if rid:
            seen.add(rid)
    ss.room3_trade_history = hist[-500:]
    now_s = datetime.now(ET).strftime("%H:%M:%S ET")
    ss.room3_last_broker_sync = now_s
    ss.room3_broker_closed_sync = {
        "fill_events": int(dbg.get("fill_events") or 0),
        "closed_count": int(dbg.get("closed_count") or 0),
        "today_closed_count": int(dbg.get("today_closed_count") or 0),
        "error": str(dbg.get("error") or ""),
        "session_day": str(dbg.get("session_day") or ""),
        "at": now_s,
    }
    ss._fills_mono = time.monotonic()
    return result


def _flatten_open(ss: PulseState, *, paper: bool) -> str:
    """Overnight / Post-off flat. Retry leftover shares. Do not go idle while Alpaca still has a pile."""
    room3_lots = room3_engine.lots
    _sync_alpaca(ss, paper=paper)
    symbols = set(_open_syms(ss))
    for lot in room3_lots.open_lots(ss):
        ticker = str(lot.get("ticker") or "").upper()
        if ticker:
            symbols.add(ticker)
    ok_n = 0
    errs: list[str] = []

    def _close_syms(syms: set[str]) -> None:
        nonlocal ok_n
        for sym in sorted(syms):
            try:
                room3_lots.close_lots_for_ticker(ss, sym)
                result = room3_alpaca.close_position_now(sym, paper=paper, aggressive=True)
                if result.get("ok"):
                    ok_n += 1
                else:
                    errs.append(f"{sym}:{result.get('error') or 'fail'}")
            except Exception as exc:
                errs.append(f"{sym}:{exc}")

    _close_syms(symbols)
    _sync_alpaca(ss, paper=paper)
    leftover = set(_open_syms(ss))
    if leftover:
        _close_syms(leftover)
        _sync_alpaca(ss, paper=paper)
        leftover = set(_open_syms(ss))
    room3_lots.stamp_unlabeled_closes(ss, peel_open=False)
    ss.room3_watch_book = room3_watcher.empty_book()
    leftover = set(_open_syms(ss))
    if leftover:
        still = ",".join(sorted(leftover))
        # Keep pulse alive so the next tick retries flatten. No new hunting.
        ss.room3_unattended_armed = True
        note = f"session-flat · flattened {ok_n} · leftover {still}"
        if errs:
            note += " · " + "; ".join(errs[:3])
        return note
    ss.room3_filter_universe = []
    ss.room3_engine_armed = False
    ss.room3_unattended_armed = False
    return f"session-flat · flattened {ok_n}"


def _apply_signals(ss: PulseState, book: dict[str, Any], signals: list[dict], *, paper: bool, new_ok: bool) -> None:
    room3_lots = room3_engine.lots
    open_syms = _open_syms(ss)
    for sig in signals:
        intent = str(sig.get("intent") or "")
        if intent == "entry" and not new_ok:
            continue
        notional = float(sig.get("notional") or 0)
        gates = room3_engine.evaluate_execution_gates(
            mode=str(ss.get("room3_execution_mode") or "paper"),
            broker="alpaca",
            broker_connected=bool(ss.get("room3_broker_truth")),
            engine_armed=bool(ss.get("room3_engine_armed")),
            kill_flat=bool(ss.get("room3_kill_flat")),
            pause_entries=bool(ss.get("room3_pause_entries")),
            intent=intent or "entry",
            session_window=room3_engine.detect_session_window(),
            allowed_sessions=list(ss.get("room3_allowed_sessions") or []),
            tradable_today=float(ss.get("room3_tradable_today") or 0),
            deployed=room3_engine.deployed_notional(ss.get("room3_open_positions")),
            order_notional=notional,
        )
        result = room3_engine.execute_matrix_signal(sig, paper=paper, gates=gates)
        key = room3_watcher.line_key(
            str(sig.get("symbol") or ""),
            str(sig.get("timeframe") or "1m"),
        )
        line = (book.get("lines") or {}).get(key)
        if not line:
            continue
        sym = str(sig.get("symbol") or "").upper()
        if intent == "entry":
            if result.get("ok"):
                filled = float(result.get("filled_qty") or 0)
                if filled > 0 or sym in open_syms:
                    line["state"] = "in"
                    line.pop("order_pending", None)
                    fill_qty = filled if filled > 0 else abs(float(sig.get("qty") or 0))
                    room3_lots.append_lot(
                        ss,
                        {
                            "ticker": sym,
                            "tf": str(sig.get("timeframe") or line.get("timeframe") or ""),
                            "strategy": str(sig.get("strategy") or line.get("entry_strategy") or ""),
                            "layout_id": str(sig.get("layout_id") or line.get("entry_layout") or ""),
                            "qty": fill_qty,
                            "entry_px": result.get("filled_avg_price")
                            or sig.get("ref_price")
                            or line.get("entry_price"),
                            "entry_match_pct": sig.get("match_pct") or line.get("entry_match_pct"),
                            "structural_move_pct": line.get("entry_structural_move_pct"),
                            "exit_style": sig.get("exit_style") or line.get("exit_style"),
                            "exit_r_frac": sig.get("exit_r_frac") or line.get("exit_r_frac"),
                            "exit_stop_px": sig.get("exit_stop_px") or line.get("exit_stop_px"),
                            "exit_tgt_px": sig.get("exit_tgt_px") or line.get("exit_tgt_px"),
                            "1a_handle": sig.get("1a_handle") or line.get("1a_handle"),
                            "order_id": str(result.get("order_id") or ""),
                            "entry_time": result.get("filled_at")
                            or datetime.now(ET).strftime("%H:%M:%S"),
                        },
                    )
                    open_syms.add(sym)
                else:
                    oid = str(result.get("order_id") or "").strip()
                    if oid:
                        line["state"] = "committed"
                        line["order_pending"] = True
                        line["pending_order_id"] = oid
                    else:
                        line["state"] = "watching"
                        line.pop("order_pending", None)
                        line.pop("pending_order_id", None)
                        line["entry_signal"] = None
            else:
                line["entry_signal"] = None
                line.pop("order_pending", None)
                line.pop("pending_order_id", None)
        elif intent == "exit" and result.get("ok"):
            lot_id = str(sig.get("lot_id") or "")
            if lot_id:
                room3_lots.close_lot(ss, lot_id)
            else:
                letter = room3_lots.letter_token(
                    str(sig.get("layout_id") or ""),
                    str(sig.get("strategy") or ""),
                )
                tf = str(sig.get("timeframe") or "")
                peeled = room3_lots.open_lots(ss, sym, tf=tf, letter=letter)
                if peeled:
                    room3_lots.close_lot(ss, str(peeled[0].get("id") or ""))
            remain = room3_lots.open_lots(
                ss, sym, tf=str(sig.get("timeframe") or line.get("timeframe") or "")
            )
            if remain:
                keep = remain[0]
                line["state"] = "in"
                line["entry_strategy"] = str(keep.get("strategy") or "")
                line["exit_signal"] = None
            else:
                line["state"] = "watching"
                line["entry_signal"] = None
                line["exit_signal"] = None


def run_pulse(ss: PulseState) -> str:
    paper = str(ss.get("room3_execution_mode") or "paper") != "live"
    if ss.get("room3_kill_flat"):
        note = _flatten_open(ss, paper=paper)
        ss.room3_worker_note = note
        persist_bag(ss)
        return note
    synced = _sync_alpaca(ss, paper=paper, include_fills=_fills_due(ss))
    if not synced.get("ok"):
        ss.room3_worker_note = "broker disconnected"
        return ss.room3_worker_note
    tradable = float(ss.get("room3_tradable_today") or 0)
    open_syms = _open_syms(ss)
    for line in ((ss.get("room3_watch_book") or {}).get("lines") or {}).values():
        if not isinstance(line, dict):
            continue
        pending = bool(
            line.get("order_pending") or str(line.get("state") or "") == "committed"
        )
        if not pending:
            continue
        ticker = str(line.get("ticker") or "").upper()
        if ticker and ticker in open_syms:
            continue
        if tradable > 0 and str(line.get("pending_order_id") or "").strip():
            continue
        line["state"] = "watching"
        line.pop("order_pending", None)
        line.pop("pending_order_id", None)
        line["entry_signal"] = None
        line["patience"] = False
        line.pop("patience_note", None)
    if _session_must_be_flat(ss):
        note = _flatten_open(ss, paper=paper)
        ss.room3_worker_note = note
        persist_bag(ss)
        return note
    uni = [str(t).upper() for t in (ss.get("room3_filter_universe") or []) if str(t).strip()]
    book = dict(ss.get("room3_watch_book") or room3_watcher.empty_book())
    book["keep_tickers"] = sorted(_open_syms(ss))
    ss.room3_watch_book = room3_watcher.set_filter_universe(book, uni)
    window = room3_engine.detect_session_window()
    allowed = set(ss.get("room3_allowed_sessions") or [])
    new_ok = _session_trading_allowed(ss)
    intraday = window in (
        room3_engine.SESSION_PRE,
        room3_engine.SESSION_RTH,
        room3_engine.SESSION_POST,
    )
    has_risk = bool(_open_syms(ss))
    risk_continue = bool(has_risk and window in allowed)
    manage = bool(intraday and (new_ok or risk_continue))
    book, signals = room3_watcher.tick_watcher(
        ss.room3_watch_book,
        session_state=ss,
        session_allowed=manage,
        engine_armed=bool(ss.get("room3_engine_armed")),
        entries_allowed=new_ok,
    )
    _apply_signals(ss, book, signals, paper=paper, new_ok=new_ok)
    ss.room3_watch_book = book
    room3_engine.lots.stamp_unlabeled_closes(ss, peel_open=False)
    note = (
        f"unattended · {'ARMED' if ss.get('room3_engine_armed') else 'DISARMED'} · "
        f"{room3_engine.session_label(window)} · ticks {book.get('ticks') or 0}"
    )
    ss.room3_worker_note = note
    persist_bag(ss)
    return note


_BOOT_PULSE_DONE = False


def _loop() -> None:
    global _BOOT_PULSE_DONE
    while True:
        ss = bag()
        try:
            with _LOCK:
                belt = bool(ss.get("room3_filter_universe"))
                boot = not _BOOT_PULSE_DONE
                if boot:
                    _BOOT_PULSE_DONE = True
                    paper = str(ss.get("room3_execution_mode") or "paper") != "live"
                    if unattended_armed_from_disk():
                        run_pulse(ss)
                    else:
                        _sync_alpaca(ss, paper=paper, include_fills=False)
                        if _open_syms(ss):
                            ss.room3_worker_note = _flatten_open(ss, paper=paper)
                            persist_bag(ss)
                elif (
                    ss.get("room3_unattended_armed")
                    or ss.get("room3_engine_armed")
                    or _open_syms(ss)
                    or belt
                ):
                    run_pulse(ss)
                else:
                    ss.room3_worker_note = "idle · arm + belt to keep trading after tab close"
        except Exception as exc:
            ss.room3_worker_error = str(exc).strip() or type(exc).__name__
            ss.room3_worker_note = f"pulse error · {ss.room3_worker_error}"
        time.sleep(PULSE_SEC)
