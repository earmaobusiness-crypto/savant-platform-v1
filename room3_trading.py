"""
Room 3 — Live / Paper Trading Center (shell).

Built as a standalone house: UI compartments, mode gates, and session state only.
No IBKR hooks, no vault writes, no Room 1/2 imports until explicitly wired later.
"""

from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOM3_MODE_PAPER = "paper"
ROOM3_MODE_LIVE = "live"
ROOM3_RECOVERY_EMAIL = "earmaobusiness@gmail.com"
# Flip to True later — passcode gate + recovery flow (no rebuild needed).
ROOM3_LIVE_SECURITY_ENABLED = False

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


def _inject_room3_css() -> None:
    st.markdown(
        """
        <style>
        .room3-shell {
            border: 1px solid #2A2A2A;
            border-radius: 14px;
            padding: 18px 20px;
            background: linear-gradient(180deg, #121212 0%, #0B0B0B 100%);
            margin-bottom: 16px;
        }
        .room3-shell-live {
            border-color: #5A2020;
            background: linear-gradient(180deg, #1A0F0F 0%, #0B0B0B 100%);
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
            border: 1px solid #252525;
            border-radius: 12px;
            padding: 14px 16px;
            background: #111;
            margin-bottom: 12px;
        }
        .room3-stat-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 0.08em; }
        .room3-stat-value { font-size: 20px; font-weight: 700; color: #EEE; }
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


def _render_broker_status_card(mode: str) -> None:
    is_live = mode == ROOM3_MODE_LIVE
    shell_class = "room3-shell room3-shell-live" if is_live else "room3-shell"
    lane = "LIVE" if is_live else "PAPER"
    st.markdown(
        f"<div class='{shell_class}'>"
        f"<div class='room3-kicker'>Room 3 · Trading center</div>"
        f"<div class='room3-title'>{_mode_label(mode)}</div>"
        f"<p class='room3-sub'>IBKR {lane} · <strong>Not connected</strong> "
        "(shell build — hooks reserved, nothing wired yet)</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("<div class='room3-card'>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-label'>Broker</div>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-value'>Offline</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='room3-card'>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-label'>Vault bridge</div>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-value'>Standby</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        st.markdown("<div class='room3-card'>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-label'>Auto execution</div>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-value'>Disabled</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c4:
        st.markdown("<div class='room3-card'>", unsafe_allow_html=True)
        st.markdown("<div class='room3-stat-label'>Open positions</div>", unsafe_allow_html=True)
        n = len(st.session_state.room3_open_positions or [])
        st.markdown(f"<div class='room3-stat-value'>{n}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_open_positions() -> None:
    st.markdown("### Open positions")
    rows = st.session_state.room3_open_positions or []
    if not rows:
        st.caption("No open trades — execution loop not connected yet.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_trade_history() -> None:
    st.markdown("### Trade log")
    rows = st.session_state.room3_trade_history or []
    if not rows:
        st.caption("History empty — fills will appear here after IBKR paper is wired.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_session_summary(mode: str) -> None:
    st.markdown("### Session summary")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Session P/L", "$0.00")
    with c2:
        st.metric("Wins", 0)
    with c3:
        st.metric("Losses", 0)
    with c4:
        st.metric("Win rate", "—")
    st.caption(
        "Post-trade review + vault reinforcement (good/bad confirms) land here after "
        "the execution loop is hooked to Room 2’s matrix read path."
    )


def _render_strategy_health_strip() -> None:
    st.markdown("### Strategy health (vault read — later)")
    st.info(
        "Alpha decay, halt flags, and weather-fit warnings will surface here from the "
        "vault/matrix — read-only. No strategy DNA edits from Room 3."
    )


def _render_operator_review_panel() -> None:
    st.markdown("### Operator review")
    st.caption(
        "After trades run: system proposes good/bad vs vault DNA; you confirm to reinforce."
    )
    reviews = st.session_state.room3_operator_reviews or []
    if not reviews:
        st.caption("No closed trades awaiting review.")
        return
    st.dataframe(reviews, use_container_width=True, hide_index=True)


def _render_live_only_panel() -> None:
    st.markdown("### Live controls")
    st.warning(
        "Live lane extras: capital snapshot, risk caps, and kill switch — placeholders until "
        "IBKR live gateway is wired."
    )
    c1, c2 = st.columns(2)
    with c1:
        st.metric("Buying power", "—")
        st.metric("Day P/L", "—")
    with c2:
        st.metric("Max position size", "Not set")
        st.metric("Kill switch", "ARMED (no orders)")


def _render_paper_workspace() -> None:
    _render_broker_status_card(ROOM3_MODE_PAPER)
    left, right = st.columns([1, 1])
    with left:
        _render_open_positions()
        _render_trade_history()
    with right:
        _render_session_summary(ROOM3_MODE_PAPER)
        _render_operator_review_panel()
    _render_strategy_health_strip()


def _render_live_workspace() -> None:
    _render_broker_status_card(ROOM3_MODE_LIVE)
    _render_live_only_panel()
    left, right = st.columns([1, 1])
    with left:
        _render_open_positions()
        _render_trade_history()
    with right:
        _render_session_summary(ROOM3_MODE_LIVE)
        _render_operator_review_panel()
    _render_strategy_health_strip()


def render_room3_trading_center() -> None:
    """Main Room 3 entry — UI shell only."""
    init_room3_session_state()
    _inject_room3_css()

    st.markdown("# ⚡ Room 3: Live / Paper Trading")
    st.caption(
        "Trading center shell — compartments built, utilities not hooked. "
        "Room 1 & Room 2 untouched."
    )

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
