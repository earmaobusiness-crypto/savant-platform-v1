import re
import urllib.parse

import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from groq import Groq

st.set_page_config(page_title="Savant Apprentice", page_icon="🔮", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    div[data-testid="stSidebar"] {display: none;}
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0B0B0B !important; color: #E5E5E5 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    div[data-testid="stTextInput"] input {
        background-color: #1A1A1A !important; color: #FFF !important;
        border: 1px solid #2A2A2A !important; border-radius: 999px !important;
        padding: 14px 24px !important; font-size: 16px !important;
    }
    .speaker-label { font-weight: 600; font-size: 13px; text-transform: uppercase;
        letter-spacing: 0.1em; margin: 16px 0 6px; }
    .speaker-you { color: #666; } .speaker-savant { color: #FFF; }
    .metric-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; margin: 12px 0; }
    .metric-card { background: #111; border: 1px solid #1F1F1F; border-radius: 4px; padding: 6px 10px; text-align: center; }
    .metric-label { font-size: 8px; color: #555; text-transform: uppercase; font-weight: 700; }
    .metric-value { font-size: 14px; font-weight: 600; color: #FFF; margin-top: 2px; }
    div[data-testid="stForm"] button[data-testid="stFormSubmitButton"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

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

TICKER_IGNORE = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HOW", "WHY", "WHEN",
    "SEE", "LOOK", "TALK", "STUFF", "WHAT", "THIS", "THAT", "WITH", "FROM", "HAVE", "WILL",
    "JUST", "LIKE", "THEY", "THEM", "YOUR", "WERE", "BEEN", "ABOUT", "INTO", "OVER", "ALSO",
    "ONLY", "VERY", "MUCH", "ME", "VS", "VERSUS", "STOCK", "SHARE", "CHART", "PRICE", "MOVE",
    "INFO", "TELL", "GIVE", "SHOW", "STOP", "WORD", "HELP", "PLEASE", "YES", "NO", "OK",
}
TF_MAP = {"5m": "5", "15m": "15", "1H": "60", "1D": "D", "1W": "W", "1M": "M"}
YF_EX = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NYQ": "NYSE", "ASE": "AMEX"}
LIVE_TRUTH_RE = re.compile(r"\n\[LIVE TRUTH:.*?\]", re.DOTALL)

for key, val in {
    "chat_history": [], "active_tickers": [], "timeframe": "D",
    "text_field_buffer": "", "llm_memory": [{"role": "system", "content": SYSTEM_PROMPT}],
}.items():
    if key not in st.session_state:
        st.session_state[key] = val


def bare(t: str) -> str:
    return t.split(":")[-1].upper()


def extract_tickers(text: str) -> list[str]:
    """Only explicit symbols — no blind word scan."""
    if re.search(r"not a (stock|ticker)|stop looking up", text, re.I):
        st.session_state.active_tickers = []
        st.session_state.llm_memory = st.session_state.llm_memory[:1]
        return []

    found, seen = [], set()

    def add(sym: str, force: bool = False) -> None:
        s = bare(sym)
        if s in seen or (not force and s in TICKER_IGNORE):
            return
        seen.add(s)
        found.append(sym.upper() if ":" in sym else s)

    for m in re.finditer(r"\b(NASDAQ|NYSE|AMEX):([A-Za-z]{1,5})\b", text, re.I):
        add(f"{m.group(1).upper()}:{m.group(2).upper()}", True)
    for m in re.finditer(r"\$([A-Za-z]{1,5})\b", text):
        add(m.group(1), True)
    for m in re.finditer(r"\(([A-Za-z]{1,5})\)", text):
        add(m.group(1))
    for m in re.finditer(
        r"\b(?:stock|ticker|symbol|look at|analyze)\s+[\$]?([A-Za-z]{1,5})\b", text, re.I
    ):
        add(m.group(1))

    if re.search(r"\b(vs|versus|compare)\b", text, re.I):
        for seg in re.split(r"\b(?:vs\.?|versus)\b", text, flags=re.I):
            solo = re.match(r"^[\$]?([A-Za-z]{2,5})$", seg.strip())
            if solo:
                add(solo.group(1))
            for m in re.finditer(r"\$([A-Za-z]{1,5})\b", seg):
                add(m.group(1), True)

    solo = re.match(r"^[\$]?([A-Za-z]{2,5})$", text.strip())
    if solo:
        add(solo.group(1))

    return found[:3]


@st.cache_data(ttl=3600, show_spinner=False)
def tv_symbol(ticker: str) -> str:
    if ":" in ticker:
        return ticker.upper()
    info = yf.Ticker(bare(ticker)).info or {}
    return f"{YF_EX.get(info.get('exchange', ''), 'NASDAQ')}:{bare(ticker)}"


def tape(ticker: str):
    try:
        info = yf.Ticker(bare(ticker)).info or {}
        name = info.get("longName", bare(ticker))
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
        prev = info.get("regularMarketPreviousClose") or 1.0
        pct = ((price - prev) / prev) * 100 if price else 0.0
        vol = info.get("volume") or info.get("regularMarketVolume") or 0
        h, l = info.get("dayHigh", price), info.get("dayLow", price)
        vwap = (h + l + price) / 3 if price else 0.0
        return price, pct, f"{vol:,}" if vol else "N/A", f"${vwap:.2f}", name
    except Exception:
        return 0.0, 0.0, "N/A", "N/A", bare(ticker)


def live_truth(ticker: str) -> str:
    p, pct, vol, vw, name = tape(ticker)
    return (
        f"\n[LIVE TRUTH: Ticker={bare(ticker)}, Company={name}, "
        f"Price=${p:,.2f}, Change={pct:+.2f}%, Vol={vol}, VWAP={vw}]"
    )


def groq_messages(inject: list[str]) -> list[dict]:
    msgs = [{"role": m["role"], "content": m["content"]} for m in st.session_state.llm_memory]
    for m in msgs:
        if m["role"] == "user":
            m["content"] = LIVE_TRUTH_RE.sub("", m["content"])
    if inject and msgs and msgs[-1]["role"] == "user":
        for tk in inject:
            msgs[-1]["content"] += live_truth(tk)
    return msgs


def ask_groq(inject: list[str]) -> str:
    if "GROQ_API_KEY" not in st.secrets:
        return "Add GROQ_API_KEY to `.streamlit/secrets.toml`."
    try:
        r = Groq(api_key=st.secrets["GROQ_API_KEY"]).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=groq_messages(inject),
            temperature=0.4,
            max_tokens=1000,
        )
        return r.choices[0].message.content or "Empty response."
    except Exception as e:
        err = str(e)
        if "429" in err:
            wait = re.search(r"in\s+([0-9hms\.]+)", err)
            return f"⚠️ Rate limit — retry in **{wait.group(1) if wait else '1h30m'}**."
        return f"Error: {err}"


def render_chart(ticker: str, interval: str) -> None:
    sym = urllib.parse.quote(tv_symbol(ticker), safe="")
    src = (
        f"https://s.tradingview.com/widgetembed/?symbol={sym}&interval={interval}"
        f"&theme=dark&style=1&timezone=Etc%2FUTC&locale=en&allow_symbol_change=0"
    )
    components.html(
        f'<iframe src="{src}" width="100%" height="500" frameborder="0" '
        f'allowfullscreen="true" webkitallowfullscreen="true" allow="fullscreen" '
        f'style="border:1px solid #1F1F1F;border-radius:8px;"></iframe>',
        height=508,
    )


def process_chat(text: str) -> None:
    text = text.strip()
    if not text:
        return

    tickers = extract_tickers(text)
    new_assets = tickers and [bare(t) for t in tickers] != [bare(t) for t in st.session_state.active_tickers]

    if new_assets:
        st.session_state.llm_memory = st.session_state.llm_memory[:1]
        st.session_state.active_tickers = tickers[:3]

    inject = st.session_state.active_tickers if st.session_state.active_tickers else []

    st.session_state.chat_history.append({"speaker": "You", "text": text})
    st.session_state.llm_memory.append({"role": "user", "content": text})
    reply = ask_groq(inject if tickers or inject else [])
    st.session_state.llm_memory.append({"role": "assistant", "content": reply})
    st.session_state.chat_history.append({"speaker": "Savant", "text": reply})


# ── Layout: chart left | chat right ──────────────────────────────────────────
col_chart, col_chat = st.columns([1.1, 0.9])

with col_chart:
    if st.session_state.active_tickers:
        tk = st.session_state.active_tickers[0]
        label = ", ".join(bare(t) for t in st.session_state.active_tickers)
        st.caption(f"Live Chart — {label}")
        cols = st.columns(6)
        for i, lbl in enumerate(TF_MAP):
            with cols[i]:
                if st.button(lbl, key=f"tf_{lbl}"):
                    st.session_state.timeframe = TF_MAP[lbl]
                    st.rerun()
        render_chart(tk, st.session_state.timeframe)
    else:
        st.markdown("<div style='height:20vh'></div>", unsafe_allow_html=True)
        st.caption("Enter a ticker in chat →")

with col_chat:
    if st.button("RESET MEMORY"):
        for k, v in {"chat_history": [], "active_tickers": [], "text_field_buffer": "",
                     "llm_memory": [{"role": "system", "content": SYSTEM_PROMPT}]}.items():
            st.session_state[k] = v
        st.rerun()

    if len(st.session_state.active_tickers) == 1:
        p, pct, vol, vw, name = tape(st.session_state.active_tickers[0])
        st.markdown(f"""
        <div style="background:#111;padding:12px;border-radius:6px;border:1px solid #1F1F1F;margin-bottom:12px;">
            <div class="metric-label">Exchange Tape — {name} ({bare(st.session_state.active_tickers[0])})</div>
            <div class="metric-grid">
                <div class="metric-card"><div class="metric-label">Price</div><div class="metric-value">${p:,.2f}</div></div>
                <div class="metric-card"><div class="metric-label">Change</div>
                    <div class="metric-value" style="color:{'#34C759' if pct>=0 else '#FF3B30'}">{pct:+.2f}%</div></div>
                <div class="metric-card"><div class="metric-label">Volume</div><div class="metric-value">{vol}</div></div>
                <div class="metric-card"><div class="metric-label">VWAP</div><div class="metric-value">{vw}</div></div>
            </div>
        </div>""", unsafe_allow_html=True)

    if not st.session_state.chat_history:
        st.markdown("<h2 style='color:#222;text-align:center;margin-top:12vh'>Savant Apprentice</h2>",
                      unsafe_allow_html=True)
    else:
        for msg in st.session_state.chat_history:
            cls = "speaker-you" if msg["speaker"] == "You" else "speaker-savant"
            st.markdown(f'<div class="{cls} speaker-label">{msg["speaker"]}</div>', unsafe_allow_html=True)
            st.markdown(msg["text"])

    with st.form("chat_form", clear_on_submit=False):
        st.text_input("Input", key="text_field_buffer", placeholder="Ask Savant...",
                      label_visibility="collapsed")
        submitted = st.form_submit_button("Send")
        if submitted and st.session_state.text_field_buffer.strip():
            with st.spinner("Processing..."):
                process_chat(st.session_state.text_field_buffer.strip())
            st.session_state.text_field_buffer = ""
            st.rerun()
