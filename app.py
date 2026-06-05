import os
import re
import statistics
import urllib.parse
import json
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import escape
from xml.etree import ElementTree

import core_quantum
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from groq import Groq

try:
    from supabase import Client, create_client
except ImportError:
    Client = None
    create_client = None

if "r2_good_ticker" not in st.session_state:
    st.session_state.r2_good_ticker = "MLGO"
if "r2_bad_ticker" not in st.session_state:
    st.session_state.r2_bad_ticker = "AAPL"
if "room2_chat_history" not in st.session_state:
    st.session_state.room2_chat_history = []
elif not isinstance(st.session_state.room2_chat_history, list):
    st.session_state.room2_chat_history = list(st.session_state.room2_chat_history)
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
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama3-8b-8192"
MACRO_DRIVERS = [("GC=F", "GOLD"), ("CL=F", "OIL"), ("^TNX", "TNX"), ("SPY", "SPY")]
ROOM2_INVALID_INPUT_MESSAGE = (
    "⚠️ INVALID INPUT: Verify your Ticker is filled out and your Timestamps match "
    "the 'HH:MM AM/PM' format exactly."
)
R2_TIMESTAMP_PATTERN = re.compile(r"^\d{1,2}:\d{2}\s+(AM|PM)$", re.IGNORECASE)
ROOM2_CLEAN_SLATE_MESSAGE = (
    "DATABASE SNAPSHOT: 100% CLEAN SLATE. No active patterns logged. "
    "All prior records moved to the 15-day Trash Vault — say 'restore my patterns' to undo."
)
RESCUE_VAULT_RETENTION_DAYS = 15
MATRIX_CHAT_LOG_TICKER = "_LAB_SESSION_"
MATRIX_CHAT_LOG_CATEGORY = "MATRIX_CHAT_LOG"
MATRIX_ENGINE_IDLE_MARKER = "ENGINE_IDLE"

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
        [data-testid="stSidebarCollapseButton"] { display: block !important; color: #FFFFFF !important; }
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
            background: #020802;
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
            min-height: 160px;
            box-shadow: inset 0 0 32px rgba(52, 199, 89, 0.06);
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
            padding: 10px;
            margin-top: 8px;
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
            padding: 10px;
            margin-top: 8px;
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
            font-size: 13px;
            line-height: 1.6;
            color: #E5E5E5;
            font-family: "SF Mono", Menlo, Monaco, Consolas, monospace;
        }
    </style>
""", unsafe_allow_html=True)

if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "current_ticker" not in st.session_state: st.session_state.current_ticker = None
if "timeframe" not in st.session_state: st.session_state.timeframe = "D"
if "text_field_buffer" not in st.session_state: st.session_state.text_field_buffer = ""
if "active_news_wire" not in st.session_state: st.session_state.active_news_wire = []
if "sector_rotation_context" not in st.session_state: st.session_state.sector_rotation_context = ""
if "data_payload_string" not in st.session_state: st.session_state.data_payload_string = ""
if "cross_asset_correlation_context" not in st.session_state: st.session_state.cross_asset_correlation_context = ""
if "institutional_accumulation_detected" not in st.session_state: st.session_state.institutional_accumulation_detected = False
if "polygon_lockout" not in st.session_state: st.session_state.polygon_lockout = False
if "room2_forensic_ticker" not in st.session_state: st.session_state.room2_forensic_ticker = ""
if "room2_quantum_report" not in st.session_state: st.session_state.room2_quantum_report = ""
if "room2_bar_count" not in st.session_state: st.session_state.room2_bar_count = 0
if "room2_text_buffer" not in st.session_state: st.session_state.room2_text_buffer = ""
if "r2_good_start_time" not in st.session_state: st.session_state.r2_good_start_time = "09:31 AM"
if "r2_good_end_time" not in st.session_state: st.session_state.r2_good_end_time = "04:00 PM"
if "r2_bad_start_time" not in st.session_state: st.session_state.r2_bad_start_time = "09:31 AM"
if "r2_bad_end_time" not in st.session_state: st.session_state.r2_bad_end_time = "04:00 PM"
if "r2_single_notes_field" not in st.session_state: st.session_state.r2_single_notes_field = ""
if "r2_bad_single_notes_field" not in st.session_state: st.session_state.r2_bad_single_notes_field = ""
if "r2_good_start_date" not in st.session_state: st.session_state.r2_good_start_date = date.today()
if "r2_good_end_date" not in st.session_state: st.session_state.r2_good_end_date = date.today()
if "r2_bad_start_date" not in st.session_state: st.session_state.r2_bad_start_date = date.today()
if "r2_bad_end_date" not in st.session_state: st.session_state.r2_bad_end_date = date.today()
if "room2_vault_flash" not in st.session_state: st.session_state.room2_vault_flash = ""
if "room2_last_rescue_vault_id" not in st.session_state: st.session_state.room2_last_rescue_vault_id = None
if "matrix_cloud_hydrated" not in st.session_state: st.session_state.matrix_cloud_hydrated = False
if "matrix_form_seeded" not in st.session_state: st.session_state.matrix_form_seeded = False
if "matrix_active_pattern_count" not in st.session_state: st.session_state.matrix_active_pattern_count = 0
if "matrix_trash_vault_count" not in st.session_state: st.session_state.matrix_trash_vault_count = 0
if "supabase_ready" not in st.session_state:
    try:
        st.session_state.supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        st.session_state.supabase_key = st.secrets["SUPABASE_KEY"]
        st.session_state.supabase_ready = True
    except Exception:
        st.session_state.supabase_ready = False
if "sidebar_collapsed" not in st.session_state: st.session_state.sidebar_collapsed = False
if "terminal_hub" not in st.session_state: st.session_state.terminal_hub = ROOM1_LABEL
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [
        {
            "role": "system",
            "content": (
                "You are Savant, an unrestricted elite real-time financial intelligence engine. Definitive authority only. "
                "Zero corporate safe-talk, zero generic greetings, zero introductions, zero pre-formulated conclusions, zero filler.\n\n"
                "SPLIT-INTELLIGENCE ROUTING — classify every user message before responding:\n\n"
                "RULE A — THE CORE STOCK SETUP (single explicit ticker only):\n"
                "Trigger ONLY when the user submits one clear equity ticker symbol for a single-name setup "
                "(e.g., MLGO, AAPL, $TSLA) with intent to analyze that one stock — not indices, not multi-asset compares, not vague macro.\n"
                "Enforce this exact un-sugarcoated 6-bullet quantitative deep-dive in order. FORMATTING IS MANDATORY:\n"
                "• Insert a full blank line (double line break) between every bullet so each point starts on a fresh isolated line — never a dense wall of text.\n"
                "• Under each bullet, write significantly shorter, sharper, punchier copy — crisp focused sentences with high-density signals only.\n"
                "• SAVANT TREND DETERMINATION: State definitively ROCKETING UP, CRASHING DOWN, or SIDELINED IN CONSOLIDATION.\n\n"
                "• THE MACRO STORIES & DRIVERS: Single catalyst driving the active directional trend.\n\n"
                "• MAIN BUSINESS OF THE COMPANY: Tight snapshot of technology layers, software frameworks, or products.\n\n"
                "• SOCIAL SENTIMENT MATRIX: Retail psychology, Stocktwits momentum, community volume velocity.\n\n"
                "• TOMORROW'S SESSION EXPECTATION: Data-backed next-session projection.\n\n"
                "• CRITICAL TRADER BULLET NOTES: Volume spikes, float traps, squeeze signals, anomalies.\n\n"
                "After all six bullets, insert one full blank line, then ONE highly detailed comprehensive executive summary paragraph "
                "at the absolute bottom. No bullets or headers after the six bullets except that final paragraph.\n\n"
                "RULE B — THE BROAD CONTEXT SHIFT (everything else):\n"
                "Instantly DROP the 6-bullet framework for: broad market questions, general updates, index or macro queries "
                "(e.g., S&P 500, RSI, sector rotation), comparative analysis (two or more symbols), follow-up causality "
                "(e.g., why did it move like that), technical deep-dives without a fresh single-ticker setup, jokes, or casual chat.\n"
                "Respond with sophisticated multi-paragraph macro-quantitative prose. Never force general topics into the 6-bullet slots. "
                "Address math, indicator trends, correlations, and cross-asset context naturally with institutional-grade complexity.\n\n"
                "MULTI-ASSET SWITCHING: When the user pivots from Rule A to Rule B (or back) in the same thread, switch modes immediately — "
                "do not carry the bullet template into Rule B and do not use Rule B prose when a new single-ticker setup is requested.\n"
                "Use injected 12L payload data when present; never invent prices or filings."
            ),
        }
    ]


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
        for item in (yf.Ticker(ticker).news or [])[:12]:
            title = item.get("title", "")
            if title:
                headlines.append(title)
    except Exception:
        pass
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
        try:
            info = yf.Ticker(sym).info or {}
            chg = info.get("regularMarketChangePercent")
            if chg is None and info.get("regularMarketPreviousClose"):
                price = info.get("regularMarketPrice", info.get("currentPrice", 0.0)) or 0.0
                prev = info.get("regularMarketPreviousClose") or 1.0
                chg = ((price - prev) / prev) * 100
            if chg is not None:
                flows.append((sym, label, float(chg)))
        except Exception:
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
    try:
        hist = yf.Ticker(symbol).history(period="2mo", interval="1d")
        if hist is None or len(hist) < periods + 1:
            return []
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        if len(closes) < periods + 1:
            return []
        velocity: list[float] = []
        for i in range(-periods, 0):
            prev = closes[i - 1]
            velocity.append(((closes[i] - prev) / prev) * 100 if prev else 0.0)
        return velocity
    except Exception:
        return []


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
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
        if hist is None or len(hist) < 10:
            return "VOL:INSUFFICIENT_HIST|VOLMOM:NORMAL|INST_ACCUM:FALSE", False
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        volumes = [float(x) for x in hist["Volume"].dropna().tolist()]
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
    """Fast yfinance read for UI metric cards — skips 12L engine on every rerun."""
    if not ticker:
        return 0.0, 0.0, "N/A", "N/A", "Unknown"
    try:
        ticker = ticker.upper()
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName", info.get("shortName", ticker))
        price = float(info.get("currentPrice", info.get("regularMarketPrice", 0.0)) or 0.0)
        prev = float(info.get("regularMarketPreviousClose", 1.0) or 1.0)
        pct = ((price - prev) / prev) * 100 if price and prev else 0.0
        raw_vol = int(info.get("volume", info.get("regularMarketVolume", 0)) or 0)
        vol = f"{raw_vol:,}" if raw_vol else "N/A"
        high = float(info.get("dayHigh", price) or price)
        low = float(info.get("dayLow", price) or price)
        vwap_val = (high + low + price) / 3 if price else 0.0
        vw_str = f"${vwap_val:.2f}" if vwap_val else "N/A"
        return price, pct, vol, vw_str, name
    except Exception:
        return 0.0, 0.0, "N/A", "N/A", ticker.upper()


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
        ytk = yf.Ticker(ticker)
        info = ytk.info or {}
        name = info.get("longName", info.get("shortName", ticker))
        price = float(info.get("currentPrice", info.get("regularMarketPrice", 0.0)) or 0.0)
        prev = float(info.get("regularMarketPreviousClose", 1.0) or 1.0)
        pct = ((price - prev) / prev) * 100 if price and prev else 0.0
        raw_vol = int(info.get("volume", info.get("regularMarketVolume", 0)) or 0)
        vol = f"{raw_vol:,}" if raw_vol else "N/A"
        high = float(info.get("dayHigh", price) or price)
        low = float(info.get("dayLow", price) or price)
        vwap_val = (high + low + price) / 3 if price else 0.0
        vw_str = f"${vwap_val:.2f}" if vwap_val else "N/A"

        st.session_state.active_news_wire = _fetch_news_wire(ticker)
        sector_ctx = _fetch_sector_rotation()
        corr_ctx = _compute_cross_asset_correlation(ticker)
        vol_ctx, inst_flag = _compute_volatility_engine(ticker, price, raw_vol, vwap_val)
        st.session_state.institutional_accumulation_detected = inst_flag
        sec_ctx = _fetch_sec_filings(ticker)
        _build_data_payload_string(
            ticker, name, price, pct, vol, vw_str,
            st.session_state.active_news_wire, sector_ctx, vol_ctx, sec_ctx, corr_ctx,
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


def _build_groq_message_stack(user_text: str, payload: str) -> list[dict]:
    system_msg = st.session_state.llm_memory[0]
    dialog = [m for m in st.session_state.llm_memory[1:] if m["role"] in ("user", "assistant")]
    recent = dialog[-3:] if len(dialog) > 3 else dialog
    groq_msgs = [
        {"role": "system", "content": f"{system_msg['content']}\n{TOKEN_GUARD}"},
        *[{"role": m["role"], "content": m["content"]} for m in recent[:-1]],
    ]
    latest = user_text
    if payload:
        latest = f"{user_text}\n[12L_DATA_PAYLOAD]{payload}[/12L_DATA_PAYLOAD]"
    groq_msgs.append({"role": "user", "content": latest})
    return groq_msgs


def process_chat_submission():
    user_text = st.session_state.text_field_buffer.strip()
    if not user_text:
        return

    new_ticker = extract_ticker(user_text)
    if new_ticker and new_ticker != st.session_state.current_ticker:
        st.session_state.current_ticker = new_ticker
        st.session_state.llm_memory = st.session_state.llm_memory[:1]

    st.session_state.chat_history.append({"speaker": "You", "text": user_text})
    st.session_state.llm_memory.append({"role": "user", "content": user_text})

    payload = ""
    if st.session_state.current_ticker:
        get_live_tape_data(st.session_state.current_ticker)
        payload = st.session_state.data_payload_string

    groq_msgs = _build_groq_message_stack(user_text, payload)
    ai_text = run_groq(groq_msgs)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_text})
    st.session_state.chat_history.append({"speaker": "Savant", "text": ai_text})
    st.session_state.text_field_buffer = ""


FORENSIC_EXPERT_SYSTEM = (
    "You are the Forensic Pattern Research Expert — the dedicated Room 2 brain layer for "
    "Savant Apprentice. Operate exclusively on validated good-file setups, toxic bad-file "
    "anomalies, 15m quantum frequency output, and operator coordinate matrices. "
    "Deliver institutional-grade forensic research: pattern classification rigor, failure-mode "
    "diagnostics, structural match interpretation, and actionable lab notes. "
    "Zero greetings, zero filler, zero generic market commentary unrelated to the forensic payload.\n\n"
    "PLAIN ENGLISH FILTER — MANDATORY:\n"
    "Eliminate all conversational fluff, overly dense academic gibberish, and long filler sentences. "
    "If the operator asks for a summary, inventory, or count (e.g., 'what patterns have you found', "
    "'how many stocks', 'list my saved setups'), you must immediately output a crisp, bulleted, "
    "numerical breakdown with zero fluff. Keep the language simple, clean, and professional. "
    "Only go into extreme mathematical or technical depth if the operator explicitly asks you for "
    "further details."
)

PATTERN_STRATEGIST_SYSTEM = (
    "You are the Savant Pattern-Mining Strategist. Read the injected live cloud pattern archive "
    "and quantum terminal telemetry. Simplify heavy math trends into plain institutional English. "
    "Explain exactly how the operator's custom forensic machine is evolving — pattern classes, "
    "volume anomalies, insider recon signals, and structural match scores. Be definitive and concise.\n\n"
    "PLAIN ENGLISH FILTER — MANDATORY:\n"
    "Eliminate all conversational fluff, overly dense academic gibberish, and long filler sentences. "
    "If the operator asks for a summary, inventory, or count (e.g., 'what patterns have you found', "
    "'how many stocks', 'list my saved setups'), you must immediately output a crisp, bulleted, "
    "numerical breakdown with zero fluff. Keep the language simple, clean, and professional. "
    "Only go into extreme mathematical or technical depth if the operator explicitly asks you for "
    "further details."
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
        parts.append("or=(state.is.null,state.eq.active)")
    return "&" + "&".join(parts)


def _purge_expired_trash_vault() -> None:
    """Permanently purge Trash Vault rows older than the retention window."""
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


def _seed_room2_form_from_pattern_row(row: dict) -> None:
    """Restore latest cloud pattern coordinates into the Room 2 input deck."""
    cat = str(row.get("pattern_category", "")).upper()
    ticker = str(row.get("ticker", "")).strip().upper()
    if not ticker:
        return
    if cat == "VALIDATED":
        prefix = "r2_good"
        notes_key = "r2_single_notes_field"
    elif cat == "TOXIC_ANOMALY":
        prefix = "r2_bad"
        notes_key = "r2_bad_single_notes_field"
    else:
        return
    st.session_state[f"{prefix}_ticker"] = ticker
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
            st.session_state.room2_chat_history = parsed
        saved_terminal = str(rows[0].get("quantum_report") or "").strip()
        if saved_terminal and MATRIX_ENGINE_IDLE_MARKER not in saved_terminal:
            st.session_state.quantum_terminal_output = saved_terminal
    except Exception:
        pass


def _hydrate_matrix_memory_from_cloud() -> None:
    """Load Matrix pattern archive + lab chat from Supabase once per session."""
    if st.session_state.get("matrix_cloud_hydrated"):
        return
    st.session_state.matrix_cloud_hydrated = True

    _purge_expired_trash_vault()
    _load_matrix_chat_from_cloud()

    latest = _fetch_latest_active_pattern_row()
    if latest:
        report = str(latest.get("quantum_report") or "").strip()
        if report:
            st.session_state.room2_quantum_report = report
            if MATRIX_ENGINE_IDLE_MARKER in st.session_state.quantum_terminal_output:
                st.session_state.quantum_terminal_output = report
        st.session_state.room2_forensic_ticker = str(latest.get("ticker") or "")
        st.session_state.room2_bar_count = int(latest.get("bar_count") or 0)
        if not st.session_state.get("matrix_form_seeded"):
            _seed_room2_form_from_pattern_row(latest)
            st.session_state.matrix_form_seeded = True

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
            f"{base}/rest/v1/{table}?select=id,ticker"
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

        row_id = rows[0]["id"]
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
            f"{base}/rest/v1/{table}?{_pattern_archive_query_suffix(active_only=True)[1:]}",
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
    ask_words = ("what", "how", "tell", "explain", "show", "describe")
    return any(w in low for w in pattern_words) and any(w in low for w in ask_words)


def _build_room2_groq_messages(user_text: str) -> list[dict]:
    context_bits = []
    if st.session_state.quantum_terminal_output:
        context_bits.append(
            f"[QUANTUM_TERMINAL]{st.session_state.quantum_terminal_output}[/QUANTUM_TERMINAL]"
        )
    if st.session_state.r2_good_ticker:
        context_bits.append(f"[GOOD_TICKER]{st.session_state.r2_good_ticker}[/GOOD_TICKER]")
    if st.session_state.r2_bad_ticker:
        context_bits.append(f"[BAD_TICKER]{st.session_state.r2_bad_ticker}[/BAD_TICKER]")
    groq_msgs = [
        {"role": "system", "content": f"{FORENSIC_EXPERT_SYSTEM}\n{TOKEN_GUARD}"},
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


def _build_pattern_strategist_messages(user_text: str) -> list[dict]:
    cloud_data = _fetch_live_cloud_patterns()
    return [
        {"role": "system", "content": f"{PATTERN_STRATEGIST_SYSTEM}\n{TOKEN_GUARD}"},
        {
            "role": "user",
            "content": (
                f"{user_text}\n"
                f"[CLOUD_PATTERNS]{cloud_data}[/CLOUD_PATTERNS]\n"
                f"[QUANTUM_TERMINAL]{st.session_state.quantum_terminal_output}[/QUANTUM_TERMINAL]"
            ),
        },
    ]


def process_room2_chat_submission():
    user_text = st.session_state.room2_text_buffer.strip()
    if not user_text:
        return
    st.session_state.room2_chat_history.append({"speaker": "You", "text": user_text})

    if _is_room2_restore_command(user_text):
        restore_msg = _restore_soft_deleted_pattern_from_vault(
            restore_all=_is_room2_restore_all_command(user_text)
        )
        st.session_state.room2_chat_history.append({"speaker": "Forensic Expert", "text": restore_msg})
        st.session_state.room2_text_buffer = ""
        _sync_matrix_chat_to_cloud()
        return

    if _is_room2_delete_command(user_text):
        if _is_room2_delete_all_command(user_text):
            trash_msg = _soft_delete_all_patterns_to_vault()
        else:
            trash_msg = _soft_delete_latest_pattern_to_vault()
            st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
            st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
        st.session_state.room2_chat_history.append({"speaker": "Forensic Expert", "text": trash_msg})
        st.session_state.room2_text_buffer = ""
        _sync_matrix_chat_to_cloud()
        return

    if _is_pattern_mining_query(user_text):
        ai_text = run_groq(_build_pattern_strategist_messages(user_text))
    else:
        ai_text = run_groq(_build_room2_groq_messages(user_text))

    st.session_state.room2_chat_history.append({"speaker": "Forensic Expert", "text": ai_text})
    st.session_state.room2_text_buffer = ""
    _sync_matrix_chat_to_cloud()


def purge_room2_conversation_and_cloud() -> None:
    """Soft-delete all active patterns into the Trash Vault and reset local lab chat."""
    trash_msg = _soft_delete_all_patterns_to_vault()
    st.session_state.room2_chat_history = [
        {"speaker": "Forensic Expert", "text": trash_msg}
    ]
    st.session_state.room2_text_buffer = ""
    _sync_matrix_chat_to_cloud()


@st.cache_resource
def init_supabase():
    if create_client is None:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception:
        return None


def _supabase_pattern_table() -> str:
    try:
        return st.secrets["SUPABASE_PATTERN_TABLE"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "pattern_context_anchor"


def _route_pattern_context_to_supabase(ticker: str, operator_context: str, quantum_report: str) -> tuple[bool, str]:
    client = init_supabase()
    if client is None:
        return False, "Supabase offline. Add SUPABASE_URL and SUPABASE_KEY to `.streamlit/secrets.toml`."
    payload = {
        "ticker": ticker.upper(),
        "operator_context": operator_context.strip(),
        "quantum_report": quantum_report,
        "bar_count": st.session_state.room2_bar_count,
        "source_room": "forensic_pattern_lab",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        client.table(_supabase_pattern_table()).insert(payload).execute()
        return True, f"Pattern context routed to `{_supabase_pattern_table()}`."
    except Exception as exc:
        return False, f"Supabase routing failed: {exc}"


def _room2_coordinate_string(date_val, time_val: str) -> str:
    if not date_val:
        return time_val.strip() if time_val else ""
    return f"{date_val} {time_val}".strip()


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


def _render_room2_proxy_telemetry_banners() -> None:
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
        f"</div>",
        unsafe_allow_html=True,
    )


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


def _validate_room2_deck(deck: str) -> bool:
    prefix = "r2_good" if deck == "good" else "r2_bad"
    ticker = st.session_state.get(f"{prefix}_ticker", "")
    start_time = st.session_state.get(f"{prefix}_start_time", "")
    end_time = st.session_state.get(f"{prefix}_end_time", "")
    return (
        _validate_room2_ticker(ticker)
        and _validate_room2_timestamp(start_time)
        and _validate_room2_timestamp(end_time)
    )


def _clear_room2_form_buffers(deck: str) -> None:
    """Reset only the target form chassis keys after a validated deploy."""
    if deck == "good":
        keys = (
            "r2_good_ticker",
            "r2_good_start_date",
            "r2_good_start_time",
            "r2_good_end_date",
            "r2_good_end_time",
            "r2_single_notes_field",
        )
    else:
        keys = (
            "r2_bad_ticker",
            "r2_bad_start_date",
            "r2_bad_start_time",
            "r2_bad_end_date",
            "r2_bad_end_time",
            "r2_bad_single_notes_field",
        )
    for key in keys:
        st.session_state.pop(key, None)


def _handle_room2_deck_submit(deck: str) -> None:
    if not _validate_room2_deck(deck):
        if deck == "good":
            st.session_state.r2_good_validation_error = True
        else:
            st.session_state.r2_bad_validation_error = True
        st.rerun()
        return
    if deck == "good":
        st.session_state.r2_good_validation_error = False
    else:
        st.session_state.r2_bad_validation_error = False
    if _deploy_room2_deck(deck):
        _clear_room2_form_buffers(deck)
    st.rerun()


def _deploy_room2_deck(deck: str) -> bool:
    """Harvest quantum math, vault payload, and lock matrix terminal output."""
    prefix = "r2_good" if deck == "good" else "r2_bad"
    ticker = str(st.session_state.get(f"{prefix}_ticker", "")).strip().upper()
    start_date = st.session_state.get(f"{prefix}_start_date")
    start_time = _normalize_room2_timestamp(
        st.session_state.get(f"{prefix}_start_time", "09:31 AM")
    ) or "09:31 AM"
    end_date = st.session_state.get(f"{prefix}_end_date")
    end_time = _normalize_room2_timestamp(
        st.session_state.get(f"{prefix}_end_time", "04:00 PM")
    ) or "04:00 PM"
    entry_coord = _room2_coordinate_string(start_date, start_time) or None
    exit_coord = _room2_coordinate_string(end_date, end_time) or None

    if deck == "good":
        pattern_category = "VALIDATED"
        notes = st.session_state.get("r2_single_notes_field", "")
        deck_tag = "VALID_PATTERN"
    else:
        pattern_category = "TOXIC_ANOMALY"
        notes = st.session_state.get("r2_bad_single_notes_field", "")
        deck_tag = "TOXIC_ANOMALY"

    feedback = notes.strip()
    if start_time or end_time:
        time_meta = f"START:{start_time} | END:{end_time} | DECK:{deck_tag}"
        feedback = f"{feedback} | {time_meta}".strip(" |") if feedback else time_meta

    try:
        data_stream = core_quantum.get_historical_15m_data(ticker)

        if core_quantum.is_pipeline_signal(data_stream, "THROTTLE"):
            st.session_state.polygon_lockout = True
            st.session_state.quantum_terminal_output = core_quantum.THROTTLE_MESSAGE
            st.session_state.room2_quantum_report = core_quantum.THROTTLE_MESSAGE
            return False

        if not core_quantum.is_usable_data_stream(data_stream):
            st.session_state.quantum_terminal_output = (
                f"⚠️ [DATALINK: NO_DATA] No 15m bars for {ticker}. "
                "Verify ticker symbol and market session dates."
            )
            st.session_state.room2_quantum_report = st.session_state.quantum_terminal_output
            return False

        quantum_report = core_quantum.calculate_quantum_frequencies(
            data_stream,
            pattern_category=pattern_category,
            ticker=ticker,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
            operator_context=notes,
            human_feedback=feedback,
        )

        st.session_state.polygon_lockout = False
        st.session_state.room2_bar_count = (
            len(data_stream) if core_quantum.is_usable_data_stream(data_stream) else 0
        )
        st.session_state.room2_quantum_report = quantum_report
        st.session_state.room2_forensic_ticker = ticker

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
        )
        ok, vault_message = core_quantum.stream_payload_to_vault(payload)
        vault_line = vault_message if ok else f"VAULT ERROR — {vault_message}"
        st.session_state.quantum_terminal_output = (
            f"{quantum_report}\n"
            f"╠════════════════════════════════════════╣\n"
            f"│ INTERNET VAULT: {vault_line[:32]:<32} │\n"
            f"╚════════════════════════════════════════╝"
        )
        st.session_state.room2_vault_flash = vault_line if ok else ""
        st.session_state.matrix_active_pattern_count = _count_cloud_pattern_rows(trash_only=False)
        st.session_state.matrix_trash_vault_count = _count_cloud_pattern_rows(trash_only=True)
        _sync_matrix_chat_to_cloud()
        return True
    except Exception as exc:
        st.session_state.quantum_terminal_output = (
            "⚠️ [PROCESSOR FAULT] Deploy halted safely.\n"
            f"│ Detail: {str(exc)[:100]} │\n"
            "│ Check: ticker letters only, times like 09:31 AM │"
        )
        st.session_state.room2_quantum_report = st.session_state.quantum_terminal_output
        return False


def _purge_room2_deck_inputs() -> None:
    """Drop widget-bound keys so defaults re-bind on next render — no manual assignment."""
    st.session_state.r2_good_validation_error = False
    st.session_state.r2_bad_validation_error = False
    for key in (
        "r2_good_ticker",
        "r2_bad_ticker",
        "r2_good_start_date",
        "r2_good_end_date",
        "r2_bad_start_date",
        "r2_bad_end_date",
        "r2_good_start_time",
        "r2_good_end_time",
        "r2_bad_start_time",
        "r2_bad_end_time",
        "r2_single_notes_field",
        "r2_bad_single_notes_field",
    ):
        st.session_state.pop(key, None)


def render_room2_forensic_lab():
    _hydrate_matrix_memory_from_cloud()

    active_count = st.session_state.get("matrix_active_pattern_count", 0)
    trash_count = st.session_state.get("matrix_trash_vault_count", 0)
    st.markdown(
        """
        <div class="room2-hud">
            <div class="room2-kicker">Institutional Forensic Suite</div>
            <div class="room2-title">Forensic Pattern Lab HUD</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        f"☁️ **Matrix Memory (cloud-synced):** {active_count} active pattern(s) · "
        f"{trash_count} in {RESCUE_VAULT_RETENTION_DAYS}-day Trash Vault · "
        "restores work on any device within the window."
    )

    if st.session_state.polygon_lockout:
        st.error(core_quantum.THROTTLE_MESSAGE)

    col_left, col_right = st.columns([1.0, 1.0])

    with col_left:
        sub_col_good, sub_col_bad = st.columns([1.0, 1.0])

        with sub_col_good:
            with st.container(border=True):
                st.markdown(
                    '<span class="good-card"></span>'
                    '<div class="deck-title">🟩 VALIDATED PATTERN TRACKING (GOOD FILES)</div>',
                    unsafe_allow_html=True,
                )
                if st.session_state.get("r2_good_validation_error"):
                    st.error(ROOM2_INVALID_INPUT_MESSAGE)
                with st.form("r2_good_form_chassis", clear_on_submit=False):
                    st.text_input("Good File Ticker", key="r2_good_ticker")
                    _render_r2_datalink_group("r2_good")
                    st.text_input(
                        "📝 Optional Technical Context:",
                        placeholder="e.g., bounced off the VWAP breakout...",
                        key="r2_single_notes_field",
                    )
                    good_deploy = st.form_submit_button(
                        "🔥 COMMIT VALID PATTERN TO INTERNET",
                        use_container_width=True,
                    )
                if good_deploy:
                    _handle_room2_deck_submit("good")

        with sub_col_bad:
            with st.container(border=True):
                st.markdown(
                    '<span class="bad-card"></span>'
                    '<div class="deck-title">🟥 TOXIC ANOMALY TRACKING (BAD FILES)</div>',
                    unsafe_allow_html=True,
                )
                if st.session_state.get("r2_bad_validation_error"):
                    st.error(ROOM2_INVALID_INPUT_MESSAGE)
                with st.form("r2_bad_form_chassis", clear_on_submit=False):
                    st.text_input("Bad File Ticker", key="r2_bad_ticker")
                    _render_r2_datalink_group("r2_bad")
                    st.text_input(
                        "📝 Optional Technical Context:",
                        placeholder="e.g., bounced off the VWAP breakout...",
                        key="r2_bad_single_notes_field",
                    )
                    bad_deploy = st.form_submit_button(
                        "🚨 COMMIT TOXIC ANOMALY TO INTERNET",
                        use_container_width=True,
                    )
                if bad_deploy:
                    _handle_room2_deck_submit("bad")

    with col_right:
        st.markdown(
            '<div class="room2-terminal-header">▸ WINDOW 1 — MATRIX REACTION PROCESSOR</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="room2-matrix-box">{escape(st.session_state.quantum_terminal_output)}</div>',
            unsafe_allow_html=True,
        )

        _render_room2_proxy_telemetry_banners()

        st.markdown(
            '<div class="room2-wire-title">💬 WINDOW 4 — FORENSIC LAB CONVERSATION WIRE</div>',
            unsafe_allow_html=True,
        )
        if not st.session_state.room2_chat_history:
            st.caption("Lab chat standing by — type plain English below.")
        else:
            for msg in st.session_state.room2_chat_history:
                safe_text = escape(msg.get("text", ""))
                if msg["speaker"] == "You":
                    st.markdown(
                        f'<div class="room2-chat-row">'
                        f'<div class="room2-speaker-operator">{msg["speaker"]}</div>'
                        f'<div class="room2-chat-body">{safe_text}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="room2-chat-row">'
                        f'<div class="room2-speaker-expert">{msg["speaker"]}</div>'
                        f'<div class="room2-chat-body-expert">{safe_text}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )

        with st.form("room2_chat_form", clear_on_submit=False):
            st.text_input(
                "Lab Input",
                key="room2_text_buffer",
                placeholder="Ask about patterns, 'delete pattern' / 'delete everything', or 'I didn't mean to delete' / 'restore all'...",
                label_visibility="collapsed",
            )
            if st.form_submit_button("Send") and st.session_state.room2_text_buffer.strip():
                st.session_state._pending_room2_chat_submit = True
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
    with st.spinner("Savant processing live data layers..."):
        process_chat_submission()

if st.session_state.pop("_pending_room2_chat_submit", False):
    with st.spinner("Forensic Pattern Research Expert processing..."):
        process_room2_chat_submission()

terminal_hub = render_terminal_nav()

if terminal_hub == ROOM1_LABEL:
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
        col_empty, col_btn_anchor = st.columns([0.7, 0.3])
        with col_btn_anchor:
            if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
                st.session_state.chat_history = []
                st.session_state.current_ticker = None
                st.session_state.text_field_buffer = ""
                st.session_state.llm_memory = st.session_state.llm_memory[:1]
                st.session_state.active_news_wire = []
                st.session_state.sector_rotation_context = ""
                st.session_state.cross_asset_correlation_context = ""
                st.session_state.institutional_accumulation_detected = False
                st.session_state.data_payload_string = ""
                st.rerun()

        if st.session_state.current_ticker:
            p, pct, v, vw, name = _fetch_tape_metrics(st.session_state.current_ticker)
            color_choice = "#34C759" if pct >= 0 else "#FF3B30"
            st.markdown(
                f"""
                <div style="background:#111;padding:12px;border-radius:6px;border:1px solid #1F1F1F;margin-bottom:15px;">
                    <div class="metric-label" style="font-size:10px;color:#555;font-weight:700;">
                        Exchange Tape Metrics — {name} ({st.session_state.current_ticker})
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

        if not st.session_state.chat_history:
            st.markdown("<div style='height: 18vh;'></div>", unsafe_allow_html=True)
            st.markdown(
                "<div style='text-align:center;color:#222;font-size:24px;font-weight:300;"
                "letter-spacing:0.04em;'>Savant Apprentice</div>",
                unsafe_allow_html=True,
            )
        else:
            for msg in st.session_state.chat_history:
                label_class = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
                st.markdown(
                    f'<div class="chat-row"><div class="speaker-label {label_class}">{msg["speaker"]}</div>'
                    f'<div class="data-content">{msg.get("text", "")}</div></div>',
                    unsafe_allow_html=True,
                )

        with st.form("chat_form", clear_on_submit=False):
            st.text_input(
                "Input",
                key="text_field_buffer",
                placeholder="Ask Savant anything... No filters active.",
                label_visibility="collapsed",
            )
            if st.form_submit_button("Send") and st.session_state.text_field_buffer.strip():
                st.session_state._pending_chat_submit = True
                st.rerun()

else:
    render_room2_forensic_lab()

