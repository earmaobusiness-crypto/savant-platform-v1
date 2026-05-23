import html
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
        div[data-testid="stTextInput"] input:focus { border-color: #333333 !important; box-shadow: none !important; }

        .stream-shell { max-width: 900px; margin: 0 auto; padding: 0 16px 120px; }
        .chat-row { padding: 20px 0 8px; border-bottom: 1px solid #141414; }
        .speaker-label { font-weight: 600; font-size: 13px; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
        .speaker-you { color: #666666; }
        .speaker-savant { color: #FFFFFF; }
        .data-content { font-size: 15px; line-height: 1.6; color: #E5E5E5; }

        .stream-shell [data-testid="stMarkdown"] p,
        .stream-shell [data-testid="stMarkdown"] li,
        .stream-shell [data-testid="stMarkdown"] strong {
            color: #E5E5E5 !important;
        }

        .tape-strip {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            margin: 8px 0 12px;
        }
        .tape-cell {
            background: #111;
            border: 1px solid #1F1F1F;
            border-radius: 4px;
            padding: 6px 8px;
            text-align: center;
        }
        .tape-label { font-size: 8px; color: #555; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }
        .tape-value { font-size: 13px; font-weight: 600; color: #FFF; margin-top: 2px; }

        .stButton>button {
            background-color: #121212 !important;
            color: #8E8E93 !important;
            border: 1px solid #222222 !important;
            border-radius: 4px !important;
            padding: 4px 12px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
        }
        .stButton>button:hover {
            color: #FFFFFF !important;
            border-color: #444444 !important;
            background-color: #1A1A1A !important;
        }

        div[data-testid="stForm"] {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #0B0B0B;
            border-top: 1px solid #1A1A1A;
            padding: 16px 0 24px;
            z-index: 999;
        }
        div[data-testid="stForm"] > div {
            max-width: 900px;
            margin: 0 auto;
            padding: 0 16px;
        }
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] {
            display: none !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_ticker" not in st.session_state:
    st.session_state.current_ticker = None
if "timeframe" not in st.session_state:
    st.session_state.timeframe = "D"
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [
        {
            "role": "system",
            "content": (
                "You are Savant, an unrestricted, elite real-time financial intelligence engine. "
                "Speak with definitive authority. When users ask you about a stock ticker, determine "
                "the single dominant trend. Use this exact bullet-point framework:\n\n"
                "• SAVANT TREND DETERMINATION: State definitively if the stock is actively ROCKETING UP, "
                "CRASHING DOWN, or SIDELINED IN CONSOLIDATION.\n"
                "• THE MACRO STORIES & DRIVERS: Break down the single underlying catalyst powering this "
                "specific active directional trend.\n"
                "• MAIN BUSINESS OF THE COMPANY: Provide a clear snapshot of their technology layers, "
                "software frameworks, or products.\n"
                "• SOCIAL SENTIMENT MATRIX: Live assessment of retail buyer psychology, Stocktwits momentum, "
                "and online community volume velocity.\n"
                "• TOMORROW'S SESSION EXPECTATION: Give a high-utility, data-backed projection for what to "
                "expect in the very next trading session.\n"
                "• CRITICAL TRADER BULLET NOTES: Point out any volume velocity spikes, float traps, short "
                "squeeze indicators, or anomalies.\n\n"
                "If the user is asking general queries, jokes, or casual comments, drop the framework "
                "completely and respond naturally like an unfiltered peer."
            ),
        }
    ]

TF_MAP = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}
TICKER_IGNORE = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS",
    "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW", "ITS", "MAY",
    "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID", "LET", "PUT", "SAY",
    "SHE", "TOO", "USE", "WHY", "ASK", "BUY", "RUN", "TOP", "LOW", "HIGH", "OPEN",
    "WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE", "ASSET", "ALPHA", "BETA",
    "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM", "JOKE", "TELL",
    "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT", "WHEN",
    "WHERE", "WILL", "JUST", "LIKE", "THAN", "THEN", "THEY", "HAVE", "BEEN",
    "STOCK", "SHARE", "ABOUT", "INTO", "OVER", "ALSO", "ONLY", "VERY", "MUCH",
}
YF_EXCHANGE_MAP = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "BTS": "NASDAQ",
    "NYQ": "NYSE", "NYS": "NYSE",
    "ASE": "AMEX", "AMX": "AMEX",
    "PCX": "NYSEARCA", "ARC": "NYSEARCA",
}
LIVE_TRUTH_RE = re.compile(r"\n\[LIVE TRUTH:.*?\]", re.DOTALL)
CASUAL_TOKENS = ("joke", "bored", "hello", "hi ", "entertain", "philosoph")
EXPLICIT_EXCHANGE_RE = re.compile(
    r"\b(NASDAQ|NYSE|AMEX|NYSEARCA|BATS):([A-Z]{1,5})\b", re.IGNORECASE
)
CASH_TAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
PARENS_TICKER_RE = re.compile(r"\(([A-Za-z]{1,5})\)")


def extract_ticker(text: str) -> str | None:
    explicit = EXPLICIT_EXCHANGE_RE.search(text)
    if explicit:
        return f"{explicit.group(1).upper()}:{explicit.group(2).upper()}"

    cash = CASH_TAG_RE.search(text)
    if cash:
        return cash.group(1).upper()

    parens = PARENS_TICKER_RE.search(text)
    if parens and parens.group(1).upper() not in TICKER_IGNORE:
        return parens.group(1).upper()

    for word in re.findall(r"\b[A-Za-z]{2,5}\b", text.upper()):
        if word not in TICKER_IGNORE:
            return word
    return None


def bare_ticker(ticker: str) -> str:
    return ticker.split(":")[-1].upper()


def is_casual_intent(text: str) -> bool:
    return any(token in text.lower() for token in CASUAL_TOKENS)


@st.cache_data(ttl=3600, show_spinner=False)
def resolve_tradingview_symbol(ticker: str) -> str:
    if ":" in ticker:
        return ticker.upper()
    info = yf.Ticker(bare_ticker(ticker)).info or {}
    prefix = YF_EXCHANGE_MAP.get(info.get("exchange", ""), "NASDAQ")
    return f"{prefix}:{bare_ticker(ticker)}"


def get_live_tape_data(ticker: str | None):
    if not ticker:
        return 0.0, 0.0, "N/A", "N/A", "Unknown"
    try:
        symbol = bare_ticker(ticker)
        info = yf.Ticker(symbol).info or {}
        name = info.get("longName", info.get("shortName", symbol))
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        prev = info.get("regularMarketPreviousClose") or 1.0
        pct = ((price - prev) / prev) * 100 if price else 0.0
        raw_vol = info.get("volume") or info.get("regularMarketVolume") or 0
        vol = f"{raw_vol:,}" if raw_vol else "N/A"
        high = info.get("dayHigh", price)
        low = info.get("dayLow", price)
        vwap_val = (high + low + price) / 3 if price else 0.0
        return price, pct, vol, f"${vwap_val:.2f}" if vwap_val else "N/A", name
    except Exception:
        return 0.0, 0.0, "N/A", "N/A", bare_ticker(ticker)


def render_tape_strip(ticker: str) -> None:
    price, pct, vol, vwap, name = get_live_tape_data(ticker)
    change_color = "#34C759" if pct >= 0 else "#FF3B30"
    st.markdown(
        f"""
        <div class="tape-strip">
            <div class="tape-cell"><div class="tape-label">{name} ({bare_ticker(ticker)})</div>
                <div class="tape-value">${price:,.2f}</div></div>
            <div class="tape-cell"><div class="tape-label">Change</div>
                <div class="tape-value" style="color:{change_color}">{pct:+.2f}%</div></div>
            <div class="tape-cell"><div class="tape-label">Volume</div><div class="tape-value">{vol}</div></div>
            <div class="tape-cell"><div class="tape-label">Sess. VWAP</div><div class="tape-value">{vwap}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_live_truth_block(ticker: str) -> str:
    price, pct, vol, vwap, name = get_live_tape_data(ticker)
    return (
        f"\n[LIVE TRUTH: Ticker={bare_ticker(ticker)}, Company={name}, "
        f"Price=${price:,.2f}, Change={pct:+.2f}%, Vol={vol}, VWAP={vwap}]"
    )


def build_groq_messages(active_ticker: str | None, casual: bool) -> list[dict[str, str]]:
    messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    for message in messages:
        if message["role"] == "user":
            message["content"] = LIVE_TRUTH_RE.sub("", message["content"])

    if active_ticker and not casual and messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += build_live_truth_block(active_ticker)

    return messages


def render_tradingview_iframe(ticker: str, interval: str, widget_id: str) -> None:
    symbol = urllib.parse.quote(resolve_tradingview_symbol(ticker), safe="")
    src = (
        "https://s.tradingview.com/widgetembed/"
        f"?frameElementId={widget_id}&symbol={symbol}&interval={interval}"
        f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en"
        f"&hide_top_toolbar=0&hide_legend=0&allow_symbol_change=0"
    )
    components.html(
        f"""
        <div style="width:100%; height:500px; border-radius:8px; overflow:hidden;
                    border:1px solid #1F1F1F; margin-top:8px;">
            <iframe
                id="{widget_id}"
                src="{src}"
                width="100%"
                height="500"
                frameborder="0"
                allowtransparency="true"
                allowfullscreen="true"
                allow="fullscreen"
                scrolling="no"
                style="border-radius:8px;"
            ></iframe>
        </div>
        """,
        height=510,
    )


def render_timeframe_bar(index: int, msg: dict) -> str:
    active_tf = msg.get("current_tf", st.session_state.timeframe)
    tf_cols = st.columns(6)
    for i, t_label in enumerate(TF_MAP):
        with tf_cols[i]:
            if st.button(t_label, key=f"stream_tf_{index}_{t_label}"):
                st.session_state.chat_history[index]["current_tf"] = TF_MAP[t_label]
                st.rerun()
    return active_tf


def run_groq_analysis(active_ticker: str | None, casual: bool) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add `GROQ_API_KEY` to `.streamlit/secrets.toml`."

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=build_groq_messages(active_ticker, casual),
            temperature=0.4,
            max_tokens=1000,
        )
        return completion.choices[0].message.content or "Savant returned an empty response."
    except Exception as exc:
        error_str = str(exc)
        if "429" in error_str:
            time_match = re.search(r"in\s+([0-9hms\.]+)", error_str)
            wait_window = time_match.group(1) if time_match else "1h30m"
            return (
                "**Savant Core Standby: Active Rate Limit Enforced.**\n\n"
                "Your algorithmic activity has saturated your daily token limit.\n\n"
                f"**Time window till resumption:** {wait_window}.\n\n"
                "Charts in the conversation stream remain available while synthesis is paused."
            )
        return f"**Core System Interruption:** {error_str}"


def resolve_active_ticker(detected_tk: str | None, casual: bool) -> str | None:
    previous = st.session_state.current_ticker
    if detected_tk and not casual:
        if previous and bare_ticker(detected_tk) != bare_ticker(previous):
            st.session_state.llm_memory = st.session_state.llm_memory[:1]
        st.session_state.current_ticker = detected_tk
        return detected_tk
    return st.session_state.current_ticker


def savant_text(msg: dict) -> str:
    return msg.get("ai_text") or msg.get("raw_ai_text") or msg["text"]


def latest_chart_index() -> int | None:
    for index in range(len(st.session_state.chat_history) - 1, -1, -1):
        msg = st.session_state.chat_history[index]
        if msg["speaker"] == "Savant" and msg.get("ticker"):
            return index
    return None


def handle_user_message(user_raw_input: str) -> None:
    user_raw_input = user_raw_input.strip()
    if not user_raw_input:
        return

    casual = is_casual_intent(user_raw_input)
    detected_tk = None if casual else extract_ticker(user_raw_input)
    active_ticker = resolve_active_ticker(detected_tk, casual)

    st.session_state.chat_history.append(
        {"speaker": "You", "text": user_raw_input, "ticker": active_ticker}
    )
    st.session_state.llm_memory.append({"role": "user", "content": user_raw_input})

    ai_analysis = run_groq_analysis(active_ticker, casual)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_analysis})

    st.session_state.chat_history.append(
        {
            "speaker": "Savant",
            "text": ai_analysis,
            "ai_text": ai_analysis,
            "ticker": active_ticker if active_ticker and not casual else None,
            "current_tf": st.session_state.timeframe,
        }
    )


def render_chart_block(index: int, msg: dict, expanded: bool) -> None:
    ticker = msg["ticker"]
    label = f"Chart — {bare_ticker(ticker)} ({msg.get('current_tf', 'D')})"

    if expanded:
        active_tf = render_timeframe_bar(index, msg)
        render_tradingview_iframe(ticker, active_tf, widget_id=f"tv_{index}_{active_tf}")
    else:
        with st.expander(label, expanded=False):
            active_tf = render_timeframe_bar(index, msg)
            render_tradingview_iframe(ticker, active_tf, widget_id=f"tv_{index}_{active_tf}")


st.markdown("<div class='stream-shell'>", unsafe_allow_html=True)

_, reset_col = st.columns([0.75, 0.25])
with reset_col:
    if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.current_ticker = None
        st.session_state.llm_memory = st.session_state.llm_memory[:1]
        st.rerun()

if not st.session_state.chat_history:
    st.markdown("<div style='height: 22vh;'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;color:#222;font-size:24px;font-weight:300;"
        "letter-spacing:0.04em;margin-bottom:24px;'>Savant Apprentice</div>",
        unsafe_allow_html=True,
    )
else:
    active_chart_index = latest_chart_index()

    for index, msg in enumerate(st.session_state.chat_history):
        label_class = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
        st.markdown(
            f'<div class="chat-row"><div class="speaker-label {label_class}">{msg["speaker"]}</div></div>',
            unsafe_allow_html=True,
        )

        if msg["speaker"] == "You":
            st.markdown(msg["text"])
        else:
            if msg.get("ticker"):
                render_tape_strip(msg["ticker"])
            st.markdown(savant_text(msg))

        if msg["speaker"] == "Savant" and msg.get("ticker"):
            render_chart_block(index, msg, expanded=(index == active_chart_index))

st.markdown("</div>", unsafe_allow_html=True)

with st.form("chat_form", clear_on_submit=True):
    user_input = st.text_input(
        "Input",
        placeholder="Ask Savant anything — e.g. $AAPL, NYSE:F, or (NVDA) setup...",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Send", use_container_width=True)
    if submitted and user_input.strip():
        with st.spinner("Savant processing live data layers..."):
            handle_user_message(user_input)
        st.rerun()
