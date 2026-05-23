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
        .chat-shell { max-width: 920px; margin: 0 auto; padding: 0 16px 200px; }
        .chat-panel [data-testid="stMarkdown"] p,
        .chat-panel [data-testid="stMarkdown"] li,
        .chat-panel [data-testid="stMarkdown"] strong { color: #E5E5E5 !important; }
        .speaker-label {
            font-weight: 600; font-size: 13px; text-transform: uppercase;
            letter-spacing: 0.1em; margin: 18px 0 6px;
        }
        .speaker-you { color: #666; }
        .speaker-savant { color: #FFF; }
        .chart-dock {
            position: fixed; bottom: 72px; left: 0; right: 0; z-index: 900;
            background: #0B0B0B; border-top: 1px solid #1A1A1A; padding: 10px 16px 12px;
        }
        .chart-dock-inner { max-width: 920px; margin: 0 auto; }
        .dock-label {
            font-size: 10px; color: #555; text-transform: uppercase;
            letter-spacing: 0.08em; font-weight: 700; margin-bottom: 6px;
        }
        .input-dock {
            position: fixed; bottom: 0; left: 0; right: 0; z-index: 950;
            background: #0B0B0B; border-top: 1px solid #141414; padding: 12px 16px 18px;
        }
        .input-dock-inner { max-width: 920px; margin: 0 auto; }
        .stButton>button {
            background: #121212 !important; color: #8E8E93 !important;
            border: 1px solid #222 !important; border-radius: 4px !important;
            font-size: 11px !important; font-weight: 600 !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

SYSTEM_PROMPT = (
    "You are Savant, an elite real-time financial intelligence engine.\n\n"
    "Follow the RESPONSE MODE instruction appended to each user message exactly.\n\n"
    "INITIAL TICKER MODE: Clean spaced bulleted list only. Max 8 bullets. One fact per line. "
    "Scan-ready: trend, price snapshot, catalyst, business one-liner, volume, session bias, risk flag.\n\n"
    "CHITCHAT MODE: Natural conversation like a sharp trading peer. Short paragraphs. "
    "No rigid frameworks. Never hide important facts.\n\n"
    "SMART COMPARE MODE: Use sections — **Shared Ground**, **Side by Side** (aligned matching metrics), "
    "**Where They Diverge** (unique differences per ticker).\n\n"
    "SENTIMENT MODE: Conversational macro take. Simple and direct."
)

MODE_HINTS = {
    "initial_ticker": (
        "[RESPONSE MODE: INITIAL TICKER SCAN] Reply with ONLY a clean, spaced bulleted list. "
        "No walls of text. Max 8 essential bullets."
    ),
    "chitchat": (
        "[RESPONSE MODE: CHITCHAT] Follow-up conversation. Talk naturally. Keep it simple but factual."
    ),
    "compare": (
        "[RESPONSE MODE: SMART COMPARE] Align matching traits side-by-side, then break down unique divergences."
    ),
    "sentiment": (
        "[RESPONSE MODE: SENTIMENT/MACRO] General market conversation. No full ticker framework."
    ),
}

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "current_ticker" not in st.session_state:
    st.session_state.current_ticker = None
if "timeframe" not in st.session_state:
    st.session_state.timeframe = "D"
if "dock_tickers" not in st.session_state:
    st.session_state.dock_tickers = []
if "dock_mode" not in st.session_state:
    st.session_state.dock_mode = "none"
if "chart_anchor_idx" not in st.session_state:
    st.session_state.chart_anchor_idx = None
if "fullscreen_ticker" not in st.session_state:
    st.session_state.fullscreen_ticker = None
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]

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
    "STOCK", "SHARE", "ABOUT", "INTO", "OVER", "ALSO", "ONLY", "VERY", "MUCH", "ME",
    "VS", "VERSUS",
}
YF_EXCHANGE_MAP = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "BTS": "NASDAQ",
    "NYQ": "NYSE", "NYS": "NYSE", "ASE": "AMEX", "AMX": "AMEX", "PCX": "NYSEARCA", "ARC": "NYSEARCA",
}
LIVE_TRUTH_RE = re.compile(r"\n(\[LIVE TRUTH:.*?\]|\[RESPONSE MODE:.*?\])", re.DOTALL)
CASUAL_TOKENS = ("joke", "bored", "hello", "hi ", "entertain", "philosoph")
COMPARE_KW = ("compare", " vs ", " versus ", "difference between", "better than", " against ")
SENTIMENT_KW = ("market sentiment", "macro", "broad market", " spy", " vix", "economy", "the fed", "interest rate")
TICKER_FILLER = {"LOOK", "AT", "SHOW", "ANALYZE", "CHECK", "TELL", "ME", "SETUP", "SCAN"}
CASH_TAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
PARENS_TICKER_RE = re.compile(r"\(([A-Za-z]{1,5})\)")


def bare_ticker(ticker: str) -> str:
    return ticker.split(":")[-1].upper()


def is_casual_intent(text: str) -> bool:
    return any(token in text.lower() for token in CASUAL_TOKENS)


def _candidate_tickers(text: str) -> list[str]:
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


def extract_all_tickers(text: str) -> list[str]:
    if is_casual_intent(text):
        return []
    return _candidate_tickers(text)


def extract_ticker(text: str) -> str | None:
    tickers = extract_all_tickers(text)
    return tickers[0] if tickers else None


def is_ticker_only_query(text: str, ticker: str) -> bool:
    bare = bare_ticker(ticker)
    words = [w for w in re.findall(r"\b[A-Z]{2,5}\b", text.upper()) if w not in TICKER_IGNORE]
    extra = [w for w in words if w != bare and w not in TICKER_FILLER]
    return len(extra) == 0


def classify_query(text: str) -> tuple[str, list[str]]:
    lower = text.lower()
    tickers = extract_all_tickers(text)

    if is_casual_intent(text):
        return "chitchat", tickers

    if len(tickers) >= 2:
        return "compare", tickers[:4]

    if any(k in lower for k in SENTIMENT_KW) and not tickers:
        return "sentiment", []

    if len(tickers) == 1 and (not st.session_state.chat_history or is_ticker_only_query(text, tickers[0])):
        return "initial_ticker", tickers

    if st.session_state.chat_history:
        return "chitchat", tickers

    if tickers:
        return "initial_ticker", tickers

    return "chitchat", []


@st.cache_data(ttl=3600, show_spinner=False)
def resolve_tradingview_symbol(ticker: str) -> str:
    if ":" in ticker:
        return ticker.upper()
    info = yf.Ticker(bare_ticker(ticker)).info or {}
    prefix = YF_EXCHANGE_MAP.get(info.get("exchange", ""), "NASDAQ")
    return f"{prefix}:{bare_ticker(ticker)}"


def get_live_tape_data(ticker: str):
    try:
        symbol = bare_ticker(ticker)
        info = yf.Ticker(symbol).info or {}
        name = info.get("longName", info.get("shortName", symbol))
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        prev = info.get("regularMarketPreviousClose") or 1.0
        pct = ((price - prev) / prev) * 100 if price else 0.0
        raw_vol = info.get("volume") or info.get("regularMarketVolume") or 0
        vol = f"{raw_vol:,}" if raw_vol else "N/A"
        return price, pct, vol, name
    except Exception:
        return 0.0, 0.0, "N/A", bare_ticker(ticker)


def build_live_truth_block(ticker: str) -> str:
    price, pct, vol, name = get_live_tape_data(ticker)
    return (
        f"\n[LIVE TRUTH: Ticker={bare_ticker(ticker)}, Company={name}, "
        f"Price=${price:,.2f}, Change={pct:+.2f}%, Vol={vol}]"
    )


def build_groq_messages(mode: str, tickers: list[str]) -> list[dict[str, str]]:
    messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    for message in messages:
        if message["role"] == "user":
            message["content"] = LIVE_TRUTH_RE.sub("", message["content"])

    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"] += f"\n{MODE_HINTS[mode]}"
        inject = tickers if mode == "compare" else ([tickers[0]] if tickers else [])
        if not inject and st.session_state.current_ticker and mode in ("chitchat", "sentiment"):
            inject = [st.session_state.current_ticker]
        for tk in inject:
            messages[-1]["content"] += build_live_truth_block(tk)

    return messages


def tv_iframe_html(ticker: str, interval: str, height: int, frame_id: str) -> str:
    symbol = urllib.parse.quote(resolve_tradingview_symbol(ticker), safe="")
    src = (
        "https://s.tradingview.com/widgetembed/"
        f"?frameElementId={frame_id}&symbol={symbol}&interval={interval}"
        f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en&allow_symbol_change=0"
    )
    return (
        f'<iframe id="{frame_id}" src="{src}" width="100%" height="{height}" frameborder="0" '
        f'allowtransparency="true" allowfullscreen="true" allow="fullscreen" scrolling="no" '
        f'style="border-radius:6px;border:1px solid #1F1F1F;"></iframe>'
    )


def render_chart_iframe(ticker: str, interval: str, height: int, frame_id: str) -> None:
    components.html(
        f'<div style="width:100%;height:{height}px;overflow:hidden;">'
        f"{tv_iframe_html(ticker, interval, height, frame_id)}</div>",
        height=height + 8,
    )


def render_fullscreen_overlay() -> None:
    tk = st.session_state.fullscreen_ticker
    if not tk:
        return
    _, close_col = st.columns([0.85, 0.15])
    with close_col:
        if st.button("✕ Close", key="close_fs", use_container_width=True):
            st.session_state.fullscreen_ticker = None
            st.rerun()
    st.markdown(f"**Full Screen — {bare_ticker(tk)}**")
    render_chart_iframe(tk, st.session_state.timeframe, 560, f"fs_{bare_ticker(tk)}")


def update_chart_dock(mode: str, tickers: list[str]) -> tuple[str, list[str]]:
    current = st.session_state.current_ticker

    if mode == "compare" and len(tickers) >= 2:
        st.session_state.dock_mode = "compare"
        st.session_state.dock_tickers = tickers
        st.session_state.current_ticker = tickers[0]
        return "compare", tickers

    if mode == "sentiment":
        st.session_state.dock_mode = "keep"
        return "keep", st.session_state.dock_tickers

    new_tk = tickers[0] if tickers else None
    if mode == "chitchat":
        if new_tk and (not current or bare_ticker(new_tk) != bare_ticker(current)):
            st.session_state.dock_mode = "single"
            st.session_state.dock_tickers = [new_tk]
            st.session_state.current_ticker = new_tk
            return "single", [new_tk]
        st.session_state.dock_mode = "keep"
        return "keep", st.session_state.dock_tickers

    if mode == "initial_ticker" and new_tk:
        st.session_state.dock_mode = "single"
        st.session_state.dock_tickers = [new_tk]
        st.session_state.current_ticker = new_tk
        return "single", [new_tk]

    st.session_state.dock_mode = "keep"
    return "keep", st.session_state.dock_tickers


def run_groq_analysis(mode: str, tickers: list[str]) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add `GROQ_API_KEY` to `.streamlit/secrets.toml`."

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=build_groq_messages(mode, tickers),
            temperature=0.35 if mode == "initial_ticker" else 0.5,
            max_tokens=900 if mode == "chitchat" else 1200,
        )
        return completion.choices[0].message.content or "Savant returned an empty response."
    except Exception as exc:
        return f"**Core System Interruption:** {exc}"


def handle_user_message(user_raw_input: str) -> None:
    user_raw_input = user_raw_input.strip()
    if not user_raw_input:
        return

    mode, tickers = classify_query(user_raw_input)
    chart_action, dock_tickers = update_chart_dock(mode, tickers)

    st.session_state.chat_history.append({"speaker": "You", "text": user_raw_input})
    st.session_state.llm_memory.append({"role": "user", "content": user_raw_input})

    ai_analysis = run_groq_analysis(mode, tickers)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_analysis})

    savant_idx = len(st.session_state.chat_history)
    st.session_state.chat_history.append(
        {
            "speaker": "Savant",
            "text": ai_analysis,
            "ai_text": ai_analysis,
            "mode": mode,
            "chart_action": chart_action,
            "chart_tickers": list(dock_tickers),
        }
    )
    if chart_action in ("single", "compare"):
        st.session_state.chart_anchor_idx = savant_idx


def process_chat_submission() -> None:
    user_text = st.session_state.get("chat_input", "").strip()
    if not user_text:
        return
    handle_user_message(user_text)
    st.session_state.chat_input = ""


st.markdown("<div class='chat-shell chat-panel'>", unsafe_allow_html=True)

_, reset_col = st.columns([0.75, 0.25])
with reset_col:
    if st.button("RESET MEMORY", key="reset_btn", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.current_ticker = None
        st.session_state.dock_tickers = []
        st.session_state.dock_mode = "none"
        st.session_state.chart_anchor_idx = None
        st.session_state.fullscreen_ticker = None
        st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]
        st.rerun()

if st.session_state.fullscreen_ticker:
    render_fullscreen_overlay()

if not st.session_state.chat_history:
    st.markdown("<div style='height:20vh;'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;color:#222;font-size:24px;font-weight:300;'>"
        "Savant Apprentice</div>",
        unsafe_allow_html=True,
    )
else:
    anchor = st.session_state.chart_anchor_idx
    for index, msg in enumerate(st.session_state.chat_history):
        label = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
        st.markdown(f'<div class="speaker-label {label}">{msg["speaker"]}</div>', unsafe_allow_html=True)
        st.markdown(msg.get("ai_text") or msg.get("text", ""))
        if index == anchor and msg.get("chart_action") in ("single", "compare"):
            tickers = msg.get("chart_tickers") or []
            if tickers:
                names = ", ".join(bare_ticker(t) for t in tickers)
                st.caption(f"Chart dock updated here — {names}")

st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.dock_tickers:
    st.markdown("<div class='chart-dock'><div class='chart-dock-inner'>", unsafe_allow_html=True)

    if st.session_state.dock_mode == "compare":
        st.markdown('<div class="dock-label">Compare — click Expand for full screen</div>', unsafe_allow_html=True)
        cols = st.columns(min(len(st.session_state.dock_tickers), 4))
        for i, tk in enumerate(st.session_state.dock_tickers[:4]):
            with cols[i]:
                st.markdown(f"**{bare_ticker(tk)}**")
                render_chart_iframe(tk, st.session_state.timeframe, 130, f"mini_{i}_{bare_ticker(tk)}")
                if st.button("Expand", key=f"exp_{i}_{bare_ticker(tk)}", use_container_width=True):
                    st.session_state.fullscreen_ticker = tk
                    st.rerun()
    elif st.session_state.dock_tickers:
        tk = st.session_state.dock_tickers[0]
        st.markdown(f'<div class="dock-label">Live Chart — {bare_ticker(tk)}</div>', unsafe_allow_html=True)
        tf_cols = st.columns(6)
        for i, label in enumerate(TF_MAP):
            with tf_cols[i]:
                if st.button(label, key=f"dock_tf_{label}"):
                    st.session_state.timeframe = TF_MAP[label]
                    st.rerun()
        render_chart_iframe(tk, st.session_state.timeframe, 280, f"dock_{bare_ticker(tk)}")
        if st.button("Full Screen", key="dock_fullscreen"):
            st.session_state.fullscreen_ticker = tk
            st.rerun()

    st.markdown("</div></div>", unsafe_allow_html=True)

st.markdown("<div class='input-dock'><div class='input-dock-inner'>", unsafe_allow_html=True)
st.text_input(
    "Input",
    placeholder="Ticker (AEHL) · follow-up · compare AAPL vs NVDA · macro sentiment...",
    label_visibility="collapsed",
    key="chat_input",
    on_change=process_chat_submission,
)
st.markdown("</div></div>", unsafe_allow_html=True)
