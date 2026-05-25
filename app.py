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
    "Eliminate conversational fluff. Maximum density output only.]"
)
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama3-8b-8192"

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
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [
        {
            "role": "system", 
            "content": (
                "You are Savant, an unrestricted, elite real-time financial intelligence engine. Speak with definitive authority. "
                "When users ask you about a stock ticker, determine the single dominant trend. Use this exact bullet-point framework:\n\n"
                "• SAVANT TREND DETERMINATION: State definitively if the stock is actively ROCKETING UP, CRASHING DOWN, or SIDELINED IN CONSOLIDATION.\n"
                "• THE MACRO STORIES & DRIVERS: Break down the single underlying catalyst powering this specific active directional trend.\n"
                "• MAIN BUSINESS OF THE COMPANY: Provide a clear snapshot of their technology layers, software frameworks, or products.\n"
                "• SOCIAL SENTIMENT MATRIX: Live assessment of retail buyer psychology, Stocktwits momentum, and online community volume velocity.\n"
                "• TOMORROW'S SESSION EXPECTATION: Give a high-utility, data-backed projection for what to expect in the very next trading session.\n"
                "• CRITICAL TRADER BULLET NOTES: Point out any volume velocity spikes, float traps, short squeeze indicators, or anomalies.\n\n"
                "If the user is asking general queries, jokes, or casual comments, drop the framework completely and respond naturally like an unfiltered peer."
            )
        }
    ]

def extract_ticker(text):
    words = re.findall(r"\b[A-Z]{3,5}\b", text)
    ignore = [
        "ARE", "WHY", "HOW", "WHEN", "CAN", "WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE",
        "ASSET", "ALPHA", "BETA", "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM",
        "JOKE", "TELL", "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT",
    ]
    cash = re.search(r"\$([A-Za-z]{1,5})\b", text)
    if cash and cash.group(1).upper() not in ignore:
        return cash.group(1).upper()
    for w in words:
        if w not in ignore:
            return w
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


def _compute_volatility_engine(ticker: str, price: float, session_vol: int) -> str:
    try:
        hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
        if hist is None or len(hist) < 10:
            return "VOL:INSUFFICIENT_HIST|VOLMOM:NORMAL"
        closes = [float(x) for x in hist["Close"].dropna().tolist()]
        volumes = [float(x) for x in hist["Volume"].dropna().tolist()]
        if len(closes) < 10:
            return "VOL:INSUFFICIENT_HIST|VOLMOM:NORMAL"
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
        return (
            f"VOL|BAND:{band}|DEV:{dev_pct:+.2f}%|20D_MEAN:{mean:.2f}|"
            f"UP:{upper:.2f}|DN:{lower:.2f}|VOLMOM:{vol_mom}|VEL_RATIO:{ratio:.2f}x"
        )
    except Exception:
        return "VOL:CALC_ERR|VOLMOM:NORMAL"


def _build_data_payload_string(
    ticker: str, name: str, price: float, pct: float, vol: str, vw: str,
    news: list[str], sector_ctx: str, vol_ctx: str, sec_ctx: str,
) -> str:
    wire = "||".join(news[:6]) if news else "NONE"
    payload = (
        f"12L|TK:{ticker}|CO:{name}|P:{price:.2f}|CHG:{pct:+.2f}%|V:{vol}|VW:{vw}|"
        f"WIRE:{wire}|{sector_ctx}|{vol_ctx}|{sec_ctx}"
    )
    st.session_state.data_payload_string = payload
    return payload


def get_live_tape_data(ticker):
    if not ticker:
        st.session_state.active_news_wire = []
        st.session_state.sector_rotation_context = ""
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
        vol_ctx = _compute_volatility_engine(ticker, price, raw_vol)
        sec_ctx = _fetch_sec_filings(ticker)
        _build_data_payload_string(
            ticker, name, price, pct, vol, vw_str,
            st.session_state.active_news_wire, sector_ctx, vol_ctx, sec_ctx,
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
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.4,
                max_tokens=1000,
            )
            return r.choices[0].message.content or "Savant returned an empty response."
        except Exception as exc:
            err = str(exc)
            if model == PRIMARY_MODEL and _groq_should_fallback(err):
                continue
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
    return "Savant returned an empty response."


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

# Split Canvas: Shorter Left Panel Charting Grid | Open Right Panel Conversational Stream
col_chart_side, col_chat_side = st.columns([1.1, 0.9])

# --- LEFT COLUMN PANEL: THE TECHNIQUE WORKSPACE ---
with col_chart_side:
    st.markdown("<div style='height: 2vh;'></div>", unsafe_allow_html=True)
    if st.session_state.current_ticker:
        active_tk = st.session_state.current_ticker
        
        tf_cols = st.columns(6)
        tfs = ["5m", "15m", "1H", "1D", "1W", "1M"]
        tf_map = {"5m":"5", "15m":"15", "1H":"60", "1D":"D", "1W":"W", "1M":"M"}
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
                <iframe src="{pure_chart_url}" width="100%" height="620" frameborder="0" allowtransparency="true" allowfullscreen="true" webkitallowfullscreen="true" scrolling="no"></iframe>
            </div>
        """, height=630)
    else:
        st.markdown("<div style='height: 25vh;'></div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center; color:#333; font-size:15px; font-weight:300;'>Chart display queued. Enter an UPPERCASE stock setup query inside the terminal.</div>", unsafe_allow_html=True)

# --- RIGHT COLUMN PANEL: NATURAL SCROLLING DIALOGUE ENGINE ---
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
            st.session_state.data_payload_string = ""
            st.rerun()

    if st.session_state.current_ticker:
        p, pct, v, vw, name = get_live_tape_data(st.session_state.current_ticker)
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
