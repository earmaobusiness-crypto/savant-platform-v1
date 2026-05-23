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
        div[data-testid="stTextInput"] input:focus {
            border-color: #333333 !important;
            box-shadow: none !important;
        }
        .chat-panel [data-testid="stMarkdown"] p,
        .chat-panel [data-testid="stMarkdown"] li,
        .chat-panel [data-testid="stMarkdown"] strong {
            color: #E5E5E5 !important;
        }
        .speaker-label {
            font-weight: 600; font-size: 13px; text-transform: uppercase;
            letter-spacing: 0.1em; margin: 16px 0 6px;
        }
        .speaker-you { color: #666666; }
        .speaker-savant { color: #FFFFFF; }
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
        .metric-label {
            font-size: 8px; color: #555555; text-transform: uppercase;
            letter-spacing: 0.05em; font-weight: 700;
        }
        .metric-value {
            font-size: 14px; font-weight: 600; color: #FFFFFF; margin-top: 2px;
        }
        .stButton>button {
            background-color: #121212 !important;
            color: #8E8E93 !important;
            border: 1px solid #222222 !important;
            border-radius: 4px !important;
            padding: 4px 10px !important;
            font-size: 11px !important;
            font-weight: 600 !important;
        }
        .stButton>button:hover {
            color: #FFFFFF !important;
            border-color: #444444 !important;
            background-color: #1A1A1A !important;
        }
        div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] {
            display: none !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

SYSTEM_PROMPT = (
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
)

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_ticker" not in st.session_state:
    st.session_state.current_ticker = None
if "compare_tickers" not in st.session_state:
    st.session_state.compare_tickers = []
if "panel_mode" not in st.session_state:
    st.session_state.panel_mode = "single"
if "timeframe" not in st.session_state:
    st.session_state.timeframe = "D"
if "fullscreen_ticker" not in st.session_state:
    st.session_state.fullscreen_ticker = None
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]

TF_MAP = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}
TICKER_IGNORE = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "WAS",
    "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW", "ITS", "MAY",
    "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID", "LET", "PUT", "SAY",
    "SHE", "TOO", "USE", "WHY", "WHEN", "ASK", "BUY", "RUN", "TOP", "LOW", "HIGH",
    "WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE", "ASSET", "ALPHA", "BETA",
    "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM", "JOKE", "TELL",
    "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT",
    "WHERE", "WILL", "JUST", "LIKE", "THAN", "THEN", "THEY", "HAVE", "BEEN",
    "STOCK", "SHARE", "ABOUT", "INTO", "OVER", "ALSO", "ONLY", "VERY", "MUCH", "ME",
    "VS", "VERSUS", "OPEN",
}
YF_EXCHANGE_MAP = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "BTS": "NASDAQ",
    "NYQ": "NYSE", "NYS": "NYSE", "ASE": "AMEX", "AMX": "AMEX", "PCX": "NYSEARCA", "ARC": "NYSEARCA",
}
LIVE_TRUTH_RE = re.compile(r"\n\[LIVE TRUTH:.*?\]", re.DOTALL)
CASUAL_TOKENS = ("joke", "bored", "hello", "hi ", "entertain", "philosoph")
CASH_TAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
PARENS_TICKER_RE = re.compile(r"\(([A-Za-z]{1,5})\)")


def bare_ticker(ticker: str) -> str:
    return ticker.split(":")[-1].upper()


def is_casual_intent(text: str) -> bool:
    return any(token in text.lower() for token in CASUAL_TOKENS)


def extract_all_tickers(text: str) -> list[str]:
    if is_casual_intent(text):
        return []

    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        key = bare_ticker(raw)
        if key not in TICKER_IGNORE and key not in seen:
            seen.add(key)
            found.append(raw.upper() if ":" in raw else key)

    for match in re.finditer(r"\b(NASDAQ|NYSE|AMEX|NYSEARCA|BATS):([A-Za-z]{1,5})\b", text, re.I):
        add(f"{match.group(1).upper()}:{match.group(2).upper()}")
    for match in CASH_TAG_RE.finditer(text):
        add(match.group(1).upper())
    for match in PARENS_TICKER_RE.finditer(text):
        add(match.group(1).upper())
    for word in re.findall(r"\b[A-Za-z]{2,5}\b", text.upper()):
        if word not in TICKER_IGNORE:
            add(word)
    return found


def extract_ticker(text: str) -> str | None:
    tickers = extract_all_tickers(text)
    return tickers[0] if tickers else None


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


def build_live_truth_block(ticker: str) -> str:
    price, pct, vol, vwap, name = get_live_tape_data(ticker)
    return (
        f"\n[LIVE TRUTH: Ticker={bare_ticker(ticker)}, Company={name}, "
        f"Price=${price:,.2f}, Change={pct:+.2f}%, Vol={vol}, VWAP={vwap}]"
    )


def build_groq_messages(inject_tickers: list[str]) -> list[dict[str, str]]:
    messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    for message in messages:
        if message["role"] == "user":
            message["content"] = LIVE_TRUTH_RE.sub("", message["content"])

    if inject_tickers and messages and messages[-1]["role"] == "user":
        for tk in inject_tickers:
            messages[-1]["content"] += build_live_truth_block(tk)

    return messages


def render_tradingview_iframe(ticker: str, interval: str, height: int, frame_id: str) -> None:
    symbol = urllib.parse.quote(resolve_tradingview_symbol(ticker), safe="")
    src = (
        "https://s.tradingview.com/widgetembed/"
        f"?frameElementId={frame_id}&symbol={symbol}&interval={interval}"
        f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en&allow_symbol_change=0"
    )
    components.html(
        f"""
        <div style="width:100%;height:{height}px;border-radius:8px;overflow:hidden;border:1px solid #1F1F1F;">
            <iframe id="{frame_id}" src="{src}" width="100%" height="{height}" frameborder="0"
                allowtransparency="true" allowfullscreen="true" webkitallowfullscreen="true"
                mozallowfullscreen="true" allow="fullscreen" scrolling="no"
                style="border-radius:8px;"></iframe>
        </div>
        """,
        height=height + 8,
    )


def run_groq_analysis(inject_tickers: list[str], casual: bool) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add GROQ_API_KEY to `.streamlit/secrets.toml`."

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=build_groq_messages(inject_tickers if not casual else []),
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
                "⚠️ **Savant Core Standby: Active Rate Limit Enforced.**\n\n"
                "Your algorithmic activity has saturated your daily limit of 100,000 baseline tokens.\n\n"
                f"• **Time Window Till Resumption:** **{wait_window}** exact remaining.\n\n"
                "The text synthesis brain is currently locked in safety standby. "
                "Your active left panel TradingView workspace remains operational for charting executions."
            )
        return f"Core System Interruption: {error_str}"


def reset_groq_context_for_new_assets() -> None:
    st.session_state.llm_memory = st.session_state.llm_memory[:1]


def update_chart_and_context(tickers: list[str], casual: bool) -> list[str]:
    """Swap chart only on new assets. Reset Groq metric context on new ticker(s)."""
    current = st.session_state.current_ticker
    inject: list[str] = []

    if casual:
        if st.session_state.current_ticker:
            inject = [st.session_state.current_ticker]
        return inject

    if len(tickers) >= 2:
        new_bare = [bare_ticker(t) for t in tickers]
        current_compare = [bare_ticker(t) for t in st.session_state.compare_tickers]
        if new_bare != current_compare or st.session_state.panel_mode != "compare":
            reset_groq_context_for_new_assets()
            st.session_state.panel_mode = "compare"
            st.session_state.compare_tickers = tickers
            st.session_state.current_ticker = tickers[0]
        return tickers

    if len(tickers) == 1:
        new_tk = tickers[0]
        if not current or bare_ticker(new_tk) != bare_ticker(current):
            reset_groq_context_for_new_assets()
            st.session_state.panel_mode = "single"
            st.session_state.compare_tickers = []
            st.session_state.current_ticker = new_tk
        inject = [new_tk]
        return inject

    if st.session_state.current_ticker:
        inject = [st.session_state.current_ticker]
    return inject


def handle_user_message(user_raw_input: str) -> None:
    user_raw_input = user_raw_input.strip()
    if not user_raw_input:
        return

    casual = is_casual_intent(user_raw_input)
    tickers = [] if casual else extract_all_tickers(user_raw_input)
    inject_tickers = update_chart_and_context(tickers, casual)

    st.session_state.chat_history.append({"speaker": "You", "text": user_raw_input})
    st.session_state.llm_memory.append({"role": "user", "content": user_raw_input})

    ai_analysis = run_groq_analysis(inject_tickers, casual)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_analysis})
    st.session_state.chat_history.append(
        {"speaker": "Savant", "text": ai_analysis, "ai_text": ai_analysis}
    )


# ── FIXED SPLIT-SCREEN: [1.1 chart | 0.9 chat] ───────────────────────────────
col_chart, col_chat = st.columns([1.1, 0.9])

with col_chart:
    st.markdown("<div style='height:1vh;'></div>", unsafe_allow_html=True)

    if st.session_state.fullscreen_ticker:
        tk = st.session_state.fullscreen_ticker
        if st.button("✕ Close Full Screen", key="close_fs", use_container_width=True):
            st.session_state.fullscreen_ticker = None
            st.rerun()
        render_tradingview_iframe(tk, st.session_state.timeframe, 560, f"fs_{bare_ticker(tk)}")

    elif st.session_state.panel_mode == "compare" and st.session_state.compare_tickers:
        st.markdown(
            '<div style="font-size:11px;color:#555;text-transform:uppercase;'
            'letter-spacing:0.08em;font-weight:700;margin-bottom:8px;">Compare Charts</div>',
            unsafe_allow_html=True,
        )
        row = st.columns(min(len(st.session_state.compare_tickers), 2))
        for i, tk in enumerate(st.session_state.compare_tickers[:4]):
            with row[i % 2]:
                st.markdown(f"**{bare_ticker(tk)}**")
                render_tradingview_iframe(tk, st.session_state.timeframe, 170, f"cmp_{i}_{bare_ticker(tk)}")
                if st.button("Expand", key=f"exp_{bare_ticker(tk)}_{i}", use_container_width=True):
                    st.session_state.fullscreen_ticker = tk
                    st.rerun()

    elif st.session_state.current_ticker:
        tk = st.session_state.current_ticker.upper()
        st.markdown(
            f'<div style="font-size:11px;color:#555;text-transform:uppercase;'
            f'letter-spacing:0.08em;font-weight:700;margin-bottom:8px;">'
            f"Live Chart — {bare_ticker(tk)}</div>",
            unsafe_allow_html=True,
        )
        tf_cols = st.columns(6)
        for i, t_label in enumerate(TF_MAP):
            with tf_cols[i]:
                if st.button(t_label, key=f"panel_tf_{t_label}"):
                    st.session_state.timeframe = TF_MAP[t_label]
                    st.rerun()
        render_tradingview_iframe(tk, st.session_state.timeframe, 500, f"panel_{bare_ticker(tk)}")
        if st.button("Full Screen", key="panel_fullscreen", use_container_width=True):
            st.session_state.fullscreen_ticker = tk
            st.rerun()

    else:
        st.markdown("<div style='height:18vh;'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='text-align:center;color:#333;font-size:14px;font-weight:300;'>"
            "Chart display queued. Enter a stock setup query inside the chat terminal."
            "</div>",
            unsafe_allow_html=True,
        )

with col_chat:
    st.markdown("<div class='chat-panel'>", unsafe_allow_html=True)

    _, reset_col = st.columns([0.7, 0.3])
    with reset_col:
        if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.current_ticker = None
            st.session_state.compare_tickers = []
            st.session_state.panel_mode = "single"
            st.session_state.fullscreen_ticker = None
            st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]
            st.rerun()

    if st.session_state.current_ticker and st.session_state.panel_mode == "single":
        p, pct, v, vw, name = get_live_tape_data(st.session_state.current_ticker)
        st.markdown(
            f"""
            <div style="background:#111;padding:12px;border-radius:6px;border:1px solid #1F1F1F;margin-bottom:12px;">
                <div class="metric-label" style="font-size:10px;color:#555;font-weight:700;">
                    Exchange Tape Metrics — {name} ({bare_ticker(st.session_state.current_ticker)})
                </div>
                <div class="metric-grid">
                    <div class="metric-card"><div class="metric-label">Price</div>
                        <div class="metric-value">${p:,.2f}</div></div>
                    <div class="metric-card"><div class="metric-label">Change</div>
                        <div class="metric-value" style="color:{'#34C759' if pct >= 0 else '#FF3B30'}">{pct:+.2f}%</div></div>
                    <div class="metric-card"><div class="metric-label">Volume</div>
                        <div class="metric-value" style="font-size:12px;">{v}</div></div>
                    <div class="metric-card"><div class="metric-label">Sess. VWAP</div>
                        <div class="metric-value">{vw}</div></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if not st.session_state.chat_history:
        st.markdown("<div style='height:12vh;'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='text-align:center;color:#222;font-size:22px;font-weight:300;"
            "letter-spacing:0.04em;'>Savant Apprentice</div>",
            unsafe_allow_html=True,
        )
    else:
        chat_box = st.container(height=420)
        with chat_box:
            for msg in st.session_state.chat_history:
                label_class = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
                st.markdown(
                    f'<div class="speaker-label {label_class}">{msg["speaker"]}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(msg.get("ai_text") or msg.get("text", ""))

    with st.form("chat_form", clear_on_submit=True):
        user_text = st.text_input(
            "Input",
            placeholder="Ask Savant anything... No filters active.",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Send")
        if submitted and user_text.strip():
            with st.spinner("Savant processing live data layers..."):
                handle_user_message(user_text.strip())

    st.markdown("</div>", unsafe_allow_html=True)
