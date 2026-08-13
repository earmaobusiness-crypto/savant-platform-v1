"""
Room 3 — Live / Paper Trading Center.

Auto path: session filters → matrix signal → gated Alpaca entry/exit.
Operator supervises capital, kill/pause, ✓/✗. No manual order ticket.
"""

from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import room3_alpaca
import room3_engine
import room3_ibkr
import room3_watcher

ROOM3_MODE_PAPER = "paper"
ROOM3_MODE_LIVE = "live"
ROOM3_RECOVERY_EMAIL = "earmaobusiness@gmail.com"
# Flip to True later — passcode gate + recovery flow (no rebuild needed).
ROOM3_LIVE_SECURITY_ENABLED = False
ROOM3_DEFAULT_EQUITY = 0.0
ROOM3_SESSION_ROLL_HOUR_ET = 4  # next trading day starts 4:00 AM Eastern
ET = ZoneInfo("America/New_York")

_SESSION_KEYS = (
    "room3_execution_mode",
    "room3_live_unlocked",
    "room3_live_gate_open",
    "room3_recovery_stage",
    "room3_recovery_token",
    "room3_auth_fail_count",
    "room3_open_positions",
    "room3_trade_history",
    "room3_operator_reviews",
)


def _read_local_secrets_toml() -> dict[str, str]:
    """Fallback when st.secrets is empty (local dev before restart)."""
    path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        import tomllib

        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in ("ROOM3_LIVE_PASSCODE", "ROOM3_LIVE_RECOVERY_CODE"):
            val = data.get(key)
            if val is not None:
                out[key] = str(val).strip().strip('"').strip("'")
    except Exception:
        pass
    return out


def _room3_secrets() -> dict:
    """Read Room 3 auth from secrets.toml, st.secrets, or env."""
    local = _read_local_secrets_toml()
    try:
        block = st.secrets.get("room3")
        if isinstance(block, dict) and str(block.get("live_passcode") or "").strip():
            return {
                "live_passcode": str(block.get("live_passcode") or "").strip(),
                "recovery_code": str(block.get("recovery_code") or "").strip(),
            }
    except Exception:
        pass
    try:
        passcode = st.secrets.get("ROOM3_LIVE_PASSCODE")
        recovery = st.secrets.get("ROOM3_LIVE_RECOVERY_CODE")
        if passcode or recovery:
            return {
                "live_passcode": str(passcode or "").strip(),
                "recovery_code": str(recovery or "").strip(),
            }
    except Exception:
        pass
    env_pass = str(os.environ.get("ROOM3_LIVE_PASSCODE") or "").strip()
    env_rec = str(os.environ.get("ROOM3_LIVE_RECOVERY_CODE") or "").strip()
    if env_pass or env_rec:
        return {"live_passcode": env_pass, "recovery_code": env_rec}
    if local.get("ROOM3_LIVE_PASSCODE") or local.get("ROOM3_LIVE_RECOVERY_CODE"):
        return {
            "live_passcode": str(local.get("ROOM3_LIVE_PASSCODE") or "").strip(),
            "recovery_code": str(local.get("ROOM3_LIVE_RECOVERY_CODE") or "").strip(),
        }
    return {}


def _hash_code(raw: str) -> str:
    return hashlib.sha256(str(raw or "").strip().encode("utf-8")).hexdigest()


def _configured_passcode_plain() -> str | None:
    cfg = _room3_secrets()
    plain = str(cfg.get("live_passcode") or "").strip()
    return plain or None


def _configured_recovery_plain() -> str | None:
    cfg = _room3_secrets()
    plain = str(cfg.get("recovery_code") or "").strip()
    return plain or None


def _passcode_matches(entered: str, expected_plain: str | None) -> bool:
    if not expected_plain:
        return False
    return str(entered or "").strip() == str(expected_plain).strip()


def _unlock_live_session() -> None:
    st.session_state.room3_live_unlocked = True
    st.session_state.room3_execution_mode = ROOM3_MODE_LIVE
    st.session_state.room3_live_gate_open = False
    st.session_state.room3_auth_fail_count = 0
    st.session_state.room3_recovery_stage = ""
    st.session_state.room3_gate_message = ""
    st.session_state.room3_gate_error = False


def _try_unlock_with_passcode(entered: str) -> bool:
    expected = _configured_passcode_plain()
    if not expected:
        st.session_state.room3_gate_message = (
            "Passcode not loaded — add ROOM3_LIVE_PASSCODE to secrets and restart."
        )
        st.session_state.room3_gate_error = True
        return False
    if not str(entered or "").strip():
        st.session_state.room3_gate_message = "Enter a passcode first."
        st.session_state.room3_gate_error = True
        return False
    if _passcode_matches(entered, expected):
        _unlock_live_session()
        return True
    st.session_state.room3_auth_fail_count = int(st.session_state.room3_auth_fail_count or 0) + 1
    st.session_state.room3_gate_message = "Wrong passcode."
    st.session_state.room3_gate_error = True
    if st.session_state.room3_auth_fail_count >= 3:
        st.session_state.room3_recovery_stage = "offer_email"
    return False


def init_room3_session_state() -> None:
    """Session defaults — safe to call on every Room 3 render."""
    if "room3_execution_mode" not in st.session_state:
        st.session_state.room3_execution_mode = ROOM3_MODE_PAPER
    if "room3_live_unlocked" not in st.session_state:
        st.session_state.room3_live_unlocked = False
    if "room3_live_gate_open" not in st.session_state:
        st.session_state.room3_live_gate_open = False
    if "room3_recovery_stage" not in st.session_state:
        st.session_state.room3_recovery_stage = ""
    if "room3_recovery_token" not in st.session_state:
        st.session_state.room3_recovery_token = ""
    if "room3_auth_fail_count" not in st.session_state:
        st.session_state.room3_auth_fail_count = 0
    if "room3_open_positions" not in st.session_state:
        st.session_state.room3_open_positions = []
    if "room3_trade_history" not in st.session_state:
        st.session_state.room3_trade_history = []
    if "room3_operator_reviews" not in st.session_state:
        st.session_state.room3_operator_reviews = []
    if "room3_gate_message" not in st.session_state:
        st.session_state.room3_gate_message = ""
    if "room3_gate_error" not in st.session_state:
        st.session_state.room3_gate_error = False
    if "room3_account_equity" not in st.session_state:
        st.session_state.room3_account_equity = ROOM3_DEFAULT_EQUITY
    if "room3_ibkr_status" not in st.session_state:
        st.session_state.room3_ibkr_status = "disconnected"  # disconnected | waiting | connected
    if "room3_ibkr_account" not in st.session_state:
        st.session_state.room3_ibkr_account = ""
    if "room3_ibkr_host" not in st.session_state:
        st.session_state.room3_ibkr_host = "127.0.0.1"
    if "room3_ibkr_port" not in st.session_state:
        st.session_state.room3_ibkr_port = room3_ibkr.GATEWAY_PAPER_PORT
    if "room3_ibkr_platform" not in st.session_state:
        st.session_state.room3_ibkr_platform = room3_ibkr.PLATFORM_GATEWAY
    if "room3_ibkr_client_id" not in st.session_state:
        st.session_state.room3_ibkr_client_id = room3_ibkr.DEFAULT_CLIENT_ID
    if "room3_ibkr_last_check" not in st.session_state:
        st.session_state.room3_ibkr_last_check = ""
    if "room3_ibkr_port_mode" not in st.session_state:
        st.session_state.room3_ibkr_port_mode = ""
    if "room3_alpaca_status" not in st.session_state:
        st.session_state.room3_alpaca_status = "disconnected"
    if "room3_alpaca_account" not in st.session_state:
        st.session_state.room3_alpaca_account = ""
    if "room3_alpaca_last_check" not in st.session_state:
        st.session_state.room3_alpaca_last_check = ""
    if "room3_broker" not in st.session_state:
        st.session_state.room3_broker = "alpaca"  # alpaca | ibkr
    if "room3_pending_reviews" not in st.session_state:
        st.session_state.room3_pending_reviews = []
    if "room3_strategy_feedback" not in st.session_state:
        st.session_state.room3_strategy_feedback = {}
    if "room3_decay_alerts" not in st.session_state:
        st.session_state.room3_decay_alerts = []
    if "room3_matrix_sync_log" not in st.session_state:
        st.session_state.room3_matrix_sync_log = []
    if "room3_archive_days" not in st.session_state:
        st.session_state.room3_archive_days = []
    if "room3_history_open_day" not in st.session_state:
        st.session_state.room3_history_open_day = None
    if "room3_history_open_trade_id" not in st.session_state:
        st.session_state.room3_history_open_trade_id = None
    if "room3_session_day_key" not in st.session_state:
        st.session_state.room3_session_day_key = ""
    if "room3_equity_curve" not in st.session_state:
        st.session_state.room3_equity_curve = []
    if "room3_starting_equity" not in st.session_state:
        st.session_state.room3_starting_equity = ROOM3_DEFAULT_EQUITY
    if "room3_tradable_today" not in st.session_state:
        st.session_state.room3_tradable_today = float(ROOM3_DEFAULT_EQUITY)
    if "room3_tradable_pct_ui" not in st.session_state:
        st.session_state.room3_tradable_pct_ui = 100.0
    if "room3_engine_armed" not in st.session_state:
        st.session_state.room3_engine_armed = False
    if "room3_kill_flat" not in st.session_state:
        st.session_state.room3_kill_flat = False
    if "room3_pause_entries" not in st.session_state:
        st.session_state.room3_pause_entries = False
    if "room3_allowed_sessions" not in st.session_state:
        st.session_state.room3_allowed_sessions = [
            room3_engine.SESSION_PRE,
            room3_engine.SESSION_RTH,
            room3_engine.SESSION_POST,
        ]
    if "room3_broker_equity" not in st.session_state:
        st.session_state.room3_broker_equity = 0.0
    if "room3_last_broker_sync" not in st.session_state:
        st.session_state.room3_last_broker_sync = ""
    if "room3_auto_event_log" not in st.session_state:
        st.session_state.room3_auto_event_log = []
    if "room3_broker_truth" not in st.session_state:
        st.session_state.room3_broker_truth = False
    if "room3_watch_book" not in st.session_state:
        st.session_state.room3_watch_book = room3_watcher.empty_book()
    if "room3_filter_universe" not in st.session_state:
        st.session_state.room3_filter_universe = []


def _inject_room3_css() -> None:
    st.markdown(
        """
        <style>
        .room3-shell {
            border: 1px solid #2A2A2A;
            border-radius: 14px;
            padding: 18px 20px;
            background: linear-gradient(180deg, #161616 0%, #101010 100%);
            margin-bottom: 16px;
        }
        .room3-shell-paper {
            border: 2px solid #C44B4B;
            box-shadow: 0 0 0 1px #5A2020 inset, 0 0 24px rgba(180, 50, 50, 0.12);
        }
        .room3-shell-live {
            border: 2px solid #3B6EA5;
            box-shadow: 0 0 0 1px #1E3A5F inset, 0 0 24px rgba(59, 110, 165, 0.18);
            background: linear-gradient(180deg, #0F1620 0%, #0B0B0B 100%);
        }
        .room3-paper-frame {
            border: 2px solid #B33A3A;
            border-radius: 14px;
            padding: 14px 14px 8px;
            margin: 0 0 12px 0;
            box-shadow: inset 0 0 0 1px rgba(180, 60, 60, 0.35);
        }
        .room3-live-frame {
            border: 2px solid #3B6EA5;
            border-radius: 14px;
            padding: 14px 14px 8px;
            margin: 0 0 12px 0;
            box-shadow: inset 0 0 0 1px rgba(59, 110, 165, 0.35);
        }
        div[data-testid="stMetric"] {
            background: #1C1C1C !important;
            border: 1px solid #333333 !important;
            border-radius: 10px !important;
            padding: 8px 10px !important;
            overflow: visible !important;
        }
        div[data-testid="stMetricLabel"] p {
            color: #9A9A9A !important;
            font-size: 11px !important;
        }
        div[data-testid="stMetricValue"] {
            color: #F0F0F0 !important;
            font-size: 1.05rem !important;
            overflow: visible !important;
            white-space: normal !important;
            word-break: break-word !important;
            line-height: 1.25 !important;
        }
        div[data-testid="stMetricDelta"] {
            overflow: visible !important;
            white-space: normal !important;
        }
        .room3-metric-grid {
            display: grid;
            gap: 8px;
            margin: 4px 0 10px 0;
        }
        .room3-metric-grid-2 {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .room3-metric-grid-auto {
            grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
        }
        .room3-metric-tile {
            background: #1C1C1C;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 8px 10px;
            min-width: 0;
            cursor: default;
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        .room3-metric-tile:hover {
            border-color: #555;
            box-shadow: 0 0 0 1px rgba(255,255,255,0.04);
        }
        .room3-metric-label {
            font-size: 10px;
            color: #8A8A8A;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            margin-bottom: 4px;
        }
        .room3-metric-value {
            font-size: 14px;
            font-weight: 700;
            color: #F0F0F0;
            line-height: 1.25;
            word-break: break-word;
            overflow-wrap: anywhere;
        }
        .room3-metric-value.pos { color: #7BC67E; }
        .room3-metric-value.neg { color: #FF6B6B; }
        .room3-metric-sub {
            font-size: 11px;
            color: #888;
            margin-top: 3px;
            word-break: break-word;
        }
        .room3-metric-expand {
            border: 1px solid #2A2A2A;
            border-radius: 10px;
            padding: 10px 12px;
            margin: 0 0 10px 0;
            background: #121212;
            animation: room3SlideIn 0.2s ease-out;
            font-size: 13px;
            color: #DDD;
            line-height: 1.45;
        }
        .room3-metric-expand strong { color: #FFF; }
        .room3-equity-chart {
            border: 1px solid #2C3036;
            border-radius: 12px;
            background: linear-gradient(180deg, #1A1D22 0%, #14171B 100%);
            padding: 12px 12px 8px;
            margin: 8px 0 6px 0;
        }
        .room3-equity-chart-title {
            font-size: 10px;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #7A8490;
            margin-bottom: 8px;
        }
        .room3-equity-insights {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
            margin: 4px 0 8px 0;
        }
        .room3-equity-insight {
            border: 1px solid #2A2E34;
            border-radius: 8px;
            background: #16191E;
            padding: 7px 9px;
            font-size: 11px;
            color: #A8B0BA;
            line-height: 1.35;
        }
        .room3-equity-insight strong {
            color: #D6DCE4;
            font-weight: 650;
        }
        .room3-equity-insight .hi { color: #7BC67E; }
        .room3-equity-insight .lo { color: #E07A7A; }
        .room3-equity-insight .mid { color: #9BB0C2; }
        .room3-capital-strip {
            border: 1px solid #2C3036;
            border-radius: 12px;
            background: linear-gradient(135deg, #1A1D22 0%, #14171B 55%, #171A1F 100%);
            padding: 14px 16px 12px;
            margin: 8px 0 12px 0;
        }
        .room3-capital-grid {
            display: grid;
            grid-template-columns: 1.1fr 1fr;
            gap: 14px;
            align-items: end;
        }
        .room3-capital-label {
            font-size: 10px;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #7A8490;
            margin-bottom: 4px;
        }
        .room3-capital-value {
            font-size: 22px;
            font-weight: 700;
            color: #E8EEF4;
            line-height: 1.15;
            word-break: break-word;
        }
        .room3-capital-value.deploy {
            color: #B7C9D8;
        }
        .room3-capital-sub {
            font-size: 11px;
            color: #7E8894;
            margin-top: 3px;
        }
        .room3-capital-bar {
            margin-top: 12px;
            height: 6px;
            border-radius: 999px;
            background: #252A31;
            overflow: hidden;
        }
        .room3-capital-bar > span {
            display: block;
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, #6E8494 0%, #A8BCCB 100%);
        }
        [data-testid="stDataFrame"] {
            background: #141414 !important;
            border: 1px solid #2A2A2A !important;
            border-radius: 10px !important;
        }
        [data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
            background: #141414 !important;
        }
        [data-testid="stDataFrame"] th {
            background: #1A1A1A !important;
            color: #B0B0B0 !important;
        }
        [data-testid="stDataFrame"] td {
            background: #141414 !important;
            color: #E8E8E8 !important;
        }
        .room3-kicker {
            font-size: 11px;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #777;
            margin-bottom: 6px;
        }
        .room3-title {
            font-size: 22px;
            font-weight: 700;
            color: #FFFFFF;
            margin: 0 0 4px 0;
        }
        .room3-sub {
            font-size: 13px;
            color: #888;
            margin: 0;
        }
        .room3-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }
        .room3-pill-paper { background: #1A2A1A; color: #7BC67E; border: 1px solid #2E4A2E; }
        .room3-pill-live { background: #3A1515; color: #FF6B6B; border: 1px solid #6A2020; }
        .room3-pill-off { background: #1A1A1A; color: #888; border: 1px solid #333; }
        .room3-gate-backdrop {
            border: 1px solid #333;
            border-radius: 16px;
            padding: 28px 24px 22px;
            background: #0F0F0F;
            box-shadow: 0 24px 80px rgba(0,0,0,0.55);
            text-align: center;
            max-width: 420px;
            margin: 12px auto 8px auto;
        }
        .room3-gate-wrap {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 8px 0 4px;
        }
        .room3-gate-actions {
            max-width: 420px;
            margin: 0 auto;
        }
        .room3-card {
            border: 1px solid #333333;
            border-radius: 12px;
            padding: 14px 16px;
            background: #1A1A1A;
            margin-bottom: 12px;
        }
        .room3-stat-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.08em; }
        .room3-stat-value { font-size: 20px; font-weight: 700; color: #EEE; }
        .room3-review-card {
            border: 1px solid #2A2A2A;
            border-radius: 10px;
            padding: 12px 14px;
            margin-bottom: 10px;
            background: #101010;
        }
        .room3-verdict-good { color: #7BC67E; font-weight: 700; }
        .room3-verdict-bad { color: #FF6B6B; font-weight: 700; }
        .room3-history-wrap {
            margin-top: 8px;
        }
        .room3-history-day-btn {
            margin-bottom: 6px;
        }
        .room3-history-panel {
            border: 1px solid #2A2A2A;
            border-radius: 10px;
            padding: 12px 14px;
            margin: 4px 0 12px 0;
            background: #121212;
            animation: room3SlideIn 0.22s ease-out;
        }
        .room3-history-trade-row {
            margin: 4px 0;
        }
        .room3-history-detail {
            border: 1px solid #333;
            border-radius: 8px;
            padding: 10px 12px;
            margin: 6px 0 10px 0;
            background: #0E0E0E;
            animation: room3SlideIn 0.2s ease-out;
        }
        .room3-history-detail p {
            margin: 4px 0;
            font-size: 13px;
            color: #C8C8C8;
        }
        @keyframes room3SlideIn {
            from { opacity: 0; transform: translateY(-6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .room3-broker-badge-row {
            display: flex;
            justify-content: flex-end;
            margin: 0 0 10px 0;
        }
        .room3-broker-badge {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 7px 12px 7px 8px;
            border-radius: 999px;
            border: 1px solid #333;
            background: linear-gradient(135deg, #1A1A1A 0%, #121212 100%);
            box-shadow: 0 8px 24px rgba(0,0,0,0.35);
            animation: room3BadgeIn 0.45s ease-out;
            max-width: 100%;
        }
        .room3-broker-badge--on {
            border-color: #3A5A3A;
            box-shadow: 0 0 0 1px rgba(80, 140, 90, 0.18), 0 8px 24px rgba(0,0,0,0.35);
        }
        .room3-broker-badge--alpaca.room3-broker-badge--on {
            border-color: #8A6A18;
            background: linear-gradient(135deg, #1C1810 0%, #12100C 100%);
            box-shadow: 0 0 0 1px rgba(212, 168, 55, 0.2), 0 8px 24px rgba(0,0,0,0.35);
        }
        .room3-broker-badge--ibkr.room3-broker-badge--on {
            border-color: #6A2020;
            background: linear-gradient(135deg, #1C1010 0%, #120C0C 100%);
            box-shadow: 0 0 0 1px rgba(180, 60, 60, 0.22), 0 8px 24px rgba(0,0,0,0.35);
        }
        .room3-broker-badge--off {
            border-color: #2E2E2E;
            opacity: 0.92;
        }
        .room3-broker-badge-mark {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            overflow: hidden;
        }
        .room3-broker-badge--alpaca .room3-broker-badge-mark {
            background: #F2C94C;
        }
        .room3-broker-badge--ibkr .room3-broker-badge-mark {
            background: #C8102E;
        }
        .room3-broker-badge--none .room3-broker-badge-mark {
            background: #2A2A2A;
            border: 1px solid #3A3A3A;
        }
        .room3-broker-badge-mark svg {
            width: 18px;
            height: 18px;
            display: block;
        }
        .room3-broker-badge-copy {
            display: flex;
            flex-direction: column;
            gap: 1px;
            min-width: 0;
            line-height: 1.15;
        }
        .room3-broker-badge-name {
            font-size: 12px;
            font-weight: 700;
            color: #F0F0F0;
            letter-spacing: 0.02em;
        }
        .room3-broker-badge-state {
            font-size: 10px;
            color: #8A8A8A;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }
        .room3-broker-badge--on .room3-broker-badge-state {
            color: #8FCB92;
        }
        .room3-broker-badge--alpaca.room3-broker-badge--on .room3-broker-badge-state {
            color: #E0C56A;
        }
        .room3-broker-badge--ibkr.room3-broker-badge--on .room3-broker-badge-state {
            color: #E08A8A;
        }
        .room3-broker-badge-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: #555;
            flex-shrink: 0;
            margin-left: 2px;
        }
        .room3-broker-badge--on .room3-broker-badge-dot {
            background: #6BCF70;
            box-shadow: 0 0 0 0 rgba(107, 207, 112, 0.55);
            animation: room3Pulse 1.8s ease-out infinite;
        }
        .room3-broker-badge--wait .room3-broker-badge-dot {
            background: #C9A227;
            animation: room3Pulse 1.2s ease-out infinite;
        }
        @keyframes room3BadgeIn {
            from { opacity: 0; transform: translateY(-8px) scale(0.96); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes room3Pulse {
            0% { box-shadow: 0 0 0 0 rgba(107, 207, 112, 0.45); }
            70% { box-shadow: 0 0 0 8px rgba(107, 207, 112, 0); }
            100% { box-shadow: 0 0 0 0 rgba(107, 207, 112, 0); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _mode_label(mode: str) -> str:
    return "Paper Trading" if mode == ROOM3_MODE_PAPER else "Live Trading"


def _request_live_mode() -> None:
    if not ROOM3_LIVE_SECURITY_ENABLED:
        st.session_state.room3_execution_mode = ROOM3_MODE_LIVE
        st.session_state.room3_live_unlocked = True
        st.session_state.room3_live_gate_open = False
        return
    if st.session_state.room3_live_unlocked:
        st.session_state.room3_execution_mode = ROOM3_MODE_LIVE
        st.session_state.room3_live_gate_open = False
        return
    st.session_state.room3_execution_mode = ROOM3_MODE_PAPER
    st.session_state.room3_live_gate_open = True
    st.session_state.room3_recovery_stage = ""


def _render_mode_slider() -> None:
    init_room3_session_state()
    mode = str(st.session_state.room3_execution_mode or ROOM3_MODE_PAPER)
    if mode not in (ROOM3_MODE_PAPER, ROOM3_MODE_LIVE):
        mode = ROOM3_MODE_PAPER

    st.markdown("#### Execution lane")
    cols = st.columns([1, 1, 2])
    with cols[0]:
        paper_active = mode == ROOM3_MODE_PAPER
        if st.button(
            "📄 Paper Trading",
            key="room3_mode_paper_btn",
            use_container_width=True,
            type="primary" if paper_active else "secondary",
        ):
            st.session_state.room3_execution_mode = ROOM3_MODE_PAPER
            st.session_state.room3_live_gate_open = False
            st.rerun()
    with cols[1]:
        live_active = mode == ROOM3_MODE_LIVE and st.session_state.room3_live_unlocked
        if st.button(
            "🔴 Live Trading",
            key="room3_mode_live_btn",
            use_container_width=True,
            type="primary" if live_active else "secondary",
        ):
            _request_live_mode()
            st.rerun()
    with cols[2]:
        if mode == ROOM3_MODE_LIVE and st.session_state.room3_live_unlocked:
            st.markdown(
                "<span class='room3-pill room3-pill-live'>LIVE ARMED · SESSION UNLOCKED</span>",
                unsafe_allow_html=True,
            )
        elif st.session_state.room3_live_unlocked:
            st.markdown(
                "<span class='room3-pill room3-pill-paper'>LIVE PASSCODE OK · PAPER ACTIVE</span>",
                unsafe_allow_html=True,
            )
        elif ROOM3_LIVE_SECURITY_ENABLED:
            st.markdown(
                "<span class='room3-pill room3-pill-off'>LIVE LOCKED · PASSCODE REQUIRED</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<span class='room3-pill room3-pill-paper'>DEV · LIVE GATE OFF</span>",
                unsafe_allow_html=True,
            )


def _render_live_gate_overlay() -> None:
    if not st.session_state.room3_live_gate_open:
        return

    st.markdown("<div class='room3-gate-wrap'>", unsafe_allow_html=True)
    st.markdown(
        "<div class='room3-gate-backdrop'>"
        "<div class='room3-kicker'>Live gate</div>"
        "<div class='room3-title'>Enter passcode</div>"
        "<p class='room3-sub'>Unlock live for this session only.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    expected_plain = _configured_passcode_plain()
    if expected_plain is None:
        st.warning("Passcode missing — add ROOM3_LIVE_PASSCODE to secrets and restart.")
    else:
        st.caption("Passcode loaded · enter code to unlock live.")

    gate_msg = str(st.session_state.get("room3_gate_message") or "").strip()
    gate_err = bool(st.session_state.get("room3_gate_error"))
    if gate_msg:
        if gate_err:
            st.error(gate_msg)
        else:
            st.success(gate_msg)
        st.session_state.room3_gate_message = ""
        st.session_state.room3_gate_error = False

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        entered = st.text_input(
            "Passcode",
            type="password",
            placeholder="••••••",
            label_visibility="collapsed",
            key="room3_live_passcode_input",
        )
        unlock_clicked = st.button(
            "Unlock live trading",
            key="room3_unlock_live_btn",
            type="primary",
            use_container_width=True,
        )

    if unlock_clicked:
        code = str(entered or st.session_state.get("room3_live_passcode_input") or "")
        _try_unlock_with_passcode(code)
        st.rerun()

    _, btn_col, _ = st.columns([1, 1.2, 1])
    with btn_col:
        if st.button("Cancel — stay on paper", key="room3_gate_cancel", use_container_width=True):
            st.session_state.room3_live_gate_open = False
            st.session_state.room3_execution_mode = ROOM3_MODE_PAPER
            st.rerun()
        if st.button("Forgot passcode?", key="room3_forgot_passcode", use_container_width=True):
            st.session_state.room3_recovery_stage = "offer_email"
            token = py_secrets.token_hex(3).upper()
            st.session_state.room3_recovery_token = token
            st.rerun()

    stage = str(st.session_state.room3_recovery_stage or "")
    if stage == "offer_email":
        st.info(f"Notification sent to **{ROOM3_RECOVERY_EMAIL}** (demo — no email yet).")
        if st.button("I received it", key="room3_recovery_ack", use_container_width=True):
            st.session_state.room3_recovery_stage = "enter_recovery_code"
            st.rerun()

    if stage == "enter_recovery_code":
        st.caption(f"Enter code from **{ROOM3_RECOVERY_EMAIL}**")
        if st.session_state.room3_recovery_token:
            st.caption(f"Demo code: `{st.session_state.room3_recovery_token}`")
        recovery_input = st.text_input(
            "Recovery code",
            placeholder="6-digit",
            label_visibility="collapsed",
            key="room3_recovery_code_input",
        )
        if st.button("Verify", key="room3_recovery_verify_btn", use_container_width=True):
            token_ok = (
                recovery_input.strip().upper()
                == str(st.session_state.room3_recovery_token or "").strip().upper()
            )
            recovery_plain = _configured_recovery_plain()
            secret_ok = recovery_plain and recovery_input.strip() == recovery_plain
            if token_ok or secret_ok:
                st.session_state.room3_recovery_stage = "reset_passcode"
                st.session_state.room3_gate_message = "Verified — enter passcode again."
                st.session_state.room3_gate_error = False
            else:
                st.session_state.room3_gate_message = "Recovery code did not match."
                st.session_state.room3_gate_error = True
            st.rerun()

    if stage == "reset_passcode":
        st.text_input(
            "Passcode",
            type="password",
            label_visibility="collapsed",
            key="room3_recovery_passcode_input",
        )
        if st.button(
            "Unlock live trading",
            key="room3_recovery_unlock_btn",
            use_container_width=True,
            type="primary",
        ):
            entered = str(st.session_state.get("room3_recovery_passcode_input") or "")
            if _passcode_matches(entered, expected_plain):
                _unlock_live_session()
                st.rerun()
            else:
                st.session_state.room3_gate_message = "Wrong passcode."
                st.session_state.room3_gate_error = True
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def _trading_day_key() -> str:
    """Trading session date — rolls at 4:00 AM Eastern."""
    now = datetime.now(ET)
    if now.hour < ROOM3_SESSION_ROLL_HOUR_ET:
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


def _trading_day_display(day_key: str) -> str:
    try:
        dt = datetime.strptime(day_key, "%Y-%m-%d")
        return dt.strftime("%A, %b %d")
    except ValueError:
        return day_key


def _maybe_roll_trading_session() -> None:
    """Reset intraday RAM when the trading day rolls (4 AM ET). Archive not wired yet."""
    key = _trading_day_key()
    prev = str(st.session_state.room3_session_day_key or "")
    if not prev:
        st.session_state.room3_session_day_key = key
        return
    if prev == key:
        return
    st.session_state.room3_session_day_key = key
    # Archive current day later when IBKR hose is live; reset intraday RAM for new session.
    st.session_state.room3_open_positions = []
    st.session_state.room3_pending_reviews = []
    st.session_state.room3_trade_history = []
    st.session_state.room3_operator_reviews = []
    st.session_state.room3_strategy_feedback = {}
    st.session_state.room3_decay_alerts = []
    # Eyes: drop unused TF maps that scanned all day with no trade
    st.session_state.room3_watch_book = room3_watcher.purge_untouched_maps(
        st.session_state.get("room3_watch_book") or room3_watcher.empty_book()
    )
    st.session_state.room3_filter_universe = []
    log = list(st.session_state.room3_matrix_sync_log or [])
    log.append(f"Session rolled · new trading day {key} (4 AM ET) · watch maps purged")
    st.session_state.room3_matrix_sync_log = log[-12:]


def _sync_equity_curve_with_today() -> None:
    """Keep the equity curve aligned with archive days + live day P/L."""
    start = float(st.session_state.room3_starting_equity or ROOM3_DEFAULT_EQUITY)
    archive = sorted(
        list(st.session_state.room3_archive_days or []),
        key=lambda d: str(d.get("date") or ""),
    )
    running = start
    rebuilt: list[dict] = [{"date": "Start", "equity": start}]
    for day in archive:
        running = round(running + float(day.get("pl_usd") or 0), 2)
        rebuilt.append(
            {
                "date": str(day.get("date") or ""),
                "equity": running,
                "day_pl": float(day.get("pl_usd") or 0),
            }
        )
    day_pl = float(_session_pl_stats().get("day_pl") or 0)
    today_eq = round(running + day_pl, 2)
    # Broker is truth when connected — don't invent equity from local P/L only.
    if st.session_state.get("room3_broker_truth"):
        broker_eq = float(st.session_state.get("room3_broker_equity") or 0)
        if broker_eq > 0:
            today_eq = broker_eq
    rebuilt.append({"date": _trading_day_key(), "equity": today_eq, "day_pl": day_pl})
    st.session_state.room3_equity_curve = rebuilt
    st.session_state.room3_account_equity = today_eq

    # Stamp end-of-day account on each archived session
    equity_by_date = {
        str(p.get("date")): float(p.get("equity") or 0)
        for p in rebuilt
        if str(p.get("date")) != "Start"
    }
    stamped = []
    for day in list(st.session_state.room3_archive_days or []):
        row = dict(day)
        dk = str(row.get("date") or "")
        if dk in equity_by_date:
            row["end_equity"] = equity_by_date[dk]
        stamped.append(row)
    st.session_state.room3_archive_days = stamped


def _all_time_stats() -> dict:
    _sync_equity_curve_with_today()
    start = float(st.session_state.room3_starting_equity or ROOM3_DEFAULT_EQUITY)
    curve = list(st.session_state.room3_equity_curve or [])
    current = float(curve[-1]["equity"]) if curve else float(
        st.session_state.room3_account_equity or start
    )
    equities = [float(p.get("equity") or 0) for p in curve] or [start]
    peak = max(equities)
    max_dd = 0.0
    peak_so_far = equities[0]
    for eq in equities:
        peak_so_far = max(peak_so_far, eq)
        dd = (peak_so_far - eq) / peak_so_far * 100.0 if peak_so_far else 0.0
        max_dd = max(max_dd, dd)
    all_time_pl = current - start
    all_time_pct = (all_time_pl / start * 100.0) if start else 0.0
    archive = list(st.session_state.room3_archive_days or [])
    today_trades = int(_session_pl_stats().get("trades_today") or 0)
    sessions = len(archive) + (1 if today_trades else 0)
    total_trades = sum(int(d.get("trade_count") or 0) for d in archive) + today_trades
    session_pls = [
        float(p.get("day_pl") or 0)
        for p in curve
        if str(p.get("date")) != "Start"
    ]
    avg_session = (sum(session_pls) / len(session_pls)) if session_pls else 0.0
    up_sessions = sum(1 for pl in session_pls if pl > 0)
    session_wr = (up_sessions / len(session_pls) * 100.0) if session_pls else 0.0
    return {
        "start": start,
        "current": current,
        "all_time_pl": all_time_pl,
        "all_time_pct": all_time_pct,
        "peak": peak,
        "max_drawdown_pct": max_dd,
        "sessions": sessions,
        "total_trades": total_trades,
        "avg_session_pl": avg_session,
        "session_win_rate": session_wr,
        "curve": curve,
    }



def _session_pl_stats() -> dict:
    equity = float(st.session_state.room3_account_equity or ROOM3_DEFAULT_EQUITY)
    open_rows = st.session_state.room3_open_positions or []
    pending = st.session_state.room3_pending_reviews or []
    history = st.session_state.room3_trade_history or []
    open_pl = sum(float(r.get("pnl_usd") or 0) for r in open_rows)
    closed_pl = sum(float(r.get("pnl_usd") or 0) for r in pending)
    closed_pl += sum(float(r.get("pnl_usd") or 0) for r in history if r.get("reviewed"))
    day_pl = open_pl + closed_pl
    wins = sum(
        1 for r in list(pending) + list(history)
        if float(r.get("pnl_usd") or 0) > 0
    )
    losses = sum(
        1 for r in list(pending) + list(history)
        if float(r.get("pnl_usd") or 0) < 0
    )
    decided = wins + losses
    win_rate = (wins / decided * 100.0) if decided else 0.0
    trades_today = len(pending) + len(history)
    awaiting_review = len(pending)
    tradable = _clamp_tradable(equity)
    return {
        "equity": equity,
        "tradable": tradable,
        "tradable_pct": (tradable / equity * 100.0) if equity > 0 else 0.0,
        "day_pl": day_pl,
        "day_pl_pct": (day_pl / equity * 100.0) if equity > 0 else 0.0,
        "open_pl": open_pl,
        "closed_pl": closed_pl,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "open_count": len(open_rows),
        "trades_today": trades_today,
        "awaiting_review": awaiting_review,
    }


def _clamp_tradable(equity: float | None = None) -> float:
    eq = float(equity if equity is not None else (st.session_state.room3_account_equity or 0))
    raw = float(st.session_state.get("room3_tradable_today") or 0)
    if eq <= 0:
        st.session_state.room3_tradable_today = 0.0
        return 0.0
    clamped = max(0.0, min(raw, eq))
    st.session_state.room3_tradable_today = clamped
    return clamped


def _set_tradable_pct(pct: float, equity: float) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    st.session_state.room3_tradable_pct_ui = pct
    st.session_state.room3_tradable_today = round(equity * (pct / 100.0), 2)


def _record_operator_review(trade_id: str, vote: str) -> None:
    """RAM-only — logs what would sync to matrix later."""
    vote_clean = "good" if str(vote).lower().startswith("g") else "bad"
    pending = list(st.session_state.room3_pending_reviews or [])
    trade = next((t for t in pending if str(t.get("id")) == str(trade_id)), None)
    if not trade:
        return
    st.session_state.room3_pending_reviews = [t for t in pending if str(t.get("id")) != str(trade_id)]
    reviewed = dict(trade)
    reviewed["operator_vote"] = vote_clean
    reviewed["reviewed"] = True
    reviewed["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    st.session_state.room3_operator_reviews = list(st.session_state.room3_operator_reviews or []) + [reviewed]
    hist = list(st.session_state.room3_trade_history or [])
    hist.append(reviewed)
    st.session_state.room3_trade_history = hist

    strat = str(trade.get("strategy") or "unknown")
    fb = dict(st.session_state.room3_strategy_feedback or {})
    bucket = dict(fb.get(strat) or {"good": 0, "bad": 0})
    bucket[vote_clean] = int(bucket.get(vote_clean) or 0) + 1
    fb[strat] = bucket
    st.session_state.room3_strategy_feedback = fb

    sync_line = (
        f"[DRY-RUN] {trade.get('ticker')} · {strat} · operator={vote_clean} · "
        "matrix sync skipped (hose not connected)"
    )
    log = list(st.session_state.room3_matrix_sync_log or [])
    log.append(sync_line)
    st.session_state.room3_matrix_sync_log = log[-12:]

    alerts = list(st.session_state.room3_decay_alerts or [])
    if bucket.get("bad", 0) >= 2:
        alert = f"Alpha decay watch — {strat} marked bad {bucket['bad']}× today (local only)."
        if alert not in alerts:
            alerts.append(alert)
    st.session_state.room3_decay_alerts = alerts


def _undo_operator_review(trade_id: str) -> None:
    """Move a reviewed trade back to pending — undo an accidental vote."""
    trade_id = str(trade_id or "").strip()
    if not trade_id:
        return
    reviewed = list(st.session_state.room3_operator_reviews or [])
    history = list(st.session_state.room3_trade_history or [])
    match = next((t for t in reviewed if str(t.get("id")) == trade_id), None)
    if match is None:
        match = next((t for t in history if str(t.get("id")) == trade_id and t.get("reviewed")), None)
    if match is None:
        return
    restored = dict(match)
    old_vote = str(restored.pop("operator_vote", "")).strip()
    restored.pop("reviewed", None)
    restored.pop("reviewed_at", None)
    st.session_state.room3_operator_reviews = [
        t for t in reviewed if str(t.get("id")) != trade_id
    ]
    st.session_state.room3_trade_history = [
        t for t in history if str(t.get("id")) != trade_id
    ]
    pending = list(st.session_state.room3_pending_reviews or [])
    pending.append(restored)
    st.session_state.room3_pending_reviews = pending

    if old_vote:
        strat = str(match.get("strategy") or "unknown")
        fb = dict(st.session_state.room3_strategy_feedback or {})
        bucket = dict(fb.get(strat) or {"good": 0, "bad": 0})
        bucket[old_vote] = max(0, int(bucket.get(old_vote) or 0) - 1)
        fb[strat] = bucket
        st.session_state.room3_strategy_feedback = fb

    log = list(st.session_state.room3_matrix_sync_log or [])
    log.append(
        f"[UNDO] {match.get('ticker')} · {match.get('strategy')} · "
        f"vote '{old_vote}' reverted — back to pending"
    )
    st.session_state.room3_matrix_sync_log = log[-12:]


def _fmt_pl_usd(value) -> str:
    v = float(value or 0)
    if v > 0:
        return f"+${v:,.2f}"
    if v < 0:
        return f"-${abs(v):,.2f}"
    return "$0.00"


def _fmt_pl_pct(value) -> str:
    v = float(value or 0)
    if v > 0:
        return f"+{v:.2f}%"
    if v < 0:
        return f"{v:.2f}%"
    return "0.00%"


def _metric_tone(value_text: str) -> str:
    text = str(value_text or "").strip()
    if text.startswith("+"):
        return "pos"
    if text.startswith("-") and text not in {"—", "-"}:
        return "neg"
    return ""


def _render_metric_tiles(
    items: list[dict],
    *,
    grid_class: str = "room3-metric-grid-2",
) -> None:
    """Compact metric tiles — full values stay visible (no truncation)."""
    cards_html = [f"<div class='room3-metric-grid {grid_class}'>"]
    for item in items:
        tone = _metric_tone(item.get("value"))
        tone_cls = f" {tone}" if tone else ""
        sub = item.get("sub") or ""
        tip = escape(str(item.get("detail") or f"{item.get('label')}: {item.get('value')}"))
        label = escape(str(item.get("label") or ""))
        value = escape(str(item.get("value") or "—"))
        sub_safe = escape(str(sub)) if sub else ""
        sub_html = f"<div class='room3-metric-sub'>{sub_safe}</div>" if sub_safe else ""
        cards_html.append(
            f"<div class='room3-metric-tile' title='{tip}'>"
            f"<div class='room3-metric-label'>{label}</div>"
            f"<div class='room3-metric-value{tone_cls}'>{value}</div>"
            f"{sub_html}"
            "</div>"
        )
    cards_html.append("</div>")
    st.markdown("".join(cards_html), unsafe_allow_html=True)


def _position_dollar_value(row: dict) -> float:
    qty = float(row.get("qty") or 0)
    mark = float(row.get("last_price") or row.get("exit_price") or row.get("entry_price") or 0)
    return round(qty * mark, 2)


def _render_dark_table(rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows)
    styled = df.style.set_properties(
        **{
            "background-color": "#141414",
            "color": "#E8E8E8",
            "border-color": "#2A2A2A",
        }
    ).set_table_styles(
        [
            {
                "selector": "thead th",
                "props": [
                    ("background-color", "#1A1A1A"),
                    ("color", "#B0B0B0"),
                    ("border-color", "#2A2A2A"),
                ],
            },
            {
                "selector": "tbody td",
                "props": [("border-color", "#252525")],
            },
        ]
    )

    def _pl_color(val):
        text = str(val)
        if text.startswith("+"):
            return "color: #7BC67E; font-weight: 600"
        if text.startswith("-") or text.startswith("-$"):
            return "color: #FF6B6B; font-weight: 600"
        return "color: #E8E8E8"

    pl_cols = [c for c in df.columns if "P/L" in str(c)]
    for col in pl_cols:
        styled = styled.map(_pl_color, subset=pd.IndexSlice[:, [col]])

    st.dataframe(styled, use_container_width=True, hide_index=True)


def _active_broker_name() -> str:
    broker = str(st.session_state.get("room3_broker") or "alpaca")
    return "Interactive Brokers" if broker == "ibkr" else "Alpaca"


def _broker_mark_svg(broker: str) -> str:
    """Tiny inline marks — stylized, not official trademark assets."""
    if broker == "ibkr":
        return (
            '<svg viewBox="0 0 24 24" aria-hidden="true">'
            '<text x="12" y="16" text-anchor="middle" '
            'font-size="11" font-weight="800" fill="#FFFFFF" '
            'font-family="Arial, Helvetica, sans-serif">IB</text>'
            "</svg>"
        )
    if broker == "alpaca":
        return (
            '<svg viewBox="0 0 24 24" aria-hidden="true">'
            '<ellipse cx="12" cy="14" rx="7" ry="6" fill="#1A1208"/>'
            '<circle cx="9.2" cy="12.5" r="1.1" fill="#F2C94C"/>'
            '<circle cx="14.8" cy="12.5" r="1.1" fill="#F2C94C"/>'
            '<path d="M8 7.5 C9 4.5 11 3.5 12 3.5 C13 3.5 15 4.5 16 7.5" '
            'fill="none" stroke="#1A1208" stroke-width="2.2" '
            'stroke-linecap="round"/>'
            '<path d="M10.5 16.5 Q12 18 13.5 16.5" fill="none" '
            'stroke="#F2C94C" stroke-width="1.2" stroke-linecap="round"/>'
            "</svg>"
        )
    return (
        '<svg viewBox="0 0 24 24" aria-hidden="true">'
        '<circle cx="12" cy="12" r="7" fill="none" stroke="#777" stroke-width="1.6"/>'
        '<path d="M8 12h8M12 8v8" stroke="#777" stroke-width="1.6" stroke-linecap="round"/>'
        "</svg>"
    )


def _render_broker_presence_chip() -> None:
    """Corner chip — which broker Room 3 thinks it's on, connected or not."""
    broker = str(st.session_state.get("room3_broker") or "alpaca")
    if broker == "ibkr":
        status = str(st.session_state.get("room3_ibkr_status") or "disconnected")
        name = "Interactive Brokers"
        mark_key = "ibkr"
    else:
        status = str(st.session_state.get("room3_alpaca_status") or "disconnected")
        name = "Alpaca"
        mark_key = "alpaca"

    if status == "connected":
        state_class = "room3-broker-badge--on"
        state_text = "Connected"
        equity = float(st.session_state.get("room3_account_equity") or 0)
        if broker == "alpaca" and equity > 0:
            state_text = f"Connected · ${equity:,.0f}"
    elif status == "waiting":
        state_class = "room3-broker-badge--wait"
        state_text = "Waiting…"
    else:
        state_class = "room3-broker-badge--off"
        state_text = "Currently not connected"

    html = (
        f"<div class='room3-broker-badge-row'>"
        f"<div class='room3-broker-badge room3-broker-badge--{mark_key} {state_class}' "
        f"title='Active broker hose'>"
        f"<span class='room3-broker-badge-mark'>{_broker_mark_svg(mark_key)}</span>"
        f"<span class='room3-broker-badge-copy'>"
        f"<span class='room3-broker-badge-name'>{name}</span>"
        f"<span class='room3-broker-badge-state'>{state_text}</span>"
        f"</span>"
        f"<span class='room3-broker-badge-dot'></span>"
        f"</div></div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _broker_connection_subtitle(mode: str) -> str:
    """Honest status line — which broker, paper/live, real connect vs idle."""
    lane = "LIVE" if mode == ROOM3_MODE_LIVE else "PAPER"
    broker = str(st.session_state.get("room3_broker") or "alpaca")
    name = _active_broker_name()

    if broker == "alpaca":
        status = str(st.session_state.get("room3_alpaca_status") or "disconnected")
        if status == "connected":
            equity = float(st.session_state.get("room3_account_equity") or 0)
            acct = str(st.session_state.get("room3_alpaca_account") or "").strip()
            core = f"<strong>Alpaca {lane}</strong> · connected"
            if equity > 0:
                core += f" · account <strong>${equity:,.2f}</strong>"
            if acct:
                core += f" · {acct.split('·')[0].strip()}"
            if mode == ROOM3_MODE_LIVE:
                core += " · <em>live lane idle until funded Alpaca or IBKR Pro</em>"
            return core
        if status == "waiting":
            return f"<strong>Alpaca {lane}</strong> · waiting for handshake"
        if mode == ROOM3_MODE_LIVE:
            return (
                f"<strong>Alpaca</strong> · live lane idle · "
                f"use <strong>Paper</strong> for the real hose right now"
            )
        return f"<strong>Alpaca PAPER</strong> · <strong>not connected</strong>"

    status = str(st.session_state.get("room3_ibkr_status") or "disconnected")
    if status == "connected":
        return f"<strong>IBKR {lane}</strong> · connected"
    if status == "waiting":
        return f"<strong>IBKR {lane}</strong> · waiting for Gateway/TWS"
    return (
        f"<strong>IBKR {lane}</strong> · <strong>not connected</strong> "
        f"(idle — API needs Pro; Alpaca paper is the working path)"
    )


def _render_broker_status_card(mode: str) -> None:
    is_live = mode == ROOM3_MODE_LIVE
    shell_class = "room3-shell"
    if is_live:
        shell_class += " room3-shell-live"
    else:
        shell_class += " room3-shell-paper"
    st.markdown(
        f"<div class='{shell_class}'>"
        f"<div class='room3-kicker'>Room 3 · Execution terminal · {_active_broker_name()}</div>"
        f"<div class='room3-title'>{_mode_label(mode)}</div>"
        f"<p class='room3-sub'>{_broker_connection_subtitle(mode)}</p>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_open_positions() -> None:
    st.markdown("### Open positions")
    rows = st.session_state.room3_open_positions or []
    if not rows:
        name = _active_broker_name()
        st.caption(f"No open trades — {name} positions show here when connected.")
        return
    display = []
    for r in rows:
        display.append(
            {
                "Ticker": r.get("ticker"),
                "TF": r.get("timeframe"),
                "Strategy": r.get("strategy"),
                "Entry": r.get("entry_time"),
                "Entry $": f"{float(r.get('entry_price') or 0):.2f}",
                "Exit $": f"{float(r.get('last_price') or 0):.2f}",
                "Position $": f"{_position_dollar_value(r):,.2f}",
                "P/L $": _fmt_pl_usd(r.get("pnl_usd")),
                "P/L %": _fmt_pl_pct(r.get("pnl_pct")),
            }
        )
    _render_dark_table(display)


def _render_trade_history() -> None:
    st.markdown("### Today's trade log")
    pending = st.session_state.room3_pending_reviews or []
    history = st.session_state.room3_trade_history or []
    rows = []
    for r in pending:
        rows.append(
            {
                "Ticker": r.get("ticker"),
                "TF": r.get("timeframe"),
                "Strategy": r.get("strategy"),
                "Entry": r.get("entry_time"),
                "Exit": r.get("exit_time"),
                "Entry $": f"{float(r.get('entry_price') or 0):.2f}",
                "Exit $": f"{float(r.get('exit_price') or 0):.2f}",
                "P/L $": _fmt_pl_usd(r.get("pnl_usd")),
                "P/L %": _fmt_pl_pct(r.get("pnl_pct")),
                "Status": "awaiting review",
            }
        )
    for r in history:
        rows.append(
            {
                "Ticker": r.get("ticker"),
                "TF": r.get("timeframe"),
                "Strategy": r.get("strategy"),
                "Entry": r.get("entry_time"),
                "Exit": r.get("exit_time"),
                "Entry $": (
                    f"{float(r.get('entry_price') or 0):.2f}"
                    if r.get("entry_price") is not None
                    else "—"
                ),
                "Exit $": (
                    f"{float(r.get('exit_price') or 0):.2f}"
                    if r.get("exit_price") is not None
                    else "—"
                ),
                "P/L $": _fmt_pl_usd(r.get("pnl_usd")),
                "P/L %": _fmt_pl_pct(r.get("pnl_pct")),
                "Status": f"reviewed · {r.get('operator_vote', '—')}",
            }
        )
    if not rows:
        st.caption("Log empty.")
        return
    _render_dark_table(rows)

    fb = st.session_state.room3_strategy_feedback or {}
    if fb:
        detail_parts = [
            f"{strat}: ✓{counts.get('good', 0)} ✗{counts.get('bad', 0)}"
            for strat, counts in fb.items()
        ]
        st.caption("Operator votes today · " + " · ".join(detail_parts))

    reviewed_in_log = [
        r for r in (st.session_state.room3_trade_history or [])
        if r.get("reviewed")
    ]
    if reviewed_in_log:
        with st.expander("Undo a review (move back to pending)", expanded=False):
            for r in reviewed_in_log:
                rid = str(r.get("id"))
                label = (
                    f"{r.get('ticker')} · {r.get('strategy')} · "
                    f"voted {r.get('operator_vote', '?')}"
                )
                if st.button(
                    f"↩ Undo: {label}",
                    key=f"room3_undo_{rid}",
                    use_container_width=True,
                ):
                    _undo_operator_review(rid)
                    st.rerun()


def _render_live_dashboard(mode: str) -> None:
    """Live-now strip — account moves with P/L; tradable cap sets today's firepower."""
    # Keep equity curve/account current before reading stats
    if st.session_state.get("room3_equity_curve") or st.session_state.get("room3_archive_days"):
        _sync_equity_curve_with_today()
    stats = _session_pl_stats()
    equity = float(stats["equity"])
    # First paint: if tradable still equals full account and equity > 0, nudge to 50%
    if (
        "room3_tradable_seen" not in st.session_state
        and equity > 0
        and abs(float(stats["tradable"]) - equity) < 0.01
    ):
        _set_tradable_pct(50.0, equity)
        st.session_state.room3_tradable_seen = True
        stats = _session_pl_stats()
    else:
        st.session_state.room3_tradable_seen = True
    tradable = float(stats["tradable"])
    pct = float(stats["tradable_pct"])
    day_label = _trading_day_display(_trading_day_key())

    st.markdown("### Live dashboard")
    st.caption(
        f"**{day_label}** · session rolls at 4:00 AM ET · "
        "account moves with fills · pause = flat"
    )

    with st.container(border=True):
        st.markdown("**Capital**")
        a1, a2 = st.columns(2)
        with a1:
            st.metric("Account", f"${equity:,.2f}")
            st.caption("Full balance · moves with day P/L")
        with a2:
            st.metric("Trading today", f"${tradable:,.2f}", delta=f"{pct:.0f}% of account", delta_color="off")
            st.caption("Only this amount is deployable today")
        st.progress(min(max(pct / 100.0, 0.0), 1.0))
        st.caption("Set today's firepower")
        p1, p2, p3, p4, p5 = st.columns([1, 1, 1, 1, 2])
        for col, preset in zip((p1, p2, p3, p4), (25, 50, 75, 100)):
            with col:
                if st.button(
                    f"{preset}%",
                    key=f"room3_tradable_pct_{preset}",
                    use_container_width=True,
                    type="primary" if abs(pct - preset) < 0.5 else "secondary",
                ):
                    _set_tradable_pct(preset, equity)
                    st.rerun()
        with p5:
            c_in, c_btn = st.columns([2.2, 1])
            with c_in:
                st.number_input(
                    "Custom trading $",
                    min_value=0.0,
                    max_value=float(max(equity, 0.0)),
                    value=float(min(tradable, equity)) if equity else 0.0,
                    step=1000.0,
                    key="room3_tradable_custom_input",
                    label_visibility="collapsed",
                )
            with c_btn:
                if st.button("Set $", key="room3_tradable_set_btn", use_container_width=True):
                    custom = float(st.session_state.get("room3_tradable_custom_input") or 0)
                    custom = max(0.0, min(custom, equity))
                    st.session_state.room3_tradable_today = round(custom, 2)
                    st.session_state.room3_tradable_pct_ui = (
                        (custom / equity * 100.0) if equity > 0 else 0.0
                    )
                    st.rerun()

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric(
            "Day P/L",
            _fmt_pl_usd(stats["day_pl"]),
            delta=f"{stats['day_pl_pct']:+.2f}%",
            delta_color="normal",
        )
    with c2:
        st.metric("Open unrealized", _fmt_pl_usd(stats["open_pl"]))
    with c3:
        st.metric("Open positions", stats["open_count"])
    with c4:
        st.metric("Wins / Losses", f"{stats['wins']} / {stats['losses']}")
    with c5:
        win_label = f"{stats['win_rate']:.0f}%" if stats["wins"] + stats["losses"] else "—"
        st.metric("Win rate", win_label)
    if mode == ROOM3_MODE_LIVE:
        st.caption(
            "Live lane: orders hard-disabled · paper auto path is the working hose"
        )
    else:
        if st.session_state.get("room3_kill_flat"):
            st.caption("Kill switch: **FLAT** — all auto orders blocked")
        elif st.session_state.get("room3_pause_entries"):
            st.caption("Entries **paused** · exits still allowed when gates pass")
        elif st.session_state.get("room3_engine_armed") and _broker_is_connected():
            st.caption("Kill switch: **SAFE** · engine **ARMED** · waiting for matrix signals")
        elif _broker_is_connected():
            st.caption("Kill switch: **SAFE** · engine **DISARMED** — arm to allow auto orders")
        else:
            st.caption("Kill switch: **SAFE** (no broker connected)")


def _render_session_summary() -> None:
    """Today's recap — closed vs open vs account, plus session activity."""
    st.markdown("### Today's summary")
    stats = _session_pl_stats()
    awaiting = (
        f"{stats['awaiting_review']} awaiting review"
        if stats["awaiting_review"]
        else "all reviewed"
    )
    _render_metric_tiles(
        [
            {
                "id": "closed",
                "label": "Closed P/L",
                "value": _fmt_pl_usd(stats["closed_pl"]),
                "detail": f"Closed P/L {_fmt_pl_usd(stats['closed_pl'])}",
            },
            {
                "id": "open_u",
                "label": "Open unrealized",
                "value": _fmt_pl_usd(stats["open_pl"]),
                "detail": f"Open unrealized {_fmt_pl_usd(stats['open_pl'])}",
            },
            {
                "id": "day_vs",
                "label": "Day vs account",
                "value": f"{stats['day_pl_pct']:+.2f}%",
                "sub": _fmt_pl_usd(stats["day_pl"]),
                "detail": (
                    f"Day vs account {stats['day_pl_pct']:+.2f}% · "
                    f"total day {_fmt_pl_usd(stats['day_pl'])}"
                ),
            },
            {
                "id": "trades",
                "label": "Trades today",
                "value": str(stats["trades_today"]),
                "sub": awaiting,
                "detail": f"{stats['trades_today']} trades today · {awaiting}",
            },
        ],
        grid_class="room3-metric-grid-2",
    )
    st.caption("Day % = (open + closed P/L) ÷ account equity.")
    with st.expander("All-time performance", expanded=False):
        _render_all_time_panel()


def _render_equity_trajectory_chart(at: dict, *, height: int = 220) -> None:
    """Dark custom SVG — equity path + session bars + non-obvious callouts."""
    curve = list(at.get("curve") or [])
    if len(curve) < 2:
        st.caption("Trajectory builds as sessions close.")
        return

    start = float(at.get("start") or curve[0].get("equity") or 0)
    peak = float(at.get("peak") or start)
    current = float(at.get("current") or curve[-1].get("equity") or start)
    points = curve
    equities = [float(p.get("equity") or 0) for p in points]
    day_pls = [float(p.get("day_pl") or 0) for p in points]
    labels = [str(p.get("date") or "") for p in points]

    sessions = [
        (labels[i], equities[i], day_pls[i])
        for i in range(1, len(points))
    ]
    best = max(sessions, key=lambda x: x[2]) if sessions else ("—", 0.0, 0.0)
    worst = min(sessions, key=lambda x: x[2]) if sessions else ("—", 0.0, 0.0)
    green_days = sum(1 for _, _, pl in sessions if pl > 0)
    red_days = sum(1 for _, _, pl in sessions if pl < 0)
    avg_day = (sum(pl for _, _, pl in sessions) / len(sessions)) if sessions else 0.0
    off_peak = peak - current
    off_peak_pct = (off_peak / peak * 100.0) if peak else 0.0
    above_start = sum(1 for _, eq, _ in sessions if eq >= start)

    w, h = 640, int(height)
    pad_l, pad_r, pad_t, pad_b = 48, 16, 18, 36
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    ymin = min(equities + [start]) * 0.995
    ymax = max(equities + [peak, start]) * 1.005
    if ymax <= ymin:
        ymax = ymin + 1.0

    def x_at(i: int) -> float:
        n = max(len(equities) - 1, 1)
        return pad_l + (i / n) * plot_w

    def y_at(eq: float) -> float:
        return pad_t + (1.0 - (eq - ymin) / (ymax - ymin)) * plot_h

    path_d = " ".join(
        f"{'M' if i == 0 else 'L'}{x_at(i):.1f},{y_at(eq):.1f}"
        for i, eq in enumerate(equities)
    )
    area_d = (
        f"{path_d} L{x_at(len(equities)-1):.1f},{pad_t + plot_h:.1f} "
        f"L{x_at(0):.1f},{pad_t + plot_h:.1f} Z"
    )

    y_start = y_at(start)
    y_peak = y_at(peak)

    bar_max = max((abs(pl) for pl in day_pls[1:]), default=1.0) or 1.0
    bars = []
    for i in range(1, len(points)):
        pl = day_pls[i]
        bh = max(3.0, (abs(pl) / bar_max) * (22.0 if height > 260 else 18.0))
        bx = x_at(i) - 5
        by = pad_t + plot_h + 4
        color = "#5F9E6E" if pl >= 0 else "#B86A6A"
        bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="10" height="{bh:.1f}" '
            f'rx="2" fill="{color}" opacity="0.85">'
            f'<title>{escape(labels[i])}: {_fmt_pl_usd(pl)}</title></rect>'
        )

    peak_i = equities.index(max(equities))
    markers = [
        f'<circle cx="{x_at(0):.1f}" cy="{y_at(equities[0]):.1f}" r="3.5" fill="#8FA3B0" />',
        f'<circle cx="{x_at(len(equities)-1):.1f}" cy="{y_at(equities[-1]):.1f}" r="4" '
        f'fill="#C5D0DA" stroke="#1A1D22" stroke-width="1.5" />',
        f'<circle cx="{x_at(peak_i):.1f}" cy="{y_peak:.1f}" r="3.5" fill="#D4B56A" />',
    ]

    short_labels = []
    for i, lab in enumerate(labels):
        if i == 0 or i == len(labels) - 1 or i == peak_i:
            shown = "Start" if lab == "Start" else lab[-5:] if len(lab) >= 5 else lab
            short_labels.append(
                f'<text x="{x_at(i):.1f}" y="{h - 6}" text-anchor="middle" '
                f'fill="#6E7884" font-size="9">{escape(shown)}</text>'
            )

    y_ticks = [(start, "start"), (current, "now"), (peak, "peak")]
    y_labels = []
    used_y = []
    for eq, _tag in y_ticks:
        yy = y_at(eq)
        if any(abs(yy - uy) < 12 for uy in used_y):
            continue
        used_y.append(yy)
        label_txt = f"${eq/1000:.1f}k" if eq >= 1000 else f"${eq:,.0f}"
        y_labels.append(
            f'<text x="4" y="{yy + 3:.1f}" fill="#6E7884" font-size="9">'
            f"{escape(label_txt)}</text>"
        )

    svg = f"""
    <div class="room3-equity-chart">
      <div class="room3-equity-chart-title">Equity trajectory · session P/L strip</div>
      <svg viewBox="0 0 {w} {h}" width="100%" height="{h}" role="img"
           aria-label="Account equity trajectory">
        <defs>
          <linearGradient id="room3EqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#6E8494" stop-opacity="0.28"/>
            <stop offset="100%" stop-color="#6E8494" stop-opacity="0.02"/>
          </linearGradient>
        </defs>
        <line x1="{pad_l}" y1="{y_start:.1f}" x2="{w - pad_r}" y2="{y_start:.1f}"
              stroke="#3A424C" stroke-width="1" stroke-dasharray="4 4"/>
        <line x1="{pad_l}" y1="{y_peak:.1f}" x2="{w - pad_r}" y2="{y_peak:.1f}"
              stroke="#5A5240" stroke-width="1" stroke-dasharray="3 5"/>
        <path d="{area_d}" fill="url(#room3EqFill)"/>
        <path d="{path_d}" fill="none" stroke="#9BB0C2" stroke-width="2.25"
              stroke-linecap="round" stroke-linejoin="round"/>
        {''.join(bars)}
        {''.join(markers)}
        {''.join(short_labels)}
        {''.join(y_labels)}
      </svg>
      <div class="room3-equity-insights">
        <div class="room3-equity-insight">
          <strong>Best session</strong><br>
          <span class="hi">{escape(str(best[0]))}</span> · {_fmt_pl_usd(best[2])}
        </div>
        <div class="room3-equity-insight">
          <strong>Worst session</strong><br>
          <span class="lo">{escape(str(worst[0]))}</span> · {_fmt_pl_usd(worst[2])}
        </div>
        <div class="room3-equity-insight">
          <strong>Off peak</strong><br>
          <span class="mid">{_fmt_pl_usd(-off_peak) if off_peak else "$0.00"}</span>
          · {off_peak_pct:.2f}% under high
        </div>
        <div class="room3-equity-insight">
          <strong>Session mix</strong><br>
          <span class="hi">{green_days} up</span> /
          <span class="lo">{red_days} down</span>
          · avg {_fmt_pl_usd(avg_day)} · {above_start}/{len(sessions)} above start
        </div>
      </div>
    </div>
    """
    st.markdown(svg, unsafe_allow_html=True)


def _render_all_time_panel() -> None:
    """Hidden all-time readout — collective P/L vs bankroll, risk, expectancy."""
    at = _all_time_stats()
    start = float(at["start"])
    _render_metric_tiles(
        [
            {
                "id": "at_pl",
                "label": "Collective P/L",
                "value": _fmt_pl_usd(at["all_time_pl"]),
                "sub": f"{_fmt_pl_pct(at['all_time_pct'])} vs ${start:,.0f} start",
                "detail": (
                    f"Net profit since bankroll open · "
                    f"{_fmt_pl_usd(at['all_time_pl'])} on ${start:,.2f} starting equity "
                    f"({_fmt_pl_pct(at['all_time_pct'])})"
                ),
            },
            {
                "id": "dd",
                "label": "Max drawdown",
                "value": f"{at['max_drawdown_pct']:.2f}%",
                "sub": f"peak was ${at['peak']:,.0f}",
                "detail": (
                    f"Worst peak-to-trough drop {at['max_drawdown_pct']:.2f}% · "
                    f"peak equity ${at['peak']:,.2f}"
                ),
            },
            {
                "id": "avg",
                "label": "Avg session",
                "value": _fmt_pl_usd(at["avg_session_pl"]),
                "sub": f"{at['sessions']} sessions",
                "detail": (
                    f"Average session P/L {_fmt_pl_usd(at['avg_session_pl'])} · "
                    f"{at['sessions']} sessions · {at['total_trades']} trades"
                ),
            },
            {
                "id": "swr",
                "label": "Session win rate",
                "value": f"{at['session_win_rate']:.0f}%",
                "sub": f"{at['total_trades']} trades total",
                "detail": (
                    f"Green sessions {at['session_win_rate']:.0f}% · "
                    f"{at['total_trades']} closed trades all-time"
                ),
            },
        ],
        grid_class="room3-metric-grid-2",
    )
    st.caption(
        f"Collective P/L = current account − starting bankroll "
        f"(${start:,.2f}). Not today’s P/L."
    )
    _render_equity_trajectory_chart(at, height=360)


def _render_history_trade_detail(trade: dict) -> None:
    vote = trade.get("operator_vote")
    vote_html = ""
    if vote:
        cls = "room3-verdict-good" if vote == "good" else "room3-verdict-bad"
        vote_html = f"<span class='{cls}'>Review: {vote}</span>"
    layout = trade.get("layout") or "—"
    qty = trade.get("qty")
    qty_line = f"<p>Qty <strong>{qty}</strong></p>" if qty else ""
    st.markdown(
        f"<div class='room3-history-detail'>"
        f"<p><strong>{trade.get('ticker')}</strong> · {trade.get('timeframe')} · "
        f"{trade.get('strategy')}</p>"
        f"<p>{layout}</p>"
        f"<p>Entry <strong>{trade.get('entry_time')}</strong> @ "
        f"${float(trade.get('entry_price') or 0):.2f} → "
        f"Exit <strong>{trade.get('exit_time')}</strong> @ "
        f"${float(trade.get('exit_price') or 0):.2f}</p>"
        f"{qty_line}"
        f"<p>P/L <strong>{_fmt_pl_usd(trade.get('pnl_usd'))}</strong> · "
        f"<strong>{_fmt_pl_pct(trade.get('pnl_pct'))}</strong></p>"
        f"{vote_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_session_history() -> None:
    st.markdown("---")
    st.markdown("### Session history")
    st.caption(
        "Past trading days · click a day to expand tickers · click a ticker for full detail · "
        "one panel open at a time"
    )
    # Ensure end_equity is stamped from curve
    if st.session_state.get("room3_archive_days"):
        _sync_equity_curve_with_today()
    days = list(st.session_state.room3_archive_days or [])
    if not days:
        st.caption("No archived sessions yet — filled days will land here after trading.")
        return

    open_day = st.session_state.room3_history_open_day
    open_trade = st.session_state.room3_history_open_trade_id

    st.markdown("<div class='room3-history-wrap'>", unsafe_allow_html=True)
    for day in days:
        date_key = str(day.get("date"))
        is_day_open = open_day == date_key
        pl_usd = _fmt_pl_usd(day.get("pl_usd"))
        pl_pct = _fmt_pl_pct(day.get("pl_pct"))
        end_eq = day.get("end_equity")
        eod = f" · EOD ${float(end_eq):,.2f}" if end_eq is not None else ""
        arrow = "▾" if is_day_open else "▸"
        day_label = (
            f"{arrow} {day.get('display')} · {day.get('trade_count')} trades · "
            f"{pl_usd} ({pl_pct}){eod}"
        )
        if st.button(
            day_label,
            key=f"room3_hist_day_{date_key}",
            use_container_width=True,
        ):
            if is_day_open:
                st.session_state.room3_history_open_day = None
                st.session_state.room3_history_open_trade_id = None
            else:
                st.session_state.room3_history_open_day = date_key
                st.session_state.room3_history_open_trade_id = None
            st.rerun()

        if is_day_open:
            st.markdown("<div class='room3-history-panel'>", unsafe_allow_html=True)
            hc1, hc2, hc3, hc4, hc5 = st.columns(5)
            with hc1:
                st.metric("Day P/L", pl_usd)
            with hc2:
                st.metric("Day %", pl_pct)
            with hc3:
                st.metric("Wins / Losses", f"{day.get('wins')} / {day.get('losses')}")
            with hc4:
                wr = day.get("win_rate")
                st.metric("Win rate", f"{wr:.0f}%" if wr is not None else "—")
            with hc5:
                if end_eq is not None:
                    st.metric("Account EOD", f"${float(end_eq):,.2f}")
                else:
                    st.metric("Account EOD", "—")

            for trade in day.get("trades") or []:
                tid = str(trade.get("id"))
                is_trade_open = open_trade == tid
                ticker_arrow = "▾" if is_trade_open else "▸"
                trade_label = (
                    f"{ticker_arrow} {trade.get('ticker')} · "
                    f"{_fmt_pl_pct(trade.get('pnl_pct'))}"
                )
                if st.button(
                    trade_label,
                    key=f"room3_hist_trade_{tid}",
                    use_container_width=True,
                ):
                    if is_trade_open:
                        st.session_state.room3_history_open_trade_id = None
                    else:
                        st.session_state.room3_history_open_trade_id = tid
                    st.rerun()
                if is_trade_open:
                    _render_history_trade_detail(trade)

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


def _render_strategy_health_strip() -> None:
    st.markdown("### Strategy health")
    hs = room3_engine.matrix_handshake(st.session_state)
    st.caption(
        f"Matrix handshake · layouts {hs['layout_count']} · patterns {hs['pattern_count']} · "
        f"deploys {hs['deploy_count']} · weather {hs['weather']}"
    )
    alerts = list(st.session_state.room3_decay_alerts or [])
    fb = st.session_state.room3_strategy_feedback or {}
    if alerts:
        for a in alerts:
            st.warning(a)
    elif fb:
        lines = [f"**{k}** — good {v.get('good',0)} · bad {v.get('bad',0)}" for k, v in fb.items()]
        st.info("Operator feedback today (local): " + " · ".join(lines))
    else:
        st.info(
            "When filters scan and matrix signals fire, decay / weather-fit warnings land here. "
            "Your ✓/✗ votes feed that loop."
        )
    sync_log = st.session_state.room3_matrix_sync_log or []
    if sync_log:
        with st.expander("Matrix sync log", expanded=False):
            for line in sync_log[-8:]:
                st.caption(line)


def _render_operator_review_panel() -> None:
    st.markdown("### Operator review")
    st.caption("System proposes · you confirm ✓ good or ✗ bad · feeds matrix learning.")
    pending = st.session_state.room3_pending_reviews or []
    if not pending:
        st.caption("No closed trades waiting for your vote.")
        return
    for trade in pending:
        tid = str(trade.get("id"))
        verdict = str(trade.get("system_verdict") or "neutral")
        verdict_class = "room3-verdict-good" if verdict == "good" else "room3-verdict-bad"
        st.markdown(
            f"<div class='room3-review-card'>"
            f"<strong>{trade.get('ticker')}</strong> · {trade.get('timeframe')} · "
            f"{trade.get('strategy')}<br>"
            f"Entry {trade.get('entry_time')} @ {trade.get('entry_price')} → "
            f"Exit {trade.get('exit_time')} @ {trade.get('exit_price')}<br>"
            f"P/L <strong>${float(trade.get('pnl_usd') or 0):,.2f}</strong> "
            f"({float(trade.get('pnl_pct') or 0):+.2f}%)<br>"
            f"<span class='{verdict_class}'>System: {verdict}</span> — "
            f"{trade.get('system_reason', '')}"
            f"</div>",
            unsafe_allow_html=True,
        )
        b1, b2, _ = st.columns([1, 1, 2])
        with b1:
            if st.button("✓ Good", key=f"room3_good_{tid}", use_container_width=True):
                _record_operator_review(tid, "good")
                st.rerun()
        with b2:
            if st.button("✗ Bad", key=f"room3_bad_{tid}", use_container_width=True):
                _record_operator_review(tid, "bad")
                st.rerun()


def _broker_is_connected() -> bool:
    if str(st.session_state.get("room3_broker") or "alpaca") == "ibkr":
        return str(st.session_state.get("room3_ibkr_status") or "") == "connected"
    return str(st.session_state.get("room3_alpaca_status") or "") == "connected"


def _ibkr_is_connected() -> bool:
    return str(st.session_state.get("room3_ibkr_status") or "") == "connected"


def _render_alpaca_connection_panel(mode: str) -> None:
    """Paper-first Alpaca gate — keys from secrets.toml, never typed in chat."""
    status = str(st.session_state.get("room3_alpaca_status") or "disconnected")
    is_paper = mode == ROOM3_MODE_PAPER

    st.markdown("### Alpaca")
    if status == "connected":
        acct = st.session_state.room3_alpaca_account or "paper"
        st.success(f"Connected · {'PAPER' if is_paper else 'LIVE'} · {acct}")
        if st.button("Disconnect Alpaca", key="room3_alpaca_disconnect"):
            st.session_state.room3_alpaca_status = "disconnected"
            st.session_state.room3_alpaca_account = ""
            st.session_state.room3_alpaca_last_check = "Disconnected."
            st.session_state.room3_broker_truth = False
            st.session_state.room3_broker_equity = 0.0
            st.rerun()
        return

    if not is_paper:
        st.warning(
            "Alpaca **live** needs a funded brokerage account + KYC. "
            "Stay on **Paper** in Room 3 for now, or switch broker to IBKR when Pro is available."
        )

    st.markdown(
        f"<div class='room3-shell'>"
        f"<div class='room3-kicker'>Connection gate</div>"
        f"<div class='room3-title'>Unlock Alpaca {'PAPER' if is_paper else 'LIVE'}</div>"
        f"<p class='room3-sub'>"
        f"Put your paper <strong>API Key</strong> + <strong>Secret</strong> in "
        f"<code>.streamlit/secrets.toml</code>, restart Streamlit, then Check connection. "
        f"Don’t paste secrets in chat."
        f"</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    creds = room3_alpaca.load_alpaca_credentials(paper=True)
    keys_ready = bool(creds["key"] and creds["secret"])
    with st.expander("secrets.toml keys (paper)", expanded=not keys_ready):
        st.code(
            'ALPACA_API_KEY = "PK..."\n'
            'ALPACA_SECRET_KEY = "..."\n'
            'ALPACA_ENDPOINT = "https://paper-api.alpaca.markets"',
            language="toml",
        )
        st.caption("File path: `.streamlit/secrets.toml` in the TradingApprentice folder.")

    if keys_ready:
        st.caption(
            f"Keys loaded · endpoint `{creds['endpoint']}` · "
            f"key starts with `{creds['key'][:4]}…`"
        )
    else:
        st.error(
            "No Alpaca keys loaded yet — save `.streamlit/secrets.toml`, "
            "fully stop Streamlit (Ctrl+C), start it again, then refresh this page."
        )

    if status == "waiting":
        st.warning("Waiting for Alpaca… click **Check connection**.")

    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if st.button("Start waiting", key="room3_alpaca_wait", use_container_width=True):
            st.session_state.room3_alpaca_status = "waiting"
            st.session_state.room3_alpaca_last_check = ""
            st.rerun()
    with b2:
        if st.button("Check connection", key="room3_alpaca_check", type="primary", use_container_width=True):
            st.session_state.room3_alpaca_status = "waiting"
            result = room3_alpaca.probe_alpaca_connection(paper=True)
            if result.get("ok"):
                equity = float(result.get("equity") or 0)
                cash = float(result.get("cash") or 0)
                buying_power = float(result.get("buying_power") or 0)
                st.session_state.room3_alpaca_status = "connected"
                st.session_state.room3_alpaca_account = (
                    f"{result.get('account_number') or 'paper'} · "
                    f"${equity:,.2f}"
                )
                # Genuine account pull — broker is truth
                st.session_state.room3_broker_equity = equity
                st.session_state.room3_account_equity = equity
                st.session_state.room3_broker_truth = True
                st.session_state.room3_last_broker_sync = datetime.now(ET).strftime(
                    "%H:%M:%S ET"
                )
                prev_start = float(st.session_state.get("room3_starting_equity") or 0)
                if prev_start <= 0:
                    st.session_state.room3_starting_equity = equity
                st.session_state.room3_tradable_today = round(equity * 0.5, 2)
                st.session_state.room3_open_positions = room3_alpaca.fetch_open_positions(
                    paper=True
                )
                st.session_state.room3_alpaca_last_check = (
                    f"Handshake OK · equity ${equity:,.2f} · cash ${cash:,.2f} · "
                    f"buying power ${buying_power:,.2f} · status {result.get('status')}"
                )
            else:
                st.session_state.room3_alpaca_status = "waiting"
                st.session_state.room3_alpaca_account = ""
                st.session_state.room3_alpaca_last_check = (
                    f"Not connected yet — {result.get('error') or 'unknown error'}"
                )
            st.rerun()

    msg = str(st.session_state.get("room3_alpaca_last_check") or "").strip()
    if msg:
        if "Not connected" in msg:
            st.error(msg)
        else:
            st.caption(msg)


def _render_broker_connection_panel(mode: str) -> None:
    """Broker picker — Alpaca paper now; IBKR when Pro/API is available."""
    st.markdown("### Broker connection")
    broker = st.radio(
        "Broker",
        options=["alpaca", "ibkr"],
        format_func=lambda x: "Alpaca (paper — recommended now)" if x == "alpaca" else "Interactive Brokers",
        horizontal=True,
        key="room3_broker",
    )
    if broker == "alpaca":
        _render_alpaca_connection_panel(mode)
    else:
        _render_ibkr_connection_panel(mode)


def _render_ibkr_connection_panel(mode: str) -> None:
    """Waiting screen → connected. Password stays in Gateway/TWS, not Room 3."""
    status = str(st.session_state.get("room3_ibkr_status") or "disconnected")
    lane = "LIVE" if mode == ROOM3_MODE_LIVE else "PAPER"
    platform = str(st.session_state.get("room3_ibkr_platform") or room3_ibkr.PLATFORM_GATEWAY)
    default_port = room3_ibkr.default_port_for_mode(mode, platform)
    sync_key = f"{mode}:{platform}"
    prev_key = str(st.session_state.get("room3_ibkr_port_mode") or "")
    if prev_key != sync_key:
        st.session_state.room3_ibkr_port = default_port
        st.session_state.room3_ibkr_port_mode = sync_key

    st.markdown("### Interactive Brokers")
    if status == "connected":
        acct = st.session_state.room3_ibkr_account or "account linked"
        host = st.session_state.room3_ibkr_host
        port = st.session_state.room3_ibkr_port
        plat = "Gateway" if platform == room3_ibkr.PLATFORM_GATEWAY else "TWS"
        st.success(f"Connected · {lane} · {plat} · {acct} · {host}:{port}")
        if st.button("Disconnect", key="room3_ibkr_disconnect"):
            st.session_state.room3_ibkr_status = "disconnected"
            st.session_state.room3_ibkr_account = ""
            st.session_state.room3_ibkr_last_check = "Disconnected."
            st.rerun()
        return

    st.markdown(
        f"<div class='room3-shell'>"
        f"<div class='room3-kicker'>Connection gate</div>"
        f"<div class='room3-title'>Unlock IBKR {lane}</div>"
        f"<p class='room3-sub'>"
        f"Log into <strong>IB Gateway</strong> (or TWS) with your {lane.lower()} password. "
        f"Room 3 never takes that password — it only attaches after IBKR is unlocked. "
        f"Don’t run Gateway and TWS on the same account at the same time."
        f"</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    plat_choice = st.radio(
        "Connect through",
        options=[room3_ibkr.PLATFORM_GATEWAY, room3_ibkr.PLATFORM_TWS],
        format_func=lambda x: "IB Gateway (recommended)" if x == room3_ibkr.PLATFORM_GATEWAY else "TWS",
        horizontal=True,
        key="room3_ibkr_platform",
    )
    if plat_choice != platform:
        st.session_state.room3_ibkr_port = room3_ibkr.default_port_for_mode(mode, plat_choice)
        st.session_state.room3_ibkr_port_mode = f"{mode}:{plat_choice}"
        st.rerun()

    platform = str(st.session_state.room3_ibkr_platform)
    default_port = room3_ibkr.default_port_for_mode(mode, platform)

    if platform == room3_ibkr.PLATFORM_GATEWAY:
        with st.expander("Do this in IB Gateway", expanded=True):
            st.markdown(
                f"""
1. Open the **IB Gateway** app you downloaded (not the App Store).
2. Log in as **{lane}** (Paper / Live on the login screen).
3. **Configure → Settings → API → Settings**
4. Check **Enable ActiveX and Socket Clients**
5. Socket port should be **{default_port}**
   (Gateway Paper **4002** · Gateway Live **4001**)
6. Apply / OK — leave Gateway open
7. Come back here → **Check connection**

Close **TWS** first if it’s logged into the same account.
"""
            )
    else:
        with st.expander("Do this in TWS", expanded=True):
            st.markdown(
                f"""
1. Open **Trader Workstation** and log in as **{lane}**
2. **Edit → Global Configuration → API → Settings**
3. Check **Enable ActiveX and Socket Clients**
4. Socket port should be **{default_port}**
   (TWS Paper **7497** · TWS Live **7496**)
5. Apply / OK — leave TWS open
6. Come back here → **Check connection**

Close **IB Gateway** first if it’s logged into the same account.
"""
            )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.text_input("Host", key="room3_ibkr_host")
    with c2:
        st.number_input("Port", min_value=1, max_value=65535, key="room3_ibkr_port", step=1)
    with c3:
        st.number_input(
            "Client ID",
            min_value=1,
            max_value=9999,
            key="room3_ibkr_client_id",
            step=1,
            help="Unique id for Room 3. Change if another app already uses it.",
        )

    if status == "waiting":
        st.warning(
            f"Waiting for IBKR {lane}… finish the steps above, then **Check connection**."
        )

    b1, b2, _ = st.columns([1, 1, 2])
    with b1:
        if st.button("Start waiting", key="room3_ibkr_wait", use_container_width=True):
            st.session_state.room3_ibkr_status = "waiting"
            st.session_state.room3_ibkr_last_check = ""
            st.rerun()
    with b2:
        if st.button("Check connection", key="room3_ibkr_check", type="primary", use_container_width=True):
            st.session_state.room3_ibkr_status = "waiting"
            result = room3_ibkr.probe_tws_connection(
                host=str(st.session_state.room3_ibkr_host or "127.0.0.1"),
                port=int(st.session_state.room3_ibkr_port or default_port),
                client_id=int(st.session_state.room3_ibkr_client_id or room3_ibkr.DEFAULT_CLIENT_ID),
            )
            if result.get("ok"):
                accounts = result.get("accounts") or []
                st.session_state.room3_ibkr_status = "connected"
                st.session_state.room3_ibkr_account = ", ".join(accounts) if accounts else "connected"
                st.session_state.room3_ibkr_last_check = (
                    f"Handshake OK · accounts: {st.session_state.room3_ibkr_account}"
                )
            else:
                st.session_state.room3_ibkr_status = "waiting"
                st.session_state.room3_ibkr_account = ""
                st.session_state.room3_ibkr_last_check = (
                    f"Not connected yet — {result.get('error') or 'unknown error'}"
                )
            st.rerun()

    msg = str(st.session_state.get("room3_ibkr_last_check") or "").strip()
    if msg:
        if "Not connected" in msg:
            st.error(msg)
        else:
            st.caption(msg)


def _sync_alpaca_account_into_session(*, paper: bool = True) -> dict:
    """Broker truth — equity + positions from Alpaca into Room 3 session state."""
    result = room3_alpaca.probe_alpaca_connection(paper=paper)
    if not result.get("ok"):
        st.session_state.room3_broker_truth = False
        return result
    equity = float(result.get("equity") or 0)
    st.session_state.room3_broker_equity = equity
    st.session_state.room3_account_equity = equity
    st.session_state.room3_broker_truth = True
    st.session_state.room3_alpaca_account = (
        f"{result.get('account_number') or 'paper'} · ${equity:,.2f}"
    )
    st.session_state.room3_open_positions = room3_alpaca.fetch_open_positions(paper=paper)
    st.session_state.room3_last_broker_sync = datetime.now(ET).strftime("%H:%M:%S ET")
    return result


def _current_gates(intent: str = "entry", order_notional: float = 0.0) -> dict:
    mode = str(st.session_state.get("room3_execution_mode") or ROOM3_MODE_PAPER)
    return room3_engine.evaluate_execution_gates(
        mode=mode,
        broker=str(st.session_state.get("room3_broker") or "alpaca"),
        broker_connected=_broker_is_connected(),
        engine_armed=bool(st.session_state.get("room3_engine_armed")),
        kill_flat=bool(st.session_state.get("room3_kill_flat")),
        pause_entries=bool(st.session_state.get("room3_pause_entries")),
        intent=intent,
        session_window=room3_engine.detect_session_window(),
        allowed_sessions=list(st.session_state.get("room3_allowed_sessions") or []),
        tradable_today=float(st.session_state.get("room3_tradable_today") or 0),
        deployed=room3_engine.deployed_notional(st.session_state.get("room3_open_positions")),
        order_notional=float(order_notional or 0),
        live_orders_enabled=room3_engine.LIVE_ORDERS_ENABLED,
    )


def execute_matrix_signal(signal: dict) -> dict:
    """Public auto path — matrix/filters call this; UI never sends tickets."""
    init_room3_session_state()
    intent = str(signal.get("intent") or "entry").lower()
    notional = float(signal.get("notional") or 0)
    if notional <= 0:
        try:
            notional = abs(float(signal.get("qty") or 0)) * abs(
                float(signal.get("ref_price") or signal.get("entry_price") or 0)
            )
        except (TypeError, ValueError):
            notional = 0.0
    gates = _current_gates(intent=intent, order_notional=notional)
    mode = str(st.session_state.get("room3_execution_mode") or ROOM3_MODE_PAPER)
    paper = mode != ROOM3_MODE_LIVE
    result = room3_engine.execute_matrix_signal(signal, paper=paper, gates=gates)
    log = list(st.session_state.get("room3_auto_event_log") or [])
    log.insert(
        0,
        {
            "ts": datetime.now(ET).strftime("%H:%M:%S"),
            "ok": bool(result.get("ok")),
            "blocked": bool(result.get("blocked")),
            "intent": intent,
            "symbol": str(signal.get("symbol") or signal.get("ticker") or ""),
            "detail": (
                result.get("error")
                or f"{result.get('status')} · {result.get('side')} {result.get('qty')}"
            ),
        },
    )
    st.session_state.room3_auto_event_log = log[:40]
    if result.get("ok"):
        _log_alpaca_order_fill(result)
        _sync_alpaca_account_into_session(paper=paper)
    return result


def _log_alpaca_order_fill(result: dict) -> None:
    """Append a paper fill into today's open book / trade log shape."""
    now = datetime.now(ET).strftime("%H:%M:%S")
    ticker = str(result.get("symbol") or "")
    side = str(result.get("side") or "")
    qty = float(result.get("qty") or 0)
    px = result.get("filled_avg_price")
    entry_px = float(px) if px not in (None, "") else 0.0
    row = {
        "id": f"alpaca-ord-{result.get('order_id') or now}",
        "ticker": ticker,
        "strategy": str(result.get("strategy") or f"Alpaca {side.upper()}"),
        "timeframe": str(result.get("timeframe") or "MKT"),
        "entry_time": now,
        "entry_price": entry_px,
        "last_price": entry_px,
        "pnl_usd": 0.0,
        "pnl_pct": 0.0,
        "qty": qty if side == "buy" else -qty,
        "broker_order_id": result.get("order_id"),
        "broker_status": result.get("status"),
    }
    # Buys / opens land in open positions via refresh; still stamp activity log
    history = list(st.session_state.get("room3_trade_history") or [])
    history.insert(
        0,
        {
            **row,
            "exit_time": "—",
            "exit_price": entry_px,
            "status": f"submitted · {result.get('status')}",
            "operator_verdict": "",
        },
    )
    st.session_state.room3_trade_history = history[:200]


def _render_execution_posture(mode: str) -> None:
    """Auto matrix path — filters/session → signal → Alpaca entry/exit. You supervise."""
    lane = "PAPER" if mode == ROOM3_MODE_PAPER else "LIVE"
    broker = _active_broker_name()
    window = room3_engine.detect_session_window()
    hs = room3_engine.matrix_handshake(st.session_state)
    gates = _current_gates("entry")
    armed = bool(st.session_state.get("room3_engine_armed"))
    flat = bool(st.session_state.get("room3_kill_flat"))
    paused = bool(st.session_state.get("room3_pause_entries"))

    st.markdown(
        f"<div class='room3-shell'>"
        f"<div class='room3-kicker'>Execution posture · auto path</div>"
        f"<div class='room3-title'>Detect → Alpaca → hold → exit</div>"
        f"<p class='room3-sub'>"
        f"Matrix strategies + session filters fire entries/exits through "
        f"<strong>{broker} {lane}</strong>. You set capital, filters, kill/pause — "
        f"you do not send tickets. "
        f"Now: <strong>{room3_engine.session_label(window)}</strong>."
        f"</p>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.markdown("#### Supervisor controls")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.session_state.room3_engine_armed = st.toggle(
            "Arm auto engine",
            value=armed,
            key="room3_toggle_engine_armed",
            help="Off = no auto orders. On = matrix signals may hit Alpaca when gates pass.",
        )
    with c2:
        st.session_state.room3_pause_entries = st.toggle(
            "Pause new entries",
            value=paused,
            key="room3_toggle_pause_entries",
            help="Blocks new entries; exits can still fire.",
        )
    with c3:
        st.session_state.room3_kill_flat = st.toggle(
            "Kill switch FLAT",
            value=flat,
            key="room3_toggle_kill_flat",
            help="Blocks all auto orders (entries and exits).",
        )

    st.markdown("#### Session filters (when engine may trade)")
    allowed = set(st.session_state.get("room3_allowed_sessions") or [])
    f1, f2, f3 = st.columns(3)
    with f1:
        pre_on = st.checkbox(
            "Pre-market",
            value=room3_engine.SESSION_PRE in allowed,
            key="room3_filter_pre",
        )
    with f2:
        rth_on = st.checkbox(
            "Market hours",
            value=room3_engine.SESSION_RTH in allowed,
            key="room3_filter_rth",
        )
    with f3:
        post_on = st.checkbox(
            "Post-market",
            value=room3_engine.SESSION_POST in allowed,
            key="room3_filter_post",
        )
    next_allowed = []
    if pre_on:
        next_allowed.append(room3_engine.SESSION_PRE)
    if rth_on:
        next_allowed.append(room3_engine.SESSION_RTH)
    if post_on:
        next_allowed.append(room3_engine.SESSION_POST)
    st.session_state.room3_allowed_sessions = next_allowed

    if gates.get("ok"):
        st.success("Gates open — entry signals can reach Alpaca.")
    else:
        st.warning("Gates closed — " + "; ".join(gates.get("reasons") or []))

    mh1, mh2, mh3, mh4 = st.columns(4)
    with mh1:
        st.metric("Matrix layouts", hs["layout_count"])
    with mh2:
        st.metric("Active patterns", hs["pattern_count"])
    with mh3:
        st.metric("Deploys seen", hs["deploy_count"])
    with mh4:
        st.metric("Weather", hs["weather"] if hs["weather"] != "—" else "—")
    if not hs["ready"]:
        st.caption("Matrix handshake quiet — open Room 2 so layouts/patterns hydrate into session.")
    else:
        st.caption("Matrix handshake live from session RAM (Room 2).")

    if mode == ROOM3_MODE_LIVE and not room3_engine.LIVE_ORDERS_ENABLED:
        st.info("Live orders are hard-disabled. Auto path is paper-only until you enable live.")

    if str(st.session_state.get("room3_broker") or "") == "alpaca" and mode == ROOM3_MODE_PAPER:
        if st.button("Refresh account from Alpaca", key="room3_alpaca_refresh_acct"):
            synced = _sync_alpaca_account_into_session(paper=True)
            if synced.get("ok"):
                st.success(
                    f"Broker truth · equity ${float(synced.get('equity') or 0):,.2f}"
                )
            else:
                st.error(synced.get("error") or "Refresh failed")
            st.rerun()

    events = list(st.session_state.get("room3_auto_event_log") or [])
    if events:
        with st.expander("Auto execution log", expanded=False):
            for ev in events[:12]:
                mark = "OK" if ev.get("ok") else ("BLOCKED" if ev.get("blocked") else "FAIL")
                st.caption(
                    f"{ev.get('ts')} · {mark} · {ev.get('intent')} "
                    f"{ev.get('symbol')} — {ev.get('detail')}"
                )


def ingest_filter_universe(tickers: list[str] | None) -> None:
    """
    Public hook for TradingView / session filters.
    Call this when a filter publishes names currently inside it.
    """
    init_room3_session_state()
    names = [str(t).strip().upper() for t in (tickers or []) if str(t).strip()]
    st.session_state.room3_filter_universe = names[: room3_watcher.MAX_NAMES]
    st.session_state.room3_watch_book = room3_watcher.set_filter_universe(
        st.session_state.get("room3_watch_book") or room3_watcher.empty_book(),
        st.session_state.room3_filter_universe,
    )


def _session_scan_allowed() -> bool:
    window = room3_engine.detect_session_window()
    if window == room3_engine.SESSION_CLOSED:
        return False
    allowed = set(st.session_state.get("room3_allowed_sessions") or [])
    return window in allowed


@st.fragment(run_every=timedelta(seconds=30))
def _room3_heartbeat_fragment() -> None:
    """Unattended pulse — broker truth + watcher eyes."""
    if not _broker_is_connected():
        st.caption("Heartbeat idle · broker disconnected")
        return
    mode = str(st.session_state.get("room3_execution_mode") or ROOM3_MODE_PAPER)
    if str(st.session_state.get("room3_broker") or "") == "alpaca":
        paper = mode != ROOM3_MODE_LIVE
        _sync_alpaca_account_into_session(paper=paper)

    # Keep book synced to latest filter feed
    st.session_state.room3_watch_book = room3_watcher.set_filter_universe(
        st.session_state.get("room3_watch_book") or room3_watcher.empty_book(),
        list(st.session_state.get("room3_filter_universe") or []),
    )
    book, signals = room3_watcher.tick_watcher(
        st.session_state.room3_watch_book,
        session_state=st.session_state,
        session_allowed=_session_scan_allowed(),
        engine_armed=bool(st.session_state.get("room3_engine_armed")),
    )
    st.session_state.room3_watch_book = book

    for sig in signals:
        result = execute_matrix_signal(sig)
        # Mark TF line if fill ok
        if result.get("ok"):
            key = room3_watcher.line_key(
                str(sig.get("symbol") or ""),
                str(sig.get("timeframe") or "1m"),
            )
            line = (st.session_state.room3_watch_book.get("lines") or {}).get(key)
            if line:
                if str(sig.get("intent")) == "entry":
                    line["state"] = "in"
                    line["trades_today"] = int(line.get("trades_today") or 0) + 1
                elif str(sig.get("intent")) == "exit":
                    line["state"] = "watching"
                    line["trades_today"] = int(line.get("trades_today") or 0) + 1

    window = room3_engine.detect_session_window()
    gates = _current_gates("entry")
    sync_t = st.session_state.get("room3_last_broker_sync") or "—"
    note = str(book.get("last_note") or "")
    st.caption(
        f"Heartbeat · {datetime.now(ET).strftime('%H:%M:%S ET')} · "
        f"{room3_engine.session_label(window)} · "
        f"broker sync {sync_t} · "
        f"gates={'OPEN' if gates.get('ok') else 'CLOSED'} · "
        f"{note}"
    )


def _render_watch_book_panel() -> None:
    st.markdown("### Eyes · watch book")
    book = st.session_state.get("room3_watch_book") or room3_watcher.empty_book()
    if book.get("awaiting_filters"):
        st.info(
            "Watcher is built and waiting. Plug TradingView session filters next — "
            "they call `ingest_filter_universe([...tickers...])`. "
            "Each name gets **1m + 5m + 15m** maps (lean / medium / rich). "
            "Heartbeat saves slices; EOD deletes maps with no trade."
        )
    else:
        st.caption(
            f"Universe: {', '.join(book.get('universe') or [])} · "
            f"last tick {book.get('last_tick') or '—'} · ticks {book.get('ticks') or 0}"
        )
    rows = room3_watcher.book_status_rows(book)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No TF maps open yet.")

    with st.expander("Filter feed (temporary until TradingView is wired)", expanded=False):
        st.caption("Paste tickers to simulate a filter hit — remove when real filters connect.")
        raw = st.text_input(
            "Tickers",
            value=",".join(st.session_state.get("room3_filter_universe") or []),
            key="room3_filter_sim_input",
            placeholder="AAPL, NVDA, MSFT",
        )
        if st.button("Apply filter universe", key="room3_filter_sim_apply"):
            names = [p.strip().upper() for p in raw.split(",") if p.strip()]
            ingest_filter_universe(names)
            st.rerun()
        if st.button("Clear filter universe", key="room3_filter_sim_clear"):
            ingest_filter_universe([])
            st.rerun()


def _render_trading_workspace(mode: str) -> None:
    frame_open = False
    if mode == ROOM3_MODE_PAPER:
        st.markdown("<div class='room3-paper-frame'>", unsafe_allow_html=True)
        frame_open = True
    elif mode == ROOM3_MODE_LIVE:
        st.markdown("<div class='room3-live-frame'>", unsafe_allow_html=True)
        frame_open = True
    _render_broker_connection_panel(mode)
    _render_broker_status_card(mode)
    if not _broker_is_connected():
        st.caption("Trading panels unlock after the broker connects.")
        if frame_open:
            st.markdown("</div>", unsafe_allow_html=True)
        return
    _render_live_dashboard(mode)
    _render_execution_posture(mode)
    _render_watch_book_panel()
    _room3_heartbeat_fragment()
    left, right = st.columns([1, 1])
    with left:
        _render_open_positions()
        _render_trade_history()
    with right:
        _render_session_summary()
        _render_operator_review_panel()
    _render_strategy_health_strip()
    if frame_open:
        st.markdown("</div>", unsafe_allow_html=True)
    _render_session_history()


def _render_paper_workspace() -> None:
    _render_trading_workspace(ROOM3_MODE_PAPER)


def _render_live_workspace() -> None:
    _render_trading_workspace(ROOM3_MODE_LIVE)


def render_room3_trading_center() -> None:
    """Main Room 3 entry — connection gate + trading shell."""
    init_room3_session_state()
    _inject_room3_css()
    _maybe_roll_trading_session()

    health = room3_engine.runtime_health()
    if not health.get("ok"):
        for issue in health.get("issues") or []:
            st.error(issue)
        st.caption("Start with `./run_room3.sh` so the project `.venv` is always used.")

    host = room3_engine.hosting_label()
    if room3_engine.is_cloud_host():
        st.caption(
            f"Host · **{host}** — Mac is not running this process. "
            "Room 1 cloud offload (Compute/HF/Supabase) still applies when those secrets are set."
        )
    else:
        st.caption(
            f"Host · **{host}** — for less heat, open the Streamlit Cloud URL instead of localhost "
            "(and stop local Streamlit). Room 1 heavy work still offloads via CLOUD_COMPUTE_URL when set."
        )

    _render_broker_presence_chip()
    _render_mode_slider()

    if ROOM3_LIVE_SECURITY_ENABLED and st.session_state.room3_live_gate_open:
        _render_live_gate_overlay()
        return

    mode = str(st.session_state.room3_execution_mode or ROOM3_MODE_PAPER)
    if mode == ROOM3_MODE_LIVE:
        if ROOM3_LIVE_SECURITY_ENABLED and not st.session_state.room3_live_unlocked:
            st.session_state.room3_execution_mode = ROOM3_MODE_PAPER
            _render_paper_workspace()
        else:
            if not ROOM3_LIVE_SECURITY_ENABLED:
                st.caption("App live passcode disabled for now — IBKR login is still required.")
            _render_live_workspace()
    else:
        _render_paper_workspace()

    st.markdown("---")
    st.caption(
        f"Session · mode={st.session_state.room3_execution_mode} · "
        f"broker={st.session_state.get('room3_broker')} · "
        f"alpaca={st.session_state.get('room3_alpaca_status')} · "
        f"ibkr={st.session_state.room3_ibkr_status} · "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
