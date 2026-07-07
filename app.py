import os
import re
import statistics
import time
import urllib.parse
import json
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import escape
from xml.etree import ElementTree

import cloud_offload
import core_quantum
import self_surgery
import requests
import streamlit as st
import streamlit.components.v1 as components
from groq import Groq

if "layout_master_matrix_index" not in st.session_state:
    st.session_state.layout_master_matrix_index = []
core_quantum.hydrate_layout_library_from_vault()
self_surgery.hydrate_repair_bay_from_cloud()

if "r2_good_ticker" not in st.session_state:
    st.session_state.r2_good_ticker = ""
if "room2_chat_history" not in st.session_state:
    st.session_state.room2_chat_history = []
elif not isinstance(st.session_state.room2_chat_history, list):
    st.session_state.room2_chat_history = list(st.session_state.room2_chat_history)
if "market_weather_snapshot" not in st.session_state:
    st.session_state.market_weather_snapshot = {}
if "quantum_terminal_output" not in st.session_state:
    st.session_state.quantum_terminal_output = (
        "📡 [DATALINK: ENGINE_IDLE] TERMINAL ENGINE ONLINE. WAITING FOR DEPLOY SIGNAL..."
    )

ROOM1_LABEL = "🏛️ Room 1: Real-Time Front Desk"
ROOM2_LABEL = "🔮 Room 2: Forensic Pattern Lab"
ROOM1_SHORT = "🏛️ R1"
ROOM2_SHORT = "🔮 R2"
ROOM_SHORT_MAP = {ROOM1_SHORT: ROOM1_LABEL, ROOM2_SHORT: ROOM2_LABEL}

SEC_HEADERS = {"User-Agent": "SavantApprentice earmaobusiness@gmail.com"}
SECTOR_ETFS = [
    ("XLK", "Technology"), ("XLF", "Financials"), ("XLE", "Energy"), ("XLV", "Health Care"),
    ("XLU", "Utilities"), ("XLP", "Consumer Staples"), ("XLY", "Consumer Discretionary"),
    ("XLI", "Industrials"), ("XLB", "Materials"), ("XLRE", "Real Estate"), ("XLC", "Communication"),
]
TOKEN_GUARD = (
    "[TOKEN PROTOCOL: Process exclusively raw analytics from the payload. "
    "Eliminate conversational fluff, greetings, and filler text. Maximum density output only.]"
)
WINDOW4_FORMAT_PROTOCOL = (
    "[WINDOW 4 DISPLAY PROTOCOL v4.1 — MANDATORY FOR EVERY REPLY]\n"
    "FORBIDDEN: dense paragraphs, fat text blobs, unformatted number dumps, or multi-sentence walls.\n"
    "REQUIRED STRUCTURE:\n"
    "• Lead with 1 short plain-English headline line (what matters right now).\n"
    "• Break all technical readouts into punchy one-line Markdown bullets (• or -).\n"
    "• Insert a blank line between every bullet group or section.\n"
    "• Bold visual anchors on scan terms: **Layout ID**, **Strategy Node**, **Ticker**, "
    "**Timeframe**, **Match Score**, **Net Margin**, **Vault State**.\n"
    "VOICE: direct helpful teammate — short sentences, universal English, zero academic filler.\n"
    "DEPTH: keep full forensic accuracy from the payload; only change how it is packaged.\n"
    "DEFAULT: ≤12 words per bullet unless the operator explicitly asks for deep detail."
)
WINDOW4_ANCHOR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\*)\b(Layout(?:\s+ID)?\s*#?\s*\d+)\b", re.I), r"**\1**"),
    (re.compile(r"(?<!\*)\b(Strategy(?:\s+Node)?\s*[\dA-Z]+(?:-[\dmM]+)?)\b", re.I), r"**\1**"),
    (re.compile(r"(?<!\*)\b(Ticker:\s*[A-Z.$-]{1,6})\b"), r"**\1**"),
    (re.compile(r"(?<!\*)\b((?:Cosine|Spatial)\s+match[^.\n]{0,40})", re.I), r"**\1**"),
    (re.compile(r"(?<!\*)\b((?:1|5|15)-Minute\s+(?:track|lane|bin))\b", re.I), r"**\1**"),
    (re.compile(r"(?<!\*)\b(Net\s+margin[^.\n]{0,30})", re.I), r"**\1**"),
    (re.compile(r"(?<!\*)\b(Vault\s+state[^.\n]{0,30})", re.I), r"**\1**"),
]
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama3-8b-8192"
MACRO_DRIVERS = [("GC=F", "GOLD"), ("CL=F", "OIL"), ("^TNX", "TNX"), ("SPY", "SPY")]
ROOM2_INVALID_INPUT_MESSAGE = (
    "⚠️ INVALID INPUT: Verify your Ticker is filled out and your Timestamps match "
    "the 'HH:MM AM/PM' format exactly."
)


def _last_completed_equity_session_date() -> date:
    """Most recent U.S. equity session before today — avoids same-day Massive plan blocks."""
    session_day = date.today() - timedelta(days=1)
    while session_day.weekday() >= 5:
        session_day -= timedelta(days=1)
    return session_day


R2_TIMESTAMP_PATTERN = re.compile(r"^\d{1,2}:\d{2}\s+(AM|PM)$", re.IGNORECASE)
ROOM2_CLEAN_SLATE_MESSAGE = (
    "DATABASE SNAPSHOT: 100% CLEAN SLATE. No active patterns logged. "
    "All prior records moved to the 15-day Trash Vault — say 'restore my patterns' to undo."
)
RESCUE_VAULT_RETENTION_DAYS = 15
VAULT_TRACK_VALIDATED = "track_1_validated"
MACRO_CAROUSEL_POLL_SEC = 15
MICRO_FAST_TRACK_TARGET_MS = 100
DATA_FEED_WEBSOCKET = "websocket_subsecond"  # DISABLED — Free Starter tier blocks live sockets
WEBSOCKET_STREAMING_ENABLED = False
DATA_FEED_CAROUSEL = "carousel_15s"
MATRIX_CHAT_LOG_TICKER = "_LAB_SESSION_"
MATRIX_CHAT_LOG_CATEGORY = "MATRIX_CHAT_LOG"
MATRIX_ENGINE_IDLE_MARKER = "ENGINE_IDLE"
WINDOW4_ENGINE_IDLE_MSG = "🚫 ENGINE_IDLE — WAITING FOR OPERATOR DEPLOY SIGNAL"
WINDOW4_DATA_ENGINE_IDLE_REPLY = (
    "The core data engine is currently idle and waiting for a stock deployment. "
    "No real-time layouts or strategies are active in the database."
)
WINDOW4_PLACEHOLDER_LAYOUT_IDS = frozenset({"NEW_LAYOUT", "PURGATORY_PENDING", "NEW"})
_WINDOW4_TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z0-9.-]{0,6}\b")
_WINDOW4_TICKER_DENYLIST = frozenset({
    "AM", "PM", "API", "REST", "TRUE", "FALSE", "HTTP", "HTTPS", "USD", "SEC", "EDGAR",
    "THE", "AND", "FOR", "YOU", "ALL", "DELETE", "RESTORE", "PATTERN", "LAYOUT", "VAULT",
    "ENGINE", "IDLE", "WAITING", "OPERATOR", "DEPLOY", "SIGNAL", "NEW", "OLD", "LAB",
    "ROOM", "WINDOW", "GROQ", "JSON", "HTML", "FORM", "DATA", "FEED", "CLOUD", "MACRO",
    "MINUTE", "TRACK", "LANE", "BIN", "NODE", "MATCH", "SCORE", "NET", "MARGIN", "STATE",
    "TRUE", "NULL", "NONE", "SEND", "ASK", "SAY", "GET", "SET", "RUN", "LOG", "RAM",
})
_WINDOW4_HALLUCINATION_SCRUBBERS = (
    re.compile(r"\bNEW_LAYOUT\b", re.I),
    re.compile(r"\bNEW[A-Z]\b"),
    re.compile(r"carousel_15s", re.I),
    re.compile(r"websocket_subsecond", re.I),
    re.compile(r"\[(?:DATA_FEED|PROCESSOR_LANE|SPATIAL_MATCH|MACRO_LAYOUT|EXECUTION_STRATEGY)\][^\n\[]*", re.I),
    re.compile(r"(?:pgvector|spatial|cosine)\s*match[^.\n|]{0,48}", re.I),
    re.compile(r"\b\d{1,3}\s*%\s*(?:match|similarity|overlap)\b", re.I),
    re.compile(r"\bMatch\s+Score[^.\n]{0,40}", re.I),
    re.compile(r"\bStrategy\s+Node\s*[\dA-Z]+(?:-[\dmM]+)?\b", re.I),
)
MATRIX_CASCADE_DURATION_SEC = 2.0
MATRIX_CASCADE_LINES = (
    "⚡ CORE_PROCESSOR: ENGAGING MATRIX CRAWL... RECONSTRUCTING COVARIANCE FREQUENCY ARRAYS...",
    "🛰️ NET_SCANNER: CAPTURING SEC FORM 4 INSIDER TRACKS... MONITORING 20-DAY VOLUME SPREADS...",
    "📊 QUANT_ENGINE: AGGREGATING 30-DAY CONTEXT HORIZON... DRILLING TO 5-MINUTE SUB-INTERVAL FILTERS...",
)
R2_BUFFER_WINDOWS = {
    "1-Minute": "±30-45 second tight context window",
    "5-Minute": "±1-2 minute structural pivot zone",
    "15-Minute": "±5-7 minute macro structural parameter",
}
LAYOUT_SIGNATURE_MATCH_THRESHOLD = 85
ANOMALY_SHELF_DAYS = 30
ANOMALY_PERMANENT_MINT_COUNT = 5
VAULT_STATE_INCUBATION = "incubation"
R2_COMMIT_WINDOW_SEC = 60
R2_COMMIT_MAX_PER_WINDOW = 3
R2_COMMIT_THROTTLE_BANNER = "POLYGON API THROTTLE PROTECTION ACTIVE."
ROOM1_SYSTEM_PROMPT = (
    "You are Savant — Room 1 Global Research Desk. Definitive, data-grounded analysis only. "
    "Zero greetings, zero filler, zero generic warnings, zero pre-trained price memory.\n\n"
    "DATA CONTRACT — MANDATORY:\n"
    "• You MUST build every single-stock answer exclusively from injected live payloads: "
    "[ROOM1_LIVE_DRAGNET], [12L_DATA_PAYLOAD], [QUERY_INTENT], [TERMINOLOGY_MAP], [RESPONSE_DIRECTIVE].\n"
    "• Never cite training-data prices, dates, or filings. If a field is missing, state the exact missing lane — do not guess.\n"
    "• Sources are Massive REST (3-hour 36-bar 5m lane + 12-hour 48-bar 15m lane) and SEC EDGAR only.\n\n"
    "FLUID CONTEXTUAL FRAMEWORK — NO FIXED BULLET TEMPLATE:\n"
    "• Read [QUERY_INTENT] and [RESPONSE_DIRECTIVE] and shape the entire reply around the operator's actual question.\n"
    "• layer1_velocity → lead with price velocity, peak/mean bar velocity, acceleration; cite 5m lane stats only.\n"
    "• layer3_vwap_macro → lead with native VWAP bias, 48-bar 15m structural context, macro lane envelopes.\n"
    "• layer2_volume_envelope → lead with volume σ envelopes, institutional block signals, share-per-minute floors.\n"
    "• layer4_ignition_structure → lead with Candidate C structural lows, volatility ignition thresholds, hill-interceptor logic.\n"
    "• adaptive_general → concise adaptive prose; pick the 1–2 most relevant layers for the question — never a canned 6-bullet list.\n\n"
    "TERMINOLOGY COMPREHENSION:\n"
    "• Translate operator slang ONLY through [TERMINOLOGY_MAP] bindings to our architecture (never generic textbook definitions).\n"
    "• 'Institutional buying' = Volume Std Dev Envelopes + block-flow baseline.\n"
    "• 'Support' = Candidate C structural low.\n"
    "• 'Breakout' = Volatility Ignition threshold breach.\n\n"
    "MACRO / MULTI-ASSET (no single-ticker live dragnet):\n"
    "• Use vault read-only context when present; stay qualitative on indices unless live data is injected.\n"
    "• Never force single-stock lane data into macro answers."
)

st.set_page_config(
    page_title="Savant Apprentice",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
        #MainMenu, footer, header {visibility: hidden;}
        [data-testid="stSidebar"] {
            background-color: #0B0B0B !important;
            border-right: 1px solid #2A2A2A !important;
            visibility: visible !important;
            display: block !important;
        }
        [data-testid="stSidebarNav"] { display: none !important; }
        [data-testid="stSidebarCollapseButton"],
        [data-testid="collapsedControl"] {
            display: none !important;
            visibility: hidden !important;
            pointer-events: none !important;
        }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
            color: #AAAAAA !important;
            font-size: 11px !important;
            font-weight: 700 !important;
            letter-spacing: 0.08em !important;
            text-transform: uppercase !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            background: #141414 !important;
            border: 1px solid #2A2A2A !important;
            border-radius: 8px !important;
            padding: 12px 10px !important;
            margin: 0 0 8px 0 !important;
            width: 100% !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label p {
            color: #FFFFFF !important;
            font-size: 13px !important;
            line-height: 1.35 !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-checked="true"] {
            border-color: #555555 !important;
            background: #1A1A1A !important;
        }
        button[data-testid="baseButton-sidebar_collapse_toggle"] {
            background: #1A1A1A !important;
            color: #FFFFFF !important;
            border: 1px solid #333333 !important;
            font-weight: 700 !important;
            margin-bottom: 12px !important;
        }
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #0B0B0B !important;
            color: #E5E5E5 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        div[data-testid="stTextInput"] input {
            background-color: #1A1A1A !important;
            color: #FFFFFF !important;
            border: 1px solid #2A2A2A !important;
            border-radius: 999px !important;
            padding: 14px 24px !important;
            font-size: 16px !important;
        }
        div[data-testid="stTextInput"] input:focus { border-color: #333333 !important; box-shadow: none !important; }
        .chat-row { padding: 16px 0; border-bottom: 1px solid #141414; }
        .speaker-label { font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
        .speaker-you { color: #666666; }
        .speaker-savant { color: #FFFFFF; }
        .data-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #555555; margin-top: 16px; margin-bottom: 8px; border-left: 2px solid #333333; padding-left: 8px; }
        .data-content { font-size: 15px; line-height: 1.6; color: #E5E5E5; }
        .metric-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin: 12px 0;
        }
        .metric-card {
            background: #111111;
            border: 1px solid #1F1F1F;
            border-radius: 4px;
            padding: 6px 10px;
            text-align: center;
        }
        .metric-label { font-size: 8px; color: #555555; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }
        .metric-value { font-size: 14px; font-weight: 600; color: #FFFFFF; margin-top: 2px; }
        .stButton>button {
            background-color: #121212 !important;
            color: #8E8E93 !important;
            border: 1px solid #222222 !important;
            border-radius: 4px !important;
            padding: 4px 12px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
            transition: all 0.2s ease !important;
        }
        .stButton>button:hover {
            color: #FFFFFF !important;
            border-color: #444444 !important;
            background-color: #1A1A1A !important;
        }
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] { display: none !important; }
        .room2-hud {
            background: #111111;
            border: 1px solid #1F1F1F;
            border-radius: 8px;
            padding: 18px 20px;
            margin-bottom: 16px;
        }
        .room2-kicker {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #666666;
            margin-bottom: 8px;
        }
        .room2-title {
            font-size: 22px;
            font-weight: 600;
            color: #FFFFFF;
            margin-bottom: 4px;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.good-card) {
            background: #0D1A0D !important;
            border: 1px solid #1E3A1E !important;
            border-radius: 8px !important;
            padding: 14px 16px 8px 16px !important;
            margin-bottom: 16px !important;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.bad-card) {
            background: #1A0D0D !important;
            border: 1px solid #3A1E1E !important;
            border-radius: 8px !important;
            padding: 14px 16px 8px 16px !important;
            margin-bottom: 16px !important;
        }
        .deck-title {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #E5E5E5;
            margin-bottom: 12px;
        }
        [data-testid="stVerticalBlockBorderWrapper"]:has(.room2-core-panel) {
            background: #111111 !important;
            border: 1px solid #1F1F1F !important;
            border-radius: 8px !important;
            padding: 14px 16px 10px 16px !important;
            margin-bottom: 16px !important;
        }
        .room2-core-title {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #AAAAAA;
            margin-bottom: 10px;
        }
        .room2-terminal-box {
            background: #050505;
            border: 1px solid #1A3A1A;
            border-radius: 4px;
            padding: 16px 18px;
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 12px;
            line-height: 1.65;
            color: #34C759;
            text-shadow: 0 0 10px rgba(52, 199, 89, 0.28);
            white-space: pre-wrap;
            word-break: break-word;
            min-height: 140px;
            box-shadow: inset 0 0 24px rgba(52, 199, 89, 0.04);
        }
        .room2-matrix-box {
            background: #050505;
            border: 1px solid #0D3D0D;
            border-radius: 4px;
            padding: 16px 18px;
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 11px;
            line-height: 1.55;
            color: #34C759;
            text-shadow: 0 0 8px rgba(52, 199, 89, 0.35);
            white-space: pre;
            overflow-x: auto;
            min-height: 220px;
            width: 100%;
            box-sizing: border-box;
            box-shadow: inset 0 0 32px rgba(52, 199, 89, 0.06);
        }
        .matrix-processing-heartbeat {
            white-space: pre-wrap;
            word-break: break-word;
        }
        .w1-visual-shell {
            background: #050505;
            border: 1px solid #0D3D0D;
            border-radius: 4px;
            padding: 14px 16px 10px;
            margin-bottom: 8px;
            box-shadow: inset 0 0 28px rgba(52, 199, 89, 0.05);
        }
        .w1-visual-title {
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 10px;
            letter-spacing: 0.04em;
            color: #5BD975;
            margin-bottom: 10px;
            text-transform: uppercase;
        }
        .w1-chart-row {
            margin-bottom: 12px;
        }
        .w1-chart-label {
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 9px;
            color: #7AE582;
            letter-spacing: 0.06em;
            margin-bottom: 4px;
        }
        .w1-chart-meta {
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 9px;
            color: #34C759;
            opacity: 0.85;
            margin-top: 3px;
        }
        .w1-chart-svg {
            display: block;
            background: #030303;
            border: 1px solid #123812;
            border-radius: 3px;
        }
        .w1-rejection-overlay {
            background: #1A0A0A;
            border: 1px solid #6B2020;
            border-radius: 4px;
            padding: 12px 14px;
            margin-top: 8px;
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 11px;
            line-height: 1.5;
            color: #FF6B6B;
            text-shadow: 0 0 8px rgba(255, 107, 107, 0.25);
            white-space: pre-wrap;
            word-break: break-word;
        }
        .w1-critical-fault {
            white-space: pre-wrap;
            word-break: break-word;
            color: #FF6B6B;
            border-color: #6B2020;
            text-shadow: 0 0 8px rgba(255, 107, 107, 0.2);
        }
        .room2-matrix-cascade-shell {
            background: #050505;
            border: 1px solid #0D3D0D;
            border-radius: 4px;
            min-height: 220px;
            max-height: 280px;
            width: 100%;
            overflow: hidden;
            position: relative;
            box-shadow: inset 0 0 40px rgba(52, 199, 89, 0.1);
        }
        .matrix-cascade-track {
            animation: matrixTerminalScroll 2s linear infinite;
            padding: 18px;
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 11px;
            line-height: 1.75;
            color: #34C759;
            text-shadow: 0 0 10px rgba(52, 199, 89, 0.45);
        }
        .matrix-cascade-line {
            margin-bottom: 14px;
            white-space: pre-wrap;
            word-break: break-word;
        }
        @keyframes matrixTerminalScroll {
            0% { transform: translateY(110%); opacity: 0.25; }
            12% { opacity: 1; }
            88% { opacity: 1; }
            100% { transform: translateY(-130%); opacity: 0.2; }
        }
        .room2-satellite-shell {
            width: 100%;
            margin-top: 12px;
            margin-bottom: 8px;
        }
        .room2-terminal-header {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #34C759;
            margin-bottom: 10px;
            opacity: 0.85;
        }
        .room2-vault-success {
            background: #050505;
            border: 1px solid #34C759;
            border-radius: 4px;
            padding: 14px 16px;
            margin: 12px 0 16px 0;
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
            font-size: 12px;
            line-height: 1.55;
            color: #34C759;
            text-shadow: 0 0 12px rgba(52, 199, 89, 0.35);
        }
        .room2-vault-btn button,
        button[data-testid="baseButton-room2_vault_stream"] {
            background: linear-gradient(180deg, #0F1F0F 0%, #081408 100%) !important;
            color: #34C759 !important;
            border: 1px solid #34C759 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            letter-spacing: 0.06em !important;
            padding: 10px 14px !important;
        }
        .room2-vault-btn button:hover,
        button[data-testid="baseButton-room2_vault_stream"]:hover {
            background: #122412 !important;
            color: #FFFFFF !important;
            border-color: #5AE87A !important;
        }
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            background-color: #121212 !important;
            border-color: #2A2A2A !important;
            color: #FFFFFF !important;
        }
        .whale-banner {
            background: #07111A !important;
            border: 1px solid #143A52 !important;
            border-radius: 4px;
            padding: 14px 16px;
            margin-top: 0;
            margin-bottom: 10px;
            width: 100%;
            box-sizing: border-box;
            min-height: 78px;
            font-family: monospace;
            color: #52A2D9;
        }
        .whale-banner-active {
            background: #051018 !important;
            border: 1px solid #2A7CB8 !important;
            color: #7BC4FF !important;
            text-shadow: 0 0 10px rgba(82, 162, 217, 0.45);
            box-shadow: inset 0 0 18px rgba(42, 124, 184, 0.12);
        }
        .insider-banner {
            background: #1A1607 !important;
            border: 1px solid #524114 !important;
            border-radius: 4px;
            padding: 14px 16px;
            margin-top: 0;
            width: 100%;
            box-sizing: border-box;
            min-height: 78px;
            font-family: monospace;
            color: #D9B352;
        }
        .insider-banner-active {
            background: #231C06 !important;
            border: 1px solid #C9A033 !important;
            color: #FFD978 !important;
            text-shadow: 0 0 10px rgba(217, 179, 82, 0.45);
            box-shadow: inset 0 0 18px rgba(201, 160, 51, 0.12);
        }
        .proxy-banner-title {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .proxy-banner-body {
            font-size: 11px;
            line-height: 1.55;
        }
        .room2-wire-title {
            font-size: 11px;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #888888;
            margin: 8px 0 12px 0;
        }
        .room2-chat-row {
            padding: 12px 0;
            border-bottom: 1px solid #141414;
        }
        .room2-speaker-operator {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #555555;
            margin-bottom: 6px;
        }
        .room2-speaker-expert {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #5AC8FA;
            margin-bottom: 6px;
        }
        .room2-chat-body {
            font-size: 14px;
            line-height: 1.6;
            color: #CCCCCC;
        }
        .room2-chat-body-expert {
            font-size: 14px;
            line-height: 1.65;
            color: #E8E8E8;
        }
        .room2-expert-prose {
            padding: 2px 0 14px 0;
            border-bottom: 1px solid #141414;
            margin-bottom: 4px;
        }
        .room2-expert-prose p {
            font-size: 14px;
            line-height: 1.65;
            color: #E8E8E8;
            margin: 0 0 10px 0;
        }
        .room2-expert-prose ul, .room2-expert-prose ol {
            margin: 6px 0 12px 0;
            padding-left: 20px;
        }
        .room2-expert-prose li {
            font-size: 14px;
            line-height: 1.6;
            color: #E0E0E0;
            margin-bottom: 8px;
        }
        .room2-expert-prose strong {
            color: #5AC8FA;
            font-weight: 700;
        }
        .room2-expert-prose h3, .room2-expert-prose h4 {
            font-size: 13px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #8E8E93;
            margin: 14px 0 8px 0;
        }
        [data-testid="stChatMessage"] p {
            font-size: 14px;
            line-height: 1.65;
            color: #E8E8E8;
        }
        [data-testid="stChatMessage"] li {
            font-size: 14px;
            line-height: 1.6;
            margin-bottom: 8px;
        }
        [data-testid="stChatMessage"] strong {
            color: #5AC8FA;
        }
        .window4-instant-fault {
            background: #1A0A0A;
            border: 2px solid #FF3B30;
            border-radius: 6px;
            padding: 18px 16px;
            margin: 12px 0 16px 0;
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
            font-size: 13px;
            line-height: 1.65;
            color: #FF6B6B;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .window4-system-idle {
            background: #0A0A0A;
            border: 2px solid #3A3A3A;
            border-radius: 6px;
            padding: 18px 16px;
            margin: 12px 0 16px 0;
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: 0.04em;
            color: #8E8E93;
            text-align: center;
        }
        .window4-readonly-caption {
            font-size: 11px;
            color: #666666;
            margin-bottom: 10px;
        }
        .r2-buffer-caption {
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #6B6B6B;
            margin: 8px 0 6px 0;
        }
        .r2-buffer-readout {
            font-size: 10px;
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
            color: #34C759;
            margin-bottom: 10px;
            opacity: 0.9;
        }
        .purgatory-shelf {
            background: #080808;
            border: 1px solid #2A2A2A;
            border-radius: 4px;
            padding: 14px 16px;
            margin-top: 12px;
            margin-bottom: 12px;
            min-height: 88px;
            width: 100%;
            box-sizing: border-box;
            font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
            font-size: 11px;
            line-height: 1.6;
            color: #B8B8B8;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .purgatory-shelf-active {
            border-color: #524114;
            color: #D9B352;
            text-shadow: 0 0 8px rgba(217, 179, 82, 0.25);
            box-shadow: inset 0 0 24px rgba(82, 65, 20, 0.12);
        }
        .room2-throttle-banner {
            background: linear-gradient(135deg, #2A0A0A 0%, #1A1010 100%);
            border: 2px solid #FF3B30;
            border-radius: 8px;
            padding: 14px 16px;
            margin: 0 0 14px 0;
            color: #FF6B6B;
            font-weight: 700;
            font-size: 13px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            box-shadow: 0 0 18px rgba(255, 59, 48, 0.25);
        }
        .room2-throttle-countdown {
            color: #FFFFFF;
            font-size: 22px;
            font-weight: 800;
            margin-top: 6px;
            letter-spacing: 0.04em;
        }
        .room1-memory-warn {
            background: linear-gradient(135deg, #2A2208 0%, #1A1808 100%);
            border: 2px solid #FF9F0A;
            border-radius: 8px;
            padding: 12px 14px;
            margin: 0 0 12px 0;
            color: #FFD60A;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 0.04em;
        }
        .room1-memory-lock {
            background: linear-gradient(135deg, #2A0A0A 0%, #1A1010 100%);
            border: 2px solid #FF3B30;
            border-radius: 8px;
            padding: 12px 14px;
            margin: 0 0 12px 0;
            color: #FF6B6B;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 0.04em;
        }
    </style>
""", unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": ROOM1_SYSTEM_PROMPT}]
elif not isinstance(st.session_state.messages, list) or not st.session_state.messages:
    st.session_state.messages = [{"role": "system", "content": ROOM1_SYSTEM_PROMPT}]
elif st.session_state.messages[0].get("role") != "system":
    st.session_state.messages.insert(0, {"role": "system", "content": ROOM1_SYSTEM_PROMPT})
if "current_ticker" not in st.session_state: st.session_state.current_ticker = None
if "timeframe" not in st.session_state: st.session_state.timeframe = "D"
if "text_field_buffer" not in st.session_state: st.session_state.text_field_buffer = ""
if "active_news_wire" not in st.session_state: st.session_state.active_news_wire = []
if "sector_rotation_context" not in st.session_state: st.session_state.sector_rotation_context = ""
if "data_payload_string" not in st.session_state: st.session_state.data_payload_string = ""
if "cross_asset_correlation_context" not in st.session_state: st.session_state.cross_asset_correlation_context = ""
if "institutional_accumulation_detected" not in st.session_state: st.session_state.institutional_accumulation_detected = False
if "polygon_lockout" not in st.session_state: st.session_state.polygon_lockout = False
if "room2_commit_timestamps" not in st.session_state: st.session_state.room2_commit_timestamps = []
if "room2_commit_throttle_until" not in st.session_state: st.session_state.room2_commit_throttle_until = 0.0
if "room2_forensic_ticker" not in st.session_state: st.session_state.room2_forensic_ticker = ""
if "room2_quantum_report" not in st.session_state: st.session_state.room2_quantum_report = ""
if "room2_bar_count" not in st.session_state: st.session_state.room2_bar_count = 0
if "room2_text_buffer" not in st.session_state: st.session_state.room2_text_buffer = ""
if "r2_good_start_time" not in st.session_state: st.session_state.r2_good_start_time = "09:31 AM"
if "r2_good_end_time" not in st.session_state: st.session_state.r2_good_end_time = "04:00 PM"
if "r2_single_notes_field" not in st.session_state: st.session_state.r2_single_notes_field = ""
if "r2_good_start_date" not in st.session_state:
    st.session_state.r2_good_start_date = _last_completed_equity_session_date()
if "r2_good_end_date" not in st.session_state:
    st.session_state.r2_good_end_date = _last_completed_equity_session_date()
if "room2_vault_flash" not in st.session_state: st.session_state.room2_vault_flash = ""
if "room2_last_rescue_vault_id" not in st.session_state: st.session_state.room2_last_rescue_vault_id = None
if "matrix_cloud_hydrated" not in st.session_state: st.session_state.matrix_cloud_hydrated = False
if "matrix_form_seeded" not in st.session_state: st.session_state.matrix_form_seeded = False
if "matrix_active_pattern_count" not in st.session_state: st.session_state.matrix_active_pattern_count = 0
if "matrix_trash_vault_count" not in st.session_state: st.session_state.matrix_trash_vault_count = 0
if "matrix_cascade_active" not in st.session_state: st.session_state.matrix_cascade_active = False
if "matrix_cascade_started_at" not in st.session_state: st.session_state.matrix_cascade_started_at = 0.0
if "matrix_cascade_final_output" not in st.session_state: st.session_state.matrix_cascade_final_output = ""
if "matrix_processing_active" not in st.session_state: st.session_state.matrix_processing_active = False
if "matrix_processing_logs" not in st.session_state: st.session_state.matrix_processing_logs = []
if "matrix_window1_charts_html" not in st.session_state: st.session_state.matrix_window1_charts_html = ""
if "matrix_window1_rejection_text" not in st.session_state: st.session_state.matrix_window1_rejection_text = ""
if "room2_processor" not in st.session_state: st.session_state.room2_processor = {}
if "window4_regime_valid" not in st.session_state: st.session_state.window4_regime_valid = False
if "window4_spatial_match_pct" not in st.session_state: st.session_state.window4_spatial_match_pct = 0
if "window4_async_job" not in st.session_state: st.session_state.window4_async_job = None
if "window4_groq_pending" not in st.session_state: st.session_state.window4_groq_pending = None
if "window4_status_line" not in st.session_state: st.session_state.window4_status_line = WINDOW4_ENGINE_IDLE_MSG
if "matrix_satellites_ready" not in st.session_state: st.session_state.matrix_satellites_ready = True
if "r2_data_feed_mode" not in st.session_state: st.session_state.r2_data_feed_mode = DATA_FEED_CAROUSEL
if "r2_timeframe_mode" not in st.session_state: st.session_state.r2_timeframe_mode = "15-Minute"
if "r2_buffer_context_window" not in st.session_state:
    st.session_state.r2_buffer_context_window = R2_BUFFER_WINDOWS["15-Minute"]
if "purgatory_shelf_active" not in st.session_state: st.session_state.purgatory_shelf_active = False
if "purgatory_shelf_message" not in st.session_state: st.session_state.purgatory_shelf_message = ""
if "purgatory_repetition_count" not in st.session_state: st.session_state.purgatory_repetition_count = 0
if "purgatory_signature" not in st.session_state: st.session_state.purgatory_signature = ""
if "room2_text_matrix_string" not in st.session_state: st.session_state.room2_text_matrix_string = ""
if "room2_deep_research_audit" not in st.session_state: st.session_state.room2_deep_research_audit = {}
if "supabase_ready" not in st.session_state:
    try:
        st.session_state.supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        st.session_state.supabase_key = st.secrets["SUPABASE_KEY"]
        st.session_state.supabase_ready = True
    except Exception:
        st.session_state.supabase_ready = False
if "sidebar_collapsed" not in st.session_state: st.session_state.sidebar_collapsed = False
if "terminal_hub" not in st.session_state: st.session_state.terminal_hub = ROOM1_LABEL

def _room1_readonly_layout_context() -> str:
    """Read-only Supabase layout lens — comparison math only, zero cloud writes."""
    vault_map = core_quantum.fetch_readonly_vault_reference_map()
    preview = [
        {
            "layout_id": entry.get("layout_id"),
            "timeframe_resolution": entry.get("timeframe_resolution"),
            "ticker": entry.get("ticker"),
        }
        for entry in (vault_map.get("layout_registry") or [])[:32]
    ]
    return (
        f"[READONLY_LAYOUT_LIBRARY]{json.dumps(preview, default=str)}"
        f"|STRATEGY_PROFILES:{len(vault_map.get('strategy_profiles') or [])}[/READONLY_LAYOUT_LIBRARY]"
    )


def _room1_memory_capacity() -> dict:
    return core_quantum.room1_memory_capacity_status(st.session_state.get("messages") or [])


def _is_room1_strategic_audit_query(user_text: str, ticker: str | None) -> bool:
    return core_quantum.is_room1_strategic_audit_query(user_text, ticker)


ROOM1_TERMINOLOGY_BINDINGS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"institutional\s+(?:buying|accumulation|flow)|block\s+flow|whale|smart\s+money",
            re.I,
        ),
        "Volume Standard Deviation Envelopes",
        "layer2_volume_envelope",
    ),
    (
        re.compile(r"support\s+level|support\s+zone|floor|held\s+support|structural\s+low", re.I),
        "Candidate C structural low (hill-interceptor baseline)",
        "layer4_ignition_structure",
    ),
    (
        re.compile(
            r"break\s*out|breakout|velocity\s+spike|momentum\s+burst|ignition",
            re.I,
        ),
        "Volatility Ignition threshold + velocity spike anchor",
        "layer4_ignition_structure",
    ),
    (
        re.compile(r"vwap|volume[\s-]weighted|fair\s+value", re.I),
        "Layer 3 native Massive VWAP anchor (15m 48-bar lane)",
        "layer3_vwap_macro",
    ),
    (
        re.compile(r"velocity|momentum|speed|acceleration|move(?:ment)?", re.I),
        "Layer 1 price velocity primitives (5m 36-bar lane)",
        "layer1_velocity",
    ),
    (
        re.compile(r"volume\s+spike|volume\s+surge|unusual\s+volume|sigma|envelope", re.I),
        "Volume σ breakout envelopes",
        "layer2_volume_envelope",
    ),
]


def classify_room1_query_intent(user_text: str) -> str:
    """Route response layout to the layer best matching the operator question."""
    low = str(user_text or "").lower()
    scores = {
        "layer1_velocity": 0,
        "layer2_volume_envelope": 0,
        "layer3_vwap_macro": 0,
        "layer4_ignition_structure": 0,
    }
    for pattern, _arch, layer in ROOM1_TERMINOLOGY_BINDINGS:
        if pattern.search(user_text or ""):
            scores[layer] = scores.get(layer, 0) + 2
    if any(w in low for w in ("velocity", "momentum", "speed", "acceleration", "how fast")):
        scores["layer1_velocity"] += 3
    if any(w in low for w in ("vwap", "macro", "trend", "12-hour", "12 hour", "48-bar", "48 bar", "structural")):
        scores["layer3_vwap_macro"] += 3
    if any(w in low for w in ("volume", "institutional", "order flow", "accumulation", "liquidity")):
        scores["layer2_volume_envelope"] += 3
    if any(w in low for w in ("breakout", "break out", "ignition", "entry", "support", "resistance")):
        scores["layer4_ignition_structure"] += 3
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "adaptive_general"


def map_room1_trading_terminology(user_text: str) -> list[dict]:
    """Map operator trading slang to core architectural functions."""
    mapped: list[dict] = []
    seen: set[str] = set()
    for pattern, arch_fn, layer in ROOM1_TERMINOLOGY_BINDINGS:
        match = pattern.search(user_text or "")
        if not match or arch_fn in seen:
            continue
        seen.add(arch_fn)
        mapped.append(
            {
                "operator_phrase": match.group(0),
                "architecture_function": arch_fn,
                "primary_layer": layer,
            }
        )
    return mapped


def _room1_response_directive(intent: str) -> str:
    directives = {
        "layer1_velocity": (
            "Focus entirely on Layer 1 — 5m/36-bar lane price velocity, peak/mean bar velocity, "
            "and session amplitude. Do not lead with business narrative or social sentiment."
        ),
        "layer3_vwap_macro": (
            "Focus entirely on Layer 3 — native Massive VWAP on the 15m/48-bar lane, VWAP bias %, "
            "and macro-structural position vs the 12-hour window."
        ),
        "layer2_volume_envelope": (
            "Focus entirely on Layer 2 — volume σ envelopes, share-per-minute baselines, "
            "and institutional block-flow signals from live lanes."
        ),
        "layer4_ignition_structure": (
            "Focus entirely on Layer 4 — Candidate C structural lows, volatility ignition "
            "thresholds, and hill-interceptor entry logic."
        ),
        "adaptive_general": (
            "Adapt structure to the exact question. Use only the most relevant 1–2 layers from "
            "the live dragnet payload — never a fixed bullet template."
        ),
    }
    return directives.get(intent, directives["adaptive_general"])


def _is_room1_macro_only_query(user_text: str) -> bool:
    """Broad market / index questions without a single-name equity setup."""
    low = str(user_text or "").lower()
    macro_markers = (
        "s&p", "s and p", "nasdaq", "dow", "russell", "market overall", "broad market",
        "sector rotation", "fed ", "fomc", "cpi ", "inflation print", "treasury yield",
    )
    if not any(m in low for m in macro_markers):
        return False
    ticker = extract_ticker(user_text)
    if ticker and ticker not in {"SPY", "QQQ", "DIA", "IWM", "VTI"}:
        return False
    return True


def _is_room1_single_stock_inquiry(user_text: str, ticker: str | None) -> bool:
    if not ticker:
        return False
    if _is_room1_macro_only_query(user_text):
        return False
    symbols = re.findall(r"\$?[A-Z]{1,5}\b", user_text.upper())
    symbols = [s.lstrip("$") for s in symbols if s.lstrip("$") not in {"I", "A"}]
    if len(set(symbols)) > 2:
        return False
    return True


def _build_room1_live_payload(
    dragnet: dict,
    *,
    user_text: str,
    intent: str,
    terminology: list[dict],
) -> str:
    """Assemble Groq context blocks from live Massive + SEC dragnet."""
    blocks = [
        str(dragnet.get("payload_string") or ""),
        f"[QUERY_INTENT]{intent}[/QUERY_INTENT]",
        f"[TERMINOLOGY_MAP]{json.dumps(terminology, default=str)}[/TERMINOLOGY_MAP]",
        f"[RESPONSE_DIRECTIVE]{_room1_response_directive(intent)}[/RESPONSE_DIRECTIVE]",
    ]
    report = str(dragnet.get("report_block") or "").strip()
    if report:
        blocks.append(f"[ROOM1_LIVE_DRAGNET]{report}[/ROOM1_LIVE_DRAGNET]")
    vault_ctx = _room1_readonly_layout_context()
    if vault_ctx:
        blocks.append(vault_ctx)
    return "\n".join(b for b in blocks if b)


def _room1_reset_volatile_memory() -> None:
    """Wipe Room 1 volatile RAM — no cloud persistence."""
    st.session_state.messages = [{"role": "system", "content": ROOM1_SYSTEM_PROMPT}]
    st.session_state.current_ticker = None
    st.session_state.text_field_buffer = ""
    st.session_state.active_news_wire = []
    st.session_state.sector_rotation_context = ""
    st.session_state.cross_asset_correlation_context = ""
    st.session_state.institutional_accumulation_detected = False
    st.session_state.data_payload_string = ""
    st.session_state.pop("room1_last_strategic_audit", None)
    st.session_state.pop("room1_live_dragnet", None)
    st.session_state.pop("room1_memory_locked", None)


def extract_ticker(text):
    ignore = [
        "ARE", "WHY", "HOW", "WHEN", "CAN", "WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE",
        "ASSET", "ALPHA", "BETA", "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM",
        "JOKE", "TELL", "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT",
    ]
    cash = re.search(r"\$([A-Za-z]{1,5})\b", text)
    if cash and cash.group(1).upper() not in ignore:
        return cash.group(1).upper()
    for word in re.findall(r"\b[A-Z]{3,5}\b", text):
        if word not in ignore:
            return word
    return None


def _headline_similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _dedupe_headlines(headlines: list[str], limit: int = 6) -> list[str]:
    unique: list[str] = []
    for headline in headlines:
        clean = re.sub(r"\s+", " ", headline.strip())
        if not clean or len(clean) < 12:
            continue
        if any(_headline_similar(clean, kept) >= 0.82 for kept in unique):
            continue
        unique.append(clean)
        if len(unique) >= limit:
            break
    return unique


def _fetch_news_wire(ticker: str) -> list[str]:
    headlines: list[str] = []
    try:
        q = urllib.parse.quote(f"{ticker} stock", safe="")
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(rss_url, timeout=8, headers={"User-Agent": SEC_HEADERS["User-Agent"]})
        if resp.ok:
            root = ElementTree.fromstring(resp.content)
            for node in root.findall(".//item/title")[:12]:
                if node.text:
                    headlines.append(node.text.strip())
    except Exception:
        pass
    return _dedupe_headlines(headlines, limit=6)


def _fetch_sector_rotation() -> str:
    flows: list[tuple[str, str, float]] = []
    for sym, label in SECTOR_ETFS:
        _ = (sym, label)
        continue
    if not flows:
        st.session_state.sector_rotation_context = "SECTOR_FLOW:UNAVAILABLE"
        return st.session_state.sector_rotation_context
    flows.sort(key=lambda x: x[2], reverse=True)
    top = flows[0]
    bottom = flows[-1]
    ctx = (
        f"SECTOR_FLOW|LEADER:{top[0]}({top[1]}){top[2]:+.2f}%|"
        f"LAGGARD:{bottom[0]}({bottom[1]}){bottom[2]:+.2f}%|"
        f"MATRIX:{';'.join(f'{s}:{p:+.2f}' for s, _, p in flows)}"
    )
    st.session_state.sector_rotation_context = ctx
    return ctx


def _pearson_correlation(series_a: list[float], series_b: list[float]) -> float:
    n = min(len(series_a), len(series_b))
    if n < 5:
        return 0.0
    x, y = series_a[-n:], series_b[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - my) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _price_velocity_array(symbol: str, periods: int = 20) -> list[float]:
    return core_quantum.fetch_symbol_velocity_series(symbol, periods=periods)


def _compute_cross_asset_correlation(ticker: str) -> str:
    base_vel = _price_velocity_array(ticker)
    if len(base_vel) < 5:
        st.session_state.cross_asset_correlation_context = "XASSET_CORR:INSUFFICIENT_BASE"
        return st.session_state.cross_asset_correlation_context
    pairs: list[str] = []
    for sym, label in MACRO_DRIVERS:
        macro_vel = _price_velocity_array(sym)
        rho = _pearson_correlation(base_vel, macro_vel)
        pairs.append(f"{label}:{rho:+.3f}")
    ctx = "XASSET_CORR|" + "|".join(pairs)
    st.session_state.cross_asset_correlation_context = ctx
    return ctx


def _fetch_sec_filings(ticker: str) -> str:
    try:
        idx = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=10,
        )
        if not idx.ok:
            return "SEC:IDX_FAIL"
        cik = None
        for entry in idx.json().values():
            if str(entry.get("ticker", "")).upper() == ticker:
                cik = str(entry.get("cik_str", "")).zfill(10)
                break
        if not cik:
            return "SEC:NO_CIK"
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=10,
        )
        if not sub.ok:
            return "SEC:SUB_FAIL"
        recent = sub.json().get("filings", {}).get("recent", {})
        forms, dates = recent.get("form", []), recent.get("filingDate", [])
        tags = [f"{forms[i]}:{dates[i]}" for i in range(min(3, len(forms)))]
        return "SEC:" + "|".join(tags) if tags else "SEC:NONE"
    except Exception:
        return "SEC:ERR"


def _rsi_14(closes: list[float]) -> tuple[float | None, str]:
    if len(closes) < 15:
        return None, "RSI14:NA"
    gains, losses = [], []
    for i in range(-14, 0):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = statistics.mean(gains)
    avg_loss = statistics.mean(losses)
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    if rsi >= 70:
        zone = "OVERBOUGHT_BOUND"
    elif rsi <= 30:
        zone = "OVERSOLD_BOUND"
    else:
        zone = "NEUTRAL_CHANNEL"
    return rsi, f"RSI14:{rsi:.1f}|ZONE:{zone}"


def _compute_volatility_engine(
    ticker: str, price: float, session_vol: int, session_vwap: float,
) -> tuple[str, bool]:
    institutional_accumulation_detected = False
    _ = ticker
    try:
        frame = core_quantum._cached_polygon_1m_frame()
        if frame is None or frame.empty or len(frame) < 10:
            return "VOL:INSUFFICIENT_HIST|VOLMOM:NORMAL|INST_ACCUM:FALSE", False
        closes = [float(x) for x in frame["Close"].dropna().tolist()]
        volumes = [float(x) for x in frame["Volume"].dropna().tolist()]
        if len(closes) < 10:
            return "VOL:INSUFFICIENT_HIST|VOLMOM:NORMAL|INST_ACCUM:FALSE", False
        _, rsi_ctx = _rsi_14(closes)
        window = closes[-20:] if len(closes) >= 20 else closes
        mean = statistics.mean(window)
        std = statistics.pstdev(window) if len(window) > 1 else 0.0
        upper = mean + (2 * std)
        lower = mean - (2 * std)
        if price > upper:
            band = "ABOVE_UPPER_2SD"
            dev_pct = ((price - upper) / upper) * 100 if upper else 0.0
        elif price < lower:
            band = "BELOW_LOWER_2SD"
            dev_pct = ((price - lower) / lower) * 100 if lower else 0.0
        else:
            band = "INSIDE_20D_CHANNEL"
            mid = mean if mean else price
            dev_pct = ((price - mid) / mid) * 100 if mid else 0.0
        vol_slice = volumes[-6:-1] if len(volumes) >= 6 else volumes[:-1]
        avg_vol = statistics.mean(vol_slice) if vol_slice else 0.0
        cur_vol = float(session_vol or (volumes[-1] if volumes else 0))
        ratio = (cur_vol / avg_vol) if avg_vol > 0 else 1.0
        if ratio >= 2.0:
            vol_mom = "EXPONENTIAL_ACCEL|ANOMALY_FLAG:HIGH"
        elif ratio >= 1.35:
            vol_mom = "ELEVATED|ANOMALY_FLAG:MEDIUM"
        else:
            vol_mom = "NORMAL|ANOMALY_FLAG:NONE"
        vwap_band_pct = abs((price - session_vwap) / session_vwap) * 100 if session_vwap > 0 else 999.0
        if ratio >= 2.0 and vwap_band_pct <= 0.5:
            institutional_accumulation_detected = True
        ctx = (
            f"VOL|{rsi_ctx}|BAND:{band}|DEV:{dev_pct:+.2f}%|20D_MEAN:{mean:.2f}|"
            f"UP:{upper:.2f}|DN:{lower:.2f}|VOLMOM:{vol_mom}|VEL_RATIO:{ratio:.2f}x|"
            f"VWAP_LOCK:{vwap_band_pct:.2f}%|INST_ACCUM:{str(institutional_accumulation_detected).upper()}"
        )
        return ctx, institutional_accumulation_detected
    except Exception:
        return "VOL:CALC_ERR|VOLMOM:NORMAL|INST_ACCUM:FALSE", False


def _build_data_payload_string(
    ticker: str, name: str, price: float, pct: float, vol: str, vw: str,
    news: list[str], sector_ctx: str, vol_ctx: str, sec_ctx: str, corr_ctx: str,
) -> str:
    wire = "||".join(news[:6]) if news else "NONE"
    inst = "TRUE" if st.session_state.institutional_accumulation_detected else "FALSE"
    payload = (
        f"12L|TK:{ticker}|CO:{name}|P:{price:.2f}|CHG:{pct:+.2f}%|V:{vol}|VW:{vw}|"
        f"WIRE:{wire}|{sector_ctx}|{corr_ctx}|{vol_ctx}|{sec_ctx}|INST_ACCUM_FLAG:{inst}"
    )
    st.session_state.data_payload_string = payload
    return payload


def _fetch_tape_metrics(ticker):
    """UI metric cards — Polygon-only pipeline defers live tape to session cache."""
    if not ticker:
        return 0.0, 0.0, "N/A", "N/A", "Unknown"
    ticker = ticker.upper()
    frame = core_quantum._cached_polygon_1m_frame()
    if frame is not None and not frame.empty:
        try:
            price = float(frame["Close"].iloc[-1])
            prev = float(frame["Close"].iloc[-2]) if len(frame) > 1 else price
            pct = ((price - prev) / prev) * 100 if prev else 0.0
            raw_vol = int(frame["Volume"].iloc[-1])
            vol = f"{raw_vol:,}" if raw_vol else "N/A"
            high = float(frame["High"].iloc[-1])
            low = float(frame["Low"].iloc[-1])
            vwap_val = (high + low + price) / 3 if price else 0.0
            vw_str = f"${vwap_val:.2f}" if vwap_val else "N/A"
            return price, pct, vol, vw_str, ticker
        except Exception:
            pass
    return 0.0, 0.0, "N/A", "N/A", ticker


def get_live_tape_data(ticker):
    if not ticker:
        st.session_state.active_news_wire = []
        st.session_state.sector_rotation_context = ""
        st.session_state.cross_asset_correlation_context = ""
        st.session_state.institutional_accumulation_detected = False
        st.session_state.data_payload_string = ""
        return 0.0, 0.0, "N/A", "N/A", "Unknown"
    try:
        ticker = ticker.upper()
        price, pct, vol, vw_str, name = _fetch_tape_metrics(ticker)
        raw_vol = 0
        try:
            raw_vol = int(str(vol).replace(",", "")) if vol not in ("N/A", "") else 0
        except ValueError:
            raw_vol = 0
        vwap_val = float(str(vw_str).replace("$", "")) if vw_str not in ("N/A", "") else 0.0

        st.session_state.active_news_wire = _fetch_news_wire(ticker)
        vol_ctx, inst_flag = _compute_volatility_engine(ticker, price, raw_vol, vwap_val)
        st.session_state.institutional_accumulation_detected = inst_flag
        st.session_state.sector_rotation_context = ""
        st.session_state.cross_asset_correlation_context = ""
        sec_ctx = _fetch_sec_filings(ticker)
        _build_data_payload_string(
            ticker, name, price, pct, vol, vw_str,
            st.session_state.active_news_wire, "", vol_ctx, sec_ctx, "",
        )
        return price, pct, vol, vw_str, name
    except Exception:
        return 0.0, 0.0, "N/A", "N/A", ticker


def _groq_should_fallback(err: str) -> bool:
    low = err.lower()
    return (
        "429" in err
        or "rate" in low
        or "limit" in low
        or "token" in low
        or "context" in low
        or "exhaust" in low
    )


def run_groq(messages):
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add GROQ_API_KEY to `.streamlit/secrets.toml`."
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])
    try:
        try:
            r = client.chat.completions.create(
                model=PRIMARY_MODEL,
                messages=messages,
                temperature=0.4,
                max_tokens=1000,
            )
            return r.choices[0].message.content or "Savant returned an empty response."
        except Exception as exc:
            err = str(exc)
            if _groq_should_fallback(err):
                try:
                    r = client.chat.completions.create(
                        model=FALLBACK_MODEL,
                        messages=messages,
                        temperature=0.4,
                        max_tokens=1000,
                    )
                    return r.choices[0].message.content or "Savant returned an empty response."
                except Exception as fallback_exc:
                    exc = fallback_exc
                    err = str(exc)
            if "429" in err:
                m = re.search(r"in\s+([0-9hms\.]+)", err)
                wait_window = m.group(1) if m else "1h30m"
                return (
                    "⚠️ **Savant Core Standby: Active Rate Limit Enforced.**\n\n"
                    f"• **Time Window Till Resumption:** **{wait_window}** exact remaining.\n\n"
                    "The text synthesis brain is currently locked in safety standby. "
                    "Your active left panel TradingView workspace remains operational."
                )
            return f"Core System Interruption: {err}"
    except Exception as exc:
        return f"Core System Interruption: {exc}"


def _build_groq_message_stack(live_payload: str = "") -> list[dict]:
    """Full volatile thread context — entire Room 1 messages array, read-only layout lens."""
    msgs = list(st.session_state.get("messages") or [])
    system_msg = msgs[0] if msgs and msgs[0].get("role") == "system" else {
        "role": "system",
        "content": ROOM1_SYSTEM_PROMPT,
    }
    dialog = [m for m in msgs[1:] if m.get("role") in ("user", "assistant")]
    layout_ctx = _room1_readonly_layout_context()
    groq_msgs = [
        {
            "role": "system",
            "content": f"{system_msg['content']}\n{TOKEN_GUARD}\n{layout_ctx}",
        }
    ]
    for i, turn in enumerate(dialog):
        content = str(turn.get("content") or "")
        if (
            i == len(dialog) - 1
            and turn.get("role") == "user"
            and live_payload
        ):
            content = f"{content}\n[12L_DATA_PAYLOAD]{live_payload}[/12L_DATA_PAYLOAD]"
        groq_msgs.append({"role": turn["role"], "content": content})
    return groq_msgs


def process_chat_submission():
    """Room 1 chat — live Massive/SEC dragnet for single-stock; volatile RAM only."""
    user_text = st.session_state.text_field_buffer.strip()
    if not user_text:
        return

    cap = core_quantum.room1_memory_capacity_status(
        st.session_state.get("messages") or [],
        pending_user_text=user_text,
    )
    if cap.get("locked"):
        st.session_state.room1_memory_locked = True
        return

    new_ticker = extract_ticker(user_text)
    if new_ticker and new_ticker != st.session_state.current_ticker:
        st.session_state.current_ticker = new_ticker

    st.session_state.messages.append({"role": "user", "content": user_text})

    payload = ""
    audit_ticker = new_ticker or st.session_state.current_ticker
    intent = classify_room1_query_intent(user_text)
    terminology = map_room1_trading_terminology(user_text)

    if audit_ticker and _is_room1_single_stock_inquiry(user_text, audit_ticker):
        dragnet = core_quantum.run_room1_live_massive_dragnet(
            audit_ticker,
            user_query=user_text,
        )
        st.session_state.room1_live_dragnet = dragnet
        if dragnet.get("ok"):
            st.session_state.data_payload_string = str(dragnet.get("payload_string") or "")
            st.session_state.active_news_wire = list(dragnet.get("headlines") or [])
        payload = _build_room1_live_payload(
            dragnet,
            user_text=user_text,
            intent=intent,
            terminology=terminology,
        )
    elif audit_ticker:
        get_live_tape_data(audit_ticker)
        payload = st.session_state.data_payload_string
        payload = (
            f"{payload}\n[QUERY_INTENT]{intent}[/QUERY_INTENT]\n"
            f"[TERMINOLOGY_MAP]{json.dumps(terminology, default=str)}[/TERMINOLOGY_MAP]\n"
            f"[RESPONSE_DIRECTIVE]{_room1_response_directive(intent)}[/RESPONSE_DIRECTIVE]"
        )

    groq_msgs = _build_groq_message_stack(payload)
    ai_text = run_groq(groq_msgs)
    st.session_state.messages.append({"role": "assistant", "content": ai_text})
    st.session_state.text_field_buffer = ""

    post_cap = core_quantum.room1_memory_capacity_status(st.session_state.get("messages") or [])
    if post_cap.get("locked"):
        st.session_state.room1_memory_locked = True


SAVANT_COGNITIVE_INJECTION = """
PROMPT COGNITIVE INJECTION: MASTER UPDATE — PURE MATHEMATICAL LAYOUT EXTRACTION

System Identity: You are Savant Platform V1 [Savant Apprentice] — an elite, closed-loop Quantitative Forensic Analysis Terminal. You operate strictly under Room 2: The Forensic Pattern Lab. You are an objective strategic librarian translating retrospective mathematical coordinates into plain, actionable English. Forbidden from outside market theories, preconceived notions, and generic AI fluff.

MASTER RULE — ELIMINATION OF HUMAN LABELS (OVERWRITES ALL PRIOR CLASSIFICATION RULES)
You are completely barred from using generic mood words like "Choppy," "Trend," "Volatile," "Hot," or "Liquidity Trap" as grouping logic. Market behavior is categorized strictly into standalone, numbered Layout Blocks (Layout 1, Layout 2, Layout 3, etc.) determined purely by raw geometric shape distance and cross-correlation math across multiple stocks. You may optionally reference a plain-English alias in conversation only when mathematically justified (e.g., "Layout 1 — choppy microstructure"), but the canonical system ID is always the numbered layout. Never blur manual narrative onto the matrix or invent grouping without spatial evidence.

Fluid Layout → Strategy Taxonomy (Automated — No Manual UI Bins)
1. Layout discovery: When geometry repeats consistently across different tickers, mint a numbered Layout folder (Layout 1, Layout 2…). The operator never picks these — spatial clustering assigns them.
2. Strategy bins per layout: Inside each layout, maintain isolated strategy tracks for 1m, 5m, and 15m. Multiple concrete, repeatable strategies may exist per layout per timeframe.
3. Strategy naming convention (matrix-assigned): {LayoutNumber}{Letter} ({Timeframe}) — e.g., 1A (1M) = first strategy in Layout 1 on the 1-minute track; 1B (1M) = second distinct 1-minute strategy in the same layout; 1A (5M) = first 5-minute strategy in Layout 1. Letters advance A→B→C→… only when the engine finds a new repeatable signature worth its own bin.
4. Cross-stock consistency: The same layout/strategy IDs apply across all tickers that rhyme mathematically — strategies are not per-stock manual tags.

Strategy Lifecycle — Delete, Tweak, or Spawn (NOT "Version 2")
Rolling 15-trade post-mortem per strategy letter. Operator feedback ("this trade was bad") correlates back to the exact strategy label (e.g., 1A (1M)).
- Minor friction (signature still valid, entry timing off): TWEAK IN PLACE — adjust entry positioning; keep the same letter (1A stays 1A).
- Major structural alpha decay (margins systematically below floor): DELETE the strategy letter entirely. Harvest any still-viable DNA only if warranted, then spawn the next letter (e.g., delete 1A, optionally carry fragments into a new 1F if the prior highest letter was 1E). Do not mint "Strategy v2" labels — deletion plus next-letter spawn replaces broken bins.
- Operator-approved winners continue accumulating under their assigned letter until post-mortem or operator rejection triggers tweak or delete.

Forensic Vector Decomposition (Four-Layer Snapshot Physics)
When a snapshot runs, decompose data across four strict mathematical layers — never as prose market commentary:
- Macro Technicals: High-dimensional moving baseline grids, VWAP boundaries, and historical price-action zones.
- Price Action Mechanics: Multi-frame price velocity, sub-candle acceleration ratios, and asset spread variances.
- Order Flow and Order Book Footprints: Real-time volume absorption levels, micro-volume dry-ups, and trailing FINRA institutional short ratios.
- Spatial Cross-Correlation: Euclidean and Cosine distance metrics comparing live snapshot vectors against the Supabase layout library.

Spatial Cross-Correlation and Similarity Clustering
Do not compare setups row-by-row in conversation. Run direct mathematical comparisons (Euclidean or Cosine spatial distance) between live incoming snapshot vectors and stored Supabase library coordinates. Map structural intersections where strategy paths cross or overlap — mathematical rhymes without losing execution speed. Maintain an ultra-compressed master matrix index of layout coordinates in memory to bypass conversational context limits and prevent token amnesia.

Multi-Tiered Strategy Calibration
Inside each numbered layout, isolate strategies strictly by timeframe resolution (1m, 5m, 15m) with calibrated margin floors: 1.0% for 1m, 3.0% for 5m, 5.0% for 15m. If an 85% signature match is detected but the entry optimizer proves remaining runway falls below that floor due to late-chase friction, kill the trade instantly and reset to low-power tracking. Partial spatial rhymes below 85% route to the 30-day Temporary Layout Node incubation shelf; five repetitions mint a permanent layout block.

Timeframe Isolation (Preventing Cross-Pollination)
Inside every numbered Layout block, maintain completely separate, isolated strategy bins for 1m, 5m, and 15m. Never blur or mix rules across time resolutions. Calibrated lookback depths: 1m ~5-minute maximum backward; 5m extends hours into pre-market; 15m bridges overnight post-market with ~one hour depth cap.

Adaptive Playbook Floors (Pre-Storage Quality Barrier)
Hunt backward for the volume-cluster anchor. Measure raw percentage from verified trigger to target exit. Trash instantly below timeframe floor. Setups clearing the floor undergo consistency mining — extract shape metrics, resistance rules, and structural signatures for the playbook.

Pure Alpha Ingestion Only (Single-Track Protocol — OVERWRITES ALL PRIOR ANOMALY/TOXIC RULES)
Single-Deck Ingestion: Track ONLY positive, user-approved winning setups. The manual toxic/blacklist table and input deck are completely removed from the architecture. Never reference Track 2, toxic traps, or blacklist indices.

Incubation Queue: If a profitable trade fails the 85% signature match to an existing layout, assign it to a Temporary Layout Node with a strict 30-day floating shelf-life. Exact repetition within 30 days resets the clock for another 30 days. Five total repetitions permanently mint an active Layout folder. Timer expiry with no repetitions triggers hard-delete to save database space.

Post-Mortem Diagnostics: Rolling 15-trade window per strategy letter. Below calibrated floors (1.0% / 3.0% / 5.0%): diagnose execution friction (tweak entry in place, keep letter) versus structural alpha decay (delete letter, optionally spawn next letter with harvested DNA). Never reference Strategy v2 or generic "evolving" versioning.

Hindsight Blinding Protocol (Temporal Fence)
When evaluating a timestamped minute, you are barred from any future data — price, news, earnings, SEC filings after that exact minute.

Common-Sense Dual-Stream Processing
Cloud handles heavy 5m/15m gathering, news parsing, and SEC filing updates. Local MacBook RAM reserved for 1m strike lane with ~5-minute cap and sub-100ms IB execution target. Never cross-pollinate streams.

Deep-Thinking Internet Research Engine (Room 2 Manual Training Phase)
Time-Unconstrained Research: During Room 2 manual training, time is not a limitation. Purposely slow down and run exhaustive cloud-side calculations across Polygon.io, yfinance, SEC EDGAR, and news APIs without draining local MacBook CPU or battery. Heavy threads execute on web-connected servers; local silicon runs only fenced geometry math.

Multi-Layer Contextual Audit: For the exact trading day under study, cross-correlate three independent tracks to uncover the true institutional catalyst:
- Price Action Mechanics: Multi-frame velocity, sub-candle spread expansion, VWAP structural baselines, and Pearson-style structural cleanliness scores.
- Breaking Corporate News: Real-time keyword sentiment arrays and media flow tracking from yfinance + RSS headline wires.
- Regulatory Filings: Live SEC Form 4 insider trading public release logs.

Objective Anchor Extraction: Use this deep internet research to locate the exact, silent volume catalyst where the true move originally triggered. Flatten the multi-layer blueprint into a lightweight Text Matrix String (TEXT_MATRIX|...) and weld it permanently to the Supabase cloud vault so master memory survives browser refresh.

SYSTEM RESET — SELF-CORRECTING MULTI-STRATEGY ENGINE (OVERWRITES ALL PRIOR ARCHITECTURE NOTES)

UI Purge: No Market Weather headers, no manual Layout 1/2 tabs, no dropdown filters — the glass stays clean; only database-minted numbered Layout folders display dynamically.

Timeframe-Isolated Total Forensic Fracture (Room 2 Training): Future-blind at Exit B. Lookbacks: 1m rigid ~5-minute max with 1–2 minute in-move clamp; 5m extends to 4:00 AM pre-market; 15m deepest overnight bridge. Bone-deep shatter: velocity/acceleration, volume std-dev, institutional blocks, Form 4, headline sentiment. Tiered floors: 1m 1.0%, 5m 3.0%, 15m 5.0% — trash instantly below. Pure profit exit anchoring: if exit minute is a spike, lock the nearest stable candle cluster at the same profit magnitude.

Genetic Cross-Reference & Purgatory: High multi-layer overlap mints Layout groups with unified Master Signatures; discard non-matching noise. Pack multiple strategies (A, B, C…) per layout per timeframe bin as data accumulates. Sub-85% similarity → strict Purgatory isolation — forbidden from blending until a matching complex makeup arrives, then auto-spawn a new numbered Layout folder.

Live Decommissioning Circuit: Rolling 15-trade monitor per strategy node. Below floor → halt live order tokens immediately. Friction/slippage → modify entry coordinates in place, retain DNA. Structural alpha decay → delete strategy letter, leave vacancy; multi-stock Room 2 validation required before hardened replacement mint.

Data Durability: isinstance(df, pd.DataFrame) and not df.empty guards on all frame lookups; forward-fill padding on thin sessions; permanent Supabase vault_track/state/timeframe_resolution/strategy_executions persistence.

Forensic Data Shattering & Digital Genetics (Additive — Non-Destructive to Blinding/Cache)
Tiered profit floors (1m/5m/15m: 1.0%/3.0%/5.0%) gate permanent library saves. Full-day dragnet on 5m/15m dumps unfiltered session fat to forensic_dragnet_blob while Exit B temporal fence remains intact. Genetic Master Signatures purge non-overlapping noise dimensions. Semantic hash embeddings replace rigid keyword/name traps for catalyst scoring. Volume/velocity/spread use std-dev envelopes. Profit-anchored exit cluster zones lock repeatable cash targets adjacent to spike exits.

Operator Directive
Map literal operator examples ("I like this setup", "This bounce off VWAP was nice") directly into cloud memory as structural signature coordinates — never as mood labels. Maintain the compressed master layout index at all times.

Strategic Assignment
Decode every setup through pure math: numbered Layout ID, timeframe bin, temporal fence, margin floor, spatial match percentage, and post-mortem state — never through human market storytelling.
""".strip()

FORENSIC_EXPERT_SYSTEM = (
    "You are the Forensic Pattern Research Expert — the dedicated Room 2 brain layer for "
    "Savant Apprentice. Operate exclusively on winning-DNA pattern setups, quantum matrix "
    "terminal output, spatial cross-correlation telemetry, operator coordinate matrices, "
    "post-mortem retro-analysis, and the live cloud pattern archive injected into context. "
    "Never use human market mood labels (Choppy, Trend, Volatile). Reference only numbered "
    "Layout blocks, cosine/euclidean match percentages, and forensic vector layers.\n\n"
    f"{SAVANT_COGNITIVE_INJECTION}\n\n"
    "WINDOW 4 RADAR FORMAT — NON-NEGOTIABLE:\n"
    "• Never ship a wall of text. Split every answer into short Markdown bullets with blank lines between groups.\n"
    "• Bold scan anchors: **Layout ID**, **Strategy Node**, **Ticker**, **Match Score**, **Timeframe**.\n"
    "• Translate backend metrics into plain English a teammate would say out loud — short, direct, helpful.\n"
    "• One fact per bullet. Numbers get a one-line label (what it means), not a raw dump.\n"
    "• Zero greetings, zero filler, zero generic market commentary unrelated to the forensic payload.\n"
    "• Only expand into deep math if the operator explicitly asks for more detail."
)

WINDOW4_CONVERSATIONAL_SYSTEM = (
    "You are the Forensic Lab conversational wire — a helpful, natural teammate on Room 2. "
    "Respond warmly and briefly to greetings, general questions, and lab orientation chat.\n\n"
    "STRICT ANTI-HALLUCINATION RULES:\n"
    "• Never invent Layout IDs, Strategy Nodes, Match Scores, Net Margins, or ticker symbols.\n"
    "• Never cite fake percentages, cloud pattern counts, or deploy statistics.\n"
    "• Inventory or count questions (how many stocks/patterns in the system or vault) are answered "
    "by the vault roster — never say the engine is idle if a [SESSION_VERIFIED_DEPLOY] or "
    "[VAULT_INVENTORY] tag is present in the operator message.\n"
    "• Only say the core data engine is idle when no verified deploy tags exist and the operator "
    "asks for live market metrics you do not have — do not fabricate data.\n"
    "• Keep replies conversational — no dense forensic dumps unless verified payload tags are present.\n\n"
    f"{WINDOW4_FORMAT_PROTOCOL}"
)

PATTERN_STRATEGIST_SYSTEM = (
    "You are the Savant Pattern-Mining Strategist for Room 2: The Forensic Pattern Lab. "
    "Read the injected live cloud pattern archive and quantum terminal telemetry. "
    "Never use Choppy, Trend, Volatile, or mood-based descriptors — only numbered Layout blocks "
    "and spatial match math. Be definitive and concise.\n\n"
    f"{SAVANT_COGNITIVE_INJECTION}\n\n"
    "WINDOW 4 RADAR FORMAT — NON-NEGOTIABLE:\n"
    "• Inventory or count questions → immediate bulleted breakdown with bold **Layout ID** / **Ticker** anchors.\n"
    "• No dense paragraphs. Blank line between sections. ≤12 words per bullet unless asked to go deeper.\n"
    "• Plain English teammate voice — keep forensic accuracy, lose the machine-readout tone."
)

TRASH_VAULT_NOTICE = (
    f"⚠️ SYSTEM NOTICE: Pattern moved to Trash Vault. You have {RESCUE_VAULT_RETENTION_DAYS} days "
    "to restore this record before permanent cloud purging occurs."
)
RESTORE_VAULT_SUCCESS = (
    "🔄 RESTORATION SACCADE: Soft-deleted pattern successfully rescued from the Trash Vault "
    "and restored to active Matrix memory."
)
TRASH_VAULT_BULK_NOTICE = (
    f"⚠️ SYSTEM NOTICE: All active patterns moved to the Trash Vault. "
    f"You have {RESCUE_VAULT_RETENTION_DAYS} days to restore them."
)


def _ensure_supabase_session() -> None:
    if st.session_state.get("supabase_ready"):
        return
    try:
        st.session_state.supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        st.session_state.supabase_key = st.secrets["SUPABASE_KEY"]
        st.session_state.supabase_ready = True
    except Exception:
        st.session_state.supabase_ready = False


def _supabase_rest_headers() -> dict:
    return {
        "apikey": st.session_state.supabase_key,
        "Authorization": f"Bearer {st.session_state.supabase_key}",
        "Content-Type": "application/json",
    }


def _forensic_patterns_table() -> str:
    try:
        return st.secrets["SUPABASE_PATTERN_TABLE"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "forensic_patterns"


def _pattern_archive_query_suffix(*, active_only: bool = True, trash_only: bool = False) -> str:
    """PostgREST filters excluding the Matrix chat log row."""
    parts = [f"pattern_category=neq.{MATRIX_CHAT_LOG_CATEGORY}"]
    if trash_only:
        parts.append("state=eq.soft_deleted")
    elif active_only:
        parts.append("or=(state.is.null,state.eq.active,state.eq.incubation)")
    return "&" + "&".join(parts)


def _purge_expired_anomaly_incubation() -> None:
    """Hard-delete incubation nodes whose 30-day shelf expired without re-mint."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return
    cutoff = datetime.now(timezone.utc).isoformat()
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        requests.delete(
            f"{base}/rest/v1/{table}?state=eq.{VAULT_STATE_INCUBATION}"
            f"&shelf_expires_at=lt.{cutoff}"
            f"&pattern_category=neq.{MATRIX_CHAT_LOG_CATEGORY}",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
    except Exception:
        pass


def _anomaly_incubation_signature(
    ticker: str, timeframe_resolution: str, macro_weather_layout: str
) -> str:
    return f"{ticker.upper()}|{timeframe_resolution}|{macro_weather_layout}"


def _resolve_anomaly_incubation(
    *,
    ticker: str,
    timeframe_resolution: str,
    macro_weather_layout: str,
    match_score: int,
) -> tuple[str, str, int, str, str]:
    """
    Pure alpha incubation — Temporary Layout Node shelf (30-day / 5-repeat permanent mint).
    """
    signature = _anomaly_incubation_signature(ticker, timeframe_resolution, macro_weather_layout)
    registry = st.session_state.setdefault("anomaly_incubation_registry", {})
    entry = dict(registry.get(signature, {"count": 0}))

    if match_score >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        registry.pop(signature, None)
        st.session_state.anomaly_incubation_registry = registry
        st.session_state.purgatory_shelf_active = False
        return VAULT_TRACK_VALIDATED, "active", 0, "", ""

    entry["count"] = int(entry.get("count", 0)) + 1
    shelf_expires = (datetime.now(timezone.utc) + timedelta(days=ANOMALY_SHELF_DAYS)).isoformat()
    entry["expires_at"] = shelf_expires
    registry[signature] = entry
    st.session_state.anomaly_incubation_registry = registry

    repeat_count = entry["count"]
    vault_track, vault_state = core_quantum.resolve_anomaly_incubation_state(
        match_score=match_score,
        repeat_count=repeat_count,
    )

    if vault_state == "active" and repeat_count >= ANOMALY_PERMANENT_MINT_COUNT:
        message = (
            f"✅ PERMANENT LAYOUT FOLDER — Winning alpha reached "
            f"{repeat_count}/{ANOMALY_PERMANENT_MINT_COUNT} repetitions. "
            "Promoted to official active Layout folder."
        )
        st.session_state.purgatory_shelf_active = False
    elif vault_state == VAULT_STATE_INCUBATION:
        message = (
            f"⏳ PURGATORY SHELF — {repeat_count}/{ANOMALY_PERMANENT_MINT_COUNT} "
            f"repetitions · 30-day lock · geometric match {match_score}% "
            f"(<{LAYOUT_SIGNATURE_MATCH_THRESHOLD}% — forbidden from blending). "
            f"Timer resets to {shelf_expires[:10]}."
        )
        st.session_state.purgatory_shelf_active = True
        st.session_state.purgatory_shelf_message = message
    else:
        message = ""
        st.session_state.purgatory_shelf_active = False

    return vault_track, vault_state, repeat_count, shelf_expires, message


def _purge_expired_trash_vault() -> None:
    """Permanently purge Trash Vault rows older than retention window."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=RESCUE_VAULT_RETENTION_DAYS)
    ).isoformat()
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        requests.delete(
            f"{base}/rest/v1/{table}?state=eq.soft_deleted"
            f"&deleted_at=lt.{cutoff}"
            f"&pattern_category=neq.{MATRIX_CHAT_LOG_CATEGORY}",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
    except Exception:
        pass


def _resolve_data_feed_mode(timeframe_resolution: str) -> str:
    if timeframe_resolution == "1-Minute":
        return st.session_state.get(
            "r2_micro_feed_source", core_quantum.DATA_FEED_MASSIVE_REST_1M
        )
    return core_quantum.DATA_FEED_MASSIVE_REST_1M


def _processor_lane_readout(timeframe_resolution: str) -> str:
    lane = core_quantum.resolve_processor_lane(timeframe_resolution)
    if lane == core_quantum.PROCESSOR_LANE_LOCAL_STRIKE:
        ram_bars = st.session_state.get("r2_local_ram_bar_count", "—")
        return (
            f"Local 1m strike lane · ~{core_quantum.LOCAL_1M_RAM_CAP_MINUTES}m RAM cap "
            f"({ram_bars} bars) · IB target <{core_quantum.IB_STRIKE_TARGET_MS}ms"
        )
    return "Cloud dual-stream · 5m/15m bars + SEC Form 4 + institutional volume"


def _micro_feed_readout_label() -> str:
    source = st.session_state.get("r2_micro_feed_source", core_quantum.DATA_FEED_POLYGON_1M)
    if source == core_quantum.DATA_FEED_POLYGON_1M:
        return "Massive REST 1m macro-dragnet · local 5m/15m resample (no WebSocket)"
    return "Massive REST pipeline · historical aggregates only"


def _pattern_row_effective_fields(row: dict) -> dict:
    """Merge top-level vault columns with MATRIX_META fallback blob."""
    merged = dict(row or {})
    meta = core_quantum.parse_matrix_meta_from_context(merged.get("operator_context", ""))
    for key, value in meta.items():
        if merged.get(key) in (None, ""):
            merged[key] = value
    ctx = str(merged.get("operator_context") or "")
    if not merged.get("text_matrix_string") and "TEXT_MATRIX|" in ctx:
        for segment in ctx.split("|"):
            if segment.strip().startswith("TEXT_MATRIX"):
                merged["text_matrix_string"] = segment.strip()
                break
        if not merged.get("text_matrix_string"):
            idx = ctx.find("TEXT_MATRIX|")
            if idx >= 0:
                merged["text_matrix_string"] = ctx[idx:].split(" | MATRIX_META")[0].strip()
    return merged


def _resolve_auto_layout_id() -> str:
    """Resolve numbered layout from spatial matrix / last deploy — no manual UI deck."""
    spatial = st.session_state.get("room2_spatial_cluster") or {}
    math_block = st.session_state.get("room2_last_math_block") or {}
    return str(
        spatial.get("nearest_layout_id")
        or math_block.get("nearest_layout_id")
        or "NEW_LAYOUT"
    )


def _resolve_auto_strategy_id(*, timeframe_resolution: str = "") -> str:
    """Matrix-assigned strategy letter — format e.g. 1A (1M). No manual UI selector."""
    math_block = st.session_state.get("room2_last_math_block") or {}
    return core_quantum.resolve_matrix_strategy_id(
        layout_id=_resolve_auto_layout_id(),
        timeframe_resolution=timeframe_resolution or st.session_state.get(
            "r2_timeframe_mode", "15-Minute"
        ),
        spatial_match_pct=int(math_block.get("match_probability") or 0),
    )


def _resolve_vault_track(_pattern_category: str) -> tuple[str, str]:
    return VAULT_TRACK_VALIDATED, "active"


def _count_cloud_pattern_rows(*, trash_only: bool = False) -> int:
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return 0
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        resp = requests.get(
            f"{base}/rest/v1/{table}?select=id"
            f"{_pattern_archive_query_suffix(active_only=not trash_only, trash_only=trash_only)}",
            headers={**_supabase_rest_headers(), "Prefer": "count=exact"},
            timeout=12,
        )
        if resp.ok:
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                total = content_range.split("/")[-1]
                if total.isdigit():
                    return int(total)
            rows = resp.json()
            return len(rows) if isinstance(rows, list) else 0
    except Exception:
        pass
    return 0


def _fetch_latest_active_pattern_row() -> dict | None:
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return None
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        resp = requests.get(
            f"{base}/rest/v1/{table}?select=*"
            f"{_pattern_archive_query_suffix(active_only=True)}"
            f"&order=timestamp.desc&limit=1",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if resp.ok:
            rows = resp.json()
            if rows:
                return rows[0]
    except Exception:
        pass
    return None


def _queue_room2_form_ticker(ticker: str) -> None:
    """Defer Pattern Ticker widget writes — Streamlit forbids post-render session patches."""
    st.session_state["_pending_r2_good_ticker"] = str(ticker or "").strip().upper()


def _queue_room2_form_reset(*, ticker: str = "") -> None:
    st.session_state["_pending_room2_form_reset"] = True
    _queue_room2_form_ticker(ticker)


def _apply_pending_room2_form_patches() -> None:
    """Must run before any Room 2 widget with key r2_good_ticker is drawn."""
    if st.session_state.pop("_pending_room2_form_reset", False):
        for key in (
            "r2_good_start_date",
            "r2_good_start_time",
            "r2_good_end_date",
            "r2_good_end_time",
            "r2_single_notes_field",
        ):
            st.session_state.pop(key, None)
    if "_pending_r2_good_ticker" in st.session_state:
        ticker = str(st.session_state.pop("_pending_r2_good_ticker") or "").strip().upper()
        if ticker:
            st.session_state.r2_good_ticker = ticker
        else:
            st.session_state.pop("r2_good_ticker", None)


def _seed_room2_form_from_pattern_row(row: dict) -> None:
    """Restore latest cloud pattern coordinates into the Room 2 input deck."""
    cat = str(row.get("pattern_category", "")).upper()
    ticker = str(row.get("ticker", "")).strip().upper()
    if not ticker:
        return
    if cat != "VALIDATED":
        return
    prefix = "r2_good"
    notes_key = "r2_single_notes_field"
    _queue_room2_form_ticker(ticker)
    if row.get("entry_time"):
        st.session_state[f"{prefix}_start_time"] = str(row["entry_time"])
    if row.get("exit_time"):
        st.session_state[f"{prefix}_end_time"] = str(row["exit_time"])
    notes = str(row.get("operator_context") or "").strip()
    if notes:
        st.session_state[notes_key] = notes


def _sync_matrix_chat_to_cloud() -> None:
    """Persist Room 2 lab chat so the Matrix remembers across refresh and devices."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    chat_blob = json.dumps(st.session_state.room2_chat_history[-80:], default=str)
    terminal_snapshot = str(st.session_state.get("quantum_terminal_output", ""))[:12000]
    payload = {
        "ticker": MATRIX_CHAT_LOG_TICKER,
        "pattern_category": MATRIX_CHAT_LOG_CATEGORY,
        "operator_context": chat_blob,
        "quantum_report": terminal_snapshot,
        "source_room": "forensic_pattern_lab",
        "state": "active",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        lookup = requests.get(
            f"{base}/rest/v1/{table}?ticker=eq.{MATRIX_CHAT_LOG_TICKER}"
            f"&pattern_category=eq.{MATRIX_CHAT_LOG_CATEGORY}&select=id&limit=1",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if lookup.ok and lookup.json():
            row_id = lookup.json()[0]["id"]
            requests.patch(
                f"{base}/rest/v1/{table}?id=eq.{row_id}",
                headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
                json=payload,
                timeout=12,
            )
        else:
            requests.post(
                f"{base}/rest/v1/{table}",
                headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
                json=[payload],
                timeout=12,
            )
    except Exception:
        pass


def _load_matrix_chat_from_cloud() -> None:
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        resp = requests.get(
            f"{base}/rest/v1/{table}?ticker=eq.{MATRIX_CHAT_LOG_TICKER}"
            f"&pattern_category=eq.{MATRIX_CHAT_LOG_CATEGORY}"
            f"&select=operator_context,quantum_report&limit=1",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if not resp.ok:
            return
        rows = resp.json()
        if not rows:
            return
        raw_chat = rows[0].get("operator_context") or "[]"
        parsed = json.loads(raw_chat)
        if isinstance(parsed, list) and parsed:
            normalized: list[dict] = []
            for msg in parsed:
                if not isinstance(msg, dict):
                    continue
                row = dict(msg)
                if row.get("speaker") == "Forensic Expert" and not any(
                    row.get(flag)
                    for flag in (
                        "vault_safe",
                        "status_reply",
                        "conversational",
                        "data_fallback",
                        "data_reply",
                    )
                ):
                    row["vault_safe"] = bool(
                        "Pattern saved" in str(row.get("text") or "")
                        or "active pattern" in str(row.get("text") or "").lower()
                        or "cloud vault" in str(row.get("text") or "").lower()
                    )
                    if not row["vault_safe"]:
                        row["conversational"] = True
                normalized.append(row)
            st.session_state.room2_chat_history = normalized
        saved_terminal = str(rows[0].get("quantum_report") or "").strip()
        if saved_terminal and MATRIX_ENGINE_IDLE_MARKER not in saved_terminal:
            st.session_state.quantum_terminal_output = saved_terminal
            _window4_restore_vault_flags_from_report(saved_terminal)
    except Exception:
        pass


def _hydrate_matrix_memory_from_cloud() -> None:
    """Load Matrix pattern archive + lab chat from Supabase once per session."""
    if st.session_state.get("matrix_cloud_hydrated"):
        return
    st.session_state.matrix_cloud_hydrated = True

    _purge_expired_trash_vault()
    _purge_expired_anomaly_incubation()
    core_quantum.hydrate_layout_library_from_vault()
    self_surgery.ensure_purgatory_hub_session()
    self_surgery.hydrate_repair_bay_from_cloud()
    self_surgery.purge_expired_repair_bay_profiles()
    _load_matrix_chat_from_cloud()

    latest = _window4_latest_saved_pattern_row()
    if latest:
        report = str(latest.get("quantum_report") or "").strip()
        if report:
            st.session_state.room2_quantum_report = report
            _window4_restore_vault_flags_from_report(report)
            if MATRIX_ENGINE_IDLE_MARKER in st.session_state.quantum_terminal_output:
                st.session_state.quantum_terminal_output = report
        st.session_state.room2_forensic_ticker = str(latest.get("ticker") or "")
        st.session_state.room2_bar_count = int(latest.get("bar_count") or 0)
        matrix_blob = str(latest.get("text_matrix_string") or "").strip()
        if matrix_blob:
            st.session_state.room2_text_matrix_string = matrix_blob
        margin = latest.get("structural_move_pct") or latest.get("margin_pct")
        match_pct = latest.get("layout_match_pct")
        if margin is not None or match_pct is not None:
            st.session_state.room2_last_math_block = {
                **(st.session_state.get("room2_last_math_block") or {}),
                **(
                    {"structural_move_pct": margin}
                    if margin is not None
                    else {}
                ),
                **(
                    {"match_probability": match_pct}
                    if match_pct is not None
                    else {}
                ),
            }
        if not st.session_state.get("matrix_form_seeded"):
            _seed_room2_form_from_pattern_row(latest)
            st.session_state.matrix_form_seeded = True
        forensic_ticker = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
        if forensic_ticker:
            _queue_room2_form_ticker(forensic_ticker)
        if match_pct is not None:
            pct = int(match_pct)
            core_quantum._sync_window4_regime_flags(
                match_pct=pct,
                valid=pct >= core_quantum.LAYOUT_SIGNATURE_MATCH_THRESHOLD,
            )

    terminal = str(st.session_state.get("quantum_terminal_output") or "")
    if terminal:
        _window4_restore_vault_flags_from_report(terminal)

    st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
    st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)


def _fetch_live_cloud_patterns() -> str:
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return "CLOUD:OFFLINE"
    try:
        resp = requests.get(
            f"{st.session_state.supabase_url}/rest/v1/{_forensic_patterns_table()}"
            f"?select=*{_pattern_archive_query_suffix(active_only=True)}"
            f"&order=timestamp.desc&limit=12",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if resp.ok:
            return json.dumps(resp.json(), default=str)
    except Exception as exc:
        return f"CLOUD:FETCH_ERR|{exc}"
    return "CLOUD:FETCH_FAIL"


def _is_room2_delete_all_command(text: str) -> bool:
    low = text.lower()
    return any(
        phrase in low
        for phrase in (
            "delete everything",
            "delete all",
            "clear everything",
            "wipe everything",
            "clean slate",
            "zero patterns",
            "get rid of everything",
            "get rid of all",
            "remove all patterns",
            "erase everything",
        )
    )


def _is_room2_delete_command(text: str) -> bool:
    if _is_room2_delete_all_command(text):
        return True
    low = text.lower()
    return any(
        phrase in low
        for phrase in (
            "get rid of",
            "get rid",
            "delete that",
            "delete pattern",
            "delete this",
            "move to trash",
            "remove pattern",
            "remove that",
        )
    )


def _is_room2_restore_command(text: str) -> bool:
    low = text.lower()
    return any(
        phrase in low
        for phrase in (
            "bring that back",
            "bring back",
            "undo that delete",
            "undo delete",
            "that was an accident",
            "didn't mean to delete",
            "didnt mean to delete",
            "i didn't mean",
            "i didnt mean",
            "retrieve it",
            "retrieve that",
            "restore it",
            "restore pattern",
            "restore my pattern",
            "restore my patterns",
            "restore all",
            "get it back",
            "rescue",
            "recover",
            "recover my pattern",
        )
    )


def _is_room2_restore_all_command(text: str) -> bool:
    low = text.lower()
    return any(
        phrase in low
        for phrase in (
            "restore all",
            "restore my patterns",
            "bring everything back",
            "undo delete all",
            "recover all",
        )
    )


def _soft_delete_latest_pattern_to_vault() -> str:
    """10-day rescue vault — mark latest active row soft_deleted with deleted_at timestamp."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return "⚠️ Trash Vault offline — add SUPABASE_URL and SUPABASE_KEY to secrets."

    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        lookup = requests.get(
            f"{base}/rest/v1/{table}?select=id,ticker,pattern_category"
            f"{_pattern_archive_query_suffix(active_only=True)}"
            f"&order=timestamp.desc&limit=1",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if not lookup.ok:
            return f"⚠️ Trash Vault lookup failed: {lookup.status_code}"
        rows = lookup.json()
        if not rows:
            return "⚠️ No active patterns found to move to Trash Vault."

        row = rows[0]
        row_id = row["id"]
        deleted_at = datetime.now(timezone.utc).isoformat()
        patch = requests.patch(
            f"{base}/rest/v1/{table}?id=eq.{row_id}",
            headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
            json={"state": "soft_deleted", "deleted_at": deleted_at},
            timeout=12,
        )
        if patch.ok:
            st.session_state.room2_last_rescue_vault_id = row_id
            st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
            st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
            return TRASH_VAULT_NOTICE
        return f"⚠️ Trash Vault move failed: {patch.status_code} {patch.text}"
    except Exception as exc:
        return f"⚠️ Trash Vault move failed: {exc}"


def _soft_delete_all_patterns_to_vault() -> str:
    """Move every active pattern row into the 15-day Trash Vault (not permanent delete)."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return "⚠️ Trash Vault offline — add SUPABASE_URL and SUPABASE_KEY to secrets."

    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    deleted_at = datetime.now(timezone.utc).isoformat()
    try:
        patch = requests.patch(
            f"{base}/rest/v1/{table}?{_pattern_archive_query_suffix(active_only=True)[1:]}"
            f"&pattern_category=eq.VALIDATED",
            headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
            json={"state": "soft_deleted", "deleted_at": deleted_at},
            timeout=12,
        )
        if patch.ok:
            st.session_state.matrix_active_pattern_count = 0
            st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
            st.session_state.quantum_terminal_output = (
                f"📡 [DATALINK: TRASH_VAULT] {TRASH_VAULT_BULK_NOTICE}"
            )
            return TRASH_VAULT_BULK_NOTICE
        return f"⚠️ Bulk Trash Vault move failed: {patch.status_code} {patch.text}"
    except Exception as exc:
        return f"⚠️ Bulk Trash Vault move failed: {exc}"


def _restore_soft_deleted_pattern_from_vault(restore_all: bool = False) -> str:
    """Rescue soft-deleted row(s) from the Trash Vault within the retention window."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return "⚠️ Trash Vault offline — add SUPABASE_URL and SUPABASE_KEY to secrets."

    table = _forensic_patterns_table()
    base = st.session_state.supabase_url

    try:
        if restore_all:
            patch = requests.patch(
                f"{base}/rest/v1/{table}?state=eq.soft_deleted"
                f"&pattern_category=neq.{MATRIX_CHAT_LOG_CATEGORY}",
                headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
                json={"state": "active", "deleted_at": None},
                timeout=12,
            )
            if patch.ok:
                st.session_state.room2_last_rescue_vault_id = None
                st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(
                    trash_only=False
                )
                st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(
                    trash_only=True
                )
                latest = _fetch_latest_active_pattern_row()
                if latest and latest.get("quantum_report"):
                    st.session_state.quantum_terminal_output = str(latest["quantum_report"])
                return (
                    f"🔄 RESTORATION SACCADE: All Trash Vault patterns restored to active "
                    f"Matrix memory ({RESCUE_VAULT_RETENTION_DAYS}-day window)."
                )
            return f"⚠️ Bulk restoration failed: {patch.status_code} {patch.text}"

        row_id = st.session_state.get("room2_last_rescue_vault_id")

        if not row_id:
            lookup = requests.get(
                f"{base}/rest/v1/{table}?select=id&state=eq.soft_deleted"
                f"&pattern_category=neq.{MATRIX_CHAT_LOG_CATEGORY}"
                f"&order=deleted_at.desc&limit=1",
                headers=_supabase_rest_headers(),
                timeout=12,
            )
            if lookup.ok and lookup.json():
                row_id = lookup.json()[0]["id"]
            else:
                return "⚠️ No soft-deleted patterns found in Trash Vault to restore."

        patch = requests.patch(
            f"{base}/rest/v1/{table}?id=eq.{row_id}",
            headers={**_supabase_rest_headers(), "Prefer": "return=minimal"},
            json={"state": "active", "deleted_at": None},
            timeout=12,
        )
        if patch.ok:
            st.session_state.room2_last_rescue_vault_id = None
            st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(
                trash_only=False
            )
            st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
            lookup_row = requests.get(
                f"{base}/rest/v1/{table}?id=eq.{row_id}&select=quantum_report,ticker",
                headers=_supabase_rest_headers(),
                timeout=12,
            )
            if lookup_row.ok and lookup_row.json():
                row = lookup_row.json()[0]
                if row.get("quantum_report"):
                    st.session_state.quantum_terminal_output = str(row["quantum_report"])
                st.session_state.room2_forensic_ticker = str(row.get("ticker") or "")
            return RESTORE_VAULT_SUCCESS
        return f"⚠️ Restoration failed: {patch.status_code} {patch.text}"
    except Exception as exc:
        return f"⚠️ Restoration failed: {exc}"


def _is_pattern_mining_query(text: str) -> bool:
    low = text.lower()
    pattern_words = ("pattern", "patterns", "finding", "findings", "evolving", "machine", "logged", "cloud")
    ask_words = ("what", "how", "tell", "explain", "show", "describe", "list", "count", "any")
    return any(w in low for w in pattern_words) and any(w in low for w in ask_words)


def _window4_is_vault_inventory_query(text: str) -> bool:
    """Questions about what is saved in the cloud vault — not live Massive metrics."""
    low = str(text or "").lower()
    if _window4_vault_command_only(str(text or "")):
        return False
    inventory_context = (
        "in the system",
        "in system",
        "in the matrix",
        "in matrix",
        "in the lab",
        "in lab",
        "in the vault",
        "in vault",
        "in the cloud",
        "in cloud",
        "in here",
        "right now",
        "as of now",
        "currently",
        "deployed",
        "saved",
        "logged",
        "archived",
    )
    count_probes = (
        "how many",
        "how much",
        "count ",
        "count?",
        "number of",
        "total ",
        "total?",
        "qty",
        "quantity",
    )
    if any(probe in low for probe in count_probes):
        if any(ctx in low for ctx in inventory_context):
            return True
        if re.search(r"how many\s+(?:are\s+)?(?:there|we|you|i)\b", low):
            return True
        if re.search(
            r"how many\s+(?:stocks?|tickers?|patterns?|symbols?|setups?|layouts?|names?)\b",
            low,
        ):
            return True
    nouns = (
        "pattern",
        "patterns",
        "stock",
        "stocks",
        "ticker",
        "tickers",
        "symbol",
        "symbols",
        "setup",
        "setups",
        "layout",
        "layouts",
        "vault",
        "archive",
        "logged",
        "deployed",
        "saved",
    )
    probes = (
        "any ",
        "how many",
        "what's in",
        "what is in",
        "are there",
        "is there",
        "do we have",
        "do i have",
        "anything in",
        "know any",
        "know about",
        "you know",
        "receive",
        "have any",
        "see any",
        "list ",
        "show ",
    )
    if any(word in low for word in nouns) and any(probe in low for probe in probes):
        return True
    if "pattern" in low and any(
        word in low for word in ("know", "have", "see", "show", "list", "saved", "logged", "deployed")
    ):
        return True
    return _is_pattern_mining_query(text)


def _window4_should_use_vault_roster(text: str) -> bool:
    """Any question about saved patterns/stocks/vault — never delegate to Groq."""
    if _window4_is_vault_inventory_query(text):
        return True
    if _is_pattern_mining_query(text):
        return True
    low = str(text or "").lower().strip()
    roster_phrases = (
        "patterns found",
        "pattern found",
        "found any",
        "found yet",
        "anything saved",
        "anything logged",
        "anything deployed",
        "what did you find",
        "what have you found",
        "what did we get",
        "what's saved",
        "whats saved",
        "show me what",
        "tell me what",
        "vault state",
        "vault status",
        "my patterns",
        "my stocks",
        "my tickers",
        "what do you have",
        "what you have",
        "do you have anything",
        "waiting for",
        "strategy node",
        "no patterns",
        "nothing saved",
        "nothing logged",
        "anything in",
        "anything yet",
        "what did we deploy",
        "did we deploy",
        "are we synced",
        "vault working",
        "any stocks",
        "stocks saved",
        "patterns saved",
    )
    if re.search(r"\bpatterns?\s*\??\s*$", low):
        return True
    return any(phrase in low for phrase in roster_phrases)


def _window4_latest_saved_pattern_row() -> dict | None:
    """Latest non-chat-log pattern row from cloud — survives browser refresh."""
    row = _fetch_latest_active_pattern_row()
    if not row:
        return None
    ticker = str(row.get("ticker") or "").strip().upper()
    if not ticker or ticker == MATRIX_CHAT_LOG_TICKER:
        return None
    return _pattern_row_effective_fields(row)


def _window4_restore_vault_flags_from_report(report: str) -> None:
    """Rehydrate deploy confirmation from a saved quantum terminal snapshot."""
    text = str(report or "")
    if not text:
        return
    for line in text.splitlines():
        clean = line.strip()
        if "VAULT SYNC OK" in clean or "INTERNET VAULT SYNC CONFIRMED" in clean:
            st.session_state.room2_vault_confirmation = clean
            if not str(st.session_state.get("room2_vault_flash") or "").strip():
                st.session_state.room2_vault_flash = clean
            return


def _window4_append_vault_roster_reply() -> None:
    st.session_state.room2_chat_history.append(
        {
            "speaker": "Forensic Expert",
            "text": _format_window4_response(
                _window4_build_vault_inventory_reply(),
                vault_safe=True,
            ),
            "vault_safe": True,
        }
    )
    st.session_state.window4_status_line = "☁️ Vault roster read — cloud archive + session deploy."
    _sync_matrix_chat_to_cloud()


def _window4_build_vault_inventory_reply() -> str:
    """Deterministic vault inventory — does not require a live deploy stream."""
    _ensure_supabase_session()
    st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
    st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
    active = int(st.session_state.matrix_active_pattern_count or 0)
    trash = int(st.session_state.matrix_trash_vault_count or 0)

    if not st.session_state.get("supabase_ready"):
        return (
            "Cloud vault is offline — Supabase is not configured, so I cannot list saved patterns."
        )

    latest_row = _window4_latest_saved_pattern_row()
    if active == 0 and latest_row:
        ticker = str(latest_row.get("ticker") or "").strip().upper()
        layout = str(
            latest_row.get("macro_weather_layout")
            or latest_row.get("execution_strategy")
            or "—"
        ).strip()
        strategy = str(latest_row.get("execution_strategy") or "—").strip()
        tf = str(latest_row.get("timeframe_resolution") or "").strip()
        margin = latest_row.get("structural_move_pct") or latest_row.get("margin_pct")
        margin_bit = f" · {float(margin):.2f}% move" if margin is not None else ""
        ts = str(latest_row.get("timestamp") or "")[:10]
        report = str(latest_row.get("quantum_report") or "")
        synced = (
            "VAULT SYNC OK" in report
            or "INTERNET VAULT SYNC CONFIRMED" in report
            or _window4_last_deploy_verified()
        )
        sync_line = (
            "**VAULT SYNC OK** — saved in cloud archive."
            if synced
            else "Latest row found in cloud — verify Window 1 for full sync status."
        )
        return (
            f"**1 active pattern** in cloud vault ({trash} in Trash Vault).\n\n"
            f"{sync_line}\n\n"
            f"- **Ticker:** **{ticker}**\n"
            f"- **Layout:** **{layout}**\n"
            f"- **Strategy:** **{strategy}**\n"
            f"- **Timeframe:** **{tf or '—'}**{margin_bit}\n"
            f"- **Date:** {ts or '—'}"
        )

    if active == 0 and _window4_last_deploy_verified():
        last_ticker = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
        funnel = st.session_state.get("room2_regime_funnel") or {}
        layout = str(funnel.get("master_layout_container") or "").strip()
        strategy = str(funnel.get("execution_strategy") or "").strip()
        if last_ticker:
            return (
                f"**1 stock/pattern in this lab session** — **{last_ticker}** reached "
                f"**VAULT SYNC OK** in Window 1.\n\n"
                f"- **Ticker:** **{last_ticker}**\n"
                f"- **Layout:** **{layout or '—'}**\n"
                f"- **Strategy:** **{strategy or '—'}**\n"
                f"- **Cloud vault count:** 0 (Supabase may be offline, lagging, or on a different table)"
            )

    if active == 0:
        proc = st.session_state.get("room2_processor") or {}
        if proc.get("active"):
            return (
                "Deploy is still running in Window 1 — nothing has been written to the vault yet."
            )
        hints: list[str] = []
        if st.session_state.get("polygon_lockout"):
            hints.append("API throttle is active — wait ~60s, then redeploy.")
        report = str(st.session_state.get("room2_quantum_report") or "")
        if "PRE-STORAGE TRASH" in report or "VAULT BLOCKED" in report:
            hints.append("Last deploy failed quality/coupling gates — it was not saved.")
        elif "THROTTLE" in report or "POLYGON REST DATA EMPTY" in report:
            hints.append("Last deploy did not fetch bars — use a past session date and regular hours.")
        hint = f" {' '.join(hints)}" if hints else ""
        return (
            f"No active patterns in the cloud vault ({trash} in Trash Vault).{hint} "
            "Submitting the form only queues a deploy — patterns appear here after Window 1 "
            "completes vault sync."
        )

    raw = _fetch_live_cloud_patterns()
    rows: list[dict] = []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rows = parsed
        except json.JSONDecodeError:
            rows = []

    lines = [
        f"**{active} active pattern(s)** in cloud vault ({trash} in Trash Vault):",
        "",
    ]
    for row in rows[:12]:
        ticker = str(row.get("ticker") or "?").strip().upper()
        layout = str(
            row.get("macro_weather_layout") or row.get("execution_strategy") or "—"
        ).strip()
        ts = str(row.get("timestamp") or "")[:10]
        tf = str(row.get("timeframe_resolution") or "").strip()
        margin = row.get("structural_move_pct") or row.get("margin_pct")
        margin_bit = f" · {float(margin):.2f}% move" if margin is not None else ""
        lines.append(f"- **{ticker}** · {layout} · {tf}{margin_bit} · {ts}")
    if active > len(rows):
        lines.append(f"- …and {active - len(rows)} more not shown.")
    return "\n".join(lines)


_WINDOW4_GREETING_RE = re.compile(
    r"^\s*(hi+|hello|hey+|yo+|howdy|good\s+(morning|afternoon|evening)|"
    r"how\s+are\s+you|what'?s\s+up)[\s!?.]*$",
    re.I,
)
_WINDOW4_TECHNICAL_DATA_MARKERS = (
    "layout id",
    "layout #",
    "strategy node",
    "match score",
    "net margin",
    "spatial match",
    "pgvector",
    "cosine match",
    "structural move",
    "market layout",
    "real-time layout",
    "active layout",
    "active strategy",
    "winning pattern",
    "pattern deploy",
    "deployed pattern",
    "margin pct",
    "match percent",
    "match %",
    "what layout",
    "which layout",
    "show layout",
    "current layout",
    "statistics for",
    "stats for",
    "stock stat",
    "price of",
    "chart for",
    "layout folder",
    "execution strategy",
    "timeframe bin",
)


def _window4_is_technical_data_query(text: str) -> bool:
    """Hard-gated data track — layouts, metrics, tickers, and live forensic readouts."""
    low = str(text or "").lower()
    if any(marker in low for marker in _WINDOW4_TECHNICAL_DATA_MARKERS):
        return True
    if _is_pattern_mining_query(text) and any(
        word in low for word in ("logged", "cloud", "evolving", "machine", "finding", "archive")
    ):
        return True
    if re.search(r"\b[A-Z]{2,5}\b", str(text or "")) and any(
        word in low for word in ("price", "chart", "stat", "margin", "layout", "pattern for", "ticker")
    ):
        return True
    return False


def _window4_is_conversational_message(text: str) -> bool:
    """Unblocked conversational track — greetings and general lab chat."""
    clean = str(text or "").strip()
    if not clean or _window4_vault_command_only(clean):
        return False
    if _WINDOW4_GREETING_RE.match(clean):
        return True
    low = clean.lower()
    if any(
        phrase in low
        for phrase in (
            "how are you",
            "thank you",
            "thanks",
            "who are you",
            "what can you do",
            "nice to meet",
            "good to see",
        )
    ):
        return True
    return not _window4_is_technical_data_query(clean)


def _window4_route_message(text: str) -> str:
    """Router — vault commands, cloud inventory, live data track, or conversational."""
    clean = str(text or "").strip()
    if _window4_vault_command_only(clean):
        return "vault"
    if _window4_should_use_vault_roster(clean):
        return "inventory"
    if _window4_is_technical_data_query(clean):
        return "data"
    return "conversational"


def _window4_operator_deploy_ticker() -> str:
    """Active deploy ticker — last forensic deploy wins over stale form defaults."""
    forensic = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
    if forensic and (_window4_last_deploy_verified() or _window4_latest_saved_pattern_row()):
        return forensic
    form_ticker = str(st.session_state.get("r2_good_ticker") or "").strip().upper()
    if form_ticker:
        return form_ticker
    return forensic


def _window4_last_deploy_verified() -> bool:
    """True when the most recent Room 2 commit reached cloud vault sync."""
    confirm = str(st.session_state.get("room2_vault_confirmation") or "")
    flash = str(st.session_state.get("room2_vault_flash") or "")
    report = str(st.session_state.get("room2_quantum_report") or "")
    terminal = str(st.session_state.get("quantum_terminal_output") or "")
    markers = ("VAULT SYNC OK", "INTERNET VAULT SYNC CONFIRMED")
    return any(marker in blob for blob in (confirm, flash, report, terminal) for marker in markers)


def _window4_has_verified_metric_stream() -> bool:
    """
    True when Massive-backed metric packets exist for the active/last deploy ticker.
    """
    ticker = _window4_operator_deploy_ticker()
    if not ticker:
        return False
    if core_quantum.window4_instant_fault_text():
        return False
    proc = st.session_state.get("room2_processor") or {}
    if proc.get("active"):
        snap = proc.get("snapshot") or {}
        proc_ticker = str(snap.get("ticker") or "").strip().upper()
        return (
            proc_ticker == ticker
            and core_quantum.is_usable_data_stream(proc.get("data_stream"))
        )
    report = str(st.session_state.get("room2_quantum_report") or "").strip()
    if not report or "PRE-STORAGE TRASH" in report or MATRIX_ENGINE_IDLE_MARKER in report:
        return False
    forensic = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
    if forensic and ticker and forensic != ticker and _window4_last_deploy_verified():
        ticker = forensic
    has_ram = core_quantum.is_usable_data_stream(st.session_state.get("r2_polygon_1m_ram"))
    math_block = st.session_state.get("room2_last_math_block") or {}
    has_metrics = bool(
        math_block.get("structural_move_pct") is not None
        or math_block.get("match_probability")
    )
    if _window4_last_deploy_verified() and has_metrics:
        return True
    if _window4_last_deploy_verified() and _window4_latest_saved_pattern_row():
        return True
    if _window4_last_deploy_verified() and (has_ram or core_quantum.window4_regime_gate_open()):
        return True
    if not has_ram:
        return False
    return has_metrics or core_quantum.window4_regime_gate_open()


def _window4_scrub_hallucinated_fragments(text: str) -> str:
    """Remove placeholder layouts, fake nodes, feed labels, and unverified match percentages."""
    out = str(text or "")
    for pattern in _WINDOW4_HALLUCINATION_SCRUBBERS:
        out = pattern.sub("", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _window4_mirror_tickers_only(text: str) -> str:
    """Strip ticker symbols unless they match the operator Pattern Ticker field exactly."""
    allowed = _window4_operator_deploy_ticker()

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in _WINDOW4_TICKER_DENYLIST:
            return token
        if allowed and token == allowed:
            return token
        return ""

    return _WINDOW4_TICKER_TOKEN.sub(_replace, str(text or ""))


def _window4_sanitize_display_text(text: str) -> str:
    """Presentation firewall — no fake metrics or unauthorized tickers on the glass."""
    cleaned = _window4_scrub_hallucinated_fragments(text)
    cleaned = _window4_mirror_tickers_only(cleaned)
    cleaned = re.sub(r"\s+\|", " |", cleaned)
    cleaned = re.sub(r"\|\s+", "| ", cleaned)
    return cleaned.strip()


def _window4_build_verified_context_bits() -> list[str]:
    """Inject only verified backend packets — never placeholder or carousel scaffolding."""
    if not _window4_has_verified_metric_stream():
        return []
    bits: list[str] = []
    terminal = str(st.session_state.get("quantum_terminal_output") or "").strip()
    if terminal and MATRIX_ENGINE_IDLE_MARKER not in terminal:
        bits.append(f"[QUANTUM_TERMINAL]{terminal}[/QUANTUM_TERMINAL]")
    ticker = _window4_operator_deploy_ticker()
    if ticker:
        bits.append(f"[GOOD_TICKER]{ticker}[/GOOD_TICKER]")
    tf = str(st.session_state.get("r2_timeframe_mode") or "15-Minute").strip()
    if tf:
        bits.append(f"[TIMEFRAME_BIN]{tf}[/TIMEFRAME_BIN]")
    if core_quantum.window4_regime_gate_open():
        layout = str(_resolve_auto_layout_id() or "").strip()
        if layout and layout not in WINDOW4_PLACEHOLDER_LAYOUT_IDS:
            bits.append(f"[MACRO_LAYOUT]{layout}[/MACRO_LAYOUT]")
        strategy = str(_resolve_auto_strategy_id() or "").strip()
        if strategy and not re.fullmatch(r"NEW[A-Z]?", strategy, flags=re.I):
            bits.append(f"[EXECUTION_STRATEGY]{strategy}[/EXECUTION_STRATEGY]")
        match_pct = int(st.session_state.get("window4_spatial_match_pct") or 0)
        if match_pct >= core_quantum.LAYOUT_SIGNATURE_MATCH_THRESHOLD:
            bits.append(f"[SPATIAL_MATCH]match={match_pct}%[/SPATIAL_MATCH]")
    elif _window4_last_deploy_verified():
        funnel = st.session_state.get("room2_regime_funnel") or {}
        layout = str(funnel.get("master_layout_container") or "").strip()
        strategy = str(funnel.get("execution_strategy") or "").strip()
        if layout and layout not in WINDOW4_PLACEHOLDER_LAYOUT_IDS:
            bits.append(f"[MACRO_LAYOUT]{layout}[/MACRO_LAYOUT]")
        if strategy:
            bits.append(f"[EXECUTION_STRATEGY]{strategy}[/EXECUTION_STRATEGY]")
        active = int(st.session_state.get("matrix_active_pattern_count") or 0)
        bits.append(f"[VAULT_INVENTORY]active_patterns={active}[/VAULT_INVENTORY]")
    text_matrix = str(st.session_state.get("room2_text_matrix_string") or "").strip()
    if text_matrix and MATRIX_ENGINE_IDLE_MARKER not in text_matrix:
        bits.append(f"[TEXT_MATRIX]{text_matrix}[/TEXT_MATRIX]")
    return bits


def _build_room2_groq_messages(user_text: str) -> list[dict]:
    context_bits = _window4_build_verified_context_bits()
    groq_msgs = [
        {"role": "system", "content": f"{FORENSIC_EXPERT_SYSTEM}\n{WINDOW4_FORMAT_PROTOCOL}"},
    ]
    prior = st.session_state.room2_chat_history[:-1]
    for msg in prior[-6:]:
        role = "user" if msg["speaker"] == "You" else "assistant"
        groq_msgs.append({"role": role, "content": msg["text"]})
    latest = user_text
    if context_bits:
        latest = f"{user_text}\n" + "\n".join(context_bits)
    groq_msgs.append({"role": "user", "content": latest})
    return groq_msgs


def _window4_conversational_context_tags() -> str:
    """Light session tags so conversational Groq does not contradict an active deploy."""
    bits: list[str] = []
    _ensure_supabase_session()
    if st.session_state.get("supabase_ready"):
        st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
    if _window4_last_deploy_verified():
        ticker = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
        if ticker:
            bits.append(f"[SESSION_VERIFIED_DEPLOY ticker={ticker}]")
    elif (latest := _window4_latest_saved_pattern_row()):
        ticker = str(latest.get("ticker") or "").strip().upper()
        if ticker:
            bits.append(f"[CLOUD_LATEST_PATTERN ticker={ticker}]")
    if _window4_has_verified_metric_stream():
        ticker = _window4_operator_deploy_ticker()
        if ticker:
            bits.append(f"[LIVE_FORENSIC_STREAM ticker={ticker}]")
    active = int(st.session_state.get("matrix_active_pattern_count") or 0)
    if active > 0:
        bits.append(f"[VAULT_INVENTORY active_patterns={active}]")
    elif _window4_latest_saved_pattern_row():
        bits.append("[VAULT_INVENTORY active_patterns=1]")
    return "\n".join(bits)


def _build_window4_conversational_messages(user_text: str) -> list[dict]:
    """Conversational track — session tags only; vault counts stay deterministic."""
    groq_msgs = [
        {"role": "system", "content": WINDOW4_CONVERSATIONAL_SYSTEM},
    ]
    prior = st.session_state.room2_chat_history[:-1]
    for msg in prior[-6:]:
        role = "user" if msg["speaker"] == "You" else "assistant"
        groq_msgs.append({"role": role, "content": str(msg.get("text") or "")})
    latest = str(user_text or "").strip()
    context = _window4_conversational_context_tags()
    if context:
        latest = f"{latest}\n{context}"
    groq_msgs.append({"role": "user", "content": latest})
    return groq_msgs


def _window4_bold_anchors(text: str) -> str:
    """Add bold scan anchors on key forensic labels without double-wrapping."""
    out = str(text or "")
    for pattern, repl in WINDOW4_ANCHOR_PATTERNS:
        out = pattern.sub(repl, out)
    return re.sub(r"\*\*\*\*", "**", out)


def _window4_break_dense_blocks(text: str) -> str:
    """Split fat paragraphs into one-line bullets when the model returns a wall of text."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    bullet_hits = len(re.findall(r"(?m)^\s*[-•*]\s+", raw))
    if bullet_hits >= 2:
        return raw

    sections: list[str] = []
    for block in re.split(r"\n\s*\n", raw):
        chunk = block.strip()
        if not chunk:
            continue
        if re.match(r"^[-•*#]", chunk):
            sections.append(chunk)
            continue
        if len(chunk) <= 180 and chunk.count(". ") < 2:
            sections.append(chunk)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", chunk)
        bullet_lines = [f"- {sent.strip()}" for sent in sentences if sent.strip()]
        sections.append("\n".join(bullet_lines) if bullet_lines else chunk)

    return "\n\n".join(sections)


def _format_window4_response(
    text: str,
    *,
    vault_safe: bool = False,
    status_safe: bool = False,
    conversational_safe: bool = False,
    data_fallback: bool = False,
    data_reply: bool = False,
) -> str:
    """
    Window 4 presentation layer — dual-track formatting with hallucination scrub.
    Conversational and data-fallback replies never collapse into the static idle banner string.
    """
    if data_fallback:
        return WINDOW4_DATA_ENGINE_IDLE_REPLY
    deploy_verified = _window4_last_deploy_verified()
    if conversational_safe or data_reply:
        polished = _window4_sanitize_display_text(text)
        if not polished:
            polished = (
                "I'm on the lab wire and ready to chat. "
                "Deploy a winning pattern when you want live forensic readouts."
            )
    elif (
        not vault_safe
        and not status_safe
        and not _window4_has_verified_metric_stream()
        and not deploy_verified
    ):
        return WINDOW4_DATA_ENGINE_IDLE_REPLY
    elif status_safe or vault_safe:
        polished = str(text or "").strip()
    else:
        polished = _window4_sanitize_display_text(text)
    if not polished and not (vault_safe or status_safe or conversational_safe):
        return WINDOW4_DATA_ENGINE_IDLE_REPLY
    if not polished:
        return polished
    polished = _window4_break_dense_blocks(polished)
    if not conversational_safe and not vault_safe:
        polished = _window4_bold_anchors(polished)
    polished = re.sub(r"\n{3,}", "\n\n", polished)
    return polished.strip()


def _window4_resolve_status_line() -> str:
    """Dynamic status banner — reflects pending Groq work on the main thread."""
    if isinstance(st.session_state.get("window4_groq_pending"), dict):
        return "⏳ PROCESSING — forensic expert replying..."
    proc = st.session_state.get("room2_processor") or {}
    if proc.get("active"):
        return f"⚙️ Deploy processor running — step {int(proc.get('step') or 0)}..."
    if _window4_has_verified_metric_stream():
        ticker = _window4_operator_deploy_ticker()
        return f"✅ Last deploy active — {ticker} forensic packets on wire."
    if _window4_last_deploy_verified():
        ticker = _window4_operator_deploy_ticker()
        return f"☁️ Vault synced — {ticker or 'pattern'} saved; inventory chat ready."
    custom = str(st.session_state.get("window4_status_line") or "").strip()
    if custom and custom != WINDOW4_ENGINE_IDLE_MSG:
        return custom
    return WINDOW4_ENGINE_IDLE_MSG


def _window4_execute_groq_pending(pending: dict) -> None:
    """Main-thread Groq execution — reliable on Streamlit Cloud (no background threads)."""
    user_text = str(pending.get("user_text") or "").strip()
    track = str(pending.get("track") or "conversational")
    if not user_text:
        return
    if _window4_should_use_vault_roster(user_text):
        _window4_append_vault_roster_reply()
        st.session_state.window4_groq_pending = None
        return
    try:
        if track == "conversational":
            ai_text = run_groq(_build_window4_conversational_messages(user_text))
            st.session_state.room2_chat_history.append(
                {
                    "speaker": "Forensic Expert",
                    "text": _format_window4_response(ai_text, conversational_safe=True),
                    "conversational": True,
                }
            )
        elif _is_pattern_mining_query(user_text):
            ai_text = run_groq(_build_pattern_strategist_messages(user_text))
            st.session_state.room2_chat_history.append(
                {
                    "speaker": "Forensic Expert",
                    "text": _format_window4_response(ai_text, data_reply=True),
                    "data_reply": True,
                }
            )
        else:
            ai_text = run_groq(_build_room2_groq_messages(user_text))
            st.session_state.room2_chat_history.append(
                {
                    "speaker": "Forensic Expert",
                    "text": _format_window4_response(ai_text, data_reply=True),
                    "data_reply": True,
                }
            )
    except Exception as exc:
        st.session_state.room2_chat_history.append(
            {
                "speaker": "Forensic Expert",
                "text": f"⚠️ Forensic chat fault: {exc}",
                "status_reply": True,
            }
        )
    finally:
        st.session_state.window4_groq_pending = None
        st.session_state.window4_status_line = _window4_resolve_status_line()
        _sync_matrix_chat_to_cloud()


def _window4_handle_chat_submit(user_text: str) -> None:
    """Instant operator echo + async forensic reply — UI thread never blocks on Groq."""
    clean = str(user_text or "").strip()
    if not clean:
        return

    st.session_state.room2_chat_history.append({"speaker": "You", "text": clean})

    if _is_room2_restore_command(clean):
        restore_msg = _restore_soft_deleted_pattern_from_vault(
            restore_all=_is_room2_restore_all_command(clean)
        )
        st.session_state.room2_chat_history.append(
            {
                "speaker": "Forensic Expert",
                "text": _format_window4_response(restore_msg, vault_safe=True),
                "vault_safe": True,
            }
        )
        st.session_state.window4_status_line = "✅ Vault restore command processed."
        _sync_matrix_chat_to_cloud()
        return

    if _is_room2_delete_command(clean):
        if _is_room2_delete_all_command(clean):
            trash_msg = _soft_delete_all_patterns_to_vault()
        else:
            trash_msg = _soft_delete_latest_pattern_to_vault()
            st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(
                trash_only=False
            )
            st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(
                trash_only=True
            )
        st.session_state.room2_chat_history.append(
            {
                "speaker": "Forensic Expert",
                "text": _format_window4_response(trash_msg, vault_safe=True),
                "vault_safe": True,
            }
        )
        st.session_state.window4_status_line = "✅ Vault delete command processed."
        _sync_matrix_chat_to_cloud()
        return

    route = _window4_route_message(clean)

    if route == "inventory":
        _window4_append_vault_roster_reply()
        return

    if route == "data":
        if not _window4_has_verified_metric_stream():
            st.session_state.room2_chat_history.append(
                {
                    "speaker": "Forensic Expert",
                    "text": WINDOW4_DATA_ENGINE_IDLE_REPLY,
                    "data_fallback": True,
                    "conversational": True,
                }
            )
            st.session_state.window4_status_line = (
                "📡 Data track — core engine idle; plain-English fallback delivered."
            )
            _sync_matrix_chat_to_cloud()
            return

        allowed, block_msg = _window4_ai_generation_allowed(
            clean,
            source=WINDOW4_SOURCE_OPERATOR,
        )
        if not allowed:
            st.session_state.room2_chat_history.append(
                {
                    "speaker": "Forensic Expert",
                    "text": block_msg,
                    "status_reply": True,
                }
            )
            st.session_state.window4_status_line = block_msg
            _sync_matrix_chat_to_cloud()
            return

        _window4_start_pending_groq(clean, track="data")
        return

    _window4_start_pending_groq(clean, track="conversational")


def _window4_start_pending_groq(user_text: str, *, track: str) -> None:
    """Queue Groq for the next main-thread drain — operator echo is already in history."""
    st.session_state.window4_groq_pending = {
        "user_text": user_text,
        "track": track,
    }
    if track == "conversational":
        st.session_state.window4_status_line = "💬 Conversational wire — composing reply..."
    else:
        st.session_state.window4_status_line = (
            "⏳ PROCESSING — forensic expert analyzing verified packets..."
        )


def _render_window4_chat_message(msg: dict, *, verified_stream: bool) -> None:
    """Render a single Window 4 history row — dual-track replies always visible when tagged."""
    speaker = str(msg.get("speaker") or "")
    body = str(msg.get("text") or "")
    vault_safe = bool(msg.get("vault_safe"))
    status_reply = bool(msg.get("status_reply"))
    conversational = bool(msg.get("conversational"))
    data_fallback = bool(msg.get("data_fallback"))
    if speaker == "You":
        st.markdown(
            f'<div class="room2-chat-row">'
            f'<div class="room2-speaker-operator">{escape(speaker)}</div>'
            f'<div class="room2-chat-body">{escape(body)}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        return
    data_reply = bool(msg.get("data_reply"))
    if (
        not verified_stream
        and not vault_safe
        and not status_reply
        and not conversational
        and not data_fallback
        and not data_reply
    ):
        return
    display = _format_window4_response(
        body,
        vault_safe=vault_safe,
        status_safe=status_reply,
        conversational_safe=conversational,
        data_fallback=data_fallback,
        data_reply=data_reply,
    )
    if (
        not vault_safe
        and not status_reply
        and not conversational
        and not data_fallback
        and not data_reply
        and display == WINDOW4_DATA_ENGINE_IDLE_REPLY
        and body.strip() not in (WINDOW4_DATA_ENGINE_IDLE_REPLY, WINDOW4_ENGINE_IDLE_MSG)
    ):
        display = body.strip() or display
    with st.chat_message("assistant", avatar="🔬"):
        st.markdown(
            '<div class="room2-speaker-expert">Forensic Expert</div>',
            unsafe_allow_html=True,
        )
        st.markdown(display)


def _build_pattern_strategist_messages(user_text: str) -> list[dict]:
    cloud_data = _fetch_live_cloud_patterns()
    context_bits = _window4_build_verified_context_bits()
    verified_blob = "\n".join(context_bits)
    return [
        {"role": "system", "content": f"{PATTERN_STRATEGIST_SYSTEM}\n{WINDOW4_FORMAT_PROTOCOL}"},
        {
            "role": "user",
            "content": (
                f"{user_text}\n"
                f"[CLOUD_PATTERNS]{cloud_data}[/CLOUD_PATTERNS]\n"
                f"{verified_blob}"
            ),
        },
    ]


def _window4_vault_command_only(user_text: str) -> bool:
    return _is_room2_restore_command(user_text) or _is_room2_delete_command(user_text)


WINDOW4_SOURCE_OPERATOR = "operator_chat"
WINDOW4_SOURCE_AUTOMATED = "automated_system"
WINDOW4_SOURCE_LAYOUT_LOOP = "layout_generation"
WINDOW4_SOURCE_FAKE_TICKER = "fake_ticker"


def _window4_is_operator_manual_input(*, source: str) -> bool:
    """True when the payload originates from the Window 4 manual chat form."""
    return source == WINDOW4_SOURCE_OPERATOR


def _window4_automated_vault_empty() -> bool:
    """Empty-vault guard for automated payloads — not applied to operator chat."""
    matrix_index = st.session_state.get("layout_master_matrix_index") or []
    if matrix_index:
        return False
    pg_pct = int(st.session_state.get("window4_spatial_match_pct") or 0)
    return pg_pct < core_quantum.LAYOUT_SIGNATURE_MATCH_THRESHOLD


def _window4_fake_ticker_automated_block(*, source: str) -> bool:
    """Block automated / layout-loop payloads tied to an invalid deploy ticker."""
    if source not in (
        WINDOW4_SOURCE_AUTOMATED,
        WINDOW4_SOURCE_LAYOUT_LOOP,
        WINDOW4_SOURCE_FAKE_TICKER,
    ):
        return False
    ticker = str(st.session_state.get("r2_good_ticker") or "").strip().upper()
    if not ticker:
        return True
    body = ticker.replace(".", "").replace("-", "")
    return not body.isalnum() or len(ticker) > 8


def _window4_ai_generation_allowed(
    user_text: str,
    *,
    source: str = WINDOW4_SOURCE_OPERATOR,
) -> tuple[bool, str]:
    """
    Hard-gated data track only — verified Massive stream + regime defenses.
    Conversational messages bypass this gate entirely via dual-track routing.
    """
    if _window4_vault_command_only(user_text):
        return True, ""
    if not _window4_has_verified_metric_stream():
        return False, WINDOW4_DATA_ENGINE_IDLE_REPLY
    if _window4_is_operator_manual_input(source=source):
        return True, ""

    fault = core_quantum.window4_instant_fault_text()
    if fault:
        return False, fault
    if _window4_fake_ticker_automated_block(source=source):
        return False, WINDOW4_DATA_ENGINE_IDLE_REPLY
    if source == WINDOW4_SOURCE_LAYOUT_LOOP:
        proc = st.session_state.get("room2_processor") or {}
        if proc.get("active") and not core_quantum.window4_regime_gate_open():
            return False, WINDOW4_DATA_ENGINE_IDLE_REPLY
    if _window4_automated_vault_empty():
        return False, WINDOW4_DATA_ENGINE_IDLE_REPLY
    if not core_quantum.window4_regime_gate_open():
        return False, WINDOW4_DATA_ENGINE_IDLE_REPLY
    return True, ""


def _window4_automated_regime_blocked(user_text: str, *, source: str) -> tuple[bool, str]:
    """Entry point for non-operator payloads — always runs the strict defense stack."""
    return _window4_ai_generation_allowed(user_text, source=source)


def _render_window4_conversation_wire() -> None:
    """Window 4 — two-phase wire: instant operator echo, then main-thread Groq drain."""
    if st.session_state.pop("_clear_room2_text_buffer", False):
        st.session_state.pop("room2_text_buffer", None)

    st.markdown(
        '<div class="room2-wire-title">💬 WINDOW 4 — FORENSIC LAB CONVERSATION WIRE</div>',
        unsafe_allow_html=True,
    )

    verified_stream = _window4_has_verified_metric_stream()
    status_line = _window4_resolve_status_line()
    st.markdown(
        f'<div class="window4-system-idle">{escape(status_line)}</div>',
        unsafe_allow_html=True,
    )

    vault_flash = str(st.session_state.get("room2_vault_flash") or "").strip()
    vault_confirm = str(st.session_state.get("room2_vault_confirmation") or "").strip()
    if vault_confirm:
        st.markdown(
            f'<div class="room2-vault-success">{escape(vault_confirm)}</div>',
            unsafe_allow_html=True,
        )
    elif vault_flash:
        st.markdown(
            f'<div class="room2-vault-success">{escape(vault_flash)}</div>',
            unsafe_allow_html=True,
        )

    if not st.session_state.room2_chat_history:
        st.caption("Type a command below — your message appears instantly on send.")
    for msg in st.session_state.room2_chat_history:
        _render_window4_chat_message(msg, verified_stream=verified_stream)

    pending = st.session_state.get("window4_groq_pending")
    if isinstance(pending, dict):
        with st.spinner("Forensic Expert replying..."):
            _window4_execute_groq_pending(pending)
        st.rerun()

    with st.form("room2_chat_form", clear_on_submit=True):
        st.text_input(
            "Lab Input",
            key="room2_text_buffer",
            placeholder="Ask the Forensic Expert · restore all · delete pattern...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send")
        if submitted:
            user_text = str(st.session_state.get("room2_text_buffer") or "").strip()
            if not user_text:
                return
            if isinstance(st.session_state.get("window4_groq_pending"), dict):
                st.session_state.room2_chat_history.append(
                    {"speaker": "You", "text": user_text}
                )
                st.session_state.window4_status_line = (
                    "⏳ Prior reply still processing — message logged on wire."
                )
                _sync_matrix_chat_to_cloud()
            else:
                _window4_handle_chat_submit(user_text)
            st.rerun()


def process_room2_chat_submission():
    """Legacy entry — redirects to the non-blocking Window 4 handler."""
    user_text = st.session_state.room2_text_buffer.strip()
    if user_text:
        _window4_handle_chat_submit(user_text)


def purge_room2_conversation_and_cloud() -> None:
    """Soft-delete all active patterns into the Trash Vault and reset local lab chat."""
    trash_msg = _soft_delete_all_patterns_to_vault()
    st.session_state.room2_chat_history = [
        {
            "speaker": "Forensic Expert",
            "text": _format_window4_response(trash_msg, vault_safe=True),
            "vault_safe": True,
        }
    ]
    st.session_state._clear_room2_text_buffer = True
    _sync_matrix_chat_to_cloud()


def _render_room1_forensic_front_desk():
    """Room 1 — zero-waste read-only lens; volatile local messages RAM only."""
    core_quantum.hydrate_layout_library_from_vault()
    col_chart_side, col_chat_side = st.columns([1.1, 0.9])

    with col_chart_side:
        st.markdown(
            '<div style="position: fixed; width: 45%; max-width: 750px; z-index: 99;">',
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height: 2vh;'></div>", unsafe_allow_html=True)
        if st.session_state.current_ticker:
            active_tk = st.session_state.current_ticker

            tf_cols = st.columns(6)
            tfs = ["5m", "15m", "1H", "1D", "1W", "1M"]
            tf_map = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}
            for i, t_label in enumerate(tfs):
                with tf_cols[i]:
                    if st.button(t_label, key=f"panel_tf_{t_label}"):
                        st.session_state.timeframe = tf_map[t_label]
                        st.rerun()

            active_tf = st.session_state.timeframe
            symbol = urllib.parse.quote(f"NASDAQ:{active_tk.upper()}", safe="")
            pure_chart_url = (
                f"https://s.tradingview.com/widgetembed/?symbol={symbol}&interval={active_tf}"
                f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en&allow_symbol_change=0"
            )

            components.html(f"""
                <div style="height:620px; width:100%; border-radius:8px; overflow:hidden; border:1px solid #1F1F1F;">
                    <iframe src="{pure_chart_url}" width="100%" height="620" frameborder="0"
                        allowtransparency="true" allowfullscreen="true" webkitallowfullscreen="true"
                        scrolling="no"></iframe>
                </div>
            """, height=630)
        else:
            st.markdown("<div style='height: 25vh;'></div>", unsafe_allow_html=True)
            st.markdown(
                "<div style='text-align:center; color:#333; font-size:15px; font-weight:300;'>"
                "Chart display queued. Enter an UPPERCASE stock setup query inside the terminal.</div>",
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with col_chat_side:
        st.markdown("<div style='height: 1vh;'></div>", unsafe_allow_html=True)
        memory_cap = _room1_memory_capacity()
        memory_locked = bool(memory_cap.get("locked") or st.session_state.get("room1_memory_locked"))
        if memory_locked:
            st.markdown(
                '<div class="room1-memory-lock">Peak memory threshold reached. '
                "Refresh the page to preserve maximum up-to-date search speeds.</div>",
                unsafe_allow_html=True,
            )
        elif memory_cap.get("warn_active"):
            st.markdown(
                '<div class="room1-memory-warn">WARNING: Approaching memory limit. '
                "5 messages remaining before a refresh is recommended.</div>",
                unsafe_allow_html=True,
            )
        col_empty, col_btn_anchor = st.columns([0.7, 0.3])
        with col_btn_anchor:
            if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
                _room1_reset_volatile_memory()
                st.rerun()

        if st.session_state.current_ticker:
            tk = st.session_state.current_ticker
            dragnet = st.session_state.get("room1_live_dragnet") or {}
            if dragnet.get("ok") and str(dragnet.get("ticker")) == tk:
                p = float(dragnet.get("price") or 0.0)
                pct = float(dragnet.get("pct_change") or 0.0)
                raw_v = int(dragnet.get("volume") or 0)
                v = f"{raw_v:,}" if raw_v else "N/A"
                vw_native = float(dragnet.get("vwap_native") or 0.0)
                vw = f"${vw_native:,.2f}" if vw_native else "N/A"
                name = tk
            else:
                p, pct, v, vw, name = _fetch_tape_metrics(tk)
            color_choice = "#34C759" if pct >= 0 else "#FF3B30"
            st.markdown(
                f"""
                <div style="background:#111;padding:12px;border-radius:6px;border:1px solid #1F1F1F;margin-bottom:15px;">
                    <div class="metric-label" style="font-size:10px;color:#555;font-weight:700;">
                        Live Massive Tape — {name} ({tk})
                    </div>
                    <div class="metric-grid">
                        <div class="metric-card"><div class="metric-label">Price</div>
                            <div class="metric-value">${p:,.2f}</div></div>
                        <div class="metric-card"><div class="metric-label">Change</div>
                            <div class="metric-value" style="color:{color_choice}">{pct:+.2f}%</div></div>
                        <div class="metric-card"><div class="metric-label">Volume</div>
                            <div class="metric-value">{v}</div></div>
                        <div class="metric-card"><div class="metric-label">Sess. VWAP</div>
                            <div class="metric-value">{vw}</div></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        dialog = [
            m for m in st.session_state.get("messages", [])[1:]
            if m.get("role") in ("user", "assistant")
        ]
        if not dialog:
            st.markdown("<div style='height: 18vh;'></div>", unsafe_allow_html=True)
            st.markdown(
                "<div style='text-align:center;color:#222;font-size:24px;font-weight:300;"
                "letter-spacing:0.04em;'>Savant Apprentice</div>",
                unsafe_allow_html=True,
            )
        else:
            for msg in dialog:
                speaker = "You" if msg.get("role") == "user" else "Savant"
                label_class = "speaker-you" if speaker == "You" else "speaker-savant"
                st.markdown(
                    f'<div class="chat-row"><div class="speaker-label {label_class}">{speaker}</div>'
                    f'<div class="data-content">{escape(str(msg.get("content", "")))}</div></div>',
                    unsafe_allow_html=True,
                )

        with st.form("chat_form", clear_on_submit=False):
            st.text_input(
                "Input",
                key="text_field_buffer",
                placeholder="Ask Savant anything... No filters active.",
                label_visibility="collapsed",
                disabled=memory_locked,
            )
            if (
                st.form_submit_button("Send", disabled=memory_locked)
                and st.session_state.text_field_buffer.strip()
                and not memory_locked
            ):
                st.session_state._pending_chat_submit = True
                st.rerun()


def _room2_coordinate_string(date_val, time_val: str) -> str:
    if not date_val:
        return time_val.strip() if time_val else ""
    return f"{date_val} {time_val}".strip()


def _as_calendar_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if hasattr(value, "date"):
        try:
            return value.date()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except Exception:
        return None


def _deck_dates_are_today(start_date, end_date) -> bool:
    today = date.today()
    start = _as_calendar_date(start_date)
    end = _as_calendar_date(end_date)
    return start == today and end == today


def _lock_r2_timeframe_mode(mode: str) -> None:
    st.session_state.r2_timeframe_mode = mode
    st.session_state.r2_buffer_context_window = R2_BUFFER_WINDOWS.get(
        mode, R2_BUFFER_WINDOWS["15-Minute"]
    )


def _r2_yfinance_interval_from_mode(mode: str) -> str:
    return {"1-Minute": "1m", "5-Minute": "5m", "15-Minute": "15m"}.get(mode, "15m")


def _render_r2_adaptive_buffer_toggles(deck_prefix: str) -> None:
    """Adaptive Buffer Matrix — shared timeframe resolution toggles per card."""
    st.markdown(
        '<div class="r2-buffer-caption">Adaptive Buffer Matrix — Timeframe Resolution</div>',
        unsafe_allow_html=True,
    )
    active = st.session_state.get("r2_timeframe_mode", "15-Minute")
    col_1m, col_5m, col_15m = st.columns(3)
    with col_1m:
        st.button(
            "1m",
            key=f"r2_tf_1m_{deck_prefix}",
            type="primary" if active == "1-Minute" else "secondary",
            use_container_width=True,
            on_click=_lock_r2_timeframe_mode,
            args=("1-Minute",),
        )
    with col_5m:
        st.button(
            "5m",
            key=f"r2_tf_5m_{deck_prefix}",
            type="primary" if active == "5-Minute" else "secondary",
            use_container_width=True,
            on_click=_lock_r2_timeframe_mode,
            args=("5-Minute",),
        )
    with col_15m:
        st.button(
            "15m",
            key=f"r2_tf_15m_{deck_prefix}",
            type="primary" if active == "15-Minute" else "secondary",
            use_container_width=True,
            on_click=_lock_r2_timeframe_mode,
            args=("15-Minute",),
        )
    st.markdown(
        f'<div class="r2-buffer-readout">LOCKED BUFFER: '
        f'{escape(st.session_state.get("r2_buffer_context_window", ""))}</div>',
        unsafe_allow_html=True,
    )
    if active == "1-Minute":
        st.markdown(
            f'<div class="r2-buffer-readout">⚡ LOCAL STRIKE — '
            f'{escape(_processor_lane_readout(active))}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="r2-buffer-readout">☁️ CLOUD STREAM — '
            f'{escape(_processor_lane_readout(active))}</div>',
            unsafe_allow_html=True,
        )


def _evaluate_purgatory_cluster(
    *,
    ticker: str,
    pattern_category: str,
) -> tuple[bool, str]:
    """Legacy wrapper — incubation queue now handles sub-85% alpha anomalies."""
    if not st.session_state.get("purgatory_shelf_active"):
        return False, ""
    return True, st.session_state.get("purgatory_shelf_message", "")


def _render_purgatory_shelf() -> None:
    self_surgery.ensure_purgatory_hub_session()
    self_surgery.purge_expired_repair_bay_profiles()
    hub_message = self_surgery.build_hub_display_message()
    st.markdown(
        '<div class="room2-terminal-header">▸ TWO-WAY PURGATORY HUB — INCUBATION & REPAIR BAY</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("purgatory_shelf_active"):
        shelf_class = "purgatory-shelf purgatory-shelf-active"
        body = st.session_state.get("purgatory_shelf_message") or hub_message
    else:
        shelf_class = "purgatory-shelf"
        body = hub_message
    st.markdown(
        f'<div class="{shelf_class}">{escape(body)}</div>',
        unsafe_allow_html=True,
    )
    bay = st.session_state.get("purgatory_repair_bay") or {}
    benched = [p for p in bay.values() if not p.get("reminted")]
    if benched:
        preview = " · ".join(
            f"{p.get('strategy_label')}@{p.get('parent_layout_id')}" for p in benched[:6]
        )
        extra = f" · +{len(benched) - 6} more" if len(benched) > 6 else ""
        st.caption(f"🔧 **Repair Bay (Track B):** {preview}{extra}")


def _render_r2_datalink_group(deck_prefix: str) -> None:
    """Linear datalink: Start anchor row + End anchor row, side-by-side columns."""
    line1_col1, line1_col2 = st.columns([1.0, 1.0])
    with line1_col1:
        st.date_input("Start Date:", key=f"{deck_prefix}_start_date")
    with line1_col2:
        st.text_input(
            "Start Time (HH:MM AM/PM):",
            key=f"{deck_prefix}_start_time",
            placeholder="09:31 AM",
        )
    line2_col1, line2_col2 = st.columns([1.0, 1.0])
    with line2_col1:
        st.date_input("End Date:", key=f"{deck_prefix}_end_date")
    with line2_col2:
        st.text_input(
            "End Time (HH:MM AM/PM):",
            key=f"{deck_prefix}_end_time",
            placeholder="04:00 PM",
        )


def _matrix_cell(label: str, value: str, width: int = 36) -> str:
    text = f"{label}: {value}" if value else f"{label}: —"
    if len(text) > width:
        text = text[: width - 3] + "..."
    return f"║ {text:<{width}} ║"


def _build_matrix_terminal_readout(
    deck_tag: str,
    ticker: str,
    start_coord: str,
    end_coord: str,
    quantum_report: str,
    vault_line: str,
) -> str:
    """Matrix reaction visualizer — live local processing calculation sheet."""
    header = [
        "╔══════════════════════════════════════╗",
        "║  MATRIX REACTION PROCESSOR — LIVE    ║",
        "╠══════════════════════════════════════╣",
        _matrix_cell("DECK", deck_tag),
        _matrix_cell("TICKER", ticker),
        _matrix_cell("START ANCHOR", start_coord or "—"),
        _matrix_cell("END ANCHOR", end_coord or "—"),
        "╠══════════════════════════════════════╣",
        "║ QUANT PROCESSOR OUTPUT               ║",
    ]
    body = []
    for segment in quantum_report.split(" | "):
        segment = segment.strip()
        while segment:
            body.append(_matrix_cell("", f"▸ {segment[:32]}", width=34))
            segment = segment[32:]
    footer = [
        "╠══════════════════════════════════════╣",
        _matrix_cell("VAULT", vault_line[:34], width=34),
        "╚══════════════════════════════════════╝",
    ]
    return "\n".join(header + body + footer)


def _coerce_quantum_summary_to_text(quantum_summary) -> str:
    """Explicit safety filter — coerce tables/objects to strict terminal text."""
    if quantum_summary is None:
        return "⚠️ [DATALINK: NO_DATA] Matrix processor returned empty."
    if isinstance(quantum_summary, str):
        return quantum_summary
    if hasattr(quantum_summary, "empty") or isinstance(quantum_summary, (dict, list)):
        try:
            if hasattr(quantum_summary, "to_string"):
                frame = quantum_summary
                if hasattr(frame, "empty") and frame.empty:
                    return "⚠️ [DATALINK: NO_DATA] Matrix processor returned empty frame."
                return str(frame.to_string())
            if isinstance(quantum_summary, dict):
                return json.dumps(quantum_summary, indent=2, default=str)
            if isinstance(quantum_summary, list):
                return "\n".join(str(row) for row in quantum_summary)
        except Exception as exc:
            return f"⚠️ [PROCESSOR FAULT] Could not serialize matrix output: {exc}"
    return str(quantum_summary)


def _assign_matrix_terminal_output(quantum_summary, vault_line: str | None = None) -> str:
    """Normalize quantum output and optionally append vault footer as plain text."""
    terminal_text = _coerce_quantum_summary_to_text(quantum_summary)
    if vault_line:
        terminal_text = (
            f"{terminal_text}\n"
            f"╠════════════════════════════════════════╣\n"
            f"│ INTERNET VAULT: {vault_line[:32]:<32} │\n"
            f"╚════════════════════════════════════════╝"
        )
    return terminal_text


def _build_processing_heartbeat_html() -> str:
    logs = st.session_state.get("matrix_processing_logs") or []
    body = "\n".join(escape(line) for line in logs)
    return f'<div class="room2-matrix-box matrix-processing-heartbeat">{body}</div>'


def _capture_room2_deploy_snapshot() -> dict:
    prefix = "r2_good"
    ticker = str(st.session_state.get(f"{prefix}_ticker", "")).strip().upper()
    start_date = st.session_state.get(f"{prefix}_start_date")
    start_time = _normalize_room2_timestamp(
        st.session_state.get(f"{prefix}_start_time", "09:31 AM")
    ) or "09:31 AM"
    end_date = st.session_state.get(f"{prefix}_end_date")
    end_time = _normalize_room2_timestamp(
        st.session_state.get(f"{prefix}_end_time", "04:00 PM")
    ) or "04:00 PM"
    entry_coord = _room2_coordinate_string(start_date, start_time) or ""
    exit_coord = _room2_coordinate_string(end_date, end_time) or ""
    notes = st.session_state.get("r2_single_notes_field", "")
    deck_tag = "WINNING_DNA"
    feedback = notes.strip()
    if start_time or end_time:
        time_meta = f"START:{start_time} | END:{end_time} | DECK:{deck_tag}"
        feedback = f"{feedback} | {time_meta}".strip(" |") if feedback else time_meta
    timeframe_resolution = st.session_state.get("r2_timeframe_mode", "15-Minute")
    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "entry_coord": entry_coord,
        "exit_coord": exit_coord,
        "notes": notes,
        "feedback": feedback,
        "timeframe_resolution": timeframe_resolution,
        "buffer_context_window": st.session_state.get(
            "r2_buffer_context_window", R2_BUFFER_WINDOWS["15-Minute"]
        ),
        "pattern_category": "VALIDATED",
    }


def _arm_room2_processor() -> None:
    """Queue a live processing heartbeat run — steps execute from Window 1 on reruns."""
    core_quantum.reset_processing_heartbeat()
    core_quantum.clear_window1_visual_state()
    st.session_state.room2_sentiment_suppressed = False
    st.session_state.window4_regime_valid = False
    st.session_state.window4_spatial_match_pct = 0
    st.session_state.room2_processor = {
        "active": True,
        "step": 0,
        "snapshot": _capture_room2_deploy_snapshot(),
    }
    st.session_state.matrix_satellites_ready = False
    st.session_state.forensic_institutional_tracker = {
        "institutional_block_accumulation": False,
        "inst_block_summary": "INST_BLOCK: RECALIBRATING...",
        "volume_baseline_20d": 0.0,
        "peak_surge_ratio": 0.0,
    }
    st.session_state.forensic_form4_tracker = {
        "insider_buy_detected": False,
        "form4_summary": "FORM4: RECALIBRATING...",
        "insider_events": [],
    }


def _halt_room2_processor(*, fault_text: str) -> str:
    """Instant hard-stop for connection/auth/syntax faults — full-screen text only."""
    proc = st.session_state.get("room2_processor") or {}
    proc["active"] = False
    st.session_state.room2_processor = proc
    st.session_state.window4_regime_valid = False
    st.session_state.window4_spatial_match_pct = 0
    core_quantum.flash_processing_fault(fault_text)
    st.session_state.room2_quantum_report = fault_text
    st.session_state.matrix_satellites_ready = True
    st.session_state.matrix_cascade_active = False
    return "failed"


def _halt_room2_processor_with_charts(*, fault_text: str) -> str:
    """Post-ingest rejection — keep charts visible with companion trash overlay."""
    proc = st.session_state.get("room2_processor") or {}
    proc["active"] = False
    st.session_state.room2_processor = proc
    st.session_state.room2_sentiment_suppressed = True
    st.session_state.window4_regime_valid = False
    st.session_state.window4_spatial_match_pct = 0
    core_quantum.publish_window1_rejection_overlay(fault_text)
    st.session_state.room2_quantum_report = fault_text
    st.session_state.room2_chart_coupling = st.session_state.get("room2_chart_coupling") or {
        "passed": False,
        "trashed": True,
    }
    st.session_state.matrix_satellites_ready = True
    st.session_state.matrix_cascade_active = False
    return "failed"


def _finalize_room2_processor_vault(proc: dict) -> None:
    """Vault sync + Window 4 strategy node — runs the instant computations conclude."""
    snap = proc.get("snapshot") or {}
    ticker = snap.get("ticker", "")
    timeframe_resolution = snap.get("timeframe_resolution", "15-Minute")
    pattern_category = snap.get("pattern_category", "VALIDATED")
    quantum_report = proc.get("quantum_report", "")
    structural_move = float(proc.get("structural_move") or 0.0)
    macro_weather_layout = proc.get("macro_weather_layout", "")
    execution_strategy = proc.get("execution_strategy", "")
    match_score = int(proc.get("match_score") or 0)
    vault_state = proc.get("vault_state", "")
    incubation_msg = proc.get("incubation_msg", "")
    in_purgatory = bool(proc.get("in_purgatory"))
    purgatory_message = proc.get("purgatory_message", "")
    quality = proc.get("quality") or {}
    chart_coupling = proc.get("chart_coupling") or {}
    research_audit = proc.get("research_audit") or {}
    math_block = proc.get("math_block") or {}
    start_time = snap.get("start_time", "")
    end_time = snap.get("end_time", "")
    entry_coord = snap.get("entry_coord", "")
    exit_coord = snap.get("exit_coord", "")
    payload = proc.get("payload") or {}

    ok, vault_message = core_quantum.stream_payload_to_vault(payload)
    if ok:
        funnel = st.session_state.get("room2_regime_funnel") or {}
        pg_pct = int(
            funnel.get("window4_spatial_match_pct")
            or match_score
            or 0
        )
        pg_valid = pg_pct >= core_quantum.LAYOUT_SIGNATURE_MATCH_THRESHOLD
        core_quantum._sync_window4_regime_flags(match_pct=pg_pct, valid=pg_valid)
    if ok and pattern_category == "VALIDATED":
        margin_pct = structural_move or abs(
            float(
                (st.session_state.get("room2_last_velocity") or {}).get(
                    "session_velocity_pct", 0.0
                )
            )
        )
        retro = core_quantum.log_strategy_execution_with_fallback(
            ticker=ticker,
            macro_weather_layout=macro_weather_layout,
            execution_strategy=execution_strategy,
            timeframe_resolution=timeframe_resolution,
            margin_pct=margin_pct,
            pattern_category=pattern_category,
            layout_match_pct=match_score,
            structural_move_pct=structural_move,
            entry_coordinate=entry_coord or "",
            exit_coordinate=exit_coord or "",
        )
        st.session_state.room2_alpha_decay_status = retro
        if retro.get("repair_bay_demoted"):
            vault_line = (
                f"{vault_message} · REPAIR BAY — {execution_strategy} benched "
                f"(live execution locked · 60-day recycle window)."
            )
        elif retro.get("autonomous_surgery", {}).get("database_action") == "entry_tweak_update":
            vault_line = (
                f"{vault_message} · AUTO-TWEAK — entry coordinates updated in cloud "
                f"for {execution_strategy}."
            )
        elif retro.get("autonomous_surgery", {}).get("database_action") == "delete_and_purgatory":
            vault_line = (
                f"{vault_message} · AUTO-PURGATORY — {execution_strategy} erased from "
                f"active layout; Repair Bay engaged."
            )
        elif retro.get("halt_live_execution") and retro.get("diagnosis"):
            vault_line = f"{vault_message} · {retro['diagnosis']}"
        elif vault_state == VAULT_STATE_INCUBATION and incubation_msg:
            vault_line = f"{vault_message} · {incubation_msg}"
        elif (retro.get("degraded") or retro.get("evolving")) and retro.get("diagnosis"):
            vault_line = f"{vault_message} · {retro['diagnosis']}"
        else:
            vault_line = vault_message
    else:
        vault_line = vault_message if ok else f"VAULT ERROR — {vault_message}"

    if ok and quality.get("passed"):
        velocity = st.session_state.get("room2_last_velocity") or {}
        feature_vector = core_quantum.extract_forensic_feature_vector(
            velocity,
            math_block,
            float(
                (st.session_state.get("room2_deep_research_audit") or {})
                .get("semantic_catalyst", {})
                .get("finbert_sentiment_score", 0.0)
            ),
        )
        genetic = st.session_state.get("room2_master_signature") or {}
        reminted = self_surgery.attempt_genetic_recycling_on_fresh_deploy(
            ticker=ticker,
            parent_layout_id=macro_weather_layout,
            strategy_label=execution_strategy,
            timeframe_resolution=timeframe_resolution,
            quality=quality,
            metric_envelopes=research_audit.get("metric_envelopes"),
            master_signature=genetic.get("master_signature"),
            feature_vector=feature_vector,
            entry_time=start_time,
            exit_time=end_time,
        )
        if reminted:
            remint_note = (
                f"GENETIC RE-MINT — {execution_strategy} restored to "
                f"{macro_weather_layout} (boundaries updated · floor re-validated)."
            )
            vault_line = f"{vault_line} · {remint_note}" if vault_line else remint_note

    if in_purgatory:
        final_terminal = _assign_matrix_terminal_output(
            f"{quantum_report}\n\n{purgatory_message}",
            vault_line if ok else None,
        )
    elif incubation_msg and vault_state == VAULT_STATE_INCUBATION:
        final_terminal = _assign_matrix_terminal_output(
            f"{quantum_report}\n\n{incubation_msg}",
            vault_line if ok else None,
        )
    elif ok and quality.get("passed") and chart_coupling.get("passed"):
        confirm = (
            f"✅ VAULT SYNC OK — {ticker} · {timeframe_resolution} · "
            f"{structural_move:.2f}% structural move · "
            f"bars={st.session_state.room2_bar_count} · Massive REST lane live."
        )
        final_terminal = _assign_matrix_terminal_output(
            quantum_report,
            f"{vault_line}\n{confirm}",
        )
        st.session_state.room2_stale_threshold_error = None
        st.session_state.room2_vault_confirmation = confirm
        st.session_state.room2_forensic_ticker = ticker
        st.session_state.matrix_window1_rejection_text = ""
        deploy_note = (
            f"✅ **Pattern saved** — **{ticker}** · **{macro_weather_layout}** · "
            f"**{execution_strategy}** · {structural_move:.2f}% structural move. "
            f"{str((st.session_state.get('room2_strategy_trust') or {}).get('message') or 'Cloud vault synced.')}"
        )
        st.session_state.room2_chat_history.append(
            {
                "speaker": "Forensic Expert",
                "text": deploy_note,
                "vault_safe": True,
            }
        )
    else:
        final_terminal = _assign_matrix_terminal_output(quantum_report, vault_line if ok else None)

    core_quantum.complete_processing_heartbeat(final_terminal)
    st.session_state.room2_quantum_report = final_terminal
    st.session_state.room2_vault_flash = vault_line if ok else ""
    st.session_state.matrix_satellites_ready = True
    st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
    st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
    if ok and int(st.session_state.matrix_active_pattern_count or 0) == 0:
        st.session_state.matrix_active_pattern_count = 1
    _sync_matrix_chat_to_cloud()
    _record_room2_successful_commit()
    _clear_room2_form_buffers()


def _advance_room2_processor() -> str:
    """
    Execute the next real pipeline stage and emit Window 1 logs on CPU completion.
    Returns idle | running | complete | failed.
    """
    proc = st.session_state.get("room2_processor") or {}
    if not proc.get("active"):
        return "idle"

    snap = proc.get("snapshot") or {}
    step = int(proc.get("step") or 0)
    ticker = snap.get("ticker", "")
    start_date = snap.get("start_date")
    start_time = snap.get("start_time", "09:31 AM")
    end_date = snap.get("end_date")
    end_time = snap.get("end_time", "04:00 PM")
    notes = snap.get("notes", "")
    feedback = snap.get("feedback", "")
    timeframe_resolution = snap.get("timeframe_resolution", "15-Minute")
    buffer_context_window = snap.get("buffer_context_window", R2_BUFFER_WINDOWS["15-Minute"])
    pattern_category = snap.get("pattern_category", "VALIDATED")
    micro_fast_track = timeframe_resolution == "1-Minute"
    data_feed_mode = _resolve_data_feed_mode(timeframe_resolution)
    st.session_state.r2_data_feed_mode = data_feed_mode
    st.session_state.r2_processor_lane = core_quantum.resolve_processor_lane(timeframe_resolution)

    try:
        if step == 0:
            data_stream = core_quantum.get_historical_interval_data(
                ticker,
                interval=_r2_yfinance_interval_from_mode(timeframe_resolution),
                micro_fast_track=micro_fast_track,
                start_date=start_date,
                end_date=end_date,
                timeframe_resolution=timeframe_resolution,
            )
            if core_quantum.is_pipeline_signal(data_stream, "THROTTLE"):
                st.session_state.polygon_lockout = True
                return _halt_room2_processor(
                    fault_text=_coerce_quantum_summary_to_text(core_quantum.THROTTLE_MESSAGE)
                )
            if core_quantum.is_pipeline_signal(
                data_stream, core_quantum.MASSIVE_PLAN_TIMEFRAME_BLOCKED
            ):
                return _halt_room2_processor(
                    fault_text=(
                        f"⚠️ {core_quantum.MASSIVE_PLAN_TIMEFRAME_BLOCKED} — Same-day 1m bars for "
                        f"{ticker} on {_session_date_label(start_date)} are not on your API tier. "
                        f"Set Start/End Date to a prior completed session "
                        f"(e.g. {_session_date_label(_last_completed_equity_session_date())})."
                    )
                )
            if core_quantum.is_pipeline_signal(data_stream, core_quantum.POLYGON_REST_DATA_EMPTY):
                api_err = str(st.session_state.get("r2_market_data_error") or "").strip()
                if api_err.startswith("MASSIVE_EMPTY_SESSION"):
                    empty_hint = (
                        f"No 1m bars returned for {ticker} on "
                        f"{_session_date_label(start_date)}–{_session_date_label(end_date)}. "
                        "Try the last trading day with regular volume."
                    )
                else:
                    empty_hint = (
                        f"No 1m bars for {ticker} on "
                        f"{_session_date_label(start_date)}–{_session_date_label(end_date)}. "
                        "Verify Massive API key and session dates."
                    )
                return _halt_room2_processor(
                    fault_text=(
                        f"⚠️ {core_quantum.POLYGON_REST_DATA_EMPTY} — {empty_hint}"
                        + (f" [{api_err}]" if api_err else "")
                    )
                )
            if not core_quantum.is_usable_data_stream(data_stream):
                return _halt_room2_processor(
                    fault_text=(
                        f"⚠️ [DATALINK: NO_DATA] No bars for {ticker} ({timeframe_resolution}). "
                        "Verify ticker symbol and market session dates."
                    )
                )
            bar_n = len(data_stream) if core_quantum.is_usable_data_stream(data_stream) else 0
            core_quantum.emit_processing_heartbeat(
                "📥 CONSUMING: Fetching historical 1-minute arrays from ://massive.com...",
                detail=f"Received {bar_n} raw 1m bars · {timeframe_resolution} lane armed",
            )
            proc["data_stream"] = data_stream
            proc["step"] = 1

        elif step == 1:
            data_stream = proc.get("data_stream")
            start_dt, end_dt, start_norm, end_norm = core_quantum.parse_operator_boundaries(
                start_date, start_time, end_date, end_time
            )
            st.session_state.room2_operator_start_norm = start_norm
            st.session_state.room2_operator_end_norm = end_norm
            data_stream = core_quantum.pad_datastream_gaps(data_stream)
            data_stream, _fence_meta = core_quantum.apply_temporal_fence_and_lookback(
                data_stream,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                timeframe_resolution=timeframe_resolution,
            )
            if not core_quantum.is_usable_data_stream(data_stream):
                return _halt_room2_processor(
                    fault_text=(
                        f"⚠️ [DATALINK: FENCE_EMPTY] Temporal fence/lookback returned no bars for "
                        f"{ticker} ({timeframe_resolution}). Operator window "
                        f"{start_norm or '?'} → {end_norm or '?'}. "
                        "Widen the date window or check session hours."
                    )
                )
            bar_count = len(data_stream)
            core_quantum.emit_parsing_telemetry(
                data_stream,
                timeframe_resolution=timeframe_resolution,
                bar_count=bar_count,
                start_norm=start_norm,
                end_norm=end_norm,
            )
            charts_html = core_quantum.build_window1_visual_charts_html(
                data_stream,
                ticker=ticker,
                timeframe_resolution=timeframe_resolution,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
            )
            if charts_html:
                core_quantum.publish_window1_visual_charts(charts_html)
            proc["data_stream"] = data_stream
            proc["start_norm"] = start_norm
            proc["end_norm"] = end_norm

            lane_check = core_quantum.validate_regime_lookback_lanes(
                data_stream,
                start_date=start_date,
                start_time=start_time,
                timeframe_resolution=timeframe_resolution,
            )
            if not lane_check.get("passed"):
                return _halt_room2_processor_with_charts(
                    fault_text=(
                        f"🗑️ PRE-STORAGE TRASH — No usable chart data before Start Time "
                        f"(need at least {lane_check.get('min_bars')} bars, got "
                        f"{lane_check.get('actual_bars')} on {timeframe_resolution})."
                    )
                )
            proc["lane_check"] = lane_check
            proc["step"] = 2

        elif step == 2:
            data_stream = proc.get("data_stream")
            core_quantum.emit_calculating_telemetry(
                data_stream,
                timeframe_resolution=timeframe_resolution,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
            )
            quality = core_quantum.evaluate_playbook_quality_barrier(
                data_stream,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                timeframe_resolution=timeframe_resolution,
            )
            st.session_state.room2_playbook_quality = quality
            chart_coupling = core_quantum.validate_chart_data_coupling(data_stream, quality)
            st.session_state.room2_chart_coupling = chart_coupling

            if not chart_coupling.get("passed"):
                reasons = chart_coupling.get("rejection_reasons") or ["chart_failed"]
                if "no_volume_ignition" in reasons:
                    trash_text = (
                        "🗑️ PRE-STORAGE TRASH — Chart coupling failed (no_volume_ignition)"
                    )
                else:
                    reasons_label = ", ".join(reasons)
                    trash_text = (
                        f"🗑️ PRE-STORAGE TRASH — Chart coupling failed ({reasons_label}). "
                        "Market data lane blocked — SEC/vault writes halted."
                    )
                return _halt_room2_processor_with_charts(fault_text=trash_text)
            if not quality.get("passed"):
                floor_pct = quality.get("floor_pct", 1.0)
                move_pct = quality.get("structural_move_pct", 0.0)
                net = quality.get("net_margin_pct", move_pct)
                friction = quality.get("execution_friction_buffer_pct", 0.0)
                return _halt_room2_processor_with_charts(
                    fault_text=(
                        f"🗑️ PRE-STORAGE TRASH — Net margin {net:.2f}% failed "
                        f"{floor_pct:.1f}% strict alpha floor for {timeframe_resolution} "
                        f"(gross {move_pct:.2f}% − slippage {friction:.2f}%). "
                        "Pattern rejected before vault mint."
                    )
                )
            session_quality = core_quantum.evaluate_session_data_quality(
                data_stream,
                ticker=ticker,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                timeframe_resolution=timeframe_resolution,
            )
            st.session_state.room2_session_quality = session_quality
            proc["quality"] = quality
            proc["chart_coupling"] = chart_coupling
            proc["session_quality"] = session_quality
            proc["step"] = 3

        elif step == 3:
            data_stream = proc.get("data_stream")
            quality = proc.get("quality") or {}
            research_audit = core_quantum.run_deep_internet_research_audit(
                ticker=ticker,
                data_stream=data_stream,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                timeframe_resolution=timeframe_resolution,
                quality=quality,
            )
            st.session_state.room2_deep_research_audit = research_audit
            semantic = research_audit.get("semantic_catalyst") or {}
            form4 = research_audit.get("form4") or {}
            headlines = research_audit.get("news_headlines") or []
            core_quantum.emit_digesting_telemetry(
                ticker=ticker,
                finbert_score=semantic.get("finbert_sentiment_score"),
                filing_count=len(form4.get("insider_events") or []),
                headline_count=len(headlines),
            )
            proc["research_audit"] = research_audit
            proc["step"] = 4

        elif step == 4:
            data_stream = proc.get("data_stream")
            quality = proc.get("quality") or {}
            research_audit = proc.get("research_audit") or {}
            entry_coord = snap.get("entry_coord", "")
            exit_coord = snap.get("exit_coord", "")

            text_matrix_string = research_audit.get("text_matrix_string", "")
            forensic_dragnet_blob = research_audit.get("forensic_dragnet_blob", "")
            metric_envelopes_json = json.dumps(
                research_audit.get("metric_envelopes", {}), default=str
            )
            semantic_catalyst_json = json.dumps(
                research_audit.get("semantic_catalyst", {}), default=str
            )

            quantum_summary = core_quantum.calculate_quantum_frequencies(
                data_stream,
                pattern_category=pattern_category,
                ticker=ticker,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                operator_context=notes,
                human_feedback=feedback,
                layout_block_id="",
            )
            quantum_report = _coerce_quantum_summary_to_text(quantum_summary)
            if "PRE-STORAGE TRASH" in quantum_report:
                return _halt_room2_processor_with_charts(fault_text=quantum_report)
            math_block = st.session_state.get("room2_last_math_block", {}) or {}
            genetic = st.session_state.get("room2_master_signature") or {}
            funnel = st.session_state.get("room2_regime_funnel") or {}
            master_signature_json = json.dumps(
                {
                    "master_signature": genetic.get("master_signature") or [],
                    "overlap_pct": genetic.get("overlap_pct", 0),
                    "dimensions_trashed": genetic.get("dimensions_trashed", 0),
                    "pure_overlap_dims": genetic.get("pure_overlap_dims", 0),
                    "finbert_sentiment_score": (
                        (research_audit.get("semantic_catalyst") or {}).get(
                            "finbert_sentiment_score", 0.0
                        )
                    ),
                },
                default=str,
            )
            macro_weather_layout = str(
                funnel.get("master_layout_container")
                or math_block.get("nearest_layout_id")
                or _resolve_auto_layout_id()
            )
            match_score = int(math_block.get("match_probability") or 0)
            execution_strategy = str(
                funnel.get("execution_strategy")
                or st.session_state.get("room2_funnel_execution_strategy")
                or core_quantum.resolve_matrix_strategy_id(
                    layout_id=macro_weather_layout,
                    timeframe_resolution=timeframe_resolution,
                    spatial_match_pct=match_score,
                )
            )

            if not (st.session_state.get("room2_chart_coupling") or {}).get("passed"):
                return _halt_room2_processor_with_charts(
                    fault_text=(
                        "🗑️ PRE-STORAGE TRASH — Chart coupling lock tripped. "
                        "Supabase write blocked."
                    )
                )

            st.session_state.polygon_lockout = False
            st.session_state.room2_bar_count = (
                len(data_stream) if core_quantum.is_usable_data_stream(data_stream) else 0
            )
            st.session_state.room2_forensic_ticker = ticker
            structural_move = float(quality.get("structural_move_pct") or 0.0)
            vault_track, vault_state = _resolve_vault_track(pattern_category)
            vault_track, vault_state, repeat_count, shelf_expires, incubation_msg = (
                _resolve_anomaly_incubation(
                    ticker=ticker,
                    timeframe_resolution=timeframe_resolution,
                    macro_weather_layout=macro_weather_layout,
                    match_score=match_score,
                )
            )
            in_purgatory, purgatory_message = _evaluate_purgatory_cluster(
                ticker=ticker,
                pattern_category=pattern_category,
            )
            day_context = core_quantum.build_day_context_envelope(
                ticker=ticker,
                data_stream=data_stream,
                start_date=start_date,
                start_time=start_time,
                end_date=end_date,
                end_time=end_time,
                timeframe_resolution=timeframe_resolution,
            )
            day_context_json = json.dumps(day_context, default=str)
            net_margin = float(
                quality.get("net_margin_pct") or quality.get("structural_move_pct") or structural_move
            )
            trust = core_quantum.evaluate_strategy_trust_promotion(
                macro_weather_layout=macro_weather_layout,
                execution_strategy=execution_strategy,
                timeframe_resolution=timeframe_resolution,
                ticker=ticker,
                session_date=start_date,
                margin_pct=net_margin,
            )
            st.session_state.room2_strategy_trust = trust
            if not trust.get("trusted"):
                vault_state = VAULT_STATE_INCUBATION
                incubation_msg = str(trust.get("message") or incubation_msg)
            elif trust.get("trusted") and vault_state == VAULT_STATE_INCUBATION:
                vault_state = "active"
                incubation_msg = str(trust.get("message") or incubation_msg)
            payload = core_quantum.build_vault_payload(
                ticker=ticker,
                pattern_category=pattern_category,
                entry_coordinate=entry_coord or "",
                exit_coordinate=exit_coord or "",
                entry_time=start_time,
                exit_time=end_time,
                operator_notes=notes,
                quantum_report=quantum_report,
                bar_count=st.session_state.room2_bar_count,
                timeframe_resolution=timeframe_resolution,
                macro_weather_layout=macro_weather_layout,
                execution_strategy=execution_strategy,
                buffer_context_window=buffer_context_window,
                vault_track=vault_track,
                vault_state=vault_state,
                data_feed_mode=data_feed_mode,
                layout_match_pct=match_score,
                anomaly_repeat_count=repeat_count,
                shelf_expires_at=shelf_expires,
                structural_move_pct=structural_move,
                text_matrix_string=text_matrix_string,
                forensic_dragnet_blob=forensic_dragnet_blob,
                master_signature_json=master_signature_json,
                metric_envelopes_json=metric_envelopes_json,
                semantic_catalyst_json=semantic_catalyst_json,
                day_context_json=day_context_json,
                strategy_trust_tier=str(trust.get("trust_tier") or "candidate"),
            )
            proc["payload"] = payload
            proc["quantum_report"] = quantum_report
            proc["structural_move"] = structural_move
            proc["macro_weather_layout"] = macro_weather_layout
            proc["execution_strategy"] = execution_strategy
            proc["match_score"] = match_score
            proc["vault_state"] = vault_state
            proc["incubation_msg"] = incubation_msg
            proc["strategy_trust"] = trust
            proc["day_context"] = day_context
            proc["in_purgatory"] = in_purgatory
            proc["purgatory_message"] = purgatory_message
            proc["quality"] = quality
            proc["chart_coupling"] = proc.get("chart_coupling") or st.session_state.get(
                "room2_chart_coupling"
            )
            proc["research_audit"] = research_audit
            proc["math_block"] = math_block
            proc["active"] = False
            st.session_state.room2_processor = proc
            _finalize_room2_processor_vault(proc)
            return "complete"

        st.session_state.room2_processor = proc
        return "running"

    except Exception as exc:
        return _halt_room2_processor(
            fault_text=(
                "⚠️ [PROCESSOR FAULT] Deploy halted safely.\n"
                f"│ Detail: {str(exc)[:100]} │\n"
                "│ Check: ticker letters only, times like 09:31 AM │"
            )
        )


def _render_matrix_window1_panel(*, processor_status: str) -> None:
    """Window 1 — hybrid chart stream, live heartbeat, or critical fault readout."""
    status = processor_status

    st.markdown(
        '<div class="room2-terminal-header">▸ WINDOW 1 — MATRIX REACTION PROCESSOR</div>',
        unsafe_allow_html=True,
    )

    charts_html = str(st.session_state.get("matrix_window1_charts_html") or "").strip()
    rejection = str(st.session_state.get("matrix_window1_rejection_text") or "").strip()
    processing = bool(
        st.session_state.get("matrix_processing_active") or status == "running"
    )
    terminal_text = _coerce_quantum_summary_to_text(st.session_state.quantum_terminal_output)

    if charts_html:
        st.markdown(charts_html, unsafe_allow_html=True)
        if processing:
            st.markdown(_build_processing_heartbeat_html(), unsafe_allow_html=True)
            if status == "running":
                st.rerun()
            return
        if rejection:
            st.markdown(
                f'<div class="w1-rejection-overlay">{escape(rejection)}</div>',
                unsafe_allow_html=True,
            )
            return
        if terminal_text and status == "complete":
            st.markdown(
                f'<div class="room2-matrix-box">{escape(terminal_text)}</div>',
                unsafe_allow_html=True,
            )
            return
        if status == "running":
            st.rerun()
        return

    if processing:
        st.markdown(_build_processing_heartbeat_html(), unsafe_allow_html=True)
        if status == "running":
            st.rerun()
        return

    fault_class = "room2-matrix-box"
    if core_quantum.is_critical_window1_fault(terminal_text):
        fault_class = "room2-matrix-box w1-critical-fault"
    st.markdown(
        f'<div class="{fault_class}">{escape(terminal_text)}</div>',
        unsafe_allow_html=True,
    )


def _render_room2_proxy_telemetry_body() -> None:
    st.markdown('<div class="room2-satellite-shell">', unsafe_allow_html=True)

    if not st.session_state.get("matrix_satellites_ready", True):
        st.markdown(
            '<div class="whale-banner">'
            '<div class="proxy-banner-title">🐳 INSTITUTIONAL BLOCK FLOWS</div>'
            '<div class="proxy-banner-body">⏳ PROCESSOR ACTIVE — LIVE VOLUME BASELINE RECALIBRATION...</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="insider-banner">'
            '<div class="proxy-banner-title">👔 MANAGEMENT INSIDER RECONNAISSANCE</div>'
            '<div class="proxy-banner-body">⏳ PROCESSOR ACTIVE — SEC FORM 4 DIGESTION IN FLIGHT...</div>'
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    inst = st.session_state.get("forensic_institutional_tracker", {})
    form4 = st.session_state.get("forensic_form4_tracker", {})

    whale_active = bool(inst.get("institutional_block_accumulation"))
    whale_class = "whale-banner whale-banner-active" if whale_active else "whale-banner"
    if whale_active:
        whale_body = inst.get("inst_block_summary", "Institutional Block Accumulation Detected")
    else:
        peak = inst.get("peak_surge_ratio", 0.0)
        baseline = inst.get("volume_baseline_20d", 0.0)
        if baseline:
            whale_body = (
                f"NO BLOCK SURGE — Peak: {peak:.1f}x vs 20D baseline | "
                f"20D Avg Vol: {baseline:,.0f} | Threshold: >300% (4.0x)"
            )
        else:
            whale_body = "STANDBY — Deploy a deck station to load institutional volume baseline wire."

    insider_active = bool(form4.get("insider_buy_detected"))
    insider_class = "insider-banner insider-banner-active" if insider_active else "insider-banner"
    if insider_active:
        insider_body = form4.get("form4_summary", "FORM4 INSIDER BUY ACTIVE")
        events = form4.get("insider_events", [])
        if events:
            detail = " | ".join(
                f"{evt.get('transaction_date', '—')}: {int(evt.get('shares', 0)):,} shares"
                for evt in events[:3]
            )
            insider_body = f"{insider_body} | RECON: {detail}"
    else:
        insider_body = form4.get("form4_summary", "STANDBY — No Form 4 insider buying flagged in last 30 days.")

    st.markdown(
        f'<div class="{whale_class}">'
        f'<div class="proxy-banner-title">🐳 INSTITUTIONAL BLOCK FLOWS</div>'
        f'<div class="proxy-banner-body">{escape(whale_body)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="{insider_class}">'
        f'<div class="proxy-banner-title">👔 MANAGEMENT INSIDER RECONNAISSANCE</div>'
        f'<div class="proxy-banner-body">{escape(insider_body)}</div>'
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_room2_proxy_telemetry_banners() -> None:
    st.markdown(
        '<div class="room2-terminal-header">▸ WINDOW 2 & 3 — INSTITUTIONAL SATELLITE TELEMETRY</div>',
        unsafe_allow_html=True,
    )
    _render_room2_proxy_telemetry_body()


def _validate_room2_ticker(ticker: str) -> bool:
    cleaned = str(ticker).strip()
    if not cleaned:
        return False
    if re.search(r"\d", cleaned):
        return False
    return bool(re.fullmatch(r"[A-Za-z.$-]{1,6}", cleaned))


def _normalize_room2_timestamp(timestamp: str) -> str | None:
    """Accept flexible operator input; return canonical 'H:MM AM/PM' or None."""
    cleaned = str(timestamp).strip().upper()
    if not cleaned:
        return None
    cleaned = re.sub(r"(\d{1,2}:\d{2})\s*(AM|PM)", r"\1 \2", cleaned)
    if not R2_TIMESTAMP_PATTERN.match(cleaned):
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})\s+(AM|PM)$", cleaned, re.IGNORECASE)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).upper()
    if hour < 1 or hour > 12 or minute > 59:
        return None
    return f"{hour}:{minute:02d} {meridiem}"


def _validate_room2_timestamp(timestamp: str) -> bool:
    return _normalize_room2_timestamp(timestamp) is not None


def _validate_room2_deck() -> bool:
    ticker = st.session_state.get("r2_good_ticker", "")
    start_time = st.session_state.get("r2_good_start_time", "")
    end_time = st.session_state.get("r2_good_end_time", "")
    return (
        _validate_room2_ticker(ticker)
        and _validate_room2_timestamp(start_time)
        and _validate_room2_timestamp(end_time)
    )


def _ensure_room2_widget_defaults() -> None:
    """Bind missing Room 2 widget keys before render (safe after form-buffer pop)."""
    today = date.today()
    forensic = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
    bindings = {
        "r2_good_ticker": forensic,
        "r2_good_start_date": today,
        "r2_good_end_date": today,
        "r2_good_start_time": "09:31 AM",
        "r2_good_end_time": "04:00 PM",
        "r2_single_notes_field": "",
    }
    for key, value in bindings.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _prune_room2_commit_timestamps(now: float | None = None) -> list[float]:
    """Rolling 60-second window of successful Commit timestamps."""
    now = now or time.time()
    window_start = now - R2_COMMIT_WINDOW_SEC
    pruned = [ts for ts in (st.session_state.get("room2_commit_timestamps") or []) if ts > window_start]
    st.session_state.room2_commit_timestamps = pruned
    return pruned


def _room2_commit_throttle_seconds_remaining(now: float | None = None) -> int:
    now = now or time.time()
    stamps = _prune_room2_commit_timestamps(now)
    if len(stamps) >= R2_COMMIT_MAX_PER_WINDOW:
        reset_at = min(stamps) + R2_COMMIT_WINDOW_SEC
        return max(0, int(reset_at - now + 0.999))
    throttle_until = float(st.session_state.get("room2_commit_throttle_until") or 0.0)
    if throttle_until > now:
        return max(0, int(throttle_until - now + 0.999))
    st.session_state.room2_commit_throttle_until = 0.0
    return 0


def _room2_commit_throttle_active() -> bool:
    return _room2_commit_throttle_seconds_remaining() > 0


def _activate_room2_commit_throttle() -> None:
    stamps = _prune_room2_commit_timestamps()
    if stamps:
        st.session_state.room2_commit_throttle_until = min(stamps) + R2_COMMIT_WINDOW_SEC
    else:
        st.session_state.room2_commit_throttle_until = time.time() + R2_COMMIT_WINDOW_SEC


def _room2_commit_would_throttle() -> bool:
    """True when a 4th deploy would breach the rolling 60-second limit."""
    return len(_prune_room2_commit_timestamps()) >= R2_COMMIT_MAX_PER_WINDOW


def _record_room2_successful_commit() -> None:
    now = time.time()
    stamps = _prune_room2_commit_timestamps(now)
    stamps.append(now)
    st.session_state.room2_commit_timestamps = stamps


@st.fragment(run_every=timedelta(seconds=1))
def _render_room2_commit_throttle_banner() -> bool:
    """Persistent throttle banner with live countdown until the window resets."""
    remaining = _room2_commit_throttle_seconds_remaining()
    if remaining <= 0:
        return False
    st.markdown(
        f'<div class="room2-throttle-banner">'
        f"🛑 {escape(R2_COMMIT_THROTTLE_BANNER)}"
        f'<div class="room2-throttle-countdown">{remaining}s until reset</div>'
        f'<div style="font-size:11px;font-weight:500;margin-top:6px;color:#FFAAAA;'
        f'text-transform:none;letter-spacing:0.02em;">'
        f"Max {R2_COMMIT_MAX_PER_WINDOW} submissions per {R2_COMMIT_WINDOW_SEC}s — "
        f"your inputs are held safely on screen."
        f"</div></div>",
        unsafe_allow_html=True,
    )
    return True


def _clear_room2_form_buffers() -> None:
    """Reset winning-deck form keys after deploy — deferred until pre-widget patch pass."""
    forensic = str(st.session_state.get("room2_forensic_ticker") or "").strip().upper()
    _queue_room2_form_reset(ticker=forensic)


def _handle_room2_deck_submit() -> None:
    if not _validate_room2_deck():
        st.session_state.r2_good_validation_error = True
        st.rerun()
        return
    st.session_state.r2_good_validation_error = False
    if _room2_commit_would_throttle():
        _activate_room2_commit_throttle()
        st.rerun()
        return
    _arm_room2_processor()
    st.rerun()


def _session_date_label(raw_date) -> str:
    if raw_date is None:
        return "?"
    if hasattr(raw_date, "strftime"):
        return raw_date.strftime("%Y-%m-%d")
    return str(raw_date)[:10]


def _fetch_active_layout_folders() -> list[str]:
    """Distinct numbered Layout folders minted in Supabase — read-only, no manual UI."""
    _ensure_supabase_session()
    if not st.session_state.get("supabase_ready"):
        return []
    table = _forensic_patterns_table()
    base = st.session_state.supabase_url
    try:
        resp = requests.get(
            f"{base}/rest/v1/{table}?select=macro_weather_layout"
            f"{_pattern_archive_query_suffix(active_only=True)}"
            f"&macro_weather_layout=not.is.null",
            headers=_supabase_rest_headers(),
            timeout=12,
        )
        if resp.ok and isinstance(resp.json(), list):
            seen: set[str] = set()
            folders: list[str] = []
            for row in resp.json():
                label = str(row.get("macro_weather_layout") or "").strip()
                if label and label not in seen:
                    seen.add(label)
                    folders.append(label)
            return sorted(folders)
    except Exception:
        pass
    return []


def _render_market_weather_banner(*, force_refresh: bool = False) -> None:
    """Market-weather footprint — layout buckets represent how the tape feels."""
    weather = core_quantum.compute_market_weather_snapshot(force_refresh=force_refresh)
    mood = str(weather.get("weather_mood") or "Scanning")
    vibe = str(weather.get("vibe_profile") or "neutral").title()
    spy = float(weather.get("spy_session_velocity_pct") or 0.0)
    vix = float(weather.get("vix_session_velocity_pct") or 0.0)
    folders = weather.get("layout_folders") or []
    folder_preview = ", ".join(folders[:4]) if folders else "none minted yet"
    st.caption(
        f"🌡️ **Market Weather:** {mood} · vibe **{vibe}** · "
        f"SPY drift {spy:+.2f}% · VIX drift {vix:+.2f}% · "
        f"Layout buckets: {folder_preview}"
    )


def _render_dynamic_layout_registry() -> None:
    """Database-minted layout folders only — zero manual selectors on the glass."""
    folders = _fetch_active_layout_folders()
    if folders:
        preview = " · ".join(folders[:16])
        extra = f" · +{len(folders) - 16} more" if len(folders) > 16 else ""
        st.caption(f"📂 **Active Layout Folders:** {preview}{extra}")
    else:
        st.caption(
            "📂 **Active Layout Folders:** awaiting first cloud mint — "
            "the math core assigns numbered folders automatically."
        )


def _purge_room2_deck_inputs() -> None:
    """Drop widget-bound keys so defaults re-bind on next render — no manual assignment."""
    st.session_state.r2_good_validation_error = False
    for key in (
        "r2_good_ticker",
        "r2_good_start_date",
        "r2_good_end_date",
        "r2_good_start_time",
        "r2_good_end_time",
        "r2_single_notes_field",
    ):
        st.session_state.pop(key, None)


def render_room2_forensic_lab():
    _apply_pending_room2_form_patches()
    _hydrate_matrix_memory_from_cloud()
    _apply_pending_room2_form_patches()
    _ensure_room2_widget_defaults()

    active_count = st.session_state.get("matrix_active_pattern_count", 0)
    trash_count = st.session_state.get("matrix_trash_vault_count", 0)
    st.markdown(
        """
        <div class="room2-hud">
            <div class="room2-kicker">Institutional Forensic Suite</div>
            <div class="room2-title">Winning-DNA Accumulation Lab</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        f"☁️ **Winning-DNA Memory (cloud-synced):** {active_count} active layouts · "
        f"{trash_count} in {RESCUE_VAULT_RETENTION_DAYS}-day Trash Vault."
    )
    _render_market_weather_banner()
    st.caption(
        "🧬 **Matrix core (Room 2):** market weather → layout buckets → strategies inside each bucket. "
        "Saves include full-day context (VIX, sectors, gap). Thin low-cap tapes use "
        "**adaptive lookback** — all valid bars up to the data edge, not a full cancel. "
        "Strategies start as **CANDIDATE** until "
        f"{core_quantum.STRATEGY_TRUST_MIN_SAMPLES}+ repeatable wins across "
        f"{core_quantum.STRATEGY_TRUST_MIN_UNIQUE_TICKERS}+ tickers promote to **TRUSTED**. "
        "Room 3 (future) = live execution."
    )
    offload = cloud_offload.offload_status()
    lanes = []
    if offload.get("cloud_compute"):
        lanes.append("Compute")
    if offload.get("hf_serverless"):
        lanes.append("HF Inference")
    if offload.get("supabase_rpc"):
        lanes.append("Supabase RPC")
    if lanes:
        st.caption(
            f"🛰️ **Distributed offload active:** {' · '.join(lanes)} — "
            "local terminal is a lightweight viewer."
        )
    elif offload.get("strict_mode"):
        st.warning(
            "Cloud offload not fully configured — set CLOUD_COMPUTE_URL, "
            "HUGGINGFACE_API_TOKEN, and Supabase keys in secrets."
        )
    _render_dynamic_layout_registry()
    decay_status = st.session_state.get("room2_alpha_decay_status")
    if decay_status:
        if decay_status.get("halt_live_execution"):
            st.error(
                f"🛑 **Live Execution HALTED** — {decay_status.get('diagnosis', 'Post-mortem review required.')} "
                f"({decay_status.get('sample_count', 0)}/{decay_status.get('window', 15)} samples · "
                f"avg margin {decay_status.get('avg_margin_pct', 0):.2f}% vs "
                f"{decay_status.get('floor_pct', 0):.2f}% floor)"
            )
        elif decay_status.get("degraded") or decay_status.get("evolving"):
            st.warning(
                f"⚠️ **Strategy Under Review:** {decay_status.get('strategy_label', '—')} · "
                f"{decay_status.get('sample_count', 0)}/{decay_status.get('window', 15)} samples · "
                f"avg margin {decay_status.get('avg_margin_pct', 0):.2f}% (floor "
                f"{decay_status.get('floor_pct', 0):.2f}%)."
            )
        else:
            st.caption(
                f"📉 Post-mortem monitor: **{decay_status.get('status', 'STABLE')}** · "
                f"{decay_status.get('sample_count', 0)}/{decay_status.get('window', 15)} "
                f"rolling samples · avg margin {decay_status.get('avg_margin_pct', 0):.2f}%."
            )

    if st.session_state.polygon_lockout:
        wait_sec = core_quantum._polygon_throttle_seconds_remaining()
        st.error(
            f"{core_quantum.THROTTLE_MESSAGE} Retry in ~{wait_sec}s "
            f"({core_quantum._polygon_calls_remaining()}/{core_quantum.POLYGON_CALLS_PER_MINUTE} calls left)."
        )

    commit_throttle_active = _room2_commit_throttle_active()
    _render_room2_commit_throttle_banner()

    processor_status = _advance_room2_processor()
    _apply_pending_room2_form_patches()

    col_left, col_right = st.columns([1.0, 1.0])

    with col_left:
        with st.container(border=True):
            st.markdown(
                '<span class="good-card"></span>'
                '<div class="deck-title">🧬 WINNING-DNA ACCUMULATION CORE</div>',
                unsafe_allow_html=True,
            )
            if st.session_state.get("r2_good_validation_error"):
                st.error(ROOM2_INVALID_INPUT_MESSAGE)
            _render_r2_adaptive_buffer_toggles("good")
            with st.form("r2_good_form_chassis", clear_on_submit=False):
                st.text_input("Pattern Ticker", key="r2_good_ticker")
                _render_r2_datalink_group("r2_good")
                st.text_input(
                    "📝 Optional Technical Context:",
                    placeholder="e.g., bounced off the VWAP breakout...",
                    key="r2_single_notes_field",
                )
                good_deploy = st.form_submit_button(
                    "🔥 COMMIT WINNING PATTERN TO INTERNET",
                    use_container_width=True,
                    disabled=commit_throttle_active,
                )
            if good_deploy and not commit_throttle_active:
                _handle_room2_deck_submit()

    with col_right:
        _render_matrix_window1_panel(processor_status=processor_status)
        _render_room2_proxy_telemetry_banners()
        _render_purgatory_shelf()

        _render_window4_conversation_wire()

    if processor_status == "running":
        st.rerun()


def render_terminal_nav() -> str:
    sidebar_width = "108px" if st.session_state.sidebar_collapsed else "340px"
    st.markdown(
        f"""
        <style>
            section[data-testid="stSidebar"] > div {{
                width: {sidebar_width} !important;
            }}
            [data-testid="stSidebar"] {{
                min-width: {sidebar_width} !important;
                max-width: {sidebar_width} !important;
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        if st.session_state.sidebar_collapsed:
            if st.button("▶ Expand", key="sidebar_collapse_toggle", use_container_width=True):
                st.session_state.sidebar_collapsed = False
                st.rerun()
            short_pick = st.radio(
                "HUB:",
                [ROOM1_SHORT, ROOM2_SHORT],
                index=0 if st.session_state.terminal_hub == ROOM1_LABEL else 1,
                label_visibility="collapsed",
                key="terminal_hub_collapsed",
            )
            st.session_state.terminal_hub = ROOM_SHORT_MAP[short_pick]
        else:
            if st.button("◀ Collapse", key="sidebar_collapse_toggle", use_container_width=True):
                st.session_state.sidebar_collapsed = True
                st.rerun()
            st.markdown(
                "<div style='font-size:11px;font-weight:700;letter-spacing:0.1em;"
                "text-transform:uppercase;color:#888;margin:4px 0 10px 2px;'>Navigation</div>",
                unsafe_allow_html=True,
            )
            room_pick = st.radio(
                "TERMINAL HUB COMMANDS:",
                [ROOM1_LABEL, ROOM2_LABEL],
                index=0 if st.session_state.terminal_hub == ROOM1_LABEL else 1,
                key="terminal_hub_expanded",
            )
            st.session_state.terminal_hub = room_pick

    return st.session_state.terminal_hub


if st.session_state.pop("_pending_chat_submit", False):
    cap = core_quantum.room1_memory_capacity_status(
        st.session_state.get("messages") or [],
        pending_user_text=st.session_state.get("text_field_buffer", ""),
    )
    if not cap.get("locked"):
        with st.spinner("Savant processing live data layers..."):
            process_chat_submission()
    else:
        st.session_state.room1_memory_locked = True

terminal_hub = render_terminal_nav()

if terminal_hub == ROOM1_LABEL:
    _render_room1_forensic_front_desk()
else:
    render_room2_forensic_lab()

