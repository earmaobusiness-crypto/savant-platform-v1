"""
Room 3 — Alpaca paper/live trading helpers.

Paper-first path while IBKR Pro/API is unavailable.
Never log secrets. Room 1 / Room 2 untouched.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


def _parse_alpaca_kv_from_text(text: str) -> dict[str, str]:
    """Line fallback if tomllib fails — only ALPACA_* keys, never logs values."""
    wanted = {
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_PAPER_API_KEY",
        "ALPACA_PAPER_SECRET_KEY",
        "ALPACA_ENDPOINT",
    }
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in wanted:
            continue
        out[key] = val.strip().strip('"').strip("'")
    return out


def _secrets_toml_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        here / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
    ]


def _read_local_secrets_toml() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in _secrets_toml_candidates():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            import tomllib

            data = tomllib.loads(text)
            for key in (
                "ALPACA_API_KEY",
                "ALPACA_SECRET_KEY",
                "ALPACA_PAPER_API_KEY",
                "ALPACA_PAPER_SECRET_KEY",
                "ALPACA_ENDPOINT",
            ):
                val = data.get(key)
                if val is not None and key not in out:
                    out[key] = str(val).strip().strip('"').strip("'")
            block = data.get("alpaca")
            if isinstance(block, dict):
                for key, dest in (
                    ("api_key", "ALPACA_API_KEY"),
                    ("secret_key", "ALPACA_SECRET_KEY"),
                    ("paper_api_key", "ALPACA_PAPER_API_KEY"),
                    ("paper_secret_key", "ALPACA_PAPER_SECRET_KEY"),
                    ("endpoint", "ALPACA_ENDPOINT"),
                ):
                    if block.get(key) is not None and dest not in out:
                        out[dest] = str(block.get(key)).strip().strip('"').strip("'")
        except Exception:
            pass
        # Always merge line fallback so empty tomllib / odd TOML still works
        for key, val in _parse_alpaca_kv_from_text(text).items():
            if val and not out.get(key):
                out[key] = val
        if out.get("ALPACA_API_KEY") and out.get("ALPACA_SECRET_KEY"):
            break
    return out


def _first_nonempty(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip().strip('"').strip("'")
        if text:
            return text
    return ""


def _read_streamlit_secret(name: str) -> str:
    """Best-effort read of one Streamlit secret without raising."""
    try:
        import streamlit as st

        try:
            val = st.secrets.get(name)  # type: ignore[attr-defined]
        except Exception:
            try:
                val = st.secrets[name]
            except Exception:
                return ""
        return _first_nonempty(val)
    except Exception:
        return ""


def _read_streamlit_alpaca_block(paper: bool) -> dict[str, str]:
    try:
        import streamlit as st

        try:
            block = st.secrets.get("alpaca")  # type: ignore[attr-defined]
        except Exception:
            try:
                block = st.secrets["alpaca"]
            except Exception:
                block = None
        if not isinstance(block, dict):
            return {}
        if paper:
            key = _first_nonempty(block.get("paper_api_key"), block.get("api_key"))
            secret = _first_nonempty(block.get("paper_secret_key"), block.get("secret_key"))
        else:
            key = _first_nonempty(block.get("api_key"))
            secret = _first_nonempty(block.get("secret_key"))
        endpoint = _first_nonempty(block.get("endpoint"))
        return {"key": key, "secret": secret, "endpoint": endpoint}
    except Exception:
        return {}


def load_alpaca_credentials(paper: bool = True) -> dict[str, str]:
    """Load key/secret/endpoint from local secrets.toml, env, or st.secrets.

    Local file is checked first so Room 3 still works if Streamlit was started
    before keys were pasted (and for processes that don't reload st.secrets).
    """
    local = _read_local_secrets_toml()
    block = _read_streamlit_alpaca_block(paper=paper)

    if paper:
        key = _first_nonempty(
            local.get("ALPACA_PAPER_API_KEY"),
            local.get("ALPACA_API_KEY"),
            os.environ.get("ALPACA_PAPER_API_KEY"),
            os.environ.get("ALPACA_API_KEY"),
            block.get("key"),
            _read_streamlit_secret("ALPACA_PAPER_API_KEY"),
            _read_streamlit_secret("ALPACA_API_KEY"),
        )
        secret = _first_nonempty(
            local.get("ALPACA_PAPER_SECRET_KEY"),
            local.get("ALPACA_SECRET_KEY"),
            os.environ.get("ALPACA_PAPER_SECRET_KEY"),
            os.environ.get("ALPACA_SECRET_KEY"),
            block.get("secret"),
            _read_streamlit_secret("ALPACA_PAPER_SECRET_KEY"),
            _read_streamlit_secret("ALPACA_SECRET_KEY"),
        )
    else:
        key = _first_nonempty(
            local.get("ALPACA_API_KEY"),
            os.environ.get("ALPACA_API_KEY"),
            block.get("key"),
            _read_streamlit_secret("ALPACA_API_KEY"),
        )
        secret = _first_nonempty(
            local.get("ALPACA_SECRET_KEY"),
            os.environ.get("ALPACA_SECRET_KEY"),
            block.get("secret"),
            _read_streamlit_secret("ALPACA_SECRET_KEY"),
        )

    endpoint = _first_nonempty(
        local.get("ALPACA_ENDPOINT"),
        os.environ.get("ALPACA_ENDPOINT"),
        block.get("endpoint"),
        _read_streamlit_secret("ALPACA_ENDPOINT"),
        PAPER_BASE_URL if paper else LIVE_BASE_URL,
    )

    if paper and "paper-api" not in endpoint and endpoint.endswith("api.alpaca.markets"):
        endpoint = PAPER_BASE_URL

    return {
        "key": key,
        "secret": secret,
        "endpoint": endpoint or (PAPER_BASE_URL if paper else LIVE_BASE_URL),
    }


def _trading_client(paper: bool = True):
    creds = load_alpaca_credentials(paper=paper)
    if not creds["key"] or not creds["secret"]:
        raise RuntimeError(
            "Alpaca keys missing — add ALPACA_API_KEY and ALPACA_SECRET_KEY "
            "to .streamlit/secrets.toml, then restart Streamlit."
        )
    from alpaca.trading.client import TradingClient

    return TradingClient(
        api_key=creds["key"],
        secret_key=creds["secret"],
        paper=bool(paper),
    )


def probe_alpaca_connection(paper: bool = True) -> dict[str, Any]:
    """One-shot account read to verify keys work."""
    creds = load_alpaca_credentials(paper=paper)
    if not creds["key"] or not creds["secret"]:
        return {
            "ok": False,
            "error": (
                "Alpaca keys missing — add ALPACA_API_KEY and ALPACA_SECRET_KEY "
                "to .streamlit/secrets.toml (paper keys), then restart Streamlit."
            ),
        }

    try:
        from alpaca.trading.client import TradingClient  # noqa: F401
    except ImportError:
        return {
            "ok": False,
            "error": "alpaca-py not installed — run: pip install alpaca-py",
        }

    try:
        client = _trading_client(paper=paper)
        account = client.get_account()
        equity = float(getattr(account, "equity", 0) or 0)
        last_equity = float(getattr(account, "last_equity", 0) or 0)
        cash = float(getattr(account, "cash", 0) or 0)
        buying_power = float(getattr(account, "buying_power", 0) or 0)
        status = str(getattr(account, "status", "") or "")
        account_number = str(getattr(account, "account_number", "") or "")
        day_pl = equity - last_equity if last_equity > 0 else 0.0
        day_pl_pct = (day_pl / last_equity * 100.0) if last_equity > 0 else 0.0
        return {
            "ok": True,
            "paper": paper,
            "equity": equity,
            "last_equity": last_equity,
            "day_pl": day_pl,
            "day_pl_pct": day_pl_pct,
            "cash": cash,
            "buying_power": buying_power,
            "status": status,
            "account_number": account_number,
            "endpoint": creds["endpoint"],
            "error": "",
        }
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        return {"ok": False, "error": msg, "endpoint": creds["endpoint"]}


def fetch_open_positions(paper: bool = True) -> list[dict[str, Any]]:
    try:
        client = _trading_client(paper=paper)
    except Exception:
        return []
    try:
        rows = []
        for p in client.get_all_positions() or []:
            qty = float(getattr(p, "qty", 0) or 0)
            entry = float(getattr(p, "avg_entry_price", 0) or 0)
            last = float(getattr(p, "current_price", 0) or 0)
            pnl = float(getattr(p, "unrealized_pl", 0) or 0)
            pnl_pct = float(getattr(p, "unrealized_plpc", 0) or 0) * 100.0
            rows.append(
                {
                    "id": f"alpaca-{getattr(p, 'asset_id', getattr(p, 'symbol', ''))}",
                    "ticker": str(getattr(p, "symbol", "") or ""),
                    "timeframe": "—",
                    "strategy": "Alpaca",
                    "entry_time": "—",
                    "entry_price": entry,
                    "last_price": last,
                    "pnl_usd": pnl,
                    "pnl_pct": pnl_pct,
                    "qty": qty,
                }
            )
        return rows
    except Exception:
        return []


def fetch_broker_day_pl(paper: bool = True) -> dict[str, Any]:
    """Day P/L from Alpaca account equity vs prior close (broker truth)."""
    probe = probe_alpaca_connection(paper=paper)
    if probe.get("ok"):
        return {
            "ok": True,
            "day_pl": float(probe.get("day_pl") or 0),
            "day_pl_pct": float(probe.get("day_pl_pct") or 0),
            "start": float(probe.get("last_equity") or 0),
            "end": float(probe.get("equity") or 0),
        }
    try:
        from alpaca.trading.requests import GetPortfolioHistoryRequest

        client = _trading_client(paper=paper)
        hist = client.get_portfolio_history(
            GetPortfolioHistoryRequest(period="1D", timeframe="5Min")
        )
        equities = list(getattr(hist, "equity", None) or [])
        if len(equities) >= 2:
            start = float(equities[0] or 0)
            end = float(equities[-1] or 0)
            pl = end - start
            pct = (pl / start * 100.0) if start else 0.0
            return {"ok": True, "day_pl": pl, "day_pl_pct": pct, "start": start, "end": end}
        return {"ok": False, "day_pl": 0.0, "day_pl_pct": 0.0, "error": "no history"}
    except Exception as exc:
        return {
            "ok": False,
            "day_pl": 0.0,
            "day_pl_pct": 0.0,
            "error": str(exc).strip() or type(exc).__name__,
        }


def _et_trading_day(now: datetime | None = None):
    """Match Room 3 session day — rolls at 4:00 AM Eastern."""
    from datetime import timedelta

    et = ZoneInfo("America/New_York")
    now = now or datetime.now(et)
    if now.tzinfo is None:
        now = now.replace(tzinfo=et)
    else:
        now = now.astimezone(et)
    if now.hour < 4:
        return (now - timedelta(days=1)).date()
    return now.date()


def _parse_alpaca_ts(raw: Any) -> datetime | None:
    et = ZoneInfo("America/New_York")
    if raw is None:
        return None
    try:
        if isinstance(raw, datetime):
            ts = raw
        else:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            return ts.replace(tzinfo=et)
        return ts.astimezone(et)
    except Exception:
        return None


def _closed_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    session_day = _et_trading_day()
    lots: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    for ev in events:
        try:
            sym = str(ev["symbol"]).upper()
            side = str(ev["side"]).lower()
            qty = abs(float(ev["qty"]))
            px = float(ev["price"])
            ts: datetime = ev["ts"]
            oid = str(ev["id"])
            book = lots.setdefault(sym, [])
            if side == "buy":
                book.append({"qty": qty, "px": px, "ts": ts.strftime("%H:%M:%S")})
                continue
            if side != "sell":
                continue
            remain = qty
            entry_px_acc = 0.0
            entry_qty_acc = 0.0
            entry_time = "—"
            while remain > 1e-9 and book:
                lot = book[0]
                take = min(remain, float(lot["qty"]))
                entry_px_acc += take * float(lot["px"])
                entry_qty_acc += take
                if entry_time == "—":
                    entry_time = str(lot.get("ts") or "—")
                lot["qty"] = float(lot["qty"]) - take
                remain -= take
                if float(lot["qty"]) <= 1e-9:
                    book.pop(0)
            if entry_qty_acc <= 0 or _et_trading_day(ts) != session_day:
                continue
            avg_entry = entry_px_acc / entry_qty_acc
            pnl = (px - avg_entry) * entry_qty_acc
            pnl_pct = ((px - avg_entry) / avg_entry * 100.0) if avg_entry else 0.0
            closed.append(
                {
                    "id": f"alpaca-fill-{oid}",
                    "ticker": sym,
                    "timeframe": "—",
                    "strategy": "Alpaca",
                    "entry_time": entry_time,
                    "exit_time": ts.strftime("%H:%M:%S"),
                    "entry_price": round(avg_entry, 4),
                    "exit_price": round(px, 4),
                    "pnl_usd": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 3),
                    "qty": entry_qty_acc,
                    "reviewed": True,
                    "status": "closed · alpaca",
                    "broker_source": True,
                }
            )
        except Exception:
            continue
    return closed


def _fetch_fill_events(paper: bool = True) -> tuple[list[dict[str, Any]], str]:
    """
    Filled buy/sell legs for FIFO. Prefer closed orders (Trading API).
    Activities `date=` is UTC and misses evening ET fills — avoid that.
    """
    from datetime import timedelta

    et = ZoneInfo("America/New_York")
    session_day = _et_trading_day()
    lookback_start = datetime.combine(
        session_day - timedelta(days=5), datetime.min.time(), tzinfo=et
    )

    events: list[dict[str, Any]] = []
    err = ""

    try:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        client = _trading_client(paper=paper)
        orders = (
            client.get_orders(
                GetOrdersRequest(
                    status=QueryOrderStatus.CLOSED,
                    after=lookback_start,
                    direction="asc",
                    limit=100,
                )
            )
            or []
        )
        for o in orders:
            filled_qty = float(getattr(o, "filled_qty", 0) or 0)
            avg = getattr(o, "filled_avg_price", None)
            px = float(avg) if avg not in (None, "") else 0.0
            if filled_qty <= 0 or px <= 0:
                continue
            ts = _parse_alpaca_ts(
                getattr(o, "filled_at", None) or getattr(o, "submitted_at", None)
            )
            if ts is None:
                continue
            side_raw = getattr(o, "side", "") or ""
            side = str(getattr(side_raw, "value", side_raw) or "").lower()
            sym = str(getattr(o, "symbol", "") or "").upper()
            oid = str(getattr(o, "id", "") or "")
            if not sym or side not in ("buy", "sell"):
                continue
            events.append(
                {
                    "symbol": sym,
                    "side": side,
                    "qty": filled_qty,
                    "price": px,
                    "ts": ts,
                    "id": oid or f"{sym}-{ts.isoformat()}",
                    "source": "order",
                }
            )
    except Exception as exc:
        err = str(exc).strip() or type(exc).__name__

    if events:
        events.sort(key=lambda e: e["ts"])
        return events, err

    try:
        creds = load_alpaca_credentials(paper=paper)
        if not creds["key"] or not creds["secret"]:
            return [], err or "Alpaca keys missing"
        base = (creds["endpoint"] or PAPER_BASE_URL).rstrip("/")
        after = lookback_start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = (datetime.now(et) + timedelta(minutes=5)).astimezone(ZoneInfo("UTC")).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        qs = urllib.parse.urlencode(
            {
                "activity_types": "FILL",
                "after": after,
                "until": until,
                "direction": "asc",
                "page_size": 100,
            }
        )
        url = f"{base}/v2/account/activities?{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": creds["key"],
                "APCA-API-SECRET-KEY": creds["secret"],
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for a in payload if isinstance(payload, list) else []:
            ts = _parse_alpaca_ts(a.get("transaction_time") or a.get("timestamp"))
            if ts is None:
                continue
            sym = str(a.get("symbol") or "").upper()
            side = str(a.get("side") or "").lower()
            qty = abs(float(a.get("qty") or 0))
            px = float(a.get("price") or 0)
            oid = str(a.get("order_id") or a.get("id") or "")
            if side in ("b",):
                side = "buy"
            if side in ("s",):
                side = "sell"
            if not sym or side not in ("buy", "sell") or qty <= 0 or px <= 0:
                continue
            events.append(
                {
                    "symbol": sym,
                    "side": side,
                    "qty": qty,
                    "price": px,
                    "ts": ts,
                    "id": oid or f"{sym}-{ts.isoformat()}",
                    "source": "activity",
                }
            )
        events.sort(key=lambda e: e["ts"])
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        err = f"{err}; {msg}" if err else msg
    return events, err


def fetch_closed_trades_today(paper: bool = True) -> list[dict[str, Any]]:
    """Rebuild this trading day's closed round-trips from Alpaca fills (manual EH included)."""
    events, _err = _fetch_fill_events(paper=paper)
    return _closed_from_events(events)


def fetch_closed_trades_today_debug(paper: bool = True) -> dict[str, Any]:
    """Closed trades plus sync diagnostics for the Room 3 refresh caption."""
    events, err = _fetch_fill_events(paper=paper)
    closed = _closed_from_events(events)
    return {
        "closed": closed,
        "fill_events": len(events),
        "closed_count": len(closed),
        "error": err,
        "session_day": _et_trading_day().isoformat(),
    }


def fetch_latest_price(symbol: str, *, paper: bool = True) -> float | None:
    """Best-effort last price for EH limit orders (trade → position → None)."""
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return None
    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest

        creds = load_alpaca_credentials(paper=paper)
        data = StockHistoricalDataClient(creds["key"], creds["secret"])
        latest = data.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=ticker))
        trade = latest.get(ticker) if isinstance(latest, dict) else None
        px = float(getattr(trade, "price", 0) or 0)
        if px > 0:
            return px
    except Exception:
        pass
    try:
        client = _trading_client(paper=paper)
        pos = client.get_open_position(ticker)
        px = float(getattr(pos, "current_price", 0) or getattr(pos, "lastday_price", 0) or 0)
        if px > 0:
            return px
    except Exception:
        pass
    return None


def session_needs_extended_hours(session_window: str | None = None) -> bool:
    """Alpaca fills market orders in RTH only; pre/post/overnight need EH limits."""
    try:
        import room3_engine

        window = session_window or room3_engine.detect_session_window()
        return window != room3_engine.SESSION_RTH
    except Exception:
        # Fail safe: outside unknown clock, prefer EH-capable limit
        return True


def place_market_order(
    symbol: str,
    side: str,
    qty: float,
    *,
    paper: bool = True,
    limit_price: float | None = None,
    ref_price: float | None = None,
    extended_hours: bool | None = None,
    prefer_limit: bool = False,
) -> dict[str, Any]:
    """
    Submit equity order.
    RTH 1m → market. 5m/15m and anything outside RTH → limit using Alpaca last
    (Yahoo map can lag; the limit is the broker's print ± a small fill offset).
    """
    ticker = str(symbol or "").strip().upper()
    side_l = str(side or "").strip().lower()
    try:
        shares = float(qty)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Quantity must be a number."}
    if not ticker:
        return {"ok": False, "error": "Ticker required."}
    if side_l not in ("buy", "sell"):
        return {"ok": False, "error": "Side must be buy or sell."}
    if shares <= 0:
        return {"ok": False, "error": "Quantity must be > 0."}

    try:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
    except ImportError:
        return {"ok": False, "error": "alpaca-py not installed — run: pip install alpaca-py"}

    use_eh = bool(extended_hours) if extended_hours is not None else session_needs_extended_hours()
    use_limit = bool(prefer_limit) or use_eh
    order_side = OrderSide.BUY if side_l == "buy" else OrderSide.SELL

    try:
        client = _trading_client(paper=paper)
        if use_limit:
            px = float(limit_price or 0) or float(ref_price or 0) or (fetch_latest_price(ticker, paper=paper) or 0.0)
            if px <= 0:
                return {
                    "ok": False,
                    "error": (
                        "Limit order needs Alpaca's last price — no quote. "
                        "Retry, or wait for regular hours."
                    ),
                }
            slip = 0.012 if use_eh else 0.0015
            if side_l == "buy":
                limit_px = round(px * (1.0 + slip), 2)
            else:
                limit_px = round(px * (1.0 - slip), 2)
            if limit_px <= 0:
                limit_px = round(px, 2)
            req = LimitOrderRequest(
                symbol=ticker,
                qty=shares,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_px,
                extended_hours=bool(use_eh),
            )
            order_kind = "limit+extended_hours" if use_eh else "limit"
        else:
            req = MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
            limit_px = None
            order_kind = "market"

        order = client.submit_order(order_data=req)
        order_id = str(getattr(order, "id", "") or "")
        status = str(getattr(order, "status", "") or "")
        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        filled_avg = getattr(order, "filled_avg_price", None)
        fill_px = float(filled_avg) if filled_avg not in (None, "") else None
        return {
            "ok": True,
            "order_id": order_id,
            "symbol": ticker,
            "side": side_l,
            "qty": shares,
            "status": status,
            "filled_qty": filled_qty,
            "filled_avg_price": fill_px,
            "limit_price": limit_px,
            "order_kind": order_kind,
            "extended_hours": use_eh,
            "paper": paper,
            "error": "",
            "ref_price": float(ref_price or 0) or None,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip() or type(exc).__name__}


def close_position_now(
    symbol: str,
    *,
    paper: bool = True,
    qty: float | None = None,
) -> dict[str, Any]:
    """
    Flatten one symbol. Outside RTH uses EH limit (dashboard 'X / liquidate'
    often queues a market order until 9:30).
    """
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        return {"ok": False, "error": "Ticker required."}
    try:
        client = _trading_client(paper=paper)
        pos = client.get_open_position(ticker)
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip() or f"No open position for {ticker}"}
    try:
        raw_qty = float(getattr(pos, "qty", 0) or 0)
    except (TypeError, ValueError):
        raw_qty = 0.0
    if raw_qty == 0:
        return {"ok": False, "error": f"{ticker} already flat"}
    shares = abs(float(qty) if qty is not None else raw_qty)
    # Long → sell; short → buy
    side = "sell" if raw_qty > 0 else "buy"
    ref = float(getattr(pos, "current_price", 0) or 0) or None
    return place_market_order(
        ticker, side, shares, paper=paper, ref_price=ref, prefer_limit=True
    )
