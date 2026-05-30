import os
import re
import statistics
import urllib.parse
from datetime import datetime, timezone
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
ROOM2_SESSION_TIMES = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(9, 17)
    for minute in (0, 15, 30, 45)
    if (hour, minute) >= (9, 30) and (hour, minute) <= (16, 0)
]

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
if "room2_chat_history" not in st.session_state: st.session_state.room2_chat_history = []
if "room2_text_buffer" not in st.session_state: st.session_state.room2_text_buffer = ""
if "room2_vault_flash" not in st.session_state: st.session_state.room2_vault_flash = ""
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
    "Zero greetings, zero filler, zero generic market commentary unrelated to the forensic payload."
)


def _build_room2_groq_messages(user_text: str) -> list[dict]:
    context_bits = []
    if st.session_state.room2_quantum_report:
        context_bits.append(
            f"[QUANTUM_CORE]{st.session_state.room2_quantum_report}[/QUANTUM_CORE]"
        )
    if st.session_state.room2_forensic_ticker:
        context_bits.append(
            f"[FORENSIC_TICKER]{st.session_state.room2_forensic_ticker}[/FORENSIC_TICKER]"
        )
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


def process_room2_chat_submission():
    user_text = st.session_state.room2_text_buffer.strip()
    if not user_text:
        return
    st.session_state.room2_chat_history.append({"speaker": "You", "text": user_text})
    groq_msgs = _build_room2_groq_messages(user_text)
    ai_text = run_groq(groq_msgs)
    st.session_state.room2_chat_history.append({"speaker": "Forensic Expert", "text": ai_text})
    st.session_state.room2_text_buffer = ""


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
        return ""
    return f"{date_val} {time_val}".strip()


def _stream_room2_payload_to_vault() -> tuple[bool, str]:
    ticker = st.session_state.room2_forensic_ticker.strip().upper()
    if not ticker:
        return False, "Set a forensic ticker before streaming to the Internet Vault."
    good_date = st.session_state.get("room2_good_date")
    bad_date = st.session_state.get("room2_bad_date")
    good_time = st.session_state.get("room2_good_time", ROOM2_SESSION_TIMES[0])
    bad_time = st.session_state.get("room2_bad_time", ROOM2_SESSION_TIMES[0])
    setup_label = st.session_state.get("room2_good_setup_label", "")
    operator_notes = st.session_state.get("room2_bad_operator_notes", "")
    quantum_report = st.session_state.room2_quantum_report or "NO_QUANTUM_OUTPUT"
    payload = core_quantum.build_vault_payload(
        ticker=ticker,
        pattern_category=setup_label,
        entry_coordinate=_room2_coordinate_string(good_date, good_time),
        exit_coordinate=_room2_coordinate_string(bad_date, bad_time),
        entry_time=good_time,
        exit_time=bad_time,
        operator_notes=operator_notes,
        quantum_report=quantum_report,
        bar_count=st.session_state.room2_bar_count,
    )
    return core_quantum.stream_payload_to_vault(payload)


def render_room2_forensic_lab():
    st.markdown(
        """
        <div class="room2-hud">
            <div class="room2-kicker">Institutional Forensic Suite</div>
            <div class="room2-title">Forensic Pattern Lab HUD</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.session_state.polygon_lockout:
        st.error(core_quantum.THROTTLE_MESSAGE)

    col_left, col_right = st.columns([1.0, 1.0])

    with col_left:
        with st.container(border=True):
            st.markdown(
                '<span class="good-card"></span>'
                '<div class="deck-title">🟩 VALIDATED PATTERN TRACKING (GOOD FILES)</div>',
                unsafe_allow_html=True,
            )
            st.date_input(
                "Entry Date Coordinate",
                key="room2_good_date",
            )
            st.selectbox(
                "Entry Session Time",
                ROOM2_SESSION_TIMES,
                index=ROOM2_SESSION_TIMES.index("09:45")
                if "09:45" in ROOM2_SESSION_TIMES
                else 0,
                key="room2_good_time",
            )
            st.text_input(
                "Setup Label (Optional)",
                placeholder="Breakout, Continuation, Accumulation...",
                key="room2_good_setup_label",
            )

        with st.container(border=True):
            st.markdown(
                '<span class="bad-card"></span>'
                '<div class="deck-title">🟥 TOXIC ANOMALY TRACKING (BAD FILES)</div>',
                unsafe_allow_html=True,
            )
            st.date_input(
                "Exit / Failure Date Coordinate",
                key="room2_bad_date",
            )
            st.selectbox(
                "Exit / Failure Session Time",
                ROOM2_SESSION_TIMES,
                index=ROOM2_SESSION_TIMES.index("15:30")
                if "15:30" in ROOM2_SESSION_TIMES
                else len(ROOM2_SESSION_TIMES) - 1,
                key="room2_bad_time",
            )
            st.text_input(
                "Operator Notes (Optional)",
                placeholder="Anomaly flags, trap signals, manual corrections...",
                key="room2_bad_operator_notes",
            )

    with col_right:
        with st.container(border=True):
            st.markdown(
                '<span class="room2-core-panel"></span>'
                '<div class="room2-core-title">🧠 MACBOOK PROCESSOR FORENSIC CORE</div>',
                unsafe_allow_html=True,
            )
            default_ticker = st.session_state.room2_forensic_ticker or st.session_state.current_ticker or ""
            lab_ticker = st.text_input(
                "Forensic Symbol",
                value=default_ticker,
                placeholder="Enter ticker for 15m deep-history scan (e.g. AAPL)",
                key="room2_ticker_input",
            ).strip().upper()
            if lab_ticker:
                st.session_state.room2_forensic_ticker = lab_ticker

            if st.button("INITIATE 15M FORENSIC SCAN", key="room2_run_scan", use_container_width=True):
                if not lab_ticker:
                    st.warning("Enter a ticker symbol to run the forensic pipeline.")
                else:
                    good_date = st.session_state.get("room2_good_date")
                    bad_date = st.session_state.get("room2_bad_date")
                    good_time = st.session_state.get("room2_good_time", ROOM2_SESSION_TIMES[0])
                    bad_time = st.session_state.get("room2_bad_time", ROOM2_SESSION_TIMES[0])
                    setup_label = st.session_state.get("room2_good_setup_label", "")
                    operator_notes = st.session_state.get("room2_bad_operator_notes", "")
                    date_coords = (
                        _room2_coordinate_string(good_date, good_time) or None,
                        _room2_coordinate_string(bad_date, bad_time) or None,
                    )
                    feedback = operator_notes.strip()
                    if good_time or bad_time:
                        feedback = f"{feedback} | ENTRY_TIME:{good_time} | EXIT_TIME:{bad_time}".strip(" |")

                    with st.spinner("MacBook local processor: pulling 15m history wire..."):
                        data_stream = core_quantum.get_historical_15m_data(lab_ticker)
                        quantum_report = core_quantum.calculate_quantum_frequencies(
                            data_stream,
                            pattern_category=setup_label,
                            date_coordinates=date_coords,
                            prices=None,
                            human_feedback=feedback,
                            ticker=lab_ticker,
                        )
                    if data_stream == "THROTTLE":
                        st.session_state.polygon_lockout = True
                        st.session_state.room2_quantum_report = core_quantum.THROTTLE_MESSAGE
                    elif data_stream == "LOCKOUT":
                        st.session_state.polygon_lockout = True
                        st.session_state.room2_quantum_report = core_quantum.THROTTLE_MESSAGE
                    elif data_stream is None:
                        st.warning("No historical data returned for this symbol.")
                    else:
                        st.session_state.polygon_lockout = False
                        st.session_state.room2_bar_count = (
                            len(data_stream) if hasattr(data_stream, "__len__") else 0
                        )
                        st.session_state.room2_quantum_report = quantum_report

            if st.session_state.room2_vault_flash:
                st.markdown(
                    f'<div class="room2-vault-success">{escape(st.session_state.room2_vault_flash)}</div>',
                    unsafe_allow_html=True,
                )

            payload_text = st.session_state.room2_quantum_report or (
                "> SAVANT FORENSIC TERMINAL ONLINE\n"
                "> AWAITING 15M SCAN — MACBOOK QUANT PROCESSOR STANDING BY\n"
                "> POLYGON SHIELD: MONITORING 5 CALLS / MINUTE"
            )
            st.markdown(
                '<div class="room2-terminal-header">▸ LIVE FORENSIC TELEMETRY STREAM</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="room2-terminal-box">{escape(payload_text)}</div>',
                unsafe_allow_html=True,
            )

            if st.button("🛰️ STREAM PAYLOAD TO INTERNET VAULT", key="room2_vault_stream", use_container_width=True):
                ok, message = _stream_room2_payload_to_vault()
                if ok:
                    st.session_state.room2_vault_flash = message
                else:
                    st.session_state.room2_vault_flash = f"VAULT ERROR — {message}"
                st.rerun()

        st.markdown(
            '<div class="room2-wire-title">💬 FORENSIC LAB CONVERSATION WIRE</div>',
            unsafe_allow_html=True,
        )
        if not st.session_state.room2_chat_history:
            st.caption("No lab conversation yet — query the Forensic Pattern Research Expert below.")
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
                placeholder="Query the Forensic Pattern Research Expert...",
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

