import json
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
        .block-container {
            max-width: 960px !important;
            padding-top: 2rem !important;
            padding-bottom: 120px !important;
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
            letter-spacing: 0.1em; margin: 20px 0 8px;
        }
        .speaker-you { color: #666666; }
        .speaker-savant { color: #FFFFFF; }
        .message-turn {
            margin-bottom: 8px;
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
        div[data-testid="stForm"] {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            background: #0B0B0B !important;
            border-top: 1px solid #1A1A1A !important;
            padding: 16px 24px 24px !important;
            z-index: 999 !important;
            max-width: 960px !important;
            margin: 0 auto !important;
        }
        div[data-testid="stForm"] [data-testid="stTextInput"] {
            max-width: 960px !important;
            margin: 0 auto !important;
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
if "active_tickers" not in st.session_state:
    st.session_state.active_tickers = []
if "llm_memory" not in st.session_state:
    st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]

TF_MAP = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}
COMPARE_COLORS = ["#2962FF", "#FF6D00", "#AB47BC"]
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
MODE_HINT_RE = re.compile(r"\n\[MODE:.*?\]", re.DOTALL)
CASUAL_TOKENS = ("joke", "bored", "hello", "hi ", "entertain", "philosoph")
FOLLOWUP_SIGNALS = ("why", "how", "when", "what", "explain", "tell me", "happened", "mean", "?")
COMPARE_SIGNALS = re.compile(r"\b(vs\.?|versus|compare|compared to)\b", re.I)
CASH_TAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
PARENS_TICKER_RE = re.compile(r"\(([A-Za-z]{1,5})\)")

MODE_HINTS = {
    "initial": (
        "\n[MODE: INITIAL_TICKER — Deliver a clean, spaced bulleted scan list (max 8 bullets). "
        "No walls of text. Still hit trend, catalyst, business, volume, bias, and risk — but keep "
        "each bullet tight and instantly scannable.]"
    ),
    "chitchat": (
        "\n[MODE: CHITCHAT — Drop the rigid framework. Talk naturally like an unfiltered peer. "
        "Keep it concise but never hide important facts. Reference the active ticker if one exists.]"
    ),
    "compare": (
        "\n[MODE: SMART_COMPARE — Structure the reply as: **Shared Ground** → **Side by Side** "
        "→ **Where They Diverge**. Be direct and comparative.]"
    ),
}


def bare_ticker(ticker: str) -> str:
    return ticker.split(":")[-1].upper()


def bare_set(tickers: list[str]) -> list[str]:
    return [bare_ticker(t) for t in tickers]


def is_casual_intent(text: str) -> bool:
    return any(token in text.lower() for token in CASUAL_TOKENS)


def is_initial_ticker_query(text: str, tickers: list[str]) -> bool:
    if len(tickers) != 1:
        return False
    remainder = text.upper()
    remainder = remainder.replace(f"${bare_ticker(tickers[0])}", " ")
    remainder = remainder.replace(bare_ticker(tickers[0]), " ")
    remainder = re.sub(r"[\$(),.?!\-]", " ", remainder)
    words = [w for w in remainder.split() if w and w not in TICKER_IGNORE]
    return len(words) == 0


def classify_turn_mode(text: str, tickers: list[str], casual: bool) -> str | None:
    if casual:
        return "chitchat"
    if len(tickers) >= 2:
        return "compare"
    if tickers and COMPARE_SIGNALS.search(text):
        return "compare"
    if tickers and any(sig in text.lower() for sig in FOLLOWUP_SIGNALS):
        return "chitchat"
    if is_initial_ticker_query(text, tickers):
        return "initial"
    if not tickers and st.session_state.active_tickers:
        return "chitchat"
    return None


def extract_all_tickers(text: str) -> list[str]:
    text = text.upper()
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
    return found[:3]


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


def build_groq_messages(inject_tickers: list[str], turn_mode: str | None = None) -> list[dict[str, str]]:
    messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    for message in messages:
        if message["role"] == "user":
            message["content"] = LIVE_TRUTH_RE.sub("", message["content"])
            message["content"] = MODE_HINT_RE.sub("", message["content"])

    if messages and messages[-1]["role"] == "user":
        if turn_mode and turn_mode in MODE_HINTS:
            messages[-1]["content"] += MODE_HINTS[turn_mode]
        if inject_tickers:
            for tk in inject_tickers:
                messages[-1]["content"] += build_live_truth_block(tk)

    return messages


def render_candlestick_iframe(ticker: str, interval: str, height: int, frame_id: str) -> None:
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


def render_compare_overlay_iframe(tickers: list[str], interval: str, height: int, frame_id: str) -> None:
    """Single-frame percentage overlay for up to 3 tickers."""
    resolved = [resolve_tradingview_symbol(t) for t in tickers]
    primary_label = bare_ticker(tickers[0])
    interval_token = interval if interval in {"5", "15", "60", "D", "W", "M"} else "D"

    widget_cfg: dict = {
        "symbols": [[primary_label, f"{bare_ticker(tickers[0])}|{interval_token}"]],
        "chartOnly": True,
        "width": "100%",
        "height": "100%",
        "locale": "en",
        "colorTheme": "dark",
        "autosize": True,
        "showVolume": False,
        "hideDateRanges": True,
        "hideMarketStatus": True,
        "hideSymbolLogo": True,
        "scalePosition": "right",
        "scaleMode": "Percentage",
        "chartType": "line",
        "lineWidth": 2,
        "fontSize": "10",
        "backgroundColor": "rgba(11, 11, 11, 1)",
        "gridLineColor": "rgba(31, 31, 31, 0.6)",
        "fontColor": "rgba(229, 229, 229, 1)",
    }

    if len(resolved) == 2:
        widget_cfg["compareSymbol"] = {
            "symbol": resolved[1],
            "lineColor": COMPARE_COLORS[0],
            "lineWidth": 2,
        }
    elif len(resolved) >= 3:
        widget_cfg["compareSymbols"] = [
            {"symbol": resolved[1], "lineColor": COMPARE_COLORS[0], "lineWidth": 2},
            {"symbol": resolved[2], "lineColor": COMPARE_COLORS[1], "lineWidth": 2},
        ]

    cfg_json = json.dumps(widget_cfg)
    components.html(
        f"""
        <div style="width:100%;height:{height}px;border-radius:8px;overflow:hidden;border:1px solid #1F1F1F;">
            <div class="tradingview-widget-container" style="width:100%;height:100%;">
                <div class="tradingview-widget-container__widget" style="width:100%;height:100%;"></div>
                <script type="text/javascript"
                    src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>
                {cfg_json}
                </script>
            </div>
        </div>
        """,
        height=height + 8,
    )


def render_message_chart(tickers: list[str], interval: str, height: int, frame_id: str) -> None:
    if len(tickers) == 1:
        render_candlestick_iframe(tickers[0], interval, height, frame_id)
    else:
        render_compare_overlay_iframe(tickers, interval, height, frame_id)


def run_groq_analysis(inject_tickers: list[str], casual: bool, turn_mode: str | None) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Security Core Offline. Add GROQ_API_KEY to `.streamlit/secrets.toml`."

    try:
        client = Groq(api_key=st.secrets["GROQ_API_KEY"])
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=build_groq_messages(inject_tickers if not casual else [], turn_mode),
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
                "Charts already embedded in your conversation stream remain operational."
            )
        return f"Core System Interruption: {error_str}"


def reset_groq_context_for_new_assets() -> None:
    st.session_state.llm_memory = st.session_state.llm_memory[:1]


def should_spawn_chart(tickers: list[str], casual: bool) -> tuple[bool, list[str]]:
    """Only mint a new inline chart row when a brand-new asset set is requested."""
    if casual or not tickers:
        return False, []

    chart_tickers = tickers[:3]
    active = bare_set(st.session_state.active_tickers)

    if len(chart_tickers) == 1:
        if bare_ticker(chart_tickers[0]) in active:
            return False, []
        return True, chart_tickers

    if sorted(bare_set(chart_tickers)) == sorted(active):
        return False, []
    return True, chart_tickers


def resolve_inject_tickers(tickers: list[str], casual: bool, spawn_chart: bool, chart_tickers: list[str]) -> list[str]:
    if casual:
        return st.session_state.active_tickers[:] if st.session_state.active_tickers else []

    if spawn_chart:
        reset_groq_context_for_new_assets()
        st.session_state.active_tickers = chart_tickers
        return chart_tickers

    if tickers:
        return st.session_state.active_tickers[:] if st.session_state.active_tickers else tickers[:3]

    return st.session_state.active_tickers[:]


def handle_user_message(user_raw_input: str) -> None:
    user_raw_input = user_raw_input.strip()
    if not user_raw_input:
        return

    casual = is_casual_intent(user_raw_input)
    tickers = [] if casual else extract_all_tickers(user_raw_input)
    turn_mode = classify_turn_mode(user_raw_input, tickers, casual)
    spawn_chart, chart_tickers = should_spawn_chart(tickers, casual)
    inject_tickers = resolve_inject_tickers(tickers, casual, spawn_chart, chart_tickers)

    st.session_state.chat_history.append({"speaker": "You", "text": user_raw_input})
    st.session_state.llm_memory.append({"role": "user", "content": user_raw_input})

    ai_analysis = run_groq_analysis(inject_tickers, casual, turn_mode)
    st.session_state.llm_memory.append({"role": "assistant", "content": ai_analysis})

    savant_turn: dict = {
        "speaker": "Savant",
        "text": ai_analysis,
        "ai_text": ai_analysis,
    }
    if spawn_chart:
        savant_turn["chart_tickers"] = chart_tickers
        savant_turn["current_tf"] = "D"
        savant_turn["msg_id"] = f"msg_{len(st.session_state.chat_history)}"

    st.session_state.chat_history.append(savant_turn)


# ── CONTINUOUS GEMINI-STYLE CHAT STREAM ──────────────────────────────────────
st.markdown("<div class='chat-panel'>", unsafe_allow_html=True)

_, reset_col = st.columns([0.75, 0.25])
with reset_col:
    if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.active_tickers = []
        st.session_state.llm_memory = [{"role": "system", "content": SYSTEM_PROMPT}]
        st.rerun()

if not st.session_state.chat_history:
    st.markdown("<div style='height:18vh;'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div style='text-align:center;color:#222;font-size:26px;font-weight:300;"
        "letter-spacing:0.04em;'>Savant Apprentice</div>",
        unsafe_allow_html=True,
    )
else:
    for idx, msg in enumerate(st.session_state.chat_history):
        label_class = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
        st.markdown(
            f'<div class="speaker-label {label_class}">{msg["speaker"]}</div>',
            unsafe_allow_html=True,
        )

        if msg["speaker"] == "Savant" and msg.get("chart_tickers"):
            chart_tickers = msg["chart_tickers"]
            interval = msg.get("current_tf", "D")
            msg_id = msg.get("msg_id", f"msg_{idx}")
            labels = ", ".join(bare_ticker(t) for t in chart_tickers)

            col_text, col_chart = st.columns([1.05, 0.95], gap="medium")
            with col_text:
                st.markdown(msg.get("ai_text") or msg.get("text", ""))

            with col_chart:
                st.markdown(
                    f'<div style="font-size:10px;color:#555;text-transform:uppercase;'
                    f'letter-spacing:0.08em;font-weight:700;margin-bottom:6px;">'
                    f"Locked Chart — {labels}</div>",
                    unsafe_allow_html=True,
                )
                tf_cols = st.columns(6)
                for i, t_label in enumerate(TF_MAP):
                    with tf_cols[i]:
                        if st.button(t_label, key=f"tf_{msg_id}_{t_label}"):
                            st.session_state.chat_history[idx]["current_tf"] = TF_MAP[t_label]
                            st.rerun()
                render_message_chart(
                    chart_tickers,
                    interval,
                    340,
                    f"chart_{msg_id}_{interval}",
                )
        else:
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
