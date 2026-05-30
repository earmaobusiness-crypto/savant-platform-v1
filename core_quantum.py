import datetime
import re
import statistics
import time
from xml.etree import ElementTree

import requests
import streamlit as st
import yfinance as yf

try:
    import pandas as pd
except ImportError:
    pd = None

POLYGON_CALLS_PER_MINUTE = 5
THROTTLE_MESSAGE = (
    "⚠️ NETWORK THROTTLING SHIELD ACTIVE: 0 API CALLS REMAINING. COOLING DOWN PROCESSOR."
)
COMPRESSED_VARIANCE_THRESHOLD = 1.25
INSTITUTIONAL_SURGE_MULTIPLIER = 4.0
SEC_HEADERS = {"User-Agent": "SavantApprentice earmaobusiness@gmail.com"}
BARS_PER_SESSION = {"5m": 78, "15m": 26, "1h": 7, "1d": 1}


def _init_polygon_rate_monitor() -> None:
    now = time.time()
    if "polygon_calls_remaining" not in st.session_state:
        st.session_state.polygon_calls_remaining = POLYGON_CALLS_PER_MINUTE
    if "polygon_rate_window_start" not in st.session_state:
        st.session_state.polygon_rate_window_start = now
    elapsed = now - float(st.session_state.polygon_rate_window_start)
    if elapsed >= 60:
        st.session_state.polygon_calls_remaining = POLYGON_CALLS_PER_MINUTE
        st.session_state.polygon_rate_window_start = now
        st.session_state.polygon_lockout = False


def _polygon_calls_remaining() -> int:
    _init_polygon_rate_monitor()
    return int(st.session_state.polygon_calls_remaining)


def _consume_polygon_call() -> bool:
    _init_polygon_rate_monitor()
    if st.session_state.polygon_calls_remaining <= 0:
        st.session_state.polygon_lockout = True
        return False
    st.session_state.polygon_calls_remaining -= 1
    if st.session_state.polygon_calls_remaining <= 0:
        st.session_state.polygon_lockout = True
    return True


def _supabase_table_name() -> str:
    try:
        return st.secrets["SUPABASE_PATTERN_TABLE"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "forensic_patterns"


def _normalize_prices(prices):
    if not prices:
        return None, None
    if isinstance(prices, (list, tuple)) and len(prices) >= 2:
        try:
            entry = float(prices[0]) if prices[0] is not None else None
            exit_p = float(prices[1]) if prices[1] is not None else None
            return entry, exit_p
        except (TypeError, ValueError):
            return None, None
    return None, None


def _normalize_date_coordinates(date_coordinates):
    if not date_coordinates:
        return None, None
    if isinstance(date_coordinates, (list, tuple)) and len(date_coordinates) >= 2:
        return str(date_coordinates[0]), str(date_coordinates[1])
    return None, None


def _series_from_data_stream(data_stream):
    if data_stream is None or data_stream in ("LOCKOUT", "THROTTLE"):
        return None
    if pd is not None and isinstance(data_stream, pd.DataFrame) and not data_stream.empty:
        close_col = "Close" if "Close" in data_stream.columns else data_stream.columns[-1]
        series = data_stream[close_col].astype(float).dropna()
        if isinstance(series.index, pd.MultiIndex):
            series.index = series.index.get_level_values(-1)
        return series
    if isinstance(data_stream, list) and data_stream:
        closes = [
            float(bar.get("c", bar.get("close", 0)))
            for bar in data_stream
            if bar.get("c") or bar.get("close")
        ]
        if closes:
            return pd.Series(closes) if pd is not None else closes
    return None


def _volume_series_from_data_stream(data_stream):
    if data_stream is None or data_stream in ("LOCKOUT", "THROTTLE"):
        return None
    if pd is not None and isinstance(data_stream, pd.DataFrame) and not data_stream.empty:
        vol_col = "Volume" if "Volume" in data_stream.columns else None
        if vol_col:
            return data_stream[vol_col].astype(float).dropna()
    if isinstance(data_stream, list) and data_stream:
        vols = [float(bar.get("v", bar.get("volume", 0))) for bar in data_stream if bar.get("v") or bar.get("volume")]
        if vols:
            return pd.Series(vols) if pd is not None else vols
    return None


def _wave_amplitude_pct(series) -> float:
    if series is None:
        return 0.0
    if pd is not None and isinstance(series, pd.Series) and len(series) >= 2:
        return float((series.max() - series.min()) / max(float(series.iloc[-1]), 1e-9) * 100)
    if isinstance(series, list) and len(series) >= 2:
        return float((max(series) - min(series)) / max(series[-1], 1e-9) * 100)
    return 0.0


def _is_compressed_variance(data_stream) -> bool:
    series = _series_from_data_stream(data_stream)
    if series is None:
        return False
    amplitude = _wave_amplitude_pct(series)
    if amplitude < COMPRESSED_VARIANCE_THRESHOLD:
        return True
    if pd is not None and isinstance(series, pd.Series):
        returns = series.pct_change().dropna()
        if len(returns) >= 5 and float(returns.std()) < 0.0025:
            return True
    return False


def _xml_local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _twenty_day_volume_baseline(ticker: str) -> float:
    """Free yfinance proxy — 20 trading-day average daily volume baseline."""
    ticker_clean = str(ticker).strip().upper()
    try:
        hist = yf.Ticker(ticker_clean).history(period="1mo", interval="1d")
        if hist is None or hist.empty or "Volume" not in hist.columns:
            return 0.0
        volumes = hist["Volume"].dropna()
        if volumes.empty:
            return 0.0
        window = volumes.tail(20)
        return float(window.mean()) if len(window) >= 5 else float(volumes.mean())
    except Exception:
        return 0.0


def _detect_institutional_block_accumulation(ticker: str, data_stream, interval: str) -> dict:
    """
    Free institutional proxy tracker: flags block accumulation when any active
    execution-window bar exceeds 300% above the 20-day volume baseline.
    """
    baseline_daily = _twenty_day_volume_baseline(ticker)
    if baseline_daily <= 0:
        return {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: BASELINE_UNAVAILABLE",
            "volume_baseline_20d": 0.0,
            "peak_surge_ratio": 0.0,
        }

    bars_per_session = BARS_PER_SESSION.get(interval, 26)
    per_bar_baseline = baseline_daily / bars_per_session
    volumes = _volume_series_from_data_stream(data_stream)
    if volumes is None:
        return {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: NO_EXECUTION_VOLUME",
            "volume_baseline_20d": round(baseline_daily, 0),
            "peak_surge_ratio": 0.0,
        }

    if pd is not None and isinstance(volumes, pd.Series):
        active_window = volumes.tail(min(len(volumes), bars_per_session * 2))
        peak_bar_vol = float(active_window.max()) if not active_window.empty else 0.0
    elif isinstance(volumes, list):
        active_window = volumes[-min(len(volumes), bars_per_session * 2):]
        peak_bar_vol = float(max(active_window)) if active_window else 0.0
    else:
        peak_bar_vol = 0.0

    peak_surge_ratio = (peak_bar_vol / per_bar_baseline) if per_bar_baseline > 0 else 0.0
    detected = peak_surge_ratio >= INSTITUTIONAL_SURGE_MULTIPLIER
    summary = (
        f"Institutional Block Accumulation Detected | Peak Surge: {peak_surge_ratio:.1f}x "
        f"(>{INSTITUTIONAL_SURGE_MULTIPLIER - 1:.0f}00% above 20D baseline) | "
        f"20D Avg Vol: {baseline_daily:,.0f} | Window Peak Bar: {peak_bar_vol:,.0f}"
        if detected
        else (
            f"INST_BLOCK: CLEAR | Peak Surge: {peak_surge_ratio:.1f}x | "
            f"20D Avg Vol: {baseline_daily:,.0f}"
        )
    )
    return {
        "institutional_block_accumulation": detected,
        "inst_block_summary": summary,
        "volume_baseline_20d": round(baseline_daily, 0),
        "peak_surge_ratio": round(peak_surge_ratio, 3),
    }


def _resolve_sec_cik(ticker: str) -> str | None:
    ticker_clean = str(ticker).strip().upper()
    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=10,
        )
        if not resp.ok:
            return None
        for entry in resp.json().values():
            if str(entry.get("ticker", "")).upper() == ticker_clean:
                return str(entry.get("cik_str", "")).zfill(10)
    except Exception:
        return None
    return None


def _parse_form4_purchases(xml_content: str) -> list[dict]:
    """Extract insider open-market purchase rows from Form 4 XML."""
    purchases: list[dict] = []
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return purchases

    for node in root.iter():
        if _xml_local_tag(node.tag) != "nonDerivativeTransaction":
            continue
        tx_date = ""
        shares = 0.0
        code = ""
        acquired = ""
        for child in node.iter():
            tag = _xml_local_tag(child.tag)
            if tag == "transactionDate":
                for sub in child.iter():
                    if _xml_local_tag(sub.tag) == "value" and sub.text:
                        tx_date = sub.text.strip()
            elif tag == "transactionShares":
                for sub in child.iter():
                    if _xml_local_tag(sub.tag) == "value" and sub.text:
                        try:
                            shares = float(sub.text.replace(",", ""))
                        except ValueError:
                            shares = 0.0
            elif tag == "transactionCode" and child.text:
                code = child.text.strip().upper()
            elif tag == "transactionAcquiredDisposedCode":
                for sub in child.iter():
                    if _xml_local_tag(sub.tag) == "value" and sub.text:
                        acquired = sub.text.strip().upper()

        is_buy = code == "P" or acquired == "A"
        if is_buy and tx_date and shares > 0:
            purchases.append({"date": tx_date, "shares": shares, "code": code or acquired})

    if purchases:
        return purchases

    date_hits = re.findall(
        r"<transactionDate>\s*<value>(\d{4}-\d{2}-\d{2})</value>",
        xml_content,
    )
    share_hits = re.findall(
        r"<transactionShares>\s*<value>([\d,\.]+)</value>",
        xml_content,
    )
    code_hits = re.findall(r"<transactionCode>([A-Z])</transactionCode>", xml_content)
    acquired_hits = re.findall(
        r"<transactionAcquiredDisposedCode>\s*<value>([A-Z])</value>",
        xml_content,
    )
    for i, tx_date in enumerate(date_hits):
        code = code_hits[i] if i < len(code_hits) else ""
        acquired = acquired_hits[i] if i < len(acquired_hits) else ""
        try:
            shares = float(share_hits[i].replace(",", "")) if i < len(share_hits) else 0.0
        except (ValueError, IndexError):
            shares = 0.0
        if (code == "P" or acquired == "A") and shares > 0:
            purchases.append({"date": tx_date, "shares": shares, "code": code or acquired})
    return purchases


def _scrape_form4_insider_buys(ticker: str) -> dict:
    """
    Free SEC EDGAR Form 4 proxy scraper — flags active insider buying inside 30 days.
    """
    ticker_clean = str(ticker).strip().upper()
    cik = _resolve_sec_cik(ticker_clean)
    if not cik:
        return {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: NO_CIK",
            "insider_events": [],
        }

    try:
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=12,
        )
        if not sub.ok:
            return {
                "insider_buy_detected": False,
                "form4_summary": "FORM4: SUBMISSIONS_FAIL",
                "insider_events": [],
            }
        recent = sub.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
    except Exception:
        return {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: ERR",
            "insider_events": [],
        }

    cutoff = datetime.datetime.now().date() - datetime.timedelta(days=30)
    cik_path = str(int(cik))
    insider_events: list[dict] = []

    for i, form in enumerate(forms[:40]):
        if form not in ("4", "4/A"):
            continue
        try:
            filing_date = datetime.datetime.strptime(dates[i], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        if filing_date < cutoff:
            continue
        if i >= len(accessions) or i >= len(primary_docs):
            continue

        accession_compact = accessions[i].replace("-", "")
        doc_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_path}/"
            f"{accession_compact}/{primary_docs[i]}"
        )
        try:
            doc_resp = requests.get(doc_url, headers=SEC_HEADERS, timeout=10)
            if not doc_resp.ok:
                continue
            purchases = _parse_form4_purchases(doc_resp.text)
            for purchase in purchases:
                try:
                    tx_date = datetime.datetime.strptime(purchase["date"], "%Y-%m-%d").date()
                except ValueError:
                    continue
                if tx_date >= cutoff:
                    insider_events.append(
                        {
                            "filing_date": dates[i],
                            "transaction_date": purchase["date"],
                            "shares": purchase["shares"],
                        }
                    )
        except Exception:
            continue

    if not insider_events:
        return {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: NO_INSIDER_BUY_30D",
            "insider_events": [],
        }

    insider_events.sort(key=lambda x: x["transaction_date"], reverse=True)
    lead = insider_events[0]
    flags = "|".join(
        f"{evt['transaction_date']}:{int(evt['shares']):,}SH"
        for evt in insider_events[:3]
    )
    summary = (
        f"FORM4 INSIDER BUY ACTIVE | Date: {lead['transaction_date']} | "
        f"Volume: {int(lead['shares']):,} shares | Flags: {flags}"
    )
    return {
        "insider_buy_detected": True,
        "form4_summary": summary,
        "insider_events": insider_events,
    }


def get_historical_interval_data(ticker, interval="15m", update_institutional_tracker=True):
    """
    Free institutional proxy interval wire with 20-day volume baseline tracker.
    - Under 60 Days: yfinance local Mac silicon wire.
    - Extended history: Polygon API with live 5-call/min throttle shield (15m only).
    """
    ticker_clean = str(ticker).strip().upper()
    now = datetime.datetime.now()
    interval = str(interval).lower()
    yf_interval = interval if interval in {"5m", "15m", "1h", "1d"} else "15m"

    data_stream = None
    try:
        df_yf = yf.download(
            ticker_clean,
            period="60d",
            interval=yf_interval,
            progress=False,
        )
        if df_yf is not None and not df_yf.empty:
            data_stream = df_yf
    except Exception:
        pass

    if data_stream is None and yf_interval == "15m":
        if not _consume_polygon_call():
            st.session_state.forensic_institutional_tracker = {
                "institutional_block_accumulation": False,
                "inst_block_summary": "INST_BLOCK: THROTTLED",
                "volume_baseline_20d": 0.0,
                "peak_surge_ratio": 0.0,
            }
            return "THROTTLE"
        try:
            api_key = st.secrets["POLYGON_API_KEY"]
            start_date = (now - datetime.timedelta(days=730)).strftime("%Y-%m-%d")
            end_date = now.strftime("%Y-%m-%d")
            url = (
                f"https://api.polygon.io/v2/aggs/ticker/{ticker_clean}/range/15/minute/"
                f"{start_date}/{end_date}?adjusted=true&sort=asc&apiKey={api_key}"
            )
            response = requests.get(url, timeout=15).json()
            if "results" in response:
                data_stream = response["results"]
            elif response.get("status") == "ERROR" and "max requests" in response.get("error", "").lower():
                st.session_state.polygon_calls_remaining = 0
                st.session_state.polygon_lockout = True
                st.session_state.forensic_institutional_tracker = {
                    "institutional_block_accumulation": False,
                    "inst_block_summary": "INST_BLOCK: THROTTLED",
                    "volume_baseline_20d": 0.0,
                    "peak_surge_ratio": 0.0,
                }
                return "THROTTLE"
        except Exception:
            data_stream = None

    if data_stream not in (None, "THROTTLE", "LOCKOUT") and update_institutional_tracker:
        tracker = _detect_institutional_block_accumulation(ticker_clean, data_stream, yf_interval)
        st.session_state.forensic_institutional_tracker = tracker
    elif update_institutional_tracker and "forensic_institutional_tracker" not in st.session_state:
        st.session_state.forensic_institutional_tracker = {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: NO_DATA",
            "volume_baseline_20d": 0.0,
            "peak_surge_ratio": 0.0,
        }

    return data_stream


def get_historical_5m_data(ticker):
    """Local yfinance micro-interval wire — no Polygon quota consumed."""
    return get_historical_interval_data(ticker, interval="5m", update_institutional_tracker=False)


def get_historical_15m_data(ticker):
    """Backward-compatible 15m wrapper around the institutional interval wire."""
    return get_historical_interval_data(ticker, interval="15m")


def _analyze_5m_micro_traps(data_5m, ticker: str) -> dict:
    """Drill-down engine for float traps and volume anomalies on compressed 15m variance."""
    closes = _series_from_data_stream(data_5m)
    volumes = _volume_series_from_data_stream(data_5m)
    if closes is None:
        return {
            "drill_active": False,
            "summary": "5M_DRILL:UNAVAILABLE",
        }

    trap_count = 0
    volume_spikes = 0
    wick_anomalies = 0
    max_spike_ratio = 1.0

    if pd is not None and isinstance(closes, pd.Series) and len(closes) >= 10:
        returns = closes.pct_change().dropna()
        if len(returns) >= 5:
            for i in range(1, len(returns)):
                if returns.iloc[i] > 0 and returns.iloc[i - 1] < 0 and abs(returns.iloc[i]) > 0.012:
                    trap_count += 1
                if returns.iloc[i] < 0 and returns.iloc[i - 1] > 0 and abs(returns.iloc[i]) > 0.012:
                    trap_count += 1

        if volumes is not None and isinstance(volumes, pd.Series) and len(volumes) >= 8:
            avg_vol = float(volumes.iloc[-20:-1].mean()) if len(volumes) >= 20 else float(volumes.iloc[:-1].mean())
            if avg_vol > 0:
                spike_ratios = (volumes / avg_vol).tolist()
                volume_spikes = sum(1 for ratio in spike_ratios if ratio >= 2.0)
                max_spike_ratio = float(max(spike_ratios))

        if isinstance(data_5m, pd.DataFrame):
            cols = (
                data_5m.columns.get_level_values(0)
                if isinstance(data_5m.columns, pd.MultiIndex)
                else data_5m.columns
            )
            if {"High", "Low", "Close"}.issubset(set(cols)):
                high = data_5m["High"]
                low = data_5m["Low"]
                close = data_5m["Close"]
                if isinstance(high, pd.DataFrame):
                    high = high.iloc[:, 0]
                    low = low.iloc[:, 0]
                    close = close.iloc[:, 0]
                open_s = data_5m["Open"] if "Open" in cols else close.shift(1)
                if isinstance(open_s, pd.DataFrame):
                    open_s = open_s.iloc[:, 0]
                recent_high = high.tail(30)
                recent_low = low.tail(30)
                recent_close = close.tail(30)
                recent_open = open_s.tail(30)
                body = (recent_close - recent_open).abs().replace(0, 1e-9)
                wick = (recent_high - recent_low).abs()
                if len(body.dropna()) >= 5:
                    wick_anomalies = int(((wick / body) > 3.5).sum())

    summary = (
        f"5M_DRILL:{ticker}|FLOAT_TRAPS:{trap_count}|VOL_SPIKES:{volume_spikes}|"
        f"MAX_VOL_RATIO:{max_spike_ratio:.2f}x|WICK_ANOMALIES:{wick_anomalies}"
    )
    return {
        "drill_active": True,
        "float_traps": trap_count,
        "volume_spikes": volume_spikes,
        "max_volume_ratio": round(max_spike_ratio, 3),
        "wick_anomalies": wick_anomalies,
        "summary": summary,
    }


def _local_pattern_math(
    data_stream,
    pattern_category,
    date_coordinates,
    prices,
    micro_block=None,
    institutional_block=None,
    form4_block=None,
):
    """Permanent pattern categorization math — 100% local on Mac silicon."""
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
            amplitude = _wave_amplitude_pct(series)
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
                amplitude = _wave_amplitude_pct(series)
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
                (
                    62
                    + (abs(pearson_r) * 18)
                    + min(amplitude, 12)
                    + (6 if trend_bias != "NEUTRAL" else 0)
                )
                * category_factor
            ),
        ),
    )

    if entry_price and exit_price and entry_price > 0:
        realized_move = ((exit_price - entry_price) / entry_price) * 100
    else:
        realized_move = None

    quantum_report = (
        f"MacBook Quant Chip | Category: {category} | Bars: {bar_count} | "
        f"Wave Amplitude: {amplitude:.2f}% | Pearson r: {pearson_r:.3f} | "
        f"Trend Bias: {trend_bias} | Structural Match: {structural_score}% | "
        f"Polygon Calls Remaining: {_polygon_calls_remaining()}/{POLYGON_CALLS_PER_MINUTE}"
    )
    if realized_move is not None:
        quantum_report += f" | Coordinate Move: {realized_move:.2f}%"
    if micro_block and micro_block.get("drill_active"):
        quantum_report += f" | {micro_block['summary']}"
    if institutional_block and institutional_block.get("institutional_block_accumulation"):
        quantum_report += f" | {institutional_block['inst_block_summary']}"
    if form4_block and form4_block.get("insider_buy_detected"):
        quantum_report += f" | {form4_block['form4_summary']}"

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
        "micro_drill_summary": micro_block.get("summary") if micro_block else None,
        "float_traps": micro_block.get("float_traps") if micro_block else None,
        "volume_spikes": micro_block.get("volume_spikes") if micro_block else None,
        "institutional_block_accumulation": (
            institutional_block.get("institutional_block_accumulation") if institutional_block else False
        ),
        "form4_insider_buy": form4_block.get("insider_buy_detected") if form4_block else False,
    }


def stream_payload_to_vault(payload: dict) -> tuple[bool, str]:
    """Direct secure Supabase REST anchor to live Postgres cloud table."""
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
            return True, (
                f"INTERNET VAULT SYNC CONFIRMED — `{table}` anchored for "
                f"{payload.get('ticker', 'UNKNOWN')} @ {payload.get('timestamp', 'UTC')}."
            )
        return False, f"Vault upload failed: {resp.status_code} {resp.text}"
    except Exception as exc:
        return False, f"Vault upload failed: {exc}"


def calculate_quantum_frequencies(
    data_stream,
    pattern_category="",
    date_coordinates=None,
    prices=None,
    human_feedback="",
    ticker="",
):
    """
    Runs permanent pattern categorization math locally on Mac silicon with adaptive
    5-minute drill-down when 15-minute variance compresses.
    """
    if data_stream == "THROTTLE":
        return THROTTLE_MESSAGE
    if data_stream is None or data_stream == "LOCKOUT":
        return "System Sidelined: Awaiting Data Pipeline Clear"

    resolved_ticker = (
        str(ticker).strip().upper()
        or str(st.session_state.get("room2_forensic_ticker", "")).strip().upper()
        or str(st.session_state.get("current_ticker", "")).strip().upper()
    )

    micro_block = None
    if _is_compressed_variance(data_stream) and resolved_ticker:
        data_5m = get_historical_5m_data(resolved_ticker)
        if data_5m is not None and data_5m not in ("THROTTLE", "LOCKOUT"):
            micro_block = _analyze_5m_micro_traps(data_5m, resolved_ticker)

    institutional_block = st.session_state.get("forensic_institutional_tracker", {})
    if not institutional_block and resolved_ticker:
        institutional_block = _detect_institutional_block_accumulation(
            resolved_ticker, data_stream, "15m"
        )
        st.session_state.forensic_institutional_tracker = institutional_block

    form4_block = _scrape_form4_insider_buys(resolved_ticker) if resolved_ticker else {
        "insider_buy_detected": False,
        "form4_summary": "FORM4: NO_TICKER",
        "insider_events": [],
    }
    st.session_state.forensic_form4_tracker = form4_block

    math_block = _local_pattern_math(
        data_stream,
        pattern_category,
        date_coordinates,
        prices,
        micro_block=micro_block,
        institutional_block=institutional_block,
        form4_block=form4_block,
    )
    return math_block["quantum_report"]


def build_vault_payload(
    *,
    ticker: str,
    pattern_category: str,
    entry_coordinate: str,
    exit_coordinate: str,
    entry_time: str,
    exit_time: str,
    operator_notes: str,
    quantum_report: str,
    bar_count: int,
) -> dict:
    """Package Room 2 deck parameters for Internet Vault streaming."""
    return {
        "ticker": ticker.upper(),
        "pattern_category": (pattern_category or "UNCLASSIFIED").strip().upper(),
        "entry_coordinate": entry_coordinate,
        "exit_coordinate": exit_coordinate,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "operator_context": operator_notes.strip(),
        "quantum_report": quantum_report,
        "bar_count": bar_count,
        "polygon_calls_remaining": _polygon_calls_remaining(),
        "institutional_block_accumulation": st.session_state.get(
            "forensic_institutional_tracker", {}
        ).get("institutional_block_accumulation", False),
        "form4_insider_summary": (
            st.session_state.get("forensic_form4_tracker", {}).get("form4_summary", "")
        ),
        "source_room": "forensic_pattern_lab",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
