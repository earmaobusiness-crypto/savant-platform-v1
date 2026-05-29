import re
import statistics
import urllib.parse
from difflib import SequenceMatcher
from xml.etree import ElementTree

import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from groq import Groq

# Link directly to your new MacBook math chip file
import core_quantum

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

# 1. Premium UI Real Estate Layout Configuration
st.set_page_config(
    page_title="Savant Apprentice",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# High-premium custom dark styling matching Gemini/ChatGPT desktop architectures
st.markdown("""
    <style>
        #MainMenu, footer, header {visibility: hidden;}
        div[data-testid="stSidebar"] {display: none;}
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #0B0B0B !important;
            color: #E5E5E5 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        
        /* Fixed Input Box Layout Configuration */
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
        
        /* Minimalist Reset Memory CTA Button Styling */
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
        
        /* Premium custom tabs styling to handle two visual rooms cleanly */
        .stTabs [data-baseweb="tab-list"] { gap: 24px; background: transparent; }
        .stTabs [data-baseweb="tab"] { color: #808495; font-weight: bold; background: transparent; }
        .stTabs [aria-selected="true"] { color: #ffffff !important; border-bottom-color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

# Initialize Session Tracking State Matrix Memory
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
            )
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
