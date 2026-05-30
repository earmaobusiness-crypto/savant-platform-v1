import core_quantum
import os
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

st.set_page_config(
    page_title="Savant Apprentice",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
    <style>
        #MainMenu, footer, header {visibility: hidden;}
        div[data-testid="stSidebar"] {display: none;}
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
    top, bottom = flows[0], flows[-1]
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


if st.session_state.pop("_pending_chat_submit", False):
    with st.spinner("Savant processing live data layers..."):
        process_chat_submission()

tab_room1, tab_room2 = st.tabs(
    ["🏛️ Room 1: Real-Time Front Desk", "🔮 Room 2: Forensic Pattern Lab"]
)

with tab_room1:
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

with tab_room2:
    st.markdown(
        "<div style='color:#888;font-size:12px;font-weight:700;letter-spacing:0.08em;"
        "text-transform:uppercase;margin-bottom:12px;'>Forensic Pattern Lab — 15m Deep History</div>",
        unsafe_allow_html=True,
    )
    if st.session_state.polygon_lockout:
        st.error("Polygon API lockout active — 5 calls/min limit reached. Standby before rescanning.")

    lab_ticker = st.text_input(
        "Forensic ticker",
        value=st.session_state.current_ticker or "",
        placeholder="Enter ticker for 15m pattern scan (e.g. AAPL)",
        key="room2_forensic_ticker",
    ).strip().upper()

    if st.button("RUN FORENSIC SCAN", key="room2_run_scan", use_container_width=True):
        if not lab_ticker:
            st.warning("Enter a ticker symbol to run the forensic pipeline.")
        else:
            with st.spinner("Pulling 15m history and running quantum frequency matrix..."):
                data_stream = core_quantum.get_historical_15m_data(lab_ticker)
                quantum_report = core_quantum.calculate_quantum_frequencies(data_stream)
            if data_stream == "LOCKOUT":
                st.session_state.polygon_lockout = True
                st.error("Polygon rate limit hit. Forensic pipeline sidelined.")
            elif data_stream is None:
                st.warning("No historical data returned for this symbol.")
            else:
                st.session_state.polygon_lockout = False
                bars = len(data_stream) if hasattr(data_stream, "__len__") else "N/A"
                st.success(f"Forensic scan complete — {lab_ticker} | bars loaded: {bars}")
                st.markdown(f"**Quantum Output:** {quantum_report}")

