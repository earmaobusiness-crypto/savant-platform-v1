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


def load_alpaca_credentials(paper: bool = True) -> dict[str, str]:
    """Load key/secret/endpoint from st.secrets, env, or local secrets.toml."""
    local = _read_local_secrets_toml()
    key = ""
    secret = ""
    endpoint = ""

    try:
        import streamlit as st

        block = st.secrets.get("alpaca")
        if isinstance(block, dict):
            if paper:
                key = str(block.get("paper_api_key") or block.get("api_key") or "").strip()
                secret = str(block.get("paper_secret_key") or block.get("secret_key") or "").strip()
            else:
                key = str(block.get("api_key") or "").strip()
                secret = str(block.get("secret_key") or "").strip()
            endpoint = str(block.get("endpoint") or "").strip()
        if not key:
            key = str(
                st.secrets.get("ALPACA_PAPER_API_KEY" if paper else "ALPACA_API_KEY")
                or st.secrets.get("ALPACA_API_KEY")
                or ""
            ).strip()
        if not secret:
            secret = str(
                st.secrets.get("ALPACA_PAPER_SECRET_KEY" if paper else "ALPACA_SECRET_KEY")
                or st.secrets.get("ALPACA_SECRET_KEY")
                or ""
            ).strip()
        if not endpoint:
            endpoint = str(st.secrets.get("ALPACA_ENDPOINT") or "").strip()
    except Exception:
        pass

    if not key:
        key = (
            os.environ.get("ALPACA_PAPER_API_KEY" if paper else "ALPACA_API_KEY")
            or os.environ.get("ALPACA_API_KEY")
            or local.get("ALPACA_PAPER_API_KEY" if paper else "ALPACA_API_KEY")
            or local.get("ALPACA_API_KEY")
            or ""
        ).strip()
    if not secret:
        secret = (
            os.environ.get("ALPACA_PAPER_SECRET_KEY" if paper else "ALPACA_SECRET_KEY")
            or os.environ.get("ALPACA_SECRET_KEY")
            or local.get("ALPACA_PAPER_SECRET_KEY" if paper else "ALPACA_SECRET_KEY")
            or local.get("ALPACA_SECRET_KEY")
            or ""
        ).strip()
    if not endpoint:
        endpoint = (
            os.environ.get("ALPACA_ENDPOINT")
            or local.get("ALPACA_ENDPOINT")
            or (PAPER_BASE_URL if paper else LIVE_BASE_URL)
        ).strip()

    if paper and "paper-api" not in endpoint and endpoint.endswith("api.alpaca.markets"):
        endpoint = PAPER_BASE_URL

    return {"key": key, "secret": secret, "endpoint": endpoint or (PAPER_BASE_URL if paper else LIVE_BASE_URL)}


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
        from alpaca.trading.client import TradingClient
    except ImportError:
        return {
            "ok": False,
            "error": "alpaca-py not installed — run: pip install alpaca-py",
        }

    try:
        client = TradingClient(
            api_key=creds["key"],
            secret_key=creds["secret"],
            paper=bool(paper),
        )
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
    creds = load_alpaca_credentials(paper=paper)
    if not creds["key"] or not creds["secret"]:
        return []
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        return []
    try:
        client = TradingClient(
            api_key=creds["key"],
            secret_key=creds["secret"],
            paper=bool(paper),
        )
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
