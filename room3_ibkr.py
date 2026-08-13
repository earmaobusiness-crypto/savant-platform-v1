"""
Room 3 — Interactive Brokers connection helpers.

Uses TWS / IB Gateway socket API only. Never asks for IBKR passwords.
Room 1 / Room 2 are untouched.
"""

from __future__ import annotations

from typing import Any


PLATFORM_TWS = "tws"
PLATFORM_GATEWAY = "gateway"

# TWS defaults
TWS_PAPER_PORT = 7497
TWS_LIVE_PORT = 7496
# IB Gateway defaults
GATEWAY_PAPER_PORT = 4002
GATEWAY_LIVE_PORT = 4001

DEFAULT_HOST = "127.0.0.1"
DEFAULT_CLIENT_ID = 71  # Room 3 dedicated id — avoid clashing with other tools


def default_port_for_mode(mode: str, platform: str = PLATFORM_GATEWAY) -> int:
    is_live = str(mode).lower() == "live"
    if str(platform).lower() == PLATFORM_TWS:
        return TWS_LIVE_PORT if is_live else TWS_PAPER_PORT
    return GATEWAY_LIVE_PORT if is_live else GATEWAY_PAPER_PORT


def probe_tws_connection(
    host: str = DEFAULT_HOST,
    port: int = GATEWAY_PAPER_PORT,
    client_id: int = DEFAULT_CLIENT_ID,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """
    One-shot connect → read managed accounts → disconnect.
    Returns {ok, accounts, server_version, error}.
    """
    host = str(host or DEFAULT_HOST).strip() or DEFAULT_HOST
    try:
        port = int(port)
    except Exception:
        return {"ok": False, "accounts": [], "error": f"Invalid port: {port}"}

    try:
        from ib_insync import IB
    except ImportError:
        return {
            "ok": False,
            "accounts": [],
            "error": "ib_insync not installed — run: pip install ib_insync",
        }

    ib = IB()
    try:
        ib.connect(host, port, clientId=int(client_id), timeout=float(timeout), readonly=True)
        accounts = list(ib.managedAccounts() or [])
        server_version = getattr(ib.client, "serverVersion", lambda: None)()
        return {
            "ok": True,
            "accounts": accounts,
            "server_version": server_version,
            "host": host,
            "port": port,
            "error": "",
        }
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        hint = ""
        low = msg.lower()
        if "timeout" in low or "connect" in low:
            hint = (
                " · Is IB Gateway or TWS open and logged in? "
                "Configure → Settings → API → Enable ActiveX and Socket Clients, "
                "and make sure the port matches Room 3."
            )
        elif "refused" in low:
            hint = " · Nothing listening on that port — wrong port or API not enabled."
        return {
            "ok": False,
            "accounts": [],
            "host": host,
            "port": port,
            "error": f"{msg}{hint}",
        }
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:
            pass
