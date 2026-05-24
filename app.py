import re
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from groq import Groq

st.set_page_config(
    page_title="Savant Apprentice",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
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
        .chat-row { padding: 16px 0; border-bottom: 1px solid #141414; }
        .speaker-label { font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
        .speaker-you { color: #666666; }
        .speaker-savant { color: #FFFFFF; }
        .data-content { font-size: 15px; line-height: 1.6; color: #E5E5E5; }
        .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 12px 0; }
        .metric-card { background: #111111; border: 1px solid #1F1F1F; border-radius: 4px; padding: 6px 10px; text-align: center; }
        .metric-label { font-size: 8px; color: #555555; text-transform: uppercase; font-weight: 700; }
        .metric-value { font-size: 14px; font-weight: 600; color: #FFFFFF; margin-top: 2px; }
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

SYSTEM_PROMPT = (
    "You are Savant, an unrestricted, elite real-time financial intelligence engine. Speak with definitive authority. "
    "When users ask you about a stock ticker, determine the single dominant trend. Use this exact bullet-point framework:\n\n"
    "• SAVANT TREND DETERMINATION: State definitively if the stock is actively ROCKETING UP, "
    "CRASHING DOWN, or SIDELINED IN CONSOLIDATION.\n"
    "• THE MACRO STORIES & DRIVERS: Break down the single underlying catalyst powering this specific active directional trend.\n"
    "• MAIN BUSINESS OF THE COMPANY: Provide a clear snapshot of their technology layers, software frameworks, or products.\n"
    "• SOCIAL SENTIMENT MATRIX: Live assessment of retail buyer psychology, Stocktwits momentum, "
    "and online community volume velocity.\n"
    "• TOMORROW'S SESSION EXPECTATION: Give a high-utility, data-backed projection for what to expect in the very next trading session.\n"
    "• CRITICAL TRADER BULLET NOTES: Point out any volume velocity spikes, float traps, short squeeze indicators, or anomalies.\n\n"
    "If the user is asking general queries, jokes, or casual comments, drop the framework completely and respond naturally like an unfiltered peer."
)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_ticker" not in st.session_state:
    st.session_state.current_ticker = None
if "timeframe" not in st.session_state:
    st.session_state.timeframe = "D"
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]

TICKER_IGNORE = {
    "WHY", "HOW", "WHEN", "CAN", "WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE", "ASSET",
    "ALPHA", "BETA", "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM", "JOKE", "TELL",
    "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT", "THE", "AND", "FOR",
}
TF_MAP = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}


def extract_ticker(text: str) -> str | None:
    cash = re.search(r"\$([A-Za-z]{1,5})\b", text)
    if cash:
        return cash.group(1).upper()
    solo = re.match(r"^[\$]?([A-Za-z]{2,5})$", text.strip())
    if solo and solo.group(1).upper() not in TICKER_IGNORE:
        return solo.group(1).upper()
    for word in re.findall(r"\b[A-Za-z]{2,5}\b", text.upper()):
        if word not in TICKER_IGNORE:
            return word
    return None


def get_live_tape_data(ticker):
    if not ticker:
        return 0.0, 0.0, "N/A", "N/A", "Unknown"
    try:
        ticker = ticker.upper()
        info = yf.Ticker(ticker).info or {}
        name = info.get("longName", info.get("shortName", ticker))
        price = info.get("currentPrice", info.get("regularMarketPrice", 0.0))
        prev = info.get("regularMarketPreviousClose", 1.0)
        pct = ((price - prev) / prev) * 100 if price else 0.0
        raw_vol = info.get("volume", info.get("regularMarketVolume", 0))
        vol = f"{raw_vol:,}" if raw_vol else "N/A"
        high = info.get("dayHigh", price)
        low = info.get("dayLow", price)
        vwap_val = (high + low + price) / 3 if price else 0.0
        return price, pct, vol, f"${vwap_val:.2f}" if vwap_val else "N/A", name
    except Exception:
        return 0.0, 0.0, "N/A", "N/A", ticker


def render_chart(ticker: str, interval: str) -> None:
    symbol = urllib.parse.quote(f"NASDAQ:{ticker.upper()}", safe="")
    src = (
        f"https://s.tradingview.com/widgetembed/?symbol={symbol}&interval={interval}"
        f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en&allow_symbol_change=0"
    )
    components.html(
        f'<iframe src="{src}" width="100%" height="620" frameborder="0" '
        f'allowfullscreen="true" webkitallowfullscreen="true" allow="fullscreen" '
        f'style="border:1px solid #1F1F1F;border-radius:8px;"></iframe>',
        height=630,
    )


def run_groq(messages: list[dict]) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add GROQ_API_KEY to `.streamlit/secrets.toml`."
    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        r = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.4,
            max_tokens=1000,
        )
        return r.choices[0].message.content or "Savant returned an empty response."
    except Exception as exc:
        err = str(exc)
        if "429" in err:
            m = re.search(r"in\s+([0-9hms\.]+)", err)
            return f"Rate limit — retry in **{m.group(1) if m else '1h30m'}**."
        return f"Core System Interruption: {err}"


def process_chat_submission(user_text: str) -> None:
    user_text = user_text.strip()
    if not user_text:
        return

    new_ticker = extract_ticker(user_text)
    if new_ticker and new_ticker != st.session_state.current_ticker:
        st.session_state.current_ticker = new_ticker
        st.session_state.llm_memory = st.session_state.llm_memory[:1]

    st.session_state.chat_history.append({"speaker": "You", "text": user_text})
    st.session_state.llm_memory.append({"role": "user", "content": user_text})

    groq_msgs = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    if st.session_state.current_ticker and groq_msgs[-1]["role"] == "user":
        p, pct, vol, vw, name = get_live_tape_data(st.session_state.current_ticker)
        groq_msgs[-1]["content"] += (
            f"\n[LIVE TRUTH: Ticker={st.session_state.current_ticker}, Company={name}, "
            f"Price=${p:,.2f}, Change={pct:+.2f}%, Vol={vol}, VWAP={vw}]"
        )

    ai_text = run_groq(groq_msgs)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_text})
    st.session_state.chat_history.append({"speaker": "Savant", "text": ai_text})


col_chart_side, col_chat_side = st.columns([1.1, 0.9])

with col_chart_side:
    if st.session_state.current_ticker:
        tf_cols = st.columns(6)
        for i, label in enumerate(TF_MAP):
            with tf_cols[i]:
                if st.button(label, key=f"panel_tf_{label}"):
                    st.session_state.timeframe = TF_MAP[label]
                    st.rerun()
        render_chart(st.session_state.current_ticker, st.session_state.timeframe)
    else:
        st.markdown("<div style='height:25vh;'></div>", unsafe_allow_html=True)
        st.caption("Enter a ticker in chat to load the chart.")

with col_chat_side:
    _, reset_col = st.columns([0.7, 0.3])
    with reset_col:
        if st.button("RESET MEMORY", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.current_ticker = None
            st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]
            st.rerun()

    if st.session_state.current_ticker:
        p, pct, v, vw, name = get_live_tape_data(st.session_state.current_ticker)
        pct_color = "#34C759" if pct >= 0 else "#FF3B30"
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
                        <div class="metric-value" style="color:{pct_color}">{pct:+.2f}%</div></div>
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
        st.markdown("<h2 style='color:#222;text-align:center;margin-top:18vh'>Savant Apprentice</h2>",
                      unsafe_allow_html=True)
    else:
        for msg in st.session_state.chat_history:
            cls = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
            st.markdown(
                f'<div class="chat-row"><div class="speaker-label {cls}">{msg["speaker"]}</div>'
                f'<div class="data-content">{msg.get("text", "")}</div></div>',
                unsafe_allow_html=True,
            )

    with st.form("chat_form", clear_on_submit=True):
        user_text = st.text_input(
            "Input",
            placeholder="Ask Savant anything...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send")
        if submitted and user_text.strip():
            with st.spinner("Savant processing live data layers..."):
                process_chat_submission(user_text.strip())
