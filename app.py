import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import re
from groq import Groq

# 1. Premium Split-Screen UI Layout Configuration
st.set_page_config(
    page_title="Savant Apprentice",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# High-premium custom dark styling matching ChatGPT/Gemini Mac desktop tools
st.markdown("""
    <style>
        #MainMenu, footer, header {visibility: hidden;}
        div[data-testid="stSidebar"] {display: none;}
        html, body, [data-testid="stAppViewContainer"] {
            background-color: #0B0B0B !important;
            color: #E5E5E5 !important;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }
        
        /* Fixed Input Box CSS */
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
        
        /* Elegant Minimalist Top-Right Reset Button Styling */
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
    </style>
""", unsafe_allow_html=True)

# Initialize Session Tracking State Matrix Memory
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "current_ticker" not in st.session_state: st.session_state.current_ticker = None
if "timeframe" not in st.session_state: st.session_state.timeframe = "D"
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
    words = re.findall(r'\b[A-Za-z]{3,5}\b', text.upper())
    ignore = ["WHAT", "YOUR", "INFO", "MOVE", "PRICE", "TRADE", "ASSET", "ALPHA", "BETA", "THIS", "LOOK", "THAT", "THEIR", "THEM", "WITH", "FROM", "JOKE", "TELL", "GIVE", "SOME", "SHOW", "CHART", "MORE", "AGAIN", "VIEW", "PLOT"]
    for w in words:
        if w not in ignore: return w
    return None

def get_live_tape_data(ticker):
    if not ticker: return 0.0, 0.0, "N/A", "N/A", "Unknown"
    try:
        ticker = ticker.upper() # FIXED: Force ticker to uppercase to prevent exchange hallucinations
        stock = yf.Ticker(ticker)
        info = stock.info
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

# Split Canvas: Left Column Chart Panel | Right Column Chat Interface
col_chart_side, col_chat_side = st.columns([1.1, 0.9])

# --- LEFT COLUMN: STABLE TECHNIQUE TRACK PANEL ---
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
        
        # FIXED: Core widget URL pathway securely optimized to clear local browser firewall blocks
        pure_chart_url = f"https://tradingview.com{active_tk}&interval={active_tf}&theme=dark&style=1&timezone=Etc%2FUTC&locale=en"
        
        components.html(f"""
            <div style="height:620px; width:100%; border-radius:8px; overflow:hidden; border:1px solid #1F1F1F;">
                <iframe src="{pure_chart_url}" width="100%" height="620" frameborder="0" allowtransparency="true" scrolling="no"></iframe>
            </div>
        """, height=630)
    else:
        st.markdown("<div style='height: 25vh;'></div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center; color:#333; font-size:15px; font-weight:300;'>Chart display queued. Enter a stock setup query inside the single interface terminal.</div>", unsafe_allow_html=True)

# --- RIGHT COLUMN: CONVERSATION PANEL & METRIC TILES ---
with col_chat_side:
    # High Premium Upper Right Alignment for Reset Interface
    st.markdown("<div style='height: 1vh;'></div>", unsafe_allow_html=True)
    col_empty, col_btn_anchor = st.columns([0.7, 0.3])
    with col_btn_anchor:
        if st.button("RESET MEMORY", key="clean_memory_cta", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.current_ticker = None
            st.session_state.llm_memory = st.session_state.llm_memory[:1]
            st.rerun()

    if not st.session_state.chat_history:
        st.markdown("<div style='height: 18vh;'></div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; color: #222222; font-size: 24px; font-weight: 300; letter-spacing:0.04em;'>Savant Apprentice</div>", unsafe_allow_html=True)
    else:
        p, pct, v, vw, name = get_live_tape_data(st.session_state.current_ticker)
        if st.session_state.current_ticker:
            st.markdown(f"""
                <div style="background:#111; padding:12px; border-radius:6px; border:1px solid #1F1F1F; margin-bottom:15px;">
                    <div class="metric-label" style="font-size:10px; color:#555; font-weight:700;">Exchange Tape Metrics — {name} ({st.session_state.current_ticker})</div>
                    <div class="metric-grid">
                        <div class="metric-card"><div class="metric-label">Price</div><div class="metric-value">${p:,.2f}</div></div>
                        <div class="metric-card"><div class="metric-label">Change</div><div class="metric-value" style="color:{'#34C759' if pct >= 0 else '#FF3B30'}">{pct:+.2f}%</div></div>
                        <div class="metric-card"><div class="metric-label">Volume</div><div class="metric-value" style="font-size:12px;">{v}</div></div>
                        <div class="metric-card"><div class="metric-label">Sess. VWAP</div><div class="metric-value">{vw}</div></div>
