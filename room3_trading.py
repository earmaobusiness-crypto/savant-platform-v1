"""
Room 3 — Live / Paper Trading Center (shell).

Built as a standalone house: UI compartments, mode gates, and session state only.
No IBKR hooks, no vault writes, no Room 1/2 imports until explicitly wired later.
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

ROOM3_MODE_PAPER = "paper"
ROOM3_MODE_LIVE = "live"
ROOM3_RECOVERY_EMAIL = "earmaobusiness@gmail.com"
# Flip to True later — passcode gate + recovery flow (no rebuild needed).
ROOM3_LIVE_SECURITY_ENABLED = False
ROOM3_DEMO_ACCOUNT_EQUITY = 50000.0
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
    if "room3_demo_active" not in st.session_state:
        st.session_state.room3_demo_active = False
    if "room3_demo_seeded" not in st.session_state:
        st.session_state.room3_demo_seeded = False
    if "room3_account_equity" not in st.session_state:
        st.session_state.room3_account_equity = ROOM3_DEMO_ACCOUNT_EQUITY
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
        st.session_state.room3_starting_equity = ROOM3_DEMO_ACCOUNT_EQUITY


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
            border-color: #5A2020;
            background: linear-gradient(180deg, #1A0F0F 0%, #0B0B0B 100%);
        }
        .room3-paper-frame {
            border: 2px solid #B33A3A;
            border-radius: 14px;
            padding: 14px 14px 8px;
            margin: 0 0 12px 0;
            box-shadow: inset 0 0 0 1px rgba(180, 60, 60, 0.35);
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


def _demo_archive_days() -> list[dict]:
    """Past sessions for history panel demo."""
    return [
        {
            "date": "2026-08-11",
            "display": "Monday, Aug 11",
            "pl_usd": 892.40,
            "pl_pct": 1.78,
            "trade_count": 4,
            "wins": 3,
            "losses": 1,
            "win_rate": 75.0,
            "trades": [
                {
                    "id": "arch-0811-mrna",
                    "ticker": "MRNA",
                    "timeframe": "5-Minute",
                    "layout": "Layout 3 — Volatile / Risk-On",
                    "strategy": "3A (5M)",
                    "entry_time": "09:35 AM",
                    "exit_time": "10:05 AM",
                    "entry_price": 28.40,
                    "exit_price": 30.12,
                    "pnl_usd": 344.0,
                    "pnl_pct": 6.06,
                    "qty": 200,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0811-soun",
                    "ticker": "SOUN",
                    "timeframe": "1-Minute",
                    "layout": "Layout 1 — Volatile / Risk-Off",
                    "strategy": "1B (1M)",
                    "entry_time": "11:18 AM",
                    "exit_time": "11:24 AM",
                    "entry_price": 4.62,
                    "exit_price": 4.88,
                    "pnl_usd": 312.0,
                    "pnl_pct": 5.63,
                    "qty": 1200,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0811-bbig",
                    "ticker": "BBIG",
                    "timeframe": "15-Minute",
                    "layout": "Layout 4 — Neutral / Risk-On",
                    "strategy": "4C (15M)",
                    "entry_time": "02:10 PM",
                    "exit_time": "02:45 PM",
                    "entry_price": 1.88,
                    "exit_price": 2.05,
                    "pnl_usd": 255.0,
                    "pnl_pct": 9.04,
                    "qty": 1500,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0811-gct",
                    "ticker": "GCT",
                    "timeframe": "5-Minute",
                    "layout": "Layout 2 — Tight / Tight Range",
                    "strategy": "2A (5M)",
                    "entry_time": "03:22 PM",
                    "exit_time": "03:38 PM",
                    "entry_price": 22.10,
                    "exit_price": 21.72,
                    "pnl_usd": -190.4,
                    "pnl_pct": -1.72,
                    "qty": 500,
                    "operator_vote": "bad",
                },
            ],
        },
        {
            "date": "2026-08-08",
            "display": "Friday, Aug 8",
            "pl_usd": -428.60,
            "pl_pct": -0.86,
            "trade_count": 3,
            "wins": 1,
            "losses": 2,
            "win_rate": 33.0,
            "trades": [
                {
                    "id": "arch-0808-lumn",
                    "ticker": "LUMN",
                    "timeframe": "5-Minute",
                    "layout": "Layout 1 — Volatile / Risk-Off",
                    "strategy": "1C (5M)",
                    "entry_time": "10:02 AM",
                    "exit_time": "10:28 AM",
                    "entry_price": 5.14,
                    "exit_price": 5.48,
                    "pnl_usd": 408.0,
                    "pnl_pct": 6.62,
                    "qty": 1200,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0808-ionq",
                    "ticker": "IONQ",
                    "timeframe": "1-Minute",
                    "layout": "Layout 3 — Volatile / Risk-On",
                    "strategy": "3B (1M)",
                    "entry_time": "12:44 PM",
                    "exit_time": "12:51 PM",
                    "entry_price": 38.20,
                    "exit_price": 37.55,
                    "pnl_usd": -325.0,
                    "pnl_pct": -1.70,
                    "qty": 500,
                    "operator_vote": "bad",
                },
                {
                    "id": "arch-0808-rgti",
                    "ticker": "RGTI",
                    "timeframe": "5-Minute",
                    "layout": "Layout 2 — Tight / Tight Range",
                    "strategy": "2B (5M)",
                    "entry_time": "01:55 PM",
                    "exit_time": "02:18 PM",
                    "entry_price": 11.88,
                    "exit_price": 11.42,
                    "pnl_usd": -305.6,
                    "pnl_pct": -3.87,
                    "qty": 800,
                    "operator_vote": "bad",
                },
            ],
        },
        {
            "date": "2026-08-05",
            "display": "Tuesday, Aug 5",
            "pl_usd": 1246.80,
            "pl_pct": 2.49,
            "trade_count": 5,
            "wins": 4,
            "losses": 1,
            "win_rate": 80.0,
            "trades": [
                {
                    "id": "arch-0805-smci",
                    "ticker": "SMCI",
                    "timeframe": "15-Minute",
                    "layout": "Layout 4 — Neutral / Risk-On",
                    "strategy": "4A (15M)",
                    "entry_time": "09:45 AM",
                    "exit_time": "10:30 AM",
                    "entry_price": 42.10,
                    "exit_price": 44.85,
                    "pnl_usd": 550.0,
                    "pnl_pct": 6.53,
                    "qty": 200,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0805-arm",
                    "ticker": "ARM",
                    "timeframe": "5-Minute",
                    "layout": "Layout 3 — Volatile / Risk-On",
                    "strategy": "3A (5M)",
                    "entry_time": "11:05 AM",
                    "exit_time": "11:22 AM",
                    "entry_price": 138.40,
                    "exit_price": 142.20,
                    "pnl_usd": 380.0,
                    "pnl_pct": 2.75,
                    "qty": 100,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0805-pltr",
                    "ticker": "PLTR",
                    "timeframe": "1-Minute",
                    "layout": "Layout 1 — Volatile / Risk-Off",
                    "strategy": "1A (1M)",
                    "entry_time": "01:12 PM",
                    "exit_time": "01:18 PM",
                    "entry_price": 26.88,
                    "exit_price": 27.42,
                    "pnl_usd": 216.0,
                    "pnl_pct": 2.01,
                    "qty": 400,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0805-coin",
                    "ticker": "COIN",
                    "timeframe": "5-Minute",
                    "layout": "Layout 3 — Volatile / Risk-On",
                    "strategy": "3C (5M)",
                    "entry_time": "02:40 PM",
                    "exit_time": "03:05 PM",
                    "entry_price": 198.50,
                    "exit_price": 202.80,
                    "pnl_usd": 210.0,
                    "pnl_pct": 2.17,
                    "qty": 50,
                    "operator_vote": "good",
                },
                {
                    "id": "arch-0805-mara",
                    "ticker": "MARA",
                    "timeframe": "1-Minute",
                    "layout": "Layout 2 — Tight / Tight Range",
                    "strategy": "2A (1M)",
                    "entry_time": "03:48 PM",
                    "exit_time": "03:54 PM",
                    "entry_price": 16.22,
                    "exit_price": 15.98,
                    "pnl_usd": -109.2,
                    "pnl_pct": -1.48,
                    "qty": 450,
                    "operator_vote": "bad",
                },
            ],
        },
    ]


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
    if st.session_state.room3_demo_active:
        st.session_state.room3_open_positions = []
        st.session_state.room3_pending_reviews = []
        st.session_state.room3_trade_history = []
        st.session_state.room3_operator_reviews = []
        st.session_state.room3_strategy_feedback = {}
        st.session_state.room3_decay_alerts = []
        log = list(st.session_state.room3_matrix_sync_log or [])
        log.append(f"Session rolled · new trading day {key} (4 AM ET)")
        st.session_state.room3_matrix_sync_log = log[-12:]


def _demo_equity_curve() -> list[dict]:
    """Demo all-time equity path ending at current account equity."""
    start = ROOM3_DEMO_ACCOUNT_EQUITY
    # Chronological closes — archive days are newest-first in UI; curve needs oldest→newest.
    archive = sorted(_demo_archive_days(), key=lambda d: str(d.get("date") or ""))
    points: list[dict] = [{"date": "Start", "equity": start}]
    running = start
    for day in archive:
        running = round(running + float(day.get("pl_usd") or 0), 2)
        points.append(
            {
                "date": str(day.get("date") or ""),
                "equity": running,
                "day_pl": float(day.get("pl_usd") or 0),
            }
        )
    today_stats_pl = 0.0  # filled after seed via sync helper
    points.append(
        {
            "date": _trading_day_key(),
            "equity": running,  # synced once today stats exist
            "day_pl": today_stats_pl,
        }
    )
    return points


def _sync_equity_curve_with_today() -> None:
    """Keep the equity curve aligned with archive days + live day P/L."""
    start = float(st.session_state.room3_starting_equity or ROOM3_DEMO_ACCOUNT_EQUITY)
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
    rebuilt.append({"date": _trading_day_key(), "equity": today_eq, "day_pl": day_pl})
    st.session_state.room3_equity_curve = rebuilt
    st.session_state.room3_account_equity = today_eq


def _all_time_stats() -> dict:
    _sync_equity_curve_with_today()
    start = float(st.session_state.room3_starting_equity or ROOM3_DEMO_ACCOUNT_EQUITY)
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
    return {
        "start": start,
        "current": current,
        "all_time_pl": all_time_pl,
        "all_time_pct": all_time_pct,
        "peak": peak,
        "max_drawdown_pct": max_dd,
        "sessions": sessions,
        "total_trades": total_trades,
        "curve": curve,
    }



def seed_demo_trading_session() -> None:
    """Mock session — Room 3 RAM only. No vault / IBKR / matrix writes."""
    st.session_state.room3_demo_active = True
    st.session_state.room3_demo_seeded = True
    st.session_state.room3_account_equity = ROOM3_DEMO_ACCOUNT_EQUITY
    st.session_state.room3_open_positions = [
        {
            "id": "open-hypot",
            "ticker": "HYPOT",
            "timeframe": "5-Minute",
            "layout": "Layout 3 — Volatile / Risk-On",
            "strategy": "3A (5M)",
            "entry_time": "10:12 AM",
            "entry_price": 4.85,
            "last_price": 5.42,
            "target_price": 5.65,
            "pnl_usd": 285.0,
            "pnl_pct": 11.75,
            "qty": 500,
        },
        {
            "id": "open-vmar",
            "ticker": "VMAR",
            "timeframe": "1-Minute",
            "layout": "Layout 1 — Volatile / Risk-Off",
            "strategy": "1B (1M)",
            "entry_time": "10:28 AM",
            "entry_price": 2.14,
            "last_price": 2.09,
            "target_price": 2.35,
            "pnl_usd": -62.5,
            "pnl_pct": -2.34,
            "qty": 1200,
        },
    ]
    st.session_state.room3_pending_reviews = [
        {
            "id": "closed-lhai",
            "ticker": "LHAI",
            "timeframe": "5-Minute",
            "layout": "Layout 4 — Neutral / Risk-On",
            "strategy": "4A (5M)",
            "entry_time": "09:10 AM",
            "exit_time": "09:30 AM",
            "entry_price": 1.53,
            "exit_price": 1.95,
            "pnl_usd": 412.0,
            "pnl_pct": 27.45,
            "qty": 800,
            "system_verdict": "good",
            "system_reason": "Vault envelope +27.45% · layout match 88%",
        },
        {
            "id": "closed-tc",
            "ticker": "TC",
            "timeframe": "15-Minute",
            "layout": "Layout 1 — Volatile / Risk-Off",
            "strategy": "1C (15M)",
            "entry_time": "06:20 PM",
            "exit_time": "06:55 PM",
            "entry_price": 8.12,
            "exit_price": 8.45,
            "pnl_usd": 198.0,
            "pnl_pct": 4.06,
            "qty": 600,
            "system_verdict": "good",
            "system_reason": "Above 15m floor · chronological rally",
        },
        {
            "id": "closed-veee",
            "ticker": "VEEE",
            "timeframe": "1-Minute",
            "layout": "Layout 2 — Tight / Tight Range",
            "strategy": "2A (1M)",
            "entry_time": "11:04 AM",
            "exit_time": "11:09 AM",
            "entry_price": 3.88,
            "exit_price": 3.72,
            "pnl_usd": -224.0,
            "pnl_pct": -4.12,
            "qty": 1400,
            "system_verdict": "bad",
            "system_reason": "Finish below start · chop inside window",
        },
    ]
    st.session_state.room3_trade_history = [
        {
            "id": "closed-jem",
            "ticker": "JEM",
            "timeframe": "5-Minute",
            "strategy": "1B (5M)",
            "entry_time": "08:20 AM",
            "exit_time": "08:45 AM",
            "pnl_usd": 310.0,
            "pnl_pct": 18.2,
            "operator_vote": "good",
            "reviewed": True,
        },
    ]
    st.session_state.room3_operator_reviews = []
    st.session_state.room3_strategy_feedback = {}
    st.session_state.room3_decay_alerts = []
    st.session_state.room3_matrix_sync_log = [
        "Demo loaded — matrix hose disconnected (no Supabase writes)."
    ]
    st.session_state.room3_archive_days = _demo_archive_days()
    st.session_state.room3_session_day_key = _trading_day_key()
    st.session_state.room3_history_open_day = None
    st.session_state.room3_history_open_trade_id = None
    st.session_state.room3_starting_equity = ROOM3_DEMO_ACCOUNT_EQUITY
    st.session_state.room3_equity_curve = _demo_equity_curve()
    _sync_equity_curve_with_today()


def clear_demo_trading_session() -> None:
    st.session_state.room3_demo_active = False
    st.session_state.room3_open_positions = []
    st.session_state.room3_trade_history = []
    st.session_state.room3_pending_reviews = []
    st.session_state.room3_operator_reviews = []
    st.session_state.room3_strategy_feedback = {}
    st.session_state.room3_decay_alerts = []
    st.session_state.room3_matrix_sync_log = ["Demo cleared — RAM only."]
    st.session_state.room3_account_equity = ROOM3_DEMO_ACCOUNT_EQUITY
    st.session_state.room3_archive_days = []
    st.session_state.room3_history_open_day = None
    st.session_state.room3_history_open_trade_id = None
    st.session_state.room3_starting_equity = ROOM3_DEMO_ACCOUNT_EQUITY
    st.session_state.room3_equity_curve = []


def _session_pl_stats() -> dict:
    equity = float(st.session_state.room3_account_equity or ROOM3_DEMO_ACCOUNT_EQUITY)
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
    return {
        "equity": equity,
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


def _render_demo_toolbar() -> None:
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("Load demo session", key="room3_load_demo", use_container_width=True):
            seed_demo_trading_session()
            st.rerun()
    with c2:
        if st.button("Clear demo", key="room3_clear_demo", use_container_width=True):
            clear_demo_trading_session()
            st.rerun()
    with c3:
        if st.session_state.room3_demo_active:
            st.caption(
                "🧪 **Demo mode** — fake fills in RAM. ✓/✗ reviews do **not** write vault/matrix yet."
            )
        else:
            st.caption("Load demo to preview open trades, log, and operator review flow.")


def _render_broker_status_card(mode: str) -> None:
    is_live = mode == ROOM3_MODE_LIVE
    shell_class = "room3-shell"
    if is_live:
        shell_class += " room3-shell-live"
    else:
        shell_class += " room3-shell-paper"
    lane = "LIVE" if is_live else "PAPER"
    stats = _session_pl_stats()
    st.markdown(
        f"<div class='{shell_class}'>"
        f"<div class='room3-kicker'>Room 3 · Execution terminal</div>"
        f"<div class='room3-title'>{_mode_label(mode)}</div>"
        f"<p class='room3-sub'>IBKR {lane} · <strong>Demo / not connected</strong></p>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_open_positions() -> None:
    st.markdown("### Open positions")
    rows = st.session_state.room3_open_positions or []
    if not rows:
        st.caption("No open trades — demo or IBKR fills will show here.")
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
    """Live-now strip — updates during the session; rolls at 4 AM ET."""
    st.markdown("### Live dashboard")
    stats = _session_pl_stats()
    day_label = _trading_day_display(_trading_day_key())
    st.caption(
        f"**{day_label}** · session rolls at 4:00 AM ET · "
        "metrics refresh while the system is active"
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Account", f"${stats['equity']:,.0f}")
    with c2:
        st.metric(
            "Day P/L",
            _fmt_pl_usd(stats["day_pl"]),
            delta=f"{stats['day_pl_pct']:+.2f}%",
            delta_color="normal",
        )
    with c3:
        st.metric("Open unrealized", _fmt_pl_usd(stats["open_pl"]))
    with c4:
        st.metric("Open positions", stats["open_count"])
    with c5:
        st.metric("Wins / Losses", f"{stats['wins']} / {stats['losses']}")
    with c6:
        win_label = f"{stats['win_rate']:.0f}%" if stats["wins"] + stats["losses"] else "—"
        st.metric("Win rate", win_label)
    if mode == ROOM3_MODE_LIVE:
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
    _render_all_time_panel()


def _render_equity_trajectory_chart(at: dict) -> None:
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

    # Session-only points (skip Start) for insight math
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

    # SVG layout
    w, h = 640, 220
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

    # Path
    path_d = " ".join(
        f"{'M' if i == 0 else 'L'}{x_at(i):.1f},{y_at(eq):.1f}"
        for i, eq in enumerate(equities)
    )
    # Area under curve (muted fill)
    area_d = (
        f"{path_d} L{x_at(len(equities)-1):.1f},{pad_t + plot_h:.1f} "
        f"L{x_at(0):.1f},{pad_t + plot_h:.1f} Z"
    )

    # Start baseline
    y_start = y_at(start)
    y_peak = y_at(peak)

    # Daily P/L micro-bars along bottom strip
    bar_max = max((abs(pl) for pl in day_pls[1:]), default=1.0) or 1.0
    bars = []
    for i in range(1, len(points)):
        pl = day_pls[i]
        bh = max(3.0, (abs(pl) / bar_max) * 18.0)
        bx = x_at(i) - 5
        by = pad_t + plot_h + 4
        color = "#5F9E6E" if pl >= 0 else "#B86A6A"
        bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="10" height="{bh:.1f}" '
            f'rx="2" fill="{color}" opacity="0.85">'
            f'<title>{escape(labels[i])}: {_fmt_pl_usd(pl)}</title></rect>'
        )

    # Markers
    peak_i = equities.index(max(equities))
    markers = [
        f'<circle cx="{x_at(0):.1f}" cy="{y_at(equities[0]):.1f}" r="3.5" fill="#8FA3B0" />',
        f'<circle cx="{x_at(len(equities)-1):.1f}" cy="{y_at(equities[-1]):.1f}" r="4" '
        f'fill="#C5D0DA" stroke="#1A1D22" stroke-width="1.5" />',
        f'<circle cx="{x_at(peak_i):.1f}" cy="{y_peak:.1f}" r="3.5" fill="#D4B56A" />',
    ]

    # Axis labels (start / end / peak)
    short_labels = []
    for i, lab in enumerate(labels):
        if i == 0 or i == len(labels) - 1 or i == peak_i:
            shown = "Start" if lab == "Start" else lab[-5:] if len(lab) >= 5 else lab
            short_labels.append(
                f'<text x="{x_at(i):.1f}" y="{h - 6}" text-anchor="middle" '
                f'fill="#6E7884" font-size="9">{escape(shown)}</text>'
            )

    y_ticks = [
        (start, "start"),
        (current, "now"),
        (peak, "peak"),
    ]
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
      <svg viewBox="0 0 {w} {h}" width="100%" height="220" role="img"
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
    """Account trajectory since start — scales with capital, demo-backed for now."""
    st.markdown("### All-time")
    at = _all_time_stats()
    _render_metric_tiles(
        [
            {
                "id": "start",
                "label": "Starting equity",
                "value": f"${at['start']:,.2f}",
                "detail": f"Starting equity ${at['start']:,.2f}",
            },
            {
                "id": "now",
                "label": "Current equity",
                "value": f"${at['current']:,.2f}",
                "detail": f"Current equity ${at['current']:,.2f}",
            },
            {
                "id": "at_pl",
                "label": "All-time P/L",
                "value": _fmt_pl_usd(at["all_time_pl"]),
                "sub": _fmt_pl_pct(at["all_time_pct"]),
                "detail": (
                    f"All-time {_fmt_pl_usd(at['all_time_pl'])} · "
                    f"{_fmt_pl_pct(at['all_time_pct'])} from start"
                ),
            },
            {
                "id": "peak",
                "label": "Peak / Max DD",
                "value": f"${at['peak']:,.2f}",
                "sub": f"DD {_fmt_pl_pct(-abs(at['max_drawdown_pct']))}",
                "detail": (
                    f"Peak ${at['peak']:,.2f} · max drawdown "
                    f"{at['max_drawdown_pct']:.2f}%"
                ),
            },
        ],
        grid_class="room3-metric-grid-2",
    )
    st.caption(
        f"{at['sessions']} sessions · {at['total_trades']} trades · "
        "trajectory since account start"
    )
    _render_equity_trajectory_chart(at)


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
    days = list(st.session_state.room3_archive_days or [])
    if not days:
        st.caption("No archived sessions — load demo to preview history.")
        return

    open_day = st.session_state.room3_history_open_day
    open_trade = st.session_state.room3_history_open_trade_id

    st.markdown("<div class='room3-history-wrap'>", unsafe_allow_html=True)
    for day in days:
        date_key = str(day.get("date"))
        is_day_open = open_day == date_key
        pl_usd = _fmt_pl_usd(day.get("pl_usd"))
        pl_pct = _fmt_pl_pct(day.get("pl_pct"))
        arrow = "▾" if is_day_open else "▸"
        day_label = (
            f"{arrow} {day.get('display')} · {day.get('trade_count')} trades · "
            f"{pl_usd} ({pl_pct})"
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
            hc1, hc2, hc3, hc4 = st.columns(4)
            with hc1:
                st.metric("Day P/L", pl_usd)
            with hc2:
                st.metric("Day %", pl_pct)
            with hc3:
                st.metric("Wins / Losses", f"{day.get('wins')} / {day.get('losses')}")
            with hc4:
                wr = day.get("win_rate")
                st.metric("Win rate", f"{wr:.0f}%" if wr is not None else "—")

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
            "Alpha decay + weather-fit warnings will read vault/matrix. "
            "Your ✓/✗ votes will feed that path when connected."
        )
    sync_log = st.session_state.room3_matrix_sync_log or []
    if sync_log:
        with st.expander("Matrix sync log (dry-run)", expanded=False):
            for line in sync_log[-8:]:
                st.caption(line)


def _render_operator_review_panel() -> None:
    st.markdown("### Operator review")
    st.caption("System proposes · you confirm ✓ good or ✗ bad · matrix hook later.")
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


def _render_trading_workspace(mode: str) -> None:
    if mode == ROOM3_MODE_PAPER:
        st.markdown("<div class='room3-paper-frame'>", unsafe_allow_html=True)
    _render_demo_toolbar()
    _render_broker_status_card(mode)
    _render_live_dashboard(mode)
    left, right = st.columns([1, 1])
    with left:
        _render_open_positions()
        _render_trade_history()
    with right:
        _render_session_summary()
        _render_operator_review_panel()
    _render_strategy_health_strip()
    if mode == ROOM3_MODE_PAPER:
        st.markdown("</div>", unsafe_allow_html=True)
    _render_session_history()


def _render_paper_workspace() -> None:
    _render_trading_workspace(ROOM3_MODE_PAPER)


def _render_live_workspace() -> None:
    _render_trading_workspace(ROOM3_MODE_LIVE)


def render_room3_trading_center() -> None:
    """Main Room 3 entry — UI shell only."""
    init_room3_session_state()
    _inject_room3_css()
    _maybe_roll_trading_session()

    _render_mode_slider()

    if not st.session_state.room3_demo_seeded:
        seed_demo_trading_session()

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
                st.caption("Build mode — live passcode disabled. Flip ROOM3_LIVE_SECURITY_ENABLED when ready.")
            _render_live_workspace()
    else:
        _render_paper_workspace()

    st.markdown("---")
    st.caption(
        f"Session · mode={st.session_state.room3_execution_mode} · "
        f"live_unlocked={bool(st.session_state.room3_live_unlocked)} · "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
