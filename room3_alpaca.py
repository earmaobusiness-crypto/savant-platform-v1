"""
Room 3 — Alpaca paper/live trading helpers.

Paper-first path while IBKR Pro/API is unavailable.
Never log secrets. Room 1 / Room 2 untouched.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


def _read_local_secrets_toml() -> dict[str, str]:
    path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in (
            "ALPACA_API_KEY",
            "ALPACA_SECRET_KEY",
            "ALPACA_PAPER_API_KEY",
            "ALPACA_PAPER_SECRET_KEY",
            "ALPACA_ENDPOINT",
        ):
            val = data.get(key)
            if val is not None:
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
        cash = float(getattr(account, "cash", 0) or 0)
        buying_power = float(getattr(account, "buying_power", 0) or 0)
        status = str(getattr(account, "status", "") or "")
        account_number = str(getattr(account, "account_number", "") or "")
        return {
            "ok": True,
            "paper": paper,
            "equity": equity,
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


def place_market_order(
    symbol: str,
    side: str,
    qty: float,
    *,
    paper: bool = True,
) -> dict[str, Any]:
    """Submit a paper/live market order. Returns ok + fill snapshot or error."""
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
        from alpaca.trading.requests import MarketOrderRequest
    except ImportError:
        return {"ok": False, "error": "alpaca-py not installed — run: pip install alpaca-py"}

    try:
        client = _trading_client(paper=paper)
        req = MarketOrderRequest(
            symbol=ticker,
            qty=shares,
            side=OrderSide.BUY if side_l == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
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
            "paper": paper,
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc).strip() or type(exc).__name__}
