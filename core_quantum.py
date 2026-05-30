import datetime
import requests
import streamlit as st
import yfinance as yf

try:
    import pandas as pd
except ImportError:
    pd = None


def get_historical_15m_data(ticker):
    """
    The Dual-Bridge Pipeline Rule: Fetches precise 15-minute historical charts.
    - Under 60 Days: Uses infinite-speed yfinance wire for free.
    - 60 Days to 2 Years: Switches to Polygon/Massive API key with a 5-call/min lockout banner.
    """
    ticker_clean = str(ticker).strip().upper()
    now = datetime.datetime.now()
    cutoff_date = now - datetime.timedelta(days=59)

    # TRACK 1: UNDER 60 DAYS (yfinance infinite-speed wire)
    try:
        df_yf = yf.download(ticker_clean, period="60d", interval="15m")
        if not df_yf.empty:
            return df_yf
    except Exception:
        pass  # Fallback seamlessly to Track 2 if Track 1 hits a gap

    # TRACK 2: 60 DAYS TO 2 YEARS (Polygon/Massive Core API Key)
    try:
        api_key = st.secrets["POLYGON_API_KEY"]
        start_date = (now - datetime.timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker_clean}/range/15/minute/{start_date}/{end_date}?adjusted=true&sort=asc&apiKey={api_key}"
        response = requests.get(url, timeout=15).json()

        if "results" in response:
            return response["results"]
        if response.get("status") == "ERROR" and "max requests" in response.get("error", "").lower():
            st.session_state["polygon_lockout"] = True
            return "LOCKOUT"
    except Exception:
        return None


def _supabase_table_name() -> str:
    try:
        return st.secrets["SUPABASE_PATTERN_TABLE"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "forensic_patterns"


def _normalize_prices(prices):
    if not prices:
        return None, None
    if isinstance(prices, (list, tuple)) and len(prices) >= 2:
        return float(prices[0]), float(prices[1])
    return None, None


def _normalize_date_coordinates(date_coordinates):
    if not date_coordinates:
        return None, None
    if isinstance(date_coordinates, (list, tuple)) and len(date_coordinates) >= 2:
        return str(date_coordinates[0]), str(date_coordinates[1])
    return None, None


def _series_from_data_stream(data_stream):
    if data_stream is None or data_stream == "LOCKOUT":
        return None
    if pd is not None and isinstance(data_stream, pd.DataFrame) and not data_stream.empty:
        close_col = "Close" if "Close" in data_stream.columns else data_stream.columns[-1]
        series = data_stream[close_col].astype(float).dropna()
        if isinstance(series.index, pd.MultiIndex):
            series.index = series.index.get_level_values(-1)
        return series
    if isinstance(data_stream, list) and data_stream:
        closes = [float(bar.get("c", bar.get("close", 0))) for bar in data_stream if bar.get("c") or bar.get("close")]
        if closes:
            return pd.Series(closes) if pd is not None else closes
    return None


def _local_pattern_math(data_stream, pattern_category, date_coordinates, prices):
    """
    Permanent pattern categorization math — 100% local on Mac silicon, zero cloud cost.
    """
    entry_date, exit_date = _normalize_date_coordinates(date_coordinates)
    entry_price, exit_price = _normalize_prices(prices)
    series = _series_from_data_stream(data_stream)

    amplitude = 0.0
    pearson_r = 0.0
    bar_count = 0
    trend_bias = "NEUTRAL"

    if series is not None:
        if pd is not None and isinstance(series, pd.Series):
            bar_count = len(series)
            returns = series.pct_change().dropna()
            if len(series) >= 2:
                amplitude = float((series.max() - series.min()) / max(series.iloc[-1], 1e-9) * 100)
            if len(returns) >= 3:
                benchmark = returns.expanding().mean().dropna()
                aligned = returns.loc[benchmark.index]
                if len(aligned) >= 3 and aligned.std() > 0 and benchmark.std() > 0:
                    pearson_r = float(aligned.corr(benchmark))
            delta = float(series.iloc[-1] - series.iloc[0])
            if delta > 0:
                trend_bias = "BULLISH"
            elif delta < 0:
                trend_bias = "BEARISH"
        elif isinstance(series, list):
            bar_count = len(series)
            if bar_count >= 2:
                amplitude = float((max(series) - min(series)) / max(series[-1], 1e-9) * 100)
                delta = series[-1] - series[0]
                trend_bias = "BULLISH" if delta > 0 else "BEARISH" if delta < 0 else "NEUTRAL"

    category = (pattern_category or "UNCLASSIFIED").strip().upper()
    category_weights = {
        "BREAKOUT": 1.08,
        "REVERSAL": 1.04,
        "CONTINUATION": 1.06,
        "DISTRIBUTION": 0.98,
        "ACCUMULATION": 1.02,
    }
    category_factor = category_weights.get(category, 1.0)
    structural_score = min(
        99,
        max(
            52,
            int(
                62
                + (abs(pearson_r) * 18)
                + min(amplitude, 12)
                + (6 if trend_bias != "NEUTRAL" else 0)
            )
            * category_factor,
        ),
    )

    if entry_price and exit_price and entry_price > 0:
        realized_move = ((exit_price - entry_price) / entry_price) * 100
    else:
        realized_move = None

    quantum_report = (
        f"MacBook Quant Chip | Category: {category} | Bars: {bar_count} | "
        f"Wave Amplitude: {amplitude:.2f}% | Pearson r: {pearson_r:.3f} | "
        f"Trend Bias: {trend_bias} | Structural Match: {structural_score}%"
    )
    if realized_move is not None:
        quantum_report += f" | Coordinate Move: {realized_move:.2f}%"

    return {
        "pattern_category": category,
        "entry_coordinate": entry_date,
        "exit_coordinate": exit_date,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "match_probability": structural_score,
        "quantum_report": quantum_report,
        "bar_count": bar_count,
        "wave_amplitude_pct": round(amplitude, 4),
        "pearson_r": round(pearson_r, 4),
        "trend_bias": trend_bias,
        "realized_move_pct": round(realized_move, 4) if realized_move is not None else None,
    }


def _anchor_payload_to_supabase(payload: dict) -> tuple[bool, str]:
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        supabase_key = st.secrets["SUPABASE_KEY"]
    except Exception:
        return False, "Supabase offline. Add SUPABASE_URL and SUPABASE_KEY to `.streamlit/secrets.toml`."

    table = _supabase_table_name()
    try:
        resp = requests.post(
            f"{supabase_url}/rest/v1/{table}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=[payload],
            timeout=12,
        )
        if resp.ok:
            return True, f"Cloud anchor synchronized — `{table}` committed for {payload.get('ticker', 'UNKNOWN')}."
        return False, f"Cloud upload failed: {resp.status_code} {resp.text}"
    except Exception as exc:
        return False, f"Cloud upload failed: {exc}"


def calculate_quantum_frequencies(
    data_stream,
    pattern_category="",
    date_coordinates=None,
    prices=None,
    human_feedback="",
    ticker="",
):
    """
    Runs permanent pattern categorization math locally on Mac silicon, builds the
    forensic payload, and anchors it to Supabase when credentials are present.

    Args:
        data_stream: 15m OHLC dataframe or Polygon results list.
        pattern_category: Operator pattern class (Breakout, Reversal, etc.).
        date_coordinates: (entry_date, exit_date) coordinate pair.
        prices: (entry_price, exit_price) anchor prices.
        human_feedback: Operator manual context corrections.
        ticker: Symbol anchor for the cloud row.
    """
    if data_stream is None or data_stream == "LOCKOUT":
        return "System Sidelined: Awaiting Data Pipeline Clear"

    math_block = _local_pattern_math(data_stream, pattern_category, date_coordinates, prices)

    resolved_ticker = (
        str(ticker).strip().upper()
        or str(st.session_state.get("room2_forensic_ticker", "")).strip().upper()
        or str(st.session_state.get("current_ticker", "")).strip().upper()
    )
    feedback = (human_feedback or st.session_state.get("room2_operator_context", "")).strip()

    payload = {
        "ticker": resolved_ticker or "UNKNOWN",
        "pattern_category": math_block["pattern_category"],
        "entry_coordinate": math_block["entry_coordinate"],
        "exit_coordinate": math_block["exit_coordinate"],
        "entry_price": math_block["entry_price"],
        "exit_price": math_block["exit_price"],
        "match_probability": math_block["match_probability"],
        "operator_context": feedback,
        "quantum_report": math_block["quantum_report"],
        "bar_count": math_block["bar_count"],
        "wave_amplitude_pct": math_block["wave_amplitude_pct"],
        "pearson_r": math_block["pearson_r"],
        "trend_bias": math_block["trend_bias"],
        "realized_move_pct": math_block["realized_move_pct"],
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_room": "forensic_pattern_lab",
    }

    should_anchor = bool(resolved_ticker and resolved_ticker != "UNKNOWN" and feedback)
    if should_anchor:
        ok, cloud_message = _anchor_payload_to_supabase(payload)
        if ok:
            return f"{math_block['quantum_report']} | {cloud_message}"
        return f"{math_block['quantum_report']} | {cloud_message}"

    return math_block["quantum_report"]
