import datetime
import json
import math
import re
import statistics
import time
import urllib.parse
from xml.etree import ElementTree

import requests
import streamlit as st
import yfinance as yf

try:
    import pandas as pd
except ImportError:
    pd = None

POLYGON_CALLS_PER_MINUTE = 5
ALPHA_DECAY_ROLLING_N = 15
ALPHA_DECAY_MARGIN_FLOOR_PCT = 0.15
LAYOUT_SIGNATURE_MATCH_THRESHOLD = 85
ANOMALY_SHELF_DAYS = 30
ANOMALY_PERMANENT_MINT_COUNT = 5
TIMEFRAME_MARGIN_FLOORS = {
    "1-Minute": 1.0,
    "5-Minute": 3.0,
    "15-Minute": 5.0,
}
LOOKBACK_DELTAS = {
    "1-Minute": datetime.timedelta(minutes=5),
    "5-Minute": datetime.timedelta(hours=12),
    "15-Minute": datetime.timedelta(hours=18),
}
INNER_MOVE_MAX_1M = datetime.timedelta(minutes=2)
NOISE_DIM_EPSILON = 0.18
SEMANTIC_EMBED_DIMS = 32
DRAGNET_TIMEFRAMES = frozenset({"5-Minute", "15-Minute"})
ROOT_CAUSE_FRICTION = "execution_friction_slippage"
ROOT_CAUSE_STRUCTURAL_DECAY = "structural_alpha_decay"
EXECUTION_HALTED_STATE = "execution_halted"
VAULT_STATE_INCUBATION = "incubation"
VAULT_STATE_PURGATORY = "purgatory"
FINBERT_MODEL_ID = "ProsusAI/finbert"
ROOM1_TOKEN_BUDGET = 28000
ROOM1_WARN_RATIO = 0.90
ROOM1_WARN_MESSAGES_REMAINING = 5
ROOM1_ASSISTANT_TOKEN_RESERVE = 1200
PROCESSOR_LANE_CLOUD = "cloud_dual_stream"
PROCESSOR_LANE_LOCAL_STRIKE = "local_1m_strike"
LOCAL_1M_RAM_CAP_MINUTES = 5
IB_STRIKE_TARGET_MS = 100
DATA_FEED_CLOUD_MACRO = "cloud_macro_pipeline"
DATA_FEED_POLYGON_1M = "polygon_rest_1m"
DATA_FEED_YFINANCE_1M = "yfinance_1m"
THROTTLE_MESSAGE = (
    "⚠️ NETWORK THROTTLING SHIELD ACTIVE: 0 API CALLS REMAINING. COOLING DOWN PROCESSOR."
)
COMPRESSED_VARIANCE_THRESHOLD = 1.25
INSTITUTIONAL_SURGE_MULTIPLIER = 4.0
SEC_HEADERS = {"User-Agent": "SavantApprentice earmaobusiness@gmail.com"}
BARS_PER_SESSION = {"1m": 390, "5m": 78, "15m": 26, "1h": 7, "1d": 1}


def is_pipeline_signal(data_stream, *signals: str) -> bool:
    """True only for string status tokens (THROTTLE/LOCKOUT), never for DataFrames."""
    return isinstance(data_stream, str) and data_stream in signals


def is_usable_data_stream(data_stream) -> bool:
    """True when data_stream holds bar/table data rather than a pipeline signal."""
    if data_stream is None or isinstance(data_stream, str):
        return False
    if pd is not None and isinstance(data_stream, pd.DataFrame):
        return not data_stream.empty
    try:
        return len(data_stream) > 0
    except TypeError:
        return False


def _flatten_yfinance_frame(df):
    """Normalize yfinance MultiIndex columns so Close/Volume accessors work."""
    if pd is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _download_yfinance_bars(ticker_clean: str, yf_interval: str, micro_fast_track: bool = False):
    """Primary local datalink — 1m micro path uses tight lookback for sub-second routing."""
    if micro_fast_track or yf_interval == "1m":
        period = "1d"
    elif yf_interval == "5m":
        period = "30d"
    else:
        period = "60d"
    try:
        hist = yf.Ticker(ticker_clean).history(period=period, interval=yf_interval)
        flat = _flatten_yfinance_frame(hist)
        if is_usable_data_stream(flat):
            return flat
    except Exception:
        pass
    try:
        df_yf = yf.download(
            ticker_clean,
            period=period,
            interval=yf_interval,
            progress=False,
            group_by="column",
            auto_adjust=True,
            threads=False,
        )
        flat = _flatten_yfinance_frame(df_yf)
        if is_usable_data_stream(flat):
            return flat
    except Exception:
        pass
    return None


def _fetch_polygon_15m_bars(ticker_clean: str, start_date: str, end_date: str):
    """
    Safe Polygon aggs wire — only inspects plain dict JSON (never pandas objects).
    Returns (bars, pipeline_signal) where pipeline_signal is None or 'THROTTLE'.
    """
    try:
        api_key = st.secrets["POLYGON_API_KEY"]
    except Exception:
        return None, None

    if not _consume_polygon_call():
        return None, "THROTTLE"

    try:
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker_clean}/range/15/minute/"
            f"{start_date}/{end_date}?adjusted=true&sort=asc&apiKey={api_key}"
        )
        http_resp = requests.get(url, timeout=15)
        if not http_resp.ok:
            return None, None
        payload = http_resp.json()
    except Exception:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    results = payload.get("results")
    if isinstance(results, list) and len(results) > 0:
        return results, None

    status = str(payload.get("status", "")).upper()
    error_text = str(payload.get("error") or payload.get("message") or "").lower()
    if status == "ERROR" and "max requests" in error_text:
        st.session_state.polygon_calls_remaining = 0
        st.session_state.polygon_lockout = True
        return None, "THROTTLE"
    return None, None


def _fetch_polygon_1m_bars(ticker_clean: str, start_date: str, end_date: str):
    """Recent 1-minute aggs — preferred micro fast-track wire when Polygon key is live."""
    try:
        api_key = st.secrets["POLYGON_API_KEY"]
    except Exception:
        return None, None

    if not _consume_polygon_call():
        return None, "THROTTLE"

    try:
        url = (
            f"https://api.polygon.io/v2/aggs/ticker/{ticker_clean}/range/1/minute/"
            f"{start_date}/{end_date}?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
        )
        http_resp = requests.get(url, timeout=15)
        if not http_resp.ok:
            return None, None
        payload = http_resp.json()
    except Exception:
        return None, None

    if not isinstance(payload, dict):
        return None, None

    results = payload.get("results")
    if isinstance(results, list) and len(results) > 0:
        return results, None

    status = str(payload.get("status", "")).upper()
    error_text = str(payload.get("error") or payload.get("message") or "").lower()
    if status == "ERROR" and "max requests" in error_text:
        st.session_state.polygon_calls_remaining = 0
        st.session_state.polygon_lockout = True
        return None, "THROTTLE"
    return None, None


def _polygon_aggs_to_dataframe(results):
    """Convert Polygon agg list into a yfinance-compatible OHLCV frame."""
    if pd is None or not isinstance(results, list) or not results:
        return None
    rows = []
    for bar in results:
        if not isinstance(bar, dict):
            continue
        ts_ms = bar.get("t")
        if ts_ms is None:
            continue
        ts = datetime.datetime.fromtimestamp(float(ts_ms) / 1000.0)
        rows.append(
            {
                "Datetime": ts,
                "Open": float(bar.get("o", 0) or 0),
                "High": float(bar.get("h", 0) or 0),
                "Low": float(bar.get("l", 0) or 0),
                "Close": float(bar.get("c", 0) or 0),
                "Volume": float(bar.get("v", 0) or 0),
            }
        )
    if not rows:
        return None
    frame = pd.DataFrame(rows).set_index("Datetime")
    return frame if not frame.empty else None


def timeframe_margin_floor(timeframe_resolution: str) -> float:
    return float(TIMEFRAME_MARGIN_FLOORS.get(timeframe_resolution, 1.0))


def _ensure_dataframe(data_stream):
    if pd is None:
        return None
    if isinstance(data_stream, pd.DataFrame) and not data_stream.empty:
        return _flatten_yfinance_frame(data_stream)
    return None


def pad_datastream_gaps(data_stream):
    """Forward-fill thin pre/post-market gaps so loops never hit empty holes."""
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return data_stream
    padded = frame.copy()
    for col in ("Close", "Open", "High", "Low", "Volume"):
        if col in padded.columns:
            padded[col] = padded[col].ffill()
            if col != "Volume":
                padded[col] = padded[col].bfill()
    return padded


def _calibrated_lookback_start(end_dt: datetime.datetime, timeframe_resolution: str):
    """Timeframe-isolated forensic lookback — 1m tight, 5m to 4AM, 15m overnight bridge."""
    if end_dt is None:
        return None
    if timeframe_resolution == "1-Minute":
        return end_dt - LOOKBACK_DELTAS["1-Minute"]
    if timeframe_resolution == "5-Minute":
        premarket_open = end_dt.replace(hour=4, minute=0, second=0, microsecond=0)
        if end_dt < premarket_open:
            premarket_open = premarket_open - datetime.timedelta(days=1)
        wide_back = end_dt - LOOKBACK_DELTAS["5-Minute"]
        return premarket_open if premarket_open > wide_back else wide_back
    if timeframe_resolution == "15-Minute":
        return end_dt - LOOKBACK_DELTAS["15-Minute"]
    delta = LOOKBACK_DELTAS.get(timeframe_resolution, datetime.timedelta(hours=1))
    return end_dt - delta


def _clamp_inner_move_window(
    start_dt: datetime.datetime | None,
    end_dt: datetime.datetime | None,
    timeframe_resolution: str,
) -> datetime.datetime | None:
    """1m track: limit in-move look-in to 1–2 minutes to protect entry runway."""
    if (
        timeframe_resolution != "1-Minute"
        or start_dt is None
        or end_dt is None
        or end_dt <= start_dt
    ):
        return start_dt
    if end_dt - start_dt > INNER_MOVE_MAX_1M:
        return end_dt - INNER_MOVE_MAX_1M
    return start_dt


def _research_dragnet_lookback_start(
    end_dt: datetime.datetime | None, timeframe_resolution: str
) -> datetime.datetime | None:
    """
    Unconstrained full-day dragnet (Room 2 research only) — no profit-floor walls.
    5m: entire session back to 4:00 AM pre-market. 15m: bridges overnight into prior post-market.
    Temporal fence at Exit B still applies separately; this only widens historical ingestion.
    """
    if end_dt is None:
        return None
    if timeframe_resolution == "5-Minute":
        premarket = end_dt.replace(hour=4, minute=0, second=0, microsecond=0)
        if end_dt < premarket:
            premarket = premarket - datetime.timedelta(days=1)
        return premarket
    if timeframe_resolution == "15-Minute":
        prior = end_dt - datetime.timedelta(days=1)
        return prior.replace(hour=16, minute=0, second=0, microsecond=0)
    return _calibrated_lookback_start(end_dt, timeframe_resolution)


def compute_metric_envelopes(
    data_stream,
    end_dt: datetime.datetime | None,
    lookback_start_dt: datetime.datetime | None,
) -> dict:
    """
    Flexible std-dev envelopes for cold metrics — volume, velocity, spread.
    Maps zones like 25M–35M volume instead of a single rigid threshold.
    """
    frame = _ensure_dataframe(data_stream)
    if frame is None or end_dt is None:
        return {}
    try:
        if lookback_start_dt is not None:
            window = frame[(frame.index <= end_dt) & (frame.index >= lookback_start_dt)]
        else:
            window = frame[frame.index <= end_dt]
        if not isinstance(window, pd.DataFrame) or window.empty:
            return {}

        envelopes: dict = {}
        if "Volume" in window.columns:
            vols = window["Volume"].astype(float).dropna()
            if len(vols) >= 2:
                mu = float(vols.mean())
                sigma = float(vols.std(ddof=0))
                envelopes["volume"] = {
                    "low": round(max(0.0, mu - sigma), 0),
                    "mid": round(mu, 0),
                    "high": round(mu + sigma, 0),
                    "sigma": round(sigma, 2),
                }

        closes = window["Close"].astype(float)
        if len(closes) >= 3:
            returns = closes.pct_change().dropna() * 100
            if len(returns) >= 2:
                mu = float(returns.mean())
                sigma = float(returns.std(ddof=0))
                envelopes["velocity_pct"] = {
                    "low": round(mu - sigma, 4),
                    "mid": round(mu, 4),
                    "high": round(mu + sigma, 4),
                    "sigma": round(sigma, 4),
                }

        spread = (
            (window["High"] - window["Low"]) / window["Close"].replace(0, pd.NA) * 100
        ).astype(float).dropna()
        if len(spread) >= 2:
            mu = float(spread.mean())
            sigma = float(spread.std(ddof=0))
            envelopes["spread_pct"] = {
                "low": round(max(0.0, mu - sigma), 4),
                "mid": round(mu, 4),
                "high": round(mu + sigma, 4),
                "sigma": round(sigma, 4),
            }
        return envelopes
    except Exception:
        return {}


@st.cache_resource(show_spinner=False)
def _get_finbert_pipeline():
    """Local Hugging Face FinBERT — free SEC/headline sentiment, no paid API keys."""
    try:
        from transformers import pipeline

        return pipeline(
            "sentiment-analysis",
            model=FINBERT_MODEL_ID,
            tokenizer=FINBERT_MODEL_ID,
            truncation=True,
            max_length=512,
        )
    except Exception:
        return None


def finbert_sentiment_score(text: str) -> float:
    """
    Hard numeric sentiment: Positive probability minus Negative probability ∈ [-1, +1].
    """
    clean = str(text or "").strip()
    if not clean:
        return 0.0
    pipe = _get_finbert_pipeline()
    if pipe is None:
        return 0.0
    try:
        raw = pipe(clean, top_k=None)
        rows = raw[0] if raw and isinstance(raw[0], list) else raw
        if not isinstance(rows, list):
            rows = [rows]
        pos = neg = 0.0
        for row in rows:
            label = str(row.get("label", "")).lower()
            prob = float(row.get("score", 0.0))
            if "positive" in label:
                pos = prob
            elif "negative" in label:
                neg = prob
        return round(max(-1.0, min(1.0, pos - neg)), 4)
    except Exception:
        return 0.0


def score_semantic_catalyst_stream(
    headlines: list[str],
    filing_texts: list[str] | None = None,
) -> dict:
    """
    Local FinBERT sentiment core — SEC EDGAR headers + public headline strings.
    """
    clean_headlines = [str(h).strip() for h in headlines if str(h).strip()]
    clean_filings = [str(f).strip() for f in (filing_texts or []) if str(f).strip()]
    all_texts = clean_headlines + clean_filings
    if not all_texts:
        return {
            "finbert_sentiment_score": 0.0,
            "message_velocity": 0.0,
            "audience_scale": 0.0,
            "impact_weight": 0.0,
            "semantic_mode": "finbert_local",
            "headline_count": 0,
            "filing_count": 0,
        }
    scores = [finbert_sentiment_score(t) for t in all_texts]
    aggregate = round(sum(scores) / len(scores), 4) if scores else 0.0
    headline_scores = scores[: len(clean_headlines)]
    filing_scores = scores[len(clean_headlines) :]
    message_velocity = round(
        len(all_texts) / max(1.0, math.log1p(sum(len(h) for h in all_texts) / 80)), 3
    )
    audience_scale = round(statistics.mean([len(h) for h in all_texts]), 2)
    impact_weight = round(abs(aggregate) * (1.0 + math.log1p(message_velocity)), 4)
    return {
        "finbert_sentiment_score": aggregate,
        "headline_sentiment_scores": headline_scores,
        "filing_sentiment_scores": filing_scores,
        "message_velocity": message_velocity,
        "audience_scale": audience_scale,
        "impact_weight": impact_weight,
        "semantic_mode": "finbert_local",
        "headline_count": len(clean_headlines),
        "filing_count": len(clean_filings),
    }


def _purge_non_overlapping_dimensions(
    new_vec: list[float],
    reference_vec: list[float],
    epsilon: float = NOISE_DIM_EPSILON,
) -> tuple[list[float], int]:
    """Digital genetics waste disposal — trash non-matching dimensions, keep pure overlap."""
    if not reference_vec or len(new_vec) != len(reference_vec):
        return new_vec, 0
    pure: list[float] = []
    discarded = 0
    for fresh, ref in zip(new_vec, reference_vec):
        if abs(fresh - ref) <= epsilon:
            pure.append(round((fresh + ref) / 2.0, 6))
        else:
            pure.append(round(ref, 6))
            discarded += 1
    return pure, discarded


def _scrape_sec_regulatory_dragnet(ticker: str, *, days: int = 30) -> dict:
    """SEC dragnet — Form 4, 8-K, SC 13D filing index from EDGAR submissions wire."""
    ticker_clean = str(ticker).strip().upper()
    cik = _resolve_sec_cik(ticker_clean)
    if not cik:
        return {"status": "NO_CIK", "filings": []}
    try:
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=12,
        )
        if not sub.ok:
            return {"status": "SUBMISSIONS_FAIL", "filings": []}
        recent = sub.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        cutoff = datetime.datetime.now().date() - datetime.timedelta(days=days)
        targets = {"4", "4/A", "8-K", "8-K/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
        filings: list[dict] = []
        for i, form in enumerate(forms[:80]):
            if form not in targets:
                continue
            try:
                filing_date = datetime.datetime.strptime(dates[i], "%Y-%m-%d").date()
            except (ValueError, IndexError):
                continue
            if filing_date < cutoff:
                continue
            filings.append({"form": form, "filing_date": dates[i]})
        return {"status": "OK", "filings": filings[:25], "count": len(filings)}
    except Exception as exc:
        return {"status": f"ERR:{str(exc)[:40]}", "filings": []}


def _options_sweep_proxy(ticker: str) -> dict:
    """Options sweep proxy — nearest-expiry chain volume (cloud research fat layer)."""
    try:
        tk = yf.Ticker(str(ticker).strip().upper())
        expirations = list(tk.options or [])[:1]
        if not expirations:
            return {"status": "NO_CHAIN"}
        chain = tk.option_chain(expirations[0])
        call_vol = int(chain.calls["volume"].fillna(0).sum()) if "volume" in chain.calls else 0
        put_vol = int(chain.puts["volume"].fillna(0).sum()) if "volume" in chain.puts else 0
        return {
            "status": "OK",
            "expiry": expirations[0],
            "call_volume": call_vol,
            "put_volume": put_vol,
            "sweep_ratio": round(call_vol / max(put_vol, 1), 3),
        }
    except Exception:
        return {"status": "UNAVAILABLE"}


def run_full_day_forensic_dragnet(
    *,
    ticker: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
) -> dict:
    """
    Unconstrained full-day dragnet for 5m/15m Room 2 research.
    Ingests unfiltered session fat (still future-blind at Exit B) for Supabase archival.
    """
    if timeframe_resolution not in DRAGNET_TIMEFRAMES:
        return {}
    ticker_clean = str(ticker).strip().upper()
    end_dt = _parse_session_datetime(end_date, end_time)
    if end_dt is None:
        return {}
    dragnet_start = _research_dragnet_lookback_start(end_dt, timeframe_resolution)
    yf_interval = {"5-Minute": "5m", "15-Minute": "15m"}.get(timeframe_resolution, "15m")
    raw = pad_datastream_gaps(_download_yfinance_bars(ticker_clean, yf_interval))
    frame = _ensure_dataframe(raw)
    dragnet_frame = None
    if frame is not None and dragnet_start is not None:
        try:
            sliced = frame[(frame.index <= end_dt) & (frame.index >= dragnet_start)]
            if isinstance(sliced, pd.DataFrame) and not sliced.empty:
                dragnet_frame = sliced
        except Exception:
            dragnet_frame = None

    envelopes = compute_metric_envelopes(dragnet_frame or raw, end_dt, dragnet_start)
    headlines = _fetch_research_news_headlines(ticker_clean, limit=24)
    semantic = score_semantic_catalyst_stream(headlines)
    form4 = _scrape_form4_insider_buys(ticker_clean)
    regulatory = _scrape_sec_regulatory_dragnet(ticker_clean)
    institutional = _detect_institutional_block_accumulation(
        ticker_clean, dragnet_frame or raw, yf_interval
    )
    options = _options_sweep_proxy(ticker_clean)

    bar_count = 0
    if isinstance(dragnet_frame, pd.DataFrame) and not dragnet_frame.empty:
        bar_count = len(dragnet_frame)

    return {
        "dragnet_mode": "full_day_unfiltered_fat",
        "timeframe_resolution": timeframe_resolution,
        "dragnet_start": str(dragnet_start),
        "temporal_fence_end": str(end_dt),
        "bar_count": bar_count,
        "metric_envelopes": envelopes,
        "semantic_catalyst": semantic,
        "news_headlines": headlines[:20],
        "form4": form4,
        "regulatory_filings": regulatory,
        "institutional": institutional,
        "options_sweep_proxy": options,
        "dark_pool_proxy": {
            "block_surge_ratio": institutional.get("peak_surge_ratio", 0.0),
            "block_detected": institutional.get("institutional_block_accumulation", False),
        },
    }


def enforce_permanent_library_profit_floor(quality: dict) -> dict:
    """
    Non-negotiable tiered quality gate before permanent library save.
    1m >= 1.0%, 5m >= 3.0%, 15m >= 5.0% — trash instantly below floor.
    """
    out = dict(quality or {})
    tf = str(out.get("timeframe_resolution") or "15-Minute")
    floor_pct = float(out.get("floor_pct") or timeframe_margin_floor(tf))
    move_pct = float(out.get("structural_move_pct") or 0.0)
    passed = move_pct >= floor_pct
    out["floor_pct"] = floor_pct
    out["passed"] = passed
    out["trashed"] = not passed
    if not passed:
        out["trash_reason"] = (
            f"BELOW_TIERED_FLOOR|move={move_pct:.4f}%|required={floor_pct:.1f}%|tf={tf}"
        )
    return out


def _price_at_datetime(data_stream, target_dt: datetime.datetime):
    frame = _ensure_dataframe(data_stream)
    if frame is None or target_dt is None:
        return None
    try:
        subset = frame[frame.index <= target_dt]
        if isinstance(subset, pd.DataFrame) and not subset.empty:
            return float(subset["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _lookback_window_frame(data_stream, exit_dt, lookback_start_dt):
    frame = _ensure_dataframe(data_stream)
    if frame is None or exit_dt is None or lookback_start_dt is None:
        return None
    try:
        window = frame[(frame.index <= exit_dt) & (frame.index >= lookback_start_dt)]
        if isinstance(window, pd.DataFrame) and not window.empty:
            return window
    except Exception:
        pass
    return None


def _entry_margin_pct(entry_price: float | None, exit_price: float | None) -> float:
    if not entry_price or not exit_price or entry_price <= 0:
        return 0.0
    return abs((float(exit_price) - float(entry_price)) / float(entry_price) * 100)


def _candidate_volume_std_anchor(window) -> tuple[object | None, float | None]:
    """Candidate A — bar with the highest rolling volume standard deviation."""
    if "Volume" not in window.columns or window.empty:
        idx = window.index[0]
        return idx, float(window.loc[idx, "Close"])
    vols = window["Volume"].astype(float).fillna(0.0)
    if len(vols) <= 1:
        idx = window.index[0]
        return idx, float(window.loc[idx, "Close"])
    roll = min(3, len(vols))
    rolling_std = vols.rolling(window=roll, min_periods=1).std().fillna(0.0)
    idx = rolling_std.idxmax()
    return idx, float(window.loc[idx, "Close"])


def _candidate_manual_anchor(window, manual_entry_dt) -> tuple[object | None, float | None]:
    """Candidate B — operator-clicked entry coordinate."""
    if manual_entry_dt is None:
        return None, None
    try:
        subset = window[window.index <= manual_entry_dt]
        if not isinstance(subset, pd.DataFrame) or subset.empty:
            return None, None
        idx = subset.index[-1]
        return idx, float(subset.loc[idx, "Close"])
    except Exception:
        return None, None


def _candidate_structure_baseline(window, volume_spike_idx) -> tuple[object | None, float | None]:
    """Candidate C — lowest swing low on flat terrain before the volume spike."""
    if volume_spike_idx is None:
        return None, None
    try:
        pre_spike = window[window.index <= volume_spike_idx]
        if not isinstance(pre_spike, pd.DataFrame) or pre_spike.empty:
            return None, None
        if "Low" in pre_spike.columns:
            lows = pre_spike["Low"].astype(float)
            idx = lows.idxmin()
            return idx, float(pre_spike.loc[idx, "Low"])
        closes = pre_spike["Close"].astype(float)
        idx = closes.idxmin()
        return idx, float(closes.loc[idx])
    except Exception:
        return None, None


def resolve_adaptive_entry_anchor(
    data_stream,
    *,
    exit_dt: datetime.datetime | None,
    manual_entry_dt: datetime.datetime | None = None,
    lookback_start_dt: datetime.datetime | None = None,
    exit_price: float | None = None,
    floor_pct: float | None = None,
    timeframe_resolution: str = "15-Minute",
) -> dict:
    """
    Multi-candidate adaptive entry optimizer — volume std, manual, structure baseline.
    Floor-aware disqualification; winner = lowest-priced earliest valid candidate.
    """
    floor = float(floor_pct if floor_pct is not None else timeframe_margin_floor(timeframe_resolution))
    window = _lookback_window_frame(data_stream, exit_dt, lookback_start_dt)
    empty_result = {
        "anchor_timestamp": None,
        "anchor_price": None,
        "selected_candidate": None,
        "candidates": [],
        "floor_pct": floor,
        "passed_floor": False,
    }
    if window is None or exit_dt is None:
        return empty_result

    raw_exit = exit_price if exit_price is not None else _price_at_datetime(data_stream, exit_dt)
    vol_idx, vol_price = _candidate_volume_std_anchor(window)
    manual_idx, manual_price = _candidate_manual_anchor(window, manual_entry_dt)
    struct_idx, struct_price = _candidate_structure_baseline(window, vol_idx)

    raw_candidates = (
        ("volume_std_anchor", vol_idx, vol_price),
        ("manual_anchor", manual_idx, manual_price),
        ("structure_baseline", struct_idx, struct_price),
    )
    scored: list[dict] = []
    for label, ts, price in raw_candidates:
        if ts is None or price is None:
            scored.append(
                {
                    "id": label,
                    "timestamp": None,
                    "price": None,
                    "margin_pct": 0.0,
                    "qualified": False,
                    "disqualified_reason": "missing_bar",
                }
            )
            continue
        margin = _entry_margin_pct(price, raw_exit)
        qualified = margin >= floor
        scored.append(
            {
                "id": label,
                "timestamp": str(ts),
                "price": round(float(price), 6),
                "margin_pct": round(margin, 4),
                "qualified": qualified,
                "disqualified_reason": None if qualified else "below_floor_late_chase",
            }
        )

    qualified = [c for c in scored if c.get("qualified") and c.get("price") is not None]
    if not qualified:
        st.session_state.room2_entry_optimizer = {
            "selected_candidate": None,
            "candidates": scored,
            "floor_pct": floor,
            "downhill_pivot": False,
        }
        return {**empty_result, "candidates": scored}

    winner = min(qualified, key=lambda c: (float(c["price"]), str(c["timestamp"])))
    winner_label = winner["id"]
    winner_ts = winner["timestamp"]
    winner_price = float(winner["price"])

    meta = {
        "selected_candidate": winner_label,
        "candidates": scored,
        "floor_pct": floor,
        "downhill_pivot": winner_label != "volume_std_anchor",
        "winner_margin_pct": winner.get("margin_pct"),
    }
    st.session_state.room2_entry_optimizer = meta

    return {
        "anchor_timestamp": winner_ts,
        "anchor_price": winner_price,
        "selected_candidate": winner_label,
        "candidates": scored,
        "floor_pct": floor,
        "passed_floor": True,
        "optimizer_meta": meta,
    }


def hunt_volume_anchor(
    data_stream,
    exit_dt: datetime.datetime,
    lookback_start_dt,
    *,
    manual_entry_dt: datetime.datetime | None = None,
    timeframe_resolution: str = "15-Minute",
    floor_pct: float | None = None,
    exit_price: float | None = None,
):
    """
    Adaptive entry anchor resolver — multi-candidate floor-aware selection.
    Returns (anchor_timestamp, anchor_price).
    """
    resolved = resolve_adaptive_entry_anchor(
        data_stream,
        exit_dt=exit_dt,
        manual_entry_dt=manual_entry_dt,
        lookback_start_dt=lookback_start_dt,
        exit_price=exit_price,
        floor_pct=floor_pct,
        timeframe_resolution=timeframe_resolution,
    )
    anchor_ts = resolved.get("anchor_timestamp")
    anchor_price = resolved.get("anchor_price")
    if anchor_ts is not None and not isinstance(anchor_ts, datetime.datetime):
        try:
            anchor_ts = datetime.datetime.fromisoformat(str(anchor_ts).replace("Z", "+00:00"))
        except ValueError:
            pass
    return anchor_ts, anchor_price


def resolve_stable_profit_exit_anchor(
    data_stream,
    *,
    exit_dt: datetime.datetime | None,
    anchor_price: float | None,
    target_move_pct: float,
    timeframe_resolution: str,
) -> tuple[float | None, str | None]:
    """
    Pure profit-target exit anchoring — if the chosen exit minute is a spike,
    scan adjacent candles for the most stable cluster capturing the same magnitude.
    """
    if exit_dt is None or not anchor_price or anchor_price <= 0:
        return _price_at_datetime(data_stream, exit_dt), (
            str(exit_dt) if exit_dt is not None else None
        )
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return _price_at_datetime(data_stream, exit_dt), str(exit_dt)

    bar_minutes = {"1-Minute": 1, "5-Minute": 5, "15-Minute": 15}.get(timeframe_resolution, 5)
    window = datetime.timedelta(minutes=bar_minutes * 4)
    try:
        subset = frame[
            (frame.index >= exit_dt - window) & (frame.index <= exit_dt + window)
        ]
        if not isinstance(subset, pd.DataFrame) or subset.empty:
            return _price_at_datetime(data_stream, exit_dt), str(exit_dt)

        closes = subset["Close"].astype(float)
        median_close = float(closes.median()) if len(closes) else 0.0
        best_idx = subset.index[-1]
        best_px = float(closes.iloc[-1])
        best_score = 999.0
        cluster_count = 0
        for idx, px in closes.items():
            px_f = float(px)
            move_pct = abs((px_f - anchor_price) / anchor_price * 100)
            spike_penalty = (
                abs(px_f - median_close) / median_close * 100 if median_close else 0.0
            )
            score = abs(move_pct - target_move_pct) + spike_penalty * 0.35
            if abs(move_pct - target_move_pct) <= max(0.15, target_move_pct * 0.08):
                cluster_count += 1
            if score < best_score:
                best_score = score
                best_idx = idx
                best_px = px_f
        st.session_state.room2_exit_cluster_zone = {
            "locked_price": best_px,
            "cluster_bars": cluster_count,
            "target_move_pct": round(target_move_pct, 4),
        }
        return best_px, str(best_idx)
    except Exception:
        return _price_at_datetime(data_stream, exit_dt), str(exit_dt)


def extract_master_signature_vector(
    snapshot_vec: list[float],
    spatial_match_pct: int,
    library: list[dict] | None = None,
) -> dict:
    """
    Genetic cross-reference — high overlap merges into a unified Master Signature;
    non-matching noise is discarded to keep the layout DNA pure.
    """
    library = library or list(st.session_state.get("layout_master_matrix_index", []))
    spatial = compute_spatial_layout_match(snapshot_vec, library)
    overlap = max(int(spatial_match_pct or 0), int(spatial.get("spatial_match_pct") or 0))
    nearest = str(spatial.get("nearest_layout_id") or "NEW_LAYOUT")

    if overlap >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        for entry in library:
            if str(entry.get("layout_id")) != nearest:
                continue
            stored = entry.get("vector") or []
            if len(stored) == len(snapshot_vec):
                merged, discarded = _purge_non_overlapping_dimensions(snapshot_vec, stored)
                return {
                    "master_signature": merged,
                    "layout_id": nearest,
                    "overlap_pct": overlap,
                    "noise_discarded": True,
                    "dimensions_trashed": discarded,
                    "pure_overlap_dims": len(stored) - discarded,
                }
        return {
            "master_signature": snapshot_vec,
            "layout_id": nearest,
            "overlap_pct": overlap,
            "noise_discarded": False,
            "dimensions_trashed": 0,
            "pure_overlap_dims": len(snapshot_vec),
        }

    return {
        "master_signature": snapshot_vec,
        "layout_id": "PURGATORY_PENDING",
        "overlap_pct": overlap,
        "noise_discarded": True,
        "dimensions_trashed": len(snapshot_vec),
        "pure_overlap_dims": 0,
    }


def apply_temporal_fence_and_lookback(
    data_stream,
    *,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
):
    """
    Hindsight blinding + calibrated lookback depths.
    Bars after the exit timestamp are stripped; lookback window is timeframe-specific.
    """
    frame = pad_datastream_gaps(data_stream)
    frame = _ensure_dataframe(frame)
    if frame is None:
        return data_stream, {}

    end_dt = _parse_session_datetime(end_date, end_time)
    if end_dt is None:
        return frame, {}

    lookback_start = _calibrated_lookback_start(end_dt, timeframe_resolution)
    start_dt = _parse_session_datetime(start_date, start_time)
    if start_dt is not None and start_dt < lookback_start:
        lookback_start = start_dt

    try:
        fenced = frame[(frame.index <= end_dt) & (frame.index >= lookback_start)]
        if isinstance(fenced, pd.DataFrame) and not fenced.empty:
            frame = fenced
    except Exception:
        pass

    meta = {
        "temporal_fence_end": end_dt.isoformat(),
        "lookback_start": lookback_start.isoformat(),
        "timeframe_resolution": timeframe_resolution,
    }
    return frame, meta


def evaluate_playbook_quality_barrier(
    data_stream,
    *,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
) -> dict:
    """
    Pre-storage quality gate: anchor hunt + tiered structural move floors.
    1m >= 1.0%, 5m >= 3.0%, 15m >= 5.0%.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    end_dt = _parse_session_datetime(end_date, end_time)
    start_dt = _parse_session_datetime(start_date, start_time)
    lookback_start = _calibrated_lookback_start(end_dt, timeframe_resolution) if end_dt else None
    inner_start = _clamp_inner_move_window(start_dt, end_dt, timeframe_resolution)
    anchor_search_start = lookback_start
    if inner_start is not None and lookback_start is not None:
        anchor_search_start = max(inner_start, lookback_start)
    elif inner_start is not None:
        anchor_search_start = inner_start

    raw_exit_price = _price_at_datetime(data_stream, end_dt)
    entry_resolution = resolve_adaptive_entry_anchor(
        data_stream,
        exit_dt=end_dt,
        manual_entry_dt=start_dt,
        lookback_start_dt=anchor_search_start,
        exit_price=raw_exit_price,
        floor_pct=floor_pct,
        timeframe_resolution=timeframe_resolution,
    )
    anchor_ts = entry_resolution.get("anchor_timestamp")
    anchor_price = entry_resolution.get("anchor_price")
    if anchor_ts is not None and not isinstance(anchor_ts, datetime.datetime):
        try:
            anchor_ts = datetime.datetime.fromisoformat(str(anchor_ts).replace("Z", "+00:00"))
        except ValueError:
            pass

    structural_move_pct = 0.0
    exit_price = raw_exit_price
    exit_anchor_ts = str(end_dt) if end_dt is not None else None
    if anchor_price and raw_exit_price and anchor_price > 0:
        structural_move_pct = abs((raw_exit_price - anchor_price) / anchor_price * 100)
        exit_price, exit_anchor_ts = resolve_stable_profit_exit_anchor(
            data_stream,
            exit_dt=end_dt,
            anchor_price=anchor_price,
            target_move_pct=structural_move_pct,
            timeframe_resolution=timeframe_resolution,
        )
        if exit_price and anchor_price:
            structural_move_pct = abs((exit_price - anchor_price) / anchor_price * 100)

    passed = structural_move_pct >= floor_pct
    quality = {
        "passed": passed,
        "trashed": not passed,
        "structural_move_pct": round(structural_move_pct, 4),
        "floor_pct": floor_pct,
        "anchor_timestamp": str(anchor_ts) if anchor_ts is not None else None,
        "anchor_price": anchor_price,
        "exit_price": exit_price,
        "raw_exit_price": raw_exit_price,
        "exit_anchor_timestamp": exit_anchor_ts,
        "timeframe_resolution": timeframe_resolution,
        "lookback_start": str(lookback_start) if lookback_start else None,
        "exit_cluster_zone": st.session_state.get("room2_exit_cluster_zone", {}),
        "entry_optimizer": entry_resolution.get("optimizer_meta")
        or st.session_state.get("room2_entry_optimizer", {}),
        "entry_candidate_selected": entry_resolution.get("selected_candidate"),
    }
    return enforce_permanent_library_profit_floor(quality)


def resolve_anomaly_incubation_state(
    *,
    match_score: int,
    repeat_count: int,
) -> tuple[str, str]:
    """Map layout match + repetitions to vault track/state."""
    if match_score >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        return "track_1_validated", "active"
    if repeat_count >= ANOMALY_PERMANENT_MINT_COUNT:
        return "track_1_validated", "active"
    return "track_1_anomaly_incubation", VAULT_STATE_INCUBATION


def _extract_layout_number(layout_id: str) -> str:
    text = str(layout_id or "NEW")
    match = re.search(r"(\d+)", text)
    return match.group(1) if match else "NEW"


def _timeframe_token(timeframe_resolution: str) -> str:
    return {"1-Minute": "1M", "5-Minute": "5M", "15-Minute": "15M"}.get(
        timeframe_resolution, "15M"
    )


def resolve_matrix_strategy_id(
    *,
    layout_id: str,
    timeframe_resolution: str,
    spatial_match_pct: int = 0,
) -> str:
    """
    Fluid matrix strategy slot — no manual UI.
    Format: {layoutNumber}{letter} ({timeframe}), e.g. 1A (1M), 1B (5M).
    High spatial match maps to the primary letter in that layout/timeframe bin;
    distinct sub-threshold rhymes mint the next letter (A→B→C…).
    """
    layout_num = _extract_layout_number(layout_id)
    tf = _timeframe_token(timeframe_resolution)
    registry_key = f"{layout_num}|{tf}"
    registry = st.session_state.setdefault("matrix_strategy_letters", {})
    used = list(registry.get(registry_key, []))

    if spatial_match_pct >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        letter = used[0] if used else "A"
    else:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        letter = next((char for char in alphabet if char not in used), "A")
        if letter not in used:
            used.append(letter)
            registry[registry_key] = used
            st.session_state.matrix_strategy_letters = registry

    return f"{layout_num}{letter} ({tf})"


def parse_matrix_meta_from_context(operator_context: str) -> dict:
    """Recover extended vault fields embedded via compact schema fallback."""
    ctx = str(operator_context or "")
    marker = "MATRIX_META:"
    if marker not in ctx:
        return {}
    try:
        blob = ctx.split(marker, 1)[1].strip()
        if " | " in blob:
            blob = blob.split(" | ", 1)[0]
        parsed = json.loads(blob)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _strategy_executions_table() -> str:
    try:
        return st.secrets["SUPABASE_EXECUTIONS_TABLE"]
    except (KeyError, FileNotFoundError, AttributeError):
        return "strategy_executions"


def _strategy_timeline_key(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> str:
    return "|".join(
        (
            str(macro_weather_layout or "").strip(),
            str(execution_strategy or "").strip(),
            str(timeframe_resolution or "").strip(),
        )
    )


def record_strategy_execution(
    *,
    ticker: str,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
    margin_pct: float,
    pattern_category: str = "VALIDATED",
    layout_match_pct: int = 0,
    structural_move_pct: float = 0.0,
) -> tuple[bool, str]:
    """Append one deploy to the winning-DNA execution ledger (rolling last 15 per timeline)."""
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        supabase_key = st.secrets["SUPABASE_KEY"]
    except Exception:
        return False, "offline"

    payload = {
        "ticker": str(ticker).strip().upper(),
        "pattern_category": pattern_category,
        "macro_weather_layout": macro_weather_layout,
        "execution_strategy": execution_strategy,
        "timeframe_resolution": timeframe_resolution,
        "timeline_key": _strategy_timeline_key(
            macro_weather_layout=macro_weather_layout,
            execution_strategy=execution_strategy,
            timeframe_resolution=timeframe_resolution,
        ),
        "margin_pct": round(float(margin_pct), 4),
        "layout_match_pct": int(layout_match_pct),
        "structural_move_pct": round(float(structural_move_pct), 4),
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    table = _strategy_executions_table()
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
        return (True, "logged") if resp.ok else (False, resp.text[:120])
    except Exception as exc:
        return False, str(exc)[:120]


def _append_local_alpha_decay_sample(
    timeline_key: str,
    margin_pct: float,
    *,
    layout_match_pct: int = 0,
    structural_move_pct: float = 0.0,
) -> None:
    session_key = f"alpha_decay_local::{timeline_key}"
    bucket = list(st.session_state.get(session_key, []))
    bucket.insert(
        0,
        {
            "margin_pct": abs(float(margin_pct)),
            "layout_match_pct": int(layout_match_pct),
            "structural_move_pct": float(structural_move_pct),
        },
    )
    st.session_state[session_key] = bucket[:ALPHA_DECAY_ROLLING_N]


def _fetch_execution_samples(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> list[dict]:
    """Pull rolling execution samples for post-mortem retro-analysis."""
    timeline_key = _strategy_timeline_key(
        macro_weather_layout=macro_weather_layout,
        execution_strategy=execution_strategy,
        timeframe_resolution=timeframe_resolution,
    )
    samples: list[dict] = []
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        supabase_key = st.secrets["SUPABASE_KEY"]
        table = _strategy_executions_table()
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}"
            f"?timeline_key=eq.{urllib.parse.quote(timeline_key, safe='')}"
            f"&select=margin_pct,layout_match_pct,structural_move_pct"
            f"&order=recorded_at.desc&limit={ALPHA_DECAY_ROLLING_N}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
            timeout=12,
        )
        if resp.ok:
            for row in resp.json():
                try:
                    samples.append(
                        {
                            "margin_pct": abs(float(row.get("margin_pct", 0))),
                            "layout_match_pct": int(row.get("layout_match_pct") or 0),
                            "structural_move_pct": float(row.get("structural_move_pct") or 0),
                        }
                    )
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    if not samples:
        session_key = f"alpha_decay_local::{timeline_key}"
        raw = st.session_state.get(session_key, [])
        for item in raw:
            if isinstance(item, dict):
                samples.append(item)
            else:
                samples.append({"margin_pct": abs(float(item)), "layout_match_pct": 0, "structural_move_pct": 0})
    return samples


def diagnose_post_mortem_retro_analysis(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> dict:
    """
    Rolling 15-trade post-mortem: halt live execution when below floor and
    separate execution friction from structural alpha decay.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    samples = _fetch_execution_samples(
        macro_weather_layout=macro_weather_layout,
        execution_strategy=execution_strategy,
        timeframe_resolution=timeframe_resolution,
    )
    margins = [s["margin_pct"] for s in samples]
    count = len(margins)
    avg_margin = round(sum(margins) / count, 4) if count else 0.0
    halt_live = count >= ALPHA_DECAY_ROLLING_N and avg_margin < floor_pct

    root_cause = None
    diagnosis = ""
    recommended_action = None
    status = "STABLE"
    strategy_label = execution_strategy or resolve_matrix_strategy_id(
        layout_id=macro_weather_layout,
        timeframe_resolution=timeframe_resolution,
    )

    if halt_live:
        status = EXECUTION_HALTED_STATE
        recent = margins[:5]
        older = margins[5:ALPHA_DECAY_ROLLING_N]
        avg_struct = (
            sum(s.get("structural_move_pct", 0) for s in samples) / count if count else 0.0
        )
        avg_match = (
            sum(s.get("layout_match_pct", 0) for s in samples) / count if count else 0.0
        )
        recent_avg = sum(recent) / len(recent) if recent else 0.0
        older_avg = sum(older) / len(older) if older else avg_margin

        if (
            avg_struct >= floor_pct
            and avg_match >= 70
            and recent_avg < floor_pct
            and older_avg >= floor_pct
        ):
            root_cause = ROOT_CAUSE_FRICTION
            recommended_action = "TWEAK_IN_PLACE"
            diagnosis = (
                f"Live execution HALTED — Strategy {strategy_label}: execution friction / "
                "slippage. Core signature still viable; tweak entry positioning in place — "
                "do not delete the strategy letter."
            )
        else:
            root_cause = ROOT_CAUSE_STRUCTURAL_DECAY
            recommended_action = "DELETE_STRATEGY"
            diagnosis = (
                f"Live execution HALTED — Strategy {strategy_label}: structural alpha decay. "
                "Delete this strategy letter from the layout folder, leaving an open vacancy. "
                "Multi-stock Room 2 validation required before minting a hardened replacement."
            )
    elif count >= ALPHA_DECAY_ROLLING_N and avg_margin < floor_pct:
        status = "DEGRADED"
    elif count >= 5:
        status = "WATCH"

    timeline_key = _strategy_timeline_key(
        macro_weather_layout=macro_weather_layout,
        execution_strategy=execution_strategy,
        timeframe_resolution=timeframe_resolution,
    )
    return {
        "status": status,
        "timeline_key": timeline_key,
        "sample_count": count,
        "avg_margin_pct": avg_margin,
        "floor_pct": floor_pct,
        "window": ALPHA_DECAY_ROLLING_N,
        "evolving": status in (EXECUTION_HALTED_STATE, "DEGRADED"),
        "degraded": status in (EXECUTION_HALTED_STATE, "DEGRADED"),
        "halt_live_execution": halt_live,
        "root_cause": root_cause,
        "recommended_action": recommended_action,
        "diagnosis": diagnosis,
        "strategy_label": strategy_label,
        "multi_stock_validation_required": recommended_action == "DELETE_STRATEGY",
    }


def log_strategy_execution_with_fallback(**kwargs) -> dict:
    """Record execution to Supabase; mirror into session if cloud table missing."""
    margin_pct = float(kwargs.get("margin_pct") or 0.0)
    layout_match_pct = int(kwargs.get("layout_match_pct") or 0)
    structural_move_pct = float(kwargs.get("structural_move_pct") or 0.0)
    timeline_key = _strategy_timeline_key(
        macro_weather_layout=kwargs.get("macro_weather_layout", ""),
        execution_strategy=kwargs.get("execution_strategy", ""),
        timeframe_resolution=kwargs.get("timeframe_resolution", ""),
    )
    ok, _detail = record_strategy_execution(**kwargs)
    if not ok:
        _append_local_alpha_decay_sample(
            timeline_key,
            margin_pct,
            layout_match_pct=layout_match_pct,
            structural_move_pct=structural_move_pct,
        )
    retro = diagnose_post_mortem_retro_analysis(
        macro_weather_layout=kwargs.get("macro_weather_layout", ""),
        execution_strategy=kwargs.get("execution_strategy", ""),
        timeframe_resolution=kwargs.get("timeframe_resolution", ""),
    )
    retro["logged_to_cloud"] = ok
    st.session_state.room2_live_execution_halted = retro.get("halt_live_execution", False)
    if retro.get("halt_live_execution"):
        try:
            import self_surgery

            surgery = execute_autonomous_post_mortem_surgery(
                retro,
                macro_weather_layout=str(kwargs.get("macro_weather_layout") or ""),
                execution_strategy=str(
                    retro.get("strategy_label") or kwargs.get("execution_strategy") or ""
                ),
                timeframe_resolution=str(kwargs.get("timeframe_resolution") or ""),
                entry_coordinate=str(kwargs.get("entry_coordinate") or ""),
                exit_coordinate=str(kwargs.get("exit_coordinate") or ""),
            )
            retro["autonomous_surgery"] = surgery
            demoted = self_surgery.process_post_mortem_demotion(
                retro,
                parent_layout_id=str(kwargs.get("macro_weather_layout") or ""),
                strategy_label=str(
                    retro.get("strategy_label") or kwargs.get("execution_strategy") or ""
                ),
                timeframe_resolution=str(kwargs.get("timeframe_resolution") or ""),
            )
            if demoted:
                retro["repair_bay_demoted"] = True
                retro["repair_bay_profile"] = demoted
                self_surgery.sync_repair_bay_profile_to_cloud(demoted)
        except Exception:
            pass
    return retro


def evaluate_alpha_decay(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> dict:
    """
    Rolling last-N margin monitor — returns DEGRADED when average edge drops below floor.
    Falls back to session ledger when Supabase executions table is unavailable.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    timeline_key = _strategy_timeline_key(
        macro_weather_layout=macro_weather_layout,
        execution_strategy=execution_strategy,
        timeframe_resolution=timeframe_resolution,
    )
    margins: list[float] = []

    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        supabase_key = st.secrets["SUPABASE_KEY"]
        table = _strategy_executions_table()
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}"
            f"?timeline_key=eq.{urllib.parse.quote(timeline_key, safe='')}"
            f"&select=margin_pct&order=recorded_at.desc&limit={ALPHA_DECAY_ROLLING_N}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
            timeout=12,
        )
        if resp.ok:
            for row in resp.json():
                try:
                    margins.append(abs(float(row.get("margin_pct", 0))))
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass

    if not margins:
        session_key = f"alpha_decay_local::{timeline_key}"
        margins = list(st.session_state.get(session_key, []))

    count = len(margins)
    avg_margin = round(sum(margins) / count, 4) if count else 0.0
    degraded = count >= ALPHA_DECAY_ROLLING_N and avg_margin < floor_pct
    status = "DEGRADED" if degraded else ("WATCH" if count >= 5 else "STABLE")
    return {
        "status": status,
        "timeline_key": timeline_key,
        "sample_count": count,
        "avg_margin_pct": avg_margin,
        "floor_pct": floor_pct,
        "window": ALPHA_DECAY_ROLLING_N,
        "evolving": degraded,
        "degraded": degraded,
    }


def refresh_macro_carousel_telemetry(ticker: str) -> None:
    """Cloud-stream 15s macro refresh — institutional + Form4 via cloud pipeline."""
    ticker_clean = str(ticker or "").strip().upper()
    if not ticker_clean:
        return
    bars = _download_yfinance_bars(ticker_clean, "15m", micro_fast_track=False)
    if not is_usable_data_stream(bars):
        return
    fetch_cloud_macro_intelligence(ticker_clean, "15m", bars)
    st.session_state.macro_carousel_last_tick = datetime.datetime.now(
        datetime.timezone.utc
    ).isoformat()


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
    if data_stream is None or is_pipeline_signal(data_stream, "LOCKOUT", "THROTTLE"):
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
    if data_stream is None or is_pipeline_signal(data_stream, "LOCKOUT", "THROTTLE"):
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


def resolve_processor_lane(timeframe_resolution: str) -> str:
    """Route 1m to local strike RAM; 5m/15m to cloud macro pipeline."""
    if str(timeframe_resolution).strip() == "1-Minute":
        return PROCESSOR_LANE_LOCAL_STRIKE
    return PROCESSOR_LANE_CLOUD


def apply_local_strike_ram_cap(data_stream, cap_minutes: int = LOCAL_1M_RAM_CAP_MINUTES):
    """Keep 1m lookback capped in local RAM for low-power IB strike lane."""
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return data_stream
    try:
        latest = frame.index.max()
        cutoff = latest - datetime.timedelta(minutes=cap_minutes)
        trimmed = frame[frame.index >= cutoff]
        if isinstance(trimmed, pd.DataFrame) and not trimmed.empty:
            st.session_state.r2_local_ram_bar_count = len(trimmed)
            return trimmed
    except Exception:
        pass
    return frame


def _fetch_research_news_headlines(ticker: str, *, limit: int = 8) -> list[str]:
    """Cloud-side news wire for Room 2 deep research — keeps heavy I/O off local silicon."""
    headlines: list[str] = []
    ticker_clean = str(ticker).strip().upper()
    try:
        for item in (yf.Ticker(ticker_clean).news or [])[:limit]:
            title = str(item.get("title", "")).strip()
            if title:
                headlines.append(title)
    except Exception:
        pass
    try:
        q = urllib.parse.quote(f"{ticker_clean} stock", safe="")
        rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(rss_url, timeout=12, headers=SEC_HEADERS)
        if resp.ok:
            root = ElementTree.fromstring(resp.content)
            for node in root.findall(".//item/title")[:limit]:
                if node.text:
                    headlines.append(node.text.strip())
    except Exception:
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for headline in headlines:
        key = headline.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(headline)
        if len(unique) >= limit:
            break
    return unique


def _score_news_sentiment(headlines: list[str]) -> dict:
    """Lightweight keyword sentiment array — objective media-flow proxy."""
    bullish = (
        "surge", "beat", "upgrade", "buy", "breakout", "record", "partnership",
        "approval", "contract", "growth", "profit", "raise", "strong",
    )
    bearish = (
        "miss", "downgrade", "sell", "probe", "investigation", "cut", "loss",
        "bankruptcy", "delay", "recall", "lawsuit", "weak", "decline",
    )
    bull_hits = bear_hits = 0
    for headline in headlines:
        low = headline.lower()
        bull_hits += sum(1 for word in bullish if word in low)
        bear_hits += sum(1 for word in bearish if word in low)
    net = bull_hits - bear_hits
    if net >= 2:
        bias = "POSITIVE_FLOW"
    elif net <= -2:
        bias = "NEGATIVE_FLOW"
    else:
        bias = "NEUTRAL_FLOW"
    return {
        "bias": bias,
        "bullish_hits": bull_hits,
        "bearish_hits": bear_hits,
        "headline_count": len(headlines),
    }


def _audit_price_action_mechanics(
    data_stream,
    end_dt: datetime.datetime | None,
    lookback_start_dt: datetime.datetime | None,
    quality: dict | None = None,
) -> dict:
    """Price-action track: velocity, spread expansion, VWAP baseline, Pearson cleanliness."""
    frame = _ensure_dataframe(data_stream)
    if frame is None or end_dt is None:
        return {}
    try:
        if lookback_start_dt is not None:
            window = frame[(frame.index <= end_dt) & (frame.index >= lookback_start_dt)]
        else:
            window = frame[frame.index <= end_dt]
        if not isinstance(window, pd.DataFrame) or window.empty:
            return {}

        closes = window["Close"].astype(float)
        open_px = float(closes.iloc[0])
        close_px = float(closes.iloc[-1])
        velocity_pct = ((close_px - open_px) / open_px * 100) if open_px else 0.0

        spread_pct = ((window["High"] - window["Low"]) / window["Close"].replace(0, pd.NA) * 100).astype(float)
        spread_pct = spread_pct.fillna(0.0)
        if len(spread_pct) >= 6:
            spread_expansion = float(spread_pct.iloc[-3:].mean() - spread_pct.iloc[:3].mean())
        else:
            spread_expansion = float(spread_pct.mean()) if len(spread_pct) else 0.0

        vol_sum = float(window["Volume"].sum()) if "Volume" in window.columns else 0.0
        if vol_sum > 0:
            vwap = float((window["Close"] * window["Volume"]).sum() / vol_sum)
        else:
            vwap = close_px

        pearson_r = 0.0
        if len(closes) >= 4:
            returns = closes.pct_change().dropna()
            benchmark = returns.expanding().mean().dropna()
            aligned = returns.loc[benchmark.index]
            if len(aligned) >= 3 and aligned.std() > 0 and benchmark.std() > 0:
                pearson_r = float(aligned.corr(benchmark))

        anchor_ts = (quality or {}).get("anchor_timestamp")
        anchor_price = (quality or {}).get("anchor_price")
        return {
            "session_velocity_pct": round(velocity_pct, 3),
            "spread_expansion_pct": round(spread_expansion, 3),
            "vwap_baseline": round(vwap, 4),
            "pearson_cleanliness": round(pearson_r, 4),
            "bar_count": len(window),
            "anchor_timestamp": anchor_ts,
            "anchor_price": anchor_price,
        }
    except Exception:
        return {}


def build_text_matrix_string(
    *,
    ticker: str,
    trading_day,
    anchor_timestamp,
    structural_move_pct: float,
    price_action: dict,
    news_sentiment: dict,
    news_headlines: list[str],
    form4: dict,
    institutional: dict,
    timeframe_resolution: str,
    metric_envelopes: dict | None = None,
    semantic_catalyst: dict | None = None,
) -> str:
    """Flatten multi-layer audit into a lightweight, vault-durable Text Matrix String."""
    day_label = str(trading_day or "")[:10]
    anchor_label = str(anchor_timestamp or "UNKNOWN")[:19]
    headlines = " || ".join(news_headlines[:3])[:180] if news_headlines else "NONE"
    form4_summary = str((form4 or {}).get("form4_summary", "FORM4:NA"))[:80]
    inst_summary = str((institutional or {}).get("inst_block_summary", "INST:NA"))[:80]
    env = metric_envelopes or {}
    vol_env = env.get("volume", {})
    vol_band = (
        f"{vol_env.get('low', 0)}-{vol_env.get('high', 0)}"
        if vol_env
        else "NA"
    )
    sem = semantic_catalyst or news_sentiment or {}
    sem_impact = sem.get("impact_weight", sem.get("bias", "NEUTRAL"))
    return (
        f"TEXT_MATRIX|TKR:{ticker}|DAY:{day_label}|TF:{timeframe_resolution}|"
        f"ANCHOR:{anchor_label}|MOVE:{float(structural_move_pct or 0):.2f}%|"
        f"PA:VEL={price_action.get('session_velocity_pct', 0)}|"
        f"SPREAD={price_action.get('spread_expansion_pct', 0)}|"
        f"VWAP={price_action.get('vwap_baseline', 0)}|"
        f"PEARSON={price_action.get('pearson_cleanliness', 0)}|"
        f"VOL_ENV:{vol_band}|SEM_IMPACT:{sem_impact}|"
        f"HDLNS:{headlines}|FORM4:{form4_summary}|INST:{inst_summary}"
    )


def run_deep_internet_research_audit(
    *,
    ticker: str,
    data_stream,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
    quality: dict | None = None,
) -> dict:
    """
    Room 2 manual training — time-unconstrained, cloud-side deep research engine.
    Cross-correlates price mechanics, breaking news sentiment, and SEC Form 4 filings
    to extract the objective volume anchor catalyst without draining local MacBook power.
    """
    ticker_clean = str(ticker).strip().upper()
    end_dt = _parse_session_datetime(end_date, end_time)
    lookback_start = _calibrated_lookback_start(end_dt, timeframe_resolution) if end_dt else None
    start_dt = _parse_session_datetime(start_date, start_time)
    if start_dt is not None and lookback_start is not None and start_dt < lookback_start:
        lookback_start = start_dt

    if quality is None and is_usable_data_stream(data_stream):
        quality = evaluate_playbook_quality_barrier(
            data_stream,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
            timeframe_resolution=timeframe_resolution,
        )
    quality = quality or {}

    dragnet_blob: dict = {}
    dragnet_start = lookback_start
    audit_frame = data_stream
    if timeframe_resolution in DRAGNET_TIMEFRAMES:
        dragnet_blob = run_full_day_forensic_dragnet(
            ticker=ticker_clean,
            end_date=end_date,
            end_time=end_time,
            timeframe_resolution=timeframe_resolution,
        )
        dragnet_start = _research_dragnet_lookback_start(end_dt, timeframe_resolution)
        raw_drag = pad_datastream_gaps(
            _download_yfinance_bars(
                ticker_clean,
                {"5-Minute": "5m", "15-Minute": "15m"}.get(timeframe_resolution, "15m"),
            )
        )
        dragnet_df = _ensure_dataframe(raw_drag)
        if dragnet_df is not None and dragnet_start is not None and end_dt is not None:
            try:
                sliced = dragnet_df[
                    (dragnet_df.index <= end_dt) & (dragnet_df.index >= dragnet_start)
                ]
                if isinstance(sliced, pd.DataFrame) and not sliced.empty:
                    audit_frame = sliced
            except Exception:
                pass

    metric_envelopes = compute_metric_envelopes(audit_frame, end_dt, dragnet_start)
    if dragnet_blob.get("metric_envelopes"):
        metric_envelopes = dragnet_blob["metric_envelopes"]

    price_action = _audit_price_action_mechanics(
        audit_frame, end_dt, dragnet_start, quality
    )
    if metric_envelopes:
        price_action["metric_envelopes"] = metric_envelopes

    yf_interval = {"1-Minute": "1m", "5-Minute": "5m", "15-Minute": "15m"}.get(
        timeframe_resolution, "15m"
    )
    try:
        institutional = dragnet_blob.get("institutional") or _detect_institutional_block_accumulation(
            ticker_clean, audit_frame, yf_interval
        )
        st.session_state.forensic_institutional_tracker = institutional
    except Exception:
        institutional = st.session_state.get("forensic_institutional_tracker", {})

    try:
        form4 = dragnet_blob.get("form4") or _scrape_form4_insider_buys(ticker_clean)
        st.session_state.forensic_form4_tracker = form4
    except Exception:
        form4 = st.session_state.get("forensic_form4_tracker", {})

    news_headlines = dragnet_blob.get("news_headlines") or _fetch_research_news_headlines(
        ticker_clean
    )
    sec_dragnet = _scrape_sec_regulatory_dragnet(ticker_clean)
    filing_texts = [
        f"SEC {f.get('form', 'FILING')} filed {f.get('filing_date', '')}"
        for f in (sec_dragnet.get("filings") or [])
    ]
    semantic_catalyst = dragnet_blob.get("semantic_catalyst") or score_semantic_catalyst_stream(
        news_headlines,
        filing_texts=filing_texts,
    )
    news_sentiment = semantic_catalyst

    master_sig = st.session_state.get("room2_master_signature") or {}
    genetic_json = json.dumps(
        {
            "master_signature": master_sig.get("master_signature") or [],
            "overlap_pct": master_sig.get("overlap_pct", 0),
            "dimensions_trashed": master_sig.get("dimensions_trashed", 0),
            "pure_overlap_dims": master_sig.get("pure_overlap_dims", 0),
            "finbert_sentiment_score": semantic_catalyst.get("finbert_sentiment_score", 0.0),
        },
        default=str,
    )

    text_matrix_string = build_text_matrix_string(
        ticker=ticker_clean,
        trading_day=end_date,
        anchor_timestamp=quality.get("anchor_timestamp"),
        structural_move_pct=float(quality.get("structural_move_pct") or 0.0),
        price_action=price_action,
        news_sentiment=news_sentiment,
        news_headlines=news_headlines,
        form4=form4,
        institutional=institutional,
        timeframe_resolution=timeframe_resolution,
        metric_envelopes=metric_envelopes,
        semantic_catalyst=semantic_catalyst,
    )

    forensic_dragnet_json = json.dumps(dragnet_blob, default=str) if dragnet_blob else ""

    audit = {
        "research_mode": "deep_training_cloud",
        "processor_lane": PROCESSOR_LANE_CLOUD,
        "text_matrix_string": text_matrix_string,
        "forensic_dragnet_blob": forensic_dragnet_json,
        "metric_envelopes": metric_envelopes,
        "semantic_catalyst": semantic_catalyst,
        "master_signature_json": genetic_json,
        "price_action": price_action,
        "news_sentiment": news_sentiment,
        "news_headlines": news_headlines,
        "form4": form4,
        "institutional": institutional,
        "anchor_timestamp": quality.get("anchor_timestamp"),
        "anchor_price": quality.get("anchor_price"),
        "structural_move_pct": quality.get("structural_move_pct"),
    }
    st.session_state.room2_deep_research_audit = audit
    st.session_state.room2_text_matrix_string = text_matrix_string
    return audit


def fetch_cloud_macro_intelligence(ticker: str, interval: str, data_stream=None) -> dict:
    """
    Cloud-side dual-stream pipeline — institutional volume, SEC Form 4, macro bars.
    Offloads heavy 5m/15m gathering from the local MacBook battery.
    """
    ticker_clean = str(ticker).strip().upper()
    bundle = {
        "processor_lane": PROCESSOR_LANE_CLOUD,
        "interval": interval,
        "ticker": ticker_clean,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    try:
        institutional = _detect_institutional_block_accumulation(
            ticker_clean, data_stream, interval
        )
        st.session_state.forensic_institutional_tracker = institutional
        bundle["institutional"] = institutional
    except Exception:
        bundle["institutional"] = st.session_state.get("forensic_institutional_tracker", {})
    try:
        form4 = _scrape_form4_insider_buys(ticker_clean)
        st.session_state.forensic_form4_tracker = form4
        bundle["form4"] = form4
    except Exception:
        bundle["form4"] = st.session_state.get("forensic_form4_tracker", {})
    st.session_state.cloud_macro_intelligence = bundle
    st.session_state.r2_processor_lane = PROCESSOR_LANE_CLOUD
    return bundle


def get_historical_interval_data(
    ticker,
    interval="15m",
    update_institutional_tracker=True,
    force_yfinance_only=False,
    micro_fast_track=False,
):
    """
    Dual-stream datalink:
    - 1m local strike lane: tight RAM cap, no cloud macro scrape on deploy.
    - 5m/15m cloud lane: Polygon/yfinance bars + cloud macro intelligence bundle.
    """
    try:
        return _get_historical_interval_data_impl(
            ticker,
            interval=interval,
            update_institutional_tracker=update_institutional_tracker,
            force_yfinance_only=force_yfinance_only or micro_fast_track,
            micro_fast_track=micro_fast_track,
        )
    except Exception:
        return None


def _get_historical_interval_data_impl(
    ticker,
    interval="15m",
    update_institutional_tracker=True,
    force_yfinance_only=False,
    micro_fast_track=False,
):
    ticker_clean = str(ticker).strip().upper()
    if not ticker_clean:
        return None

    now = datetime.datetime.now()
    interval = str(interval).lower()
    yf_interval = interval if interval in {"1m", "5m", "15m", "1h", "1d"} else "15m"

    if micro_fast_track:
        update_institutional_tracker = False
        st.session_state.r2_processor_lane = PROCESSOR_LANE_LOCAL_STRIKE
        start_date = (now - datetime.timedelta(hours=8)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        polygon_bars, polygon_signal = _fetch_polygon_1m_bars(
            ticker_clean, start_date, end_date
        )
        if polygon_signal == "THROTTLE":
            st.session_state.r2_micro_feed_source = DATA_FEED_YFINANCE_1M
            st.session_state.polygon_lockout = True
            return "THROTTLE"
        polygon_frame = _polygon_aggs_to_dataframe(polygon_bars)
        if is_usable_data_stream(polygon_frame):
            st.session_state.r2_micro_feed_source = DATA_FEED_POLYGON_1M
            return apply_local_strike_ram_cap(polygon_frame)
        st.session_state.r2_micro_feed_source = DATA_FEED_YFINANCE_1M
    else:
        st.session_state.r2_processor_lane = PROCESSOR_LANE_CLOUD

    data_stream = _download_yfinance_bars(
        ticker_clean, yf_interval, micro_fast_track=micro_fast_track
    )

    if (
        data_stream is None
        and not force_yfinance_only
        and not micro_fast_track
        and yf_interval == "15m"
    ):
        start_date = (now - datetime.timedelta(days=730)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")
        polygon_bars, polygon_signal = _fetch_polygon_15m_bars(
            ticker_clean, start_date, end_date
        )
        if polygon_signal == "THROTTLE":
            st.session_state.forensic_institutional_tracker = {
                "institutional_block_accumulation": False,
                "inst_block_summary": "INST_BLOCK: THROTTLED",
                "volume_baseline_20d": 0.0,
                "peak_surge_ratio": 0.0,
            }
            return "THROTTLE"
        if is_usable_data_stream(polygon_bars):
            polygon_frame = _polygon_aggs_to_dataframe(polygon_bars)
            if is_usable_data_stream(polygon_frame):
                data_stream = polygon_frame

    if micro_fast_track and is_usable_data_stream(data_stream):
        return apply_local_strike_ram_cap(data_stream)

    if (
        is_usable_data_stream(data_stream)
        and update_institutional_tracker
        and not micro_fast_track
    ):
        fetch_cloud_macro_intelligence(ticker_clean, yf_interval, data_stream)
    elif update_institutional_tracker and not micro_fast_track:
        st.session_state.forensic_institutional_tracker = {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: CLOUD_PENDING",
            "volume_baseline_20d": 0.0,
            "peak_surge_ratio": 0.0,
        }
        st.session_state.forensic_form4_tracker = {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: CLOUD_PENDING",
            "insider_events": [],
        }
    elif micro_fast_track:
        st.session_state.forensic_institutional_tracker = {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: LOCAL_STRIKE_BYPASS",
            "volume_baseline_20d": 0.0,
            "peak_surge_ratio": 0.0,
        }
        st.session_state.forensic_form4_tracker = {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: LOCAL_STRIKE_BYPASS",
            "insider_events": [],
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


def extract_forensic_feature_vector(
    velocity: dict,
    math_block: dict,
    finbert_sentiment: float = 0.0,
) -> list[float]:
    """Snapshot vector for spatial cross-correlation — includes FinBERT sentiment axis."""
    return [
        float(velocity.get("session_velocity_pct", 0.0)),
        float(velocity.get("peak_bar_velocity_pct", 0.0)),
        float(velocity.get("mean_bar_velocity_pct", 0.0)),
        float(velocity.get("window_amplitude_pct", 0.0)),
        float(math_block.get("pearson_r", 0.0)),
        float(math_block.get("wave_amplitude_pct", 0.0)),
        min(float(math_block.get("bar_count", 0)) / 100.0, 10.0),
        float(finbert_sentiment),
    ]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _euclidean_distance(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 999.0
    return sum((a - b) ** 2 for a, b in zip(vec_a, vec_b)) ** 0.5


def compute_spatial_layout_match(
    snapshot_vec: list[float],
    library: list[dict] | None = None,
) -> dict:
    """Cosine/Euclidean spatial clustering vs compressed master matrix index."""
    library = library or list(st.session_state.get("layout_master_matrix_index", []))
    best_cosine = 0.0
    best_euclidean = 999.0
    nearest_layout = "NEW_LAYOUT"
    for entry in library:
        stored = entry.get("vector") or []
        cos = _cosine_similarity(snapshot_vec, stored)
        euc = _euclidean_distance(snapshot_vec, stored)
        if cos > best_cosine:
            best_cosine = cos
            best_euclidean = euc
            nearest_layout = str(entry.get("layout_id") or "LAYOUT")
    spatial_pct = int(round(best_cosine * 100))
    return {
        "spatial_match_pct": spatial_pct,
        "cosine_similarity": round(best_cosine, 4),
        "euclidean_distance": round(best_euclidean, 4),
        "nearest_layout_id": nearest_layout,
    }


def register_layout_vector_in_master_index(
    *,
    layout_id: str,
    vector: list[float],
    ticker: str,
    timeframe_resolution: str,
) -> None:
    """Ultra-compressed master matrix index — prevents layout token amnesia."""
    index = list(st.session_state.get("layout_master_matrix_index", []))
    index.insert(
        0,
        {
            "layout_id": layout_id,
            "vector": vector,
            "ticker": str(ticker).upper(),
            "timeframe_resolution": timeframe_resolution,
        },
    )
    st.session_state.layout_master_matrix_index = index[:256]


def _supabase_rest_headers() -> dict:
    try:
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        return {}
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _parse_master_signature_from_row(row: dict) -> list[float]:
    """Decode stored master_signature_json into a numeric feature vector."""
    raw = row.get("master_signature_json") or ""
    if not raw:
        return []
    try:
        blob = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(blob, dict):
        return []
    vec = blob.get("master_signature") or blob.get("master_signature_preview") or []
    if isinstance(vec, list) and vec:
        return [float(x) for x in vec]
    return []


def hydrate_layout_library_from_vault() -> int:
    """
    Startup memory hydration — pull permanent layout vectors from Supabase vault_track
    so spatial matching survives browser refresh.
    """
    if st.session_state.get("layout_library_hydrated"):
        return len(st.session_state.get("layout_master_matrix_index", []))

    st.session_state.layout_library_hydrated = True
    headers = _supabase_rest_headers()
    if not headers:
        st.session_state.setdefault("layout_master_matrix_index", [])
        return 0

    table = _supabase_table_name()
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}"
            "?select=macro_weather_layout,ticker,timeframe_resolution,master_signature_json,"
            "structural_move_pct,vault_track,state"
            "&vault_track=eq.track_1_validated"
            "&or=(state.is.null,state.eq.active)"
            "&order=timestamp.desc&limit=500",
            headers=headers,
            timeout=20,
        )
        if not resp.ok:
            st.session_state.setdefault("layout_master_matrix_index", [])
            return 0
        rows = resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        st.session_state.setdefault("layout_master_matrix_index", [])
        return 0

    index: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        layout_id = str(row.get("macro_weather_layout") or "").strip()
        vector = _parse_master_signature_from_row(row)
        if not layout_id or not vector:
            continue
        dedupe = f"{layout_id}|{row.get('timeframe_resolution')}|{row.get('ticker')}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        index.append(
            {
                "layout_id": layout_id,
                "vector": vector,
                "ticker": str(row.get("ticker") or "").upper(),
                "timeframe_resolution": str(row.get("timeframe_resolution") or ""),
                "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
            }
        )

    st.session_state.layout_master_matrix_index = index[:256]
    return len(index)


def estimate_room1_message_tokens(messages: list | None) -> int:
    """Rough token estimate for volatile Room 1 thread capacity monitoring."""
    total = 0
    for msg in messages or []:
        total += max(1, len(str(msg.get("content", ""))) // 4)
    return total


def room1_memory_capacity_status(
    messages: list | None,
    *,
    pending_user_text: str = "",
    pending_assistant_reserve: int = ROOM1_ASSISTANT_TOKEN_RESERVE,
) -> dict:
    """
    Volatile RAM capacity gates for Room 1 — warn at 90%, hard-lock input at 100%.
    """
    msgs = list(messages or [])
    if pending_user_text:
        msgs.append({"role": "user", "content": pending_user_text})
    used = estimate_room1_message_tokens(msgs)
    if pending_user_text:
        used += pending_assistant_reserve
    budget = ROOM1_TOKEN_BUDGET
    ratio = used / budget if budget else 0.0
    locked = ratio >= 1.0
    warn_active = ratio >= ROOM1_WARN_RATIO and not locked
    dialog_count = sum(1 for m in msgs if m.get("role") in ("user", "assistant"))
    avg_turn = max(400, used // max(1, dialog_count))
    remaining_msgs = min(
        ROOM1_WARN_MESSAGES_REMAINING,
        max(0, int((budget - used) / avg_turn)),
    )
    return {
        "used_tokens": used,
        "budget_tokens": budget,
        "fill_ratio": round(ratio, 4),
        "warn_active": warn_active,
        "locked": locked,
        "messages_remaining": remaining_msgs,
    }


def room1_forbid_cloud_write(operation: str) -> None:
    """Room 1 is read-only — block any accidental vault mutation from the front desk."""
    raise RuntimeError(
        f"Room 1 forbids Supabase {operation} on strategy vaults and layout tables."
    )


def _room1_supabase_get(table: str, *, params: dict | None = None) -> list[dict]:
    """Read-only GET plumbing for Room 1 cross-reference — no insert/update/delete."""
    headers = _supabase_rest_headers()
    if not headers:
        return []
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}",
            headers=headers,
            params=params or {},
            timeout=20,
        )
        if resp.ok and isinstance(resp.json(), list):
            return resp.json()
    except Exception:
        pass
    return []


def fetch_readonly_vault_reference_map() -> dict:
    """
    Pull permanent layout/strategy feature vectors into temporary RAM for Room 1 audits.
    Supabase access is GET-only — zero writes.
    """
    hydrate_layout_library_from_vault()
    layout_vectors = list(st.session_state.get("layout_master_matrix_index") or [])
    table = _supabase_table_name()
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}"
            "?select=macro_weather_layout,execution_strategy,timeframe_resolution,"
            "structural_move_pct,vault_track,state,ticker"
            "&vault_track=eq.track_1_validated"
            "&or=(state.is.null,state.eq.active)"
            "&order=timestamp.desc&limit=120",
            headers=headers,
            timeout=20,
        )
        strategy_rows = resp.json() if resp.ok and isinstance(resp.json(), list) else []
    except Exception:
        strategy_rows = []
    profiles: list[dict] = []
    seen: set[str] = set()
    for row in strategy_rows:
        layout_id = str(row.get("macro_weather_layout") or "").strip()
        strategy = str(row.get("execution_strategy") or "").strip()
        timeframe = str(row.get("timeframe_resolution") or "").strip()
        if not layout_id or not strategy:
            continue
        key = f"{layout_id}|{strategy}|{timeframe}"
        if key in seen:
            continue
        seen.add(key)
        profiles.append(
            {
                "layout_id": layout_id,
                "strategy_label": strategy,
                "timeframe_resolution": timeframe,
                "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
                "reference_ticker": str(row.get("ticker") or "").upper(),
            }
        )
    return {
        "readonly": True,
        "layout_vector_count": len(layout_vectors),
        "layout_vectors": layout_vectors[:48],
        "strategy_profiles": profiles[:48],
    }


def is_room1_strategic_audit_query(user_text: str, ticker: str | None) -> bool:
    """Detect strategic stock audit requests — ticker required."""
    if not ticker:
        return False
    low = str(user_text or "").lower()
    audit_terms = (
        "audit",
        "analyze",
        "analysis",
        "report",
        "playbook",
        "layout",
        "strategy",
        "match",
        "breakdown",
        "deep dive",
        "correlate",
        "setup",
        "scan",
        "rhyme",
        "compare",
    )
    if any(term in low for term in audit_terms):
        return True
    return len(low.split()) <= 8


def _room1_quick_math_block(data_stream) -> dict:
    """Lightweight live physics block for Room 1 cross-reference — no cloud writes."""
    series = _series_from_data_stream(data_stream)
    pearson_r = 0.0
    wave_amp = 0.0
    bar_count = 0
    if series is not None:
        bar_count = len(series) if hasattr(series, "__len__") else 0
        wave_amp = _wave_amplitude_pct(series)
        if pd is not None and isinstance(series, pd.Series) and len(series) >= 3:
            try:
                ys = [float(v) for v in series.tolist()]
                n = len(ys)
                xs = list(range(n))
                mean_x = sum(xs) / n
                mean_y = sum(ys) / n
                num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
                den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
                den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
                if den_x > 0 and den_y > 0:
                    pearson_r = num / (den_x * den_y)
            except Exception:
                pearson_r = 0.0
    return {
        "pearson_r": round(pearson_r, 4),
        "wave_amplitude_pct": round(wave_amp, 4),
        "bar_count": bar_count,
        "match_probability": 0,
    }


def run_room1_strategic_audit_dragnet(ticker: str, user_query: str = "") -> dict:
    """
    Deep external internet reporting + read-only vault cross-reference on local RAM.
    Combines live headlines, SEC timelines, and layout signature matching.
    """
    ticker_clean = str(ticker).strip().upper()
    vault_map = fetch_readonly_vault_reference_map()
    library = vault_map.get("layout_vectors") or []

    data_stream = get_historical_interval_data(
        ticker_clean,
        interval="15m",
        update_institutional_tracker=False,
    )
    velocity = _compute_price_velocity_metrics(data_stream)
    math_block = _room1_quick_math_block(data_stream)

    headlines = _fetch_research_news_headlines(ticker_clean, limit=8)
    sec_dragnet = _scrape_sec_regulatory_dragnet(ticker_clean)
    form4 = _scrape_form4_insider_buys(ticker_clean)
    filing_texts = [
        f"SEC {f.get('form', 'FILING')} filed {f.get('filing_date', '')}"
        for f in (sec_dragnet.get("filings") or [])
    ]
    semantic = score_semantic_catalyst_stream(headlines, filing_texts=filing_texts)
    finbert_score = float(semantic.get("finbert_sentiment_score") or 0.0)

    live_vec = extract_forensic_feature_vector(velocity, math_block, finbert_score)
    spatial = compute_spatial_layout_match(live_vec, library)

    alignments: list[dict] = []
    for entry in library[:32]:
        stored = entry.get("vector") or []
        if not stored or len(stored) != len(live_vec):
            continue
        cos = _cosine_similarity(live_vec, stored)
        alignments.append(
            {
                "layout_id": entry.get("layout_id"),
                "timeframe_resolution": entry.get("timeframe_resolution"),
                "reference_ticker": entry.get("ticker"),
                "cosine_similarity": round(cos, 4),
                "spatial_match_pct": int(round(cos * 100)),
            }
        )
    alignments.sort(key=lambda row: row.get("cosine_similarity", 0), reverse=True)
    top_alignments = alignments[:5]

    nearest_profile = None
    for profile in vault_map.get("strategy_profiles") or []:
        if str(profile.get("layout_id")) == str(spatial.get("nearest_layout_id")):
            nearest_profile = profile
            break

    headline_preview = " | ".join(headlines[:4]) if headlines else "NONE"
    sec_preview = ", ".join(
        f"{f.get('form')}@{f.get('filing_date')}" for f in (sec_dragnet.get("filings") or [])[:4]
    ) or "NONE"

    report_lines = [
        f"ROOM1_STRATEGIC_AUDIT|TK:{ticker_clean}",
        f"VAULT_REF_VECTORS:{vault_map.get('layout_vector_count', 0)}",
        f"NEAREST_LAYOUT:{spatial.get('nearest_layout_id')}",
        f"SPATIAL_MATCH:{spatial.get('spatial_match_pct')}%",
        f"SESSION_VELOCITY:{velocity.get('session_velocity_pct')}%",
        f"FINBERT_SENTIMENT:{finbert_score}",
        f"LIVE_HEADLINES:{headline_preview}",
        f"SEC_TIMELINE:{sec_preview}",
        f"FORM4:{form4.get('form4_summary', 'N/A')}",
    ]
    if nearest_profile:
        report_lines.append(
            f"PLAYBOOK_REF:{nearest_profile.get('strategy_label')}@"
            f"{nearest_profile.get('layout_id')}@"
            f"{nearest_profile.get('timeframe_resolution')}"
        )
    if top_alignments:
        rhyme = " · ".join(
            f"{a['layout_id']}({a['spatial_match_pct']}%)" for a in top_alignments[:3]
        )
        report_lines.append(f"MATHEMATICAL_RHYMES:{rhyme}")

    report_lines.append(
        "READONLY_CROSSREF: Live internet physics cross-correlated against permanent "
        "Room 2 vault signatures in local RAM — no database writes executed."
    )
    if user_query.strip():
        report_lines.append(f"OPERATOR_QUERY:{user_query.strip()[:240]}")

    report_block = " | ".join(report_lines)
    st.session_state.room1_last_strategic_audit = {
        "ticker": ticker_clean,
        "spatial": spatial,
        "vault_map": {
            "layout_vector_count": vault_map.get("layout_vector_count", 0),
            "strategy_profile_count": len(vault_map.get("strategy_profiles") or []),
        },
        "semantic": semantic,
        "top_alignments": top_alignments,
        "report_block": report_block,
    }
    return st.session_state.room1_last_strategic_audit


def execute_autonomous_post_mortem_surgery(
    retro: dict,
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
    entry_coordinate: str = "",
    exit_coordinate: str = "",
) -> dict:
    """
    Hands-free database surgery on 15-trade floor breach.
    Alpha decay → delete active strategy row + PURGATORY state.
    Execution friction → update entry trigger coordinates in cloud.
    """
    if not retro.get("halt_live_execution"):
        return {"surgery": "skipped"}

    headers = _supabase_rest_headers()
    if not headers:
        return {"surgery": "offline"}

    table = _supabase_table_name()
    supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
    layout = str(macro_weather_layout or "").strip()
    strategy = str(execution_strategy or retro.get("strategy_label") or "").strip()
    timeframe = str(timeframe_resolution or "").strip()
    action = retro.get("recommended_action") or ""
    result: dict = {"surgery": action or "halt", "layout": layout, "strategy": strategy}

    try:
        if action == "DELETE_STRATEGY":
            requests.delete(
                f"{supabase_url}/rest/v1/{table}",
                headers=headers,
                params={
                    "macro_weather_layout": f"eq.{layout}",
                    "execution_strategy": f"eq.{strategy}",
                    "timeframe_resolution": f"eq.{timeframe}",
                    "state": "eq.active",
                },
                timeout=12,
            )
            requests.patch(
                f"{supabase_url}/rest/v1/{table}",
                headers=headers,
                params={
                    "macro_weather_layout": f"eq.{layout}",
                    "execution_strategy": f"eq.{strategy}",
                    "timeframe_resolution": f"eq.{timeframe}",
                },
                json={"state": VAULT_STATE_PURGATORY},
                timeout=12,
            )
            result["database_action"] = "delete_and_purgatory"
        elif action == "TWEAK_IN_PLACE" and entry_coordinate:
            patch = {"entry_coordinate": entry_coordinate}
            if exit_coordinate:
                patch["exit_coordinate"] = exit_coordinate
            requests.patch(
                f"{supabase_url}/rest/v1/{table}",
                headers=headers,
                params={
                    "macro_weather_layout": f"eq.{layout}",
                    "execution_strategy": f"eq.{strategy}",
                    "timeframe_resolution": f"eq.{timeframe}",
                    "state": "eq.active",
                },
                json=patch,
                timeout=12,
            )
            result["database_action"] = "entry_tweak_update"
        else:
            result["database_action"] = "diagnosis_only"
    except Exception as exc:
        result["database_action"] = "error"
        result["detail"] = str(exc)[:120]

    return result


def _geometric_delta_sign(delta: float) -> str:
    """Pure geometric sign — no human trend vocabulary."""
    if delta > 0:
        return "GEOM+"
    if delta < 0:
        return "GEOM-"
    return "GEOM0"


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
    trend_bias = "GEOM0"

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
            trend_bias = _geometric_delta_sign(delta)
        elif isinstance(series, list):
            bar_count = len(series)
            if bar_count >= 2:
                amplitude = _wave_amplitude_pct(series)
                delta = series[-1] - series[0]
                trend_bias = _geometric_delta_sign(delta)

    category = (pattern_category or "UNCLASSIFIED").strip().upper()
    category_factor = 1.0
    structural_score = min(
        99,
        max(
            52,
            int(
                62
                + (abs(pearson_r) * 18)
                + min(amplitude, 12)
                + (6 if trend_bias != "GEOM0" else 0)
            ),
        ),
    )

    if entry_price and exit_price and entry_price > 0:
        realized_move = ((exit_price - entry_price) / entry_price) * 100
    else:
        realized_move = None

    quantum_report = (
        f"Quant Matrix | Layout-Class: {category} | Bars: {bar_count} | "
        f"Wave Amplitude: {amplitude:.2f}% | Pearson r: {pearson_r:.3f} | "
        f"Geometric Delta: {trend_bias} | Structural Match: {structural_score}% | "
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


def _parse_session_datetime(date_val, time_str: str):
    if not date_val or not time_str:
        return None
    try:
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%Y-%m-%d")
        else:
            date_str = str(date_val)[:10]
        time_clean = str(time_str).strip().upper()
        return datetime.datetime.strptime(f"{date_str} {time_clean}", "%Y-%m-%d %I:%M %p")
    except Exception:
        return None


def _format_session_duration(start_dt, end_dt) -> str:
    if not start_dt or not end_dt:
        return "UNRESOLVED"
    delta = end_dt - start_dt
    if delta.total_seconds() < 0:
        return "INVALID — END PRECEDES START"
    total_min = int(delta.total_seconds() // 60)
    hours, minutes = divmod(total_min, 60)
    return f"{hours}H {minutes:02d}M | {total_min} MIN ELAPSED"


def _compute_price_velocity_metrics(data_stream) -> dict:
    """Raw percentage velocity moves from the active 15m execution window."""
    series = _series_from_data_stream(data_stream)
    if series is None:
        return {
            "session_velocity_pct": 0.0,
            "peak_bar_velocity_pct": 0.0,
            "mean_bar_velocity_pct": 0.0,
            "window_amplitude_pct": 0.0,
        }
    if pd is not None and isinstance(series, pd.Series) and len(series) >= 2:
        first = float(series.iloc[0])
        last = float(series.iloc[-1])
        session_velocity = ((last - first) / first * 100) if first else 0.0
        returns = series.pct_change().dropna()
        peak_bar = float(returns.abs().max() * 100) if len(returns) else 0.0
        mean_bar = float(returns.abs().mean() * 100) if len(returns) else 0.0
        amplitude = _wave_amplitude_pct(series)
        return {
            "session_velocity_pct": round(session_velocity, 4),
            "peak_bar_velocity_pct": round(peak_bar, 4),
            "mean_bar_velocity_pct": round(mean_bar, 4),
            "window_amplitude_pct": round(amplitude, 4),
        }
    if isinstance(series, list) and len(series) >= 2:
        first, last = series[0], series[-1]
        session_velocity = ((last - first) / first * 100) if first else 0.0
        return {
            "session_velocity_pct": round(session_velocity, 4),
            "peak_bar_velocity_pct": 0.0,
            "mean_bar_velocity_pct": 0.0,
            "window_amplitude_pct": round(_wave_amplitude_pct(series), 4),
        }
    return {
        "session_velocity_pct": 0.0,
        "peak_bar_velocity_pct": 0.0,
        "mean_bar_velocity_pct": 0.0,
        "window_amplitude_pct": 0.0,
    }


def _matrix_row(label: str, value: str, width: int = 38) -> str:
    text = f"{label}: {value}" if label else str(value)
    if len(text) > width:
        text = text[: width - 3] + "..."
    return f"│ {text:<{width}} │"


def _wrap_matrix_context(notes: str, width: int = 36) -> list[str]:
    if not notes.strip():
        return [_matrix_row("OPERATOR CTX", "—", width=width)]
    lines = []
    chunk = notes.strip()
    while chunk:
        lines.append(_matrix_row("", f"▸ {chunk[:width - 2]}", width=width))
        chunk = chunk[width - 2:]
    return lines


def _build_matrix_execution_readout(
    *,
    ticker: str,
    pattern_category: str,
    start_anchor: str,
    end_anchor: str,
    duration_label: str,
    velocity: dict,
    math_block: dict,
    operator_context: str,
    micro_block=None,
    institutional_block=None,
    form4_block=None,
) -> str:
    """Bloomberg-grade ASCII box-drawing execution deck for the main monitor."""
    lane = st.session_state.get("r2_processor_lane", PROCESSOR_LANE_CLOUD)
    if lane == PROCESSOR_LANE_LOCAL_STRIKE:
        processor_label = f"LOCAL 1M STRIKE — IB TARGET <{IB_STRIKE_TARGET_MS}MS"
    else:
        processor_label = "CLOUD DUAL-STREAM — 5M/15M MACRO PIPELINE"
    header = [
        "╔════════════════════════════════════════╗",
        "║  SAVANT MATRIX EXECUTION TERMINAL      ║",
        f"║  {processor_label:<38} ║",
        "╠════════════════════════════════════════╣",
        _matrix_row("TICKER", ticker),
        _matrix_row("PATTERN CLASS", pattern_category or "UNCLASSIFIED"),
        _matrix_row("START ANCHOR", start_anchor or "—"),
        _matrix_row("END ANCHOR", end_anchor or "—"),
        _matrix_row("TIME DURATION", duration_label),
        "╠════════════════════════════════════════╣",
        "║  PRICE VELOCITY MATRIX                 ║",
        _matrix_row("SESSION MOVE", f"{velocity['session_velocity_pct']:+.4f}%"),
        _matrix_row("PEAK BAR VEL", f"{velocity['peak_bar_velocity_pct']:.4f}%"),
        _matrix_row("MEAN BAR VEL", f"{velocity['mean_bar_velocity_pct']:.4f}%"),
        _matrix_row("WINDOW AMPL", f"{velocity['window_amplitude_pct']:.4f}%"),
        "╠════════════════════════════════════════╣",
        "║  STRUCTURAL QUANT CORE                   ║",
        _matrix_row("BARS", str(math_block.get("bar_count", 0))),
        _matrix_row("PEARSON r", f"{math_block.get('pearson_r', 0):.4f}"),
        _matrix_row("GEOM DELTA", str(math_block.get("trend_bias", "GEOM0"))),
        _matrix_row("STRUCT MATCH", f"{math_block.get('match_probability', 0)}%"),
        _matrix_row("COSINE SIM", f"{math_block.get('cosine_similarity', 0):.3f}"),
        _matrix_row(
            "POLYGON SHIELD",
            f"{_polygon_calls_remaining()}/{POLYGON_CALLS_PER_MINUTE} CALLS",
        ),
    ]
    context_section = ["╠════════════════════════════════════════╣", "║  OPERATOR CONTEXT BIND                 ║"]
    context_section.extend(_wrap_matrix_context(operator_context))

    extras = []
    if micro_block and micro_block.get("drill_active"):
        extras.append(_matrix_row("5M DRILL", micro_block.get("summary", "—")[:34]))
    if institutional_block and institutional_block.get("institutional_block_accumulation"):
        extras.append(_matrix_row("INST BLOCK", "ACCUMULATION DETECTED"))
    if form4_block and form4_block.get("insider_buy_detected"):
        extras.append(_matrix_row("FORM4", form4_block.get("form4_summary", "—")[:34]))

    footer = ["╚════════════════════════════════════════╝"]
    if extras:
        extras.insert(0, "╠════════════════════════════════════════╣")
        extras.insert(1, "║  PROXY TRACKER FEED                      ║")

    return "\n".join(header + context_section + extras + footer)


def stream_payload_to_vault(payload: dict) -> tuple[bool, str]:
    """Direct secure Supabase REST anchor to live Postgres cloud table."""
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        supabase_key = st.secrets["SUPABASE_KEY"]
    except Exception:
        return False, "Supabase offline. Add SUPABASE_URL and SUPABASE_KEY to `.streamlit/secrets.toml`."

    table = _supabase_table_name()
    extended_fields = (
        "timeframe_resolution",
        "macro_weather_layout",
        "execution_strategy",
        "buffer_context_window",
        "vault_track",
        "data_feed_mode",
        "state",
        "deleted_at",
        "layout_match_pct",
        "anomaly_repeat_count",
        "shelf_expires_at",
        "structural_move_pct",
        "text_matrix_string",
        "forensic_dragnet_blob",
        "master_signature_json",
        "metric_envelopes_json",
        "semantic_catalyst_json",
    )

    def _post(body: dict):
        return requests.post(
            f"{supabase_url}/rest/v1/{table}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=[body],
            timeout=12,
        )

    try:
        resp = _post(payload)
        if resp.ok:
            return True, (
                f"INTERNET VAULT SYNC CONFIRMED — `{table}` anchored for "
                f"{payload.get('ticker', 'UNKNOWN')} @ {payload.get('timestamp', 'UTC')}."
            )

        err_text = resp.text.lower()
        if resp.status_code in (400, 404) and (
            "column" in err_text or "schema" in err_text or "could not" in err_text
        ):
            meta = {field: payload.get(field) for field in extended_fields if field in payload}
            slim = {key: value for key, value in payload.items() if key not in extended_fields}
            ctx = str(slim.get("operator_context", "")).strip()
            meta_blob = json.dumps(meta, default=str)
            slim["operator_context"] = (
                f"{ctx} | MATRIX_META:{meta_blob}".strip(" |") if ctx else f"MATRIX_META:{meta_blob}"
            )
            retry = _post(slim)
            if retry.ok:
                return True, (
                    f"INTERNET VAULT SYNC CONFIRMED — `{table}` anchored (compact schema fallback) "
                    f"for {payload.get('ticker', 'UNKNOWN')}."
                )
            return False, f"Vault upload failed: {retry.status_code} {retry.text}"

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
    start_date=None,
    start_time="",
    end_date=None,
    end_time="",
    operator_context="",
    layout_block_id="",
):
    """
    Runs permanent pattern categorization math locally on Mac silicon with adaptive
    5-minute drill-down when 15-minute variance compresses. Returns a Matrix-style
    ASCII execution deck with velocity, duration, and operator context telemetry.
    """
    if is_pipeline_signal(data_stream, "THROTTLE"):
        return THROTTLE_MESSAGE
    if data_stream is None or is_pipeline_signal(data_stream, "LOCKOUT"):
        return "System Sidelined: Awaiting Data Pipeline Clear"
    if not is_usable_data_stream(data_stream):
        return "⚠️ [DATALINK: NO_DATA] Historical wire returned empty."

    resolved_ticker = (
        str(ticker).strip().upper()
        or str(st.session_state.get("room2_forensic_ticker", "")).strip().upper()
        or str(st.session_state.get("current_ticker", "")).strip().upper()
    )

    feedback = (operator_context or human_feedback or "").strip()
    if not feedback:
        feedback = str(st.session_state.get("room2_operator_context", "")).strip()

    if start_date is not None or start_time:
        start_anchor = f"{start_date} {start_time}".strip() if start_date else str(start_time)
    else:
        entry_coord, _ = _normalize_date_coordinates(date_coordinates)
        start_anchor = entry_coord or ""

    if end_date is not None or end_time:
        end_anchor = f"{end_date} {end_time}".strip() if end_date else str(end_time)
    else:
        _, exit_coord = _normalize_date_coordinates(date_coordinates)
        end_anchor = exit_coord or ""

    start_dt = _parse_session_datetime(start_date, start_time)
    if start_dt is None and start_anchor:
        parts = start_anchor.rsplit(" ", 2)
        if len(parts) >= 3:
            start_dt = _parse_session_datetime(parts[0], f"{parts[1]} {parts[2]}")

    end_dt = _parse_session_datetime(end_date, end_time)
    if end_dt is None and end_anchor:
        parts = end_anchor.rsplit(" ", 2)
        if len(parts) >= 3:
            end_dt = _parse_session_datetime(parts[0], f"{parts[1]} {parts[2]}")

    duration_label = _format_session_duration(start_dt, end_dt)
    velocity = _compute_price_velocity_metrics(data_stream)
    st.session_state.room2_last_velocity = velocity

    quality = evaluate_playbook_quality_barrier(
        data_stream,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
        timeframe_resolution=str(
            st.session_state.get("r2_timeframe_mode", "15-Minute")
        ),
    )
    st.session_state.room2_playbook_quality = quality

    lane = st.session_state.get("r2_processor_lane", PROCESSOR_LANE_CLOUD)
    micro_block = None
    if lane == PROCESSOR_LANE_CLOUD and _is_compressed_variance(data_stream) and resolved_ticker:
        data_5m = get_historical_5m_data(resolved_ticker)
        if is_usable_data_stream(data_5m):
            micro_block = _analyze_5m_micro_traps(data_5m, resolved_ticker)

    if lane == PROCESSOR_LANE_LOCAL_STRIKE:
        institutional_block = {
            "institutional_block_accumulation": False,
            "inst_block_summary": "INST_BLOCK: LOCAL_STRIKE_BYPASS",
            "volume_baseline_20d": 0.0,
            "peak_surge_ratio": 0.0,
        }
        form4_block = {
            "insider_buy_detected": False,
            "form4_summary": "FORM4: LOCAL_STRIKE_BYPASS",
            "insider_events": [],
        }
    else:
        institutional_block = st.session_state.get("forensic_institutional_tracker", {})
        form4_block = st.session_state.get("forensic_form4_tracker", {})
        if resolved_ticker and not institutional_block:
            fetch_cloud_macro_intelligence(resolved_ticker, "15m", data_stream)
            institutional_block = st.session_state.get("forensic_institutional_tracker", {})
            form4_block = st.session_state.get("forensic_form4_tracker", {})
    st.session_state.forensic_institutional_tracker = institutional_block
    st.session_state.forensic_form4_tracker = form4_block

    math_block = _local_pattern_math(
        data_stream,
        pattern_category,
        (start_anchor or None, end_anchor or None),
        prices,
        micro_block=micro_block,
        institutional_block=institutional_block,
        form4_block=form4_block,
    )
    st.session_state.room2_last_math_block = math_block

    snapshot_vec = extract_forensic_feature_vector(
        velocity,
        math_block,
        float(
            (st.session_state.get("room2_deep_research_audit") or {})
            .get("semantic_catalyst", {})
            .get("finbert_sentiment_score", 0.0)
        ),
    )
    spatial = compute_spatial_layout_match(snapshot_vec)
    blended_match = max(int(math_block.get("match_probability") or 0), spatial["spatial_match_pct"])
    finbert_score = float(
        (st.session_state.get("room2_deep_research_audit") or {})
        .get("semantic_catalyst", {})
        .get("finbert_sentiment_score", 0.0)
    )
    if finbert_score < -0.25 and blended_match >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        blended_match = LAYOUT_SIGNATURE_MATCH_THRESHOLD - 1
    genetic = extract_master_signature_vector(snapshot_vec, blended_match)
    master_vec = genetic.get("master_signature") or snapshot_vec
    st.session_state.room2_master_signature = genetic
    math_block["match_probability"] = blended_match
    math_block["spatial_match_pct"] = spatial["spatial_match_pct"]
    math_block["cosine_similarity"] = spatial["cosine_similarity"]
    math_block["euclidean_distance"] = spatial["euclidean_distance"]
    math_block["nearest_layout_id"] = genetic.get("layout_id") or spatial["nearest_layout_id"]
    math_block["master_overlap_pct"] = genetic.get("overlap_pct", 0)
    st.session_state.room2_spatial_cluster = spatial
    st.session_state.room2_last_math_block = math_block

    register_id = str(
        layout_block_id or genetic.get("layout_id") or spatial["nearest_layout_id"]
    )
    if register_id != "PURGATORY_PENDING" and resolved_ticker:
        register_layout_vector_in_master_index(
            layout_id=register_id,
            vector=master_vec,
            ticker=resolved_ticker or "UNKNOWN",
            timeframe_resolution=str(st.session_state.get("r2_timeframe_mode", "15-Minute")),
        )

    return _build_matrix_execution_readout(
        ticker=resolved_ticker or "UNKNOWN",
        pattern_category=math_block.get("pattern_category", pattern_category),
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        duration_label=duration_label,
        velocity=velocity,
        math_block=math_block,
        operator_context=feedback,
        micro_block=micro_block,
        institutional_block=institutional_block,
        form4_block=form4_block,
    )


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
    timeframe_resolution: str = "15-Minute",
    macro_weather_layout: str = "",
    execution_strategy: str = "",
    buffer_context_window: str = "",
    vault_track: str = "track_1_validated",
    vault_state: str = "active",
    data_feed_mode: str = "carousel_15s",
    layout_match_pct: int = 0,
    anomaly_repeat_count: int = 0,
    shelf_expires_at: str = "",
    structural_move_pct: float = 0.0,
    text_matrix_string: str = "",
    forensic_dragnet_blob: str = "",
    master_signature_json: str = "",
    metric_envelopes_json: str = "",
    semantic_catalyst_json: str = "",
) -> dict:
    """Package Room 2 deck parameters for Internet Vault streaming."""
    notes = operator_notes.strip()
    matrix_blob = str(text_matrix_string or st.session_state.get("room2_text_matrix_string", "")).strip()
    if matrix_blob and "TEXT_MATRIX|" not in notes:
        notes = f"{notes} | {matrix_blob}".strip(" |") if notes else matrix_blob

    audit = st.session_state.get("room2_deep_research_audit") or {}
    dragnet_blob = forensic_dragnet_blob or audit.get("forensic_dragnet_blob", "")
    master_sig = master_signature_json or audit.get("master_signature_json", "")
    env_json = metric_envelopes_json or json.dumps(
        audit.get("metric_envelopes", {}), default=str
    )
    sem_json = semantic_catalyst_json or json.dumps(
        audit.get("semantic_catalyst", {}), default=str
    )
    body = {
        "ticker": ticker.upper(),
        "pattern_category": (pattern_category or "UNCLASSIFIED").strip().upper(),
        "entry_coordinate": entry_coordinate,
        "exit_coordinate": exit_coordinate,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "operator_context": notes,
        "quantum_report": quantum_report,
        "bar_count": bar_count,
        "timeframe_resolution": timeframe_resolution,
        "macro_weather_layout": macro_weather_layout,
        "execution_strategy": execution_strategy,
        "buffer_context_window": buffer_context_window,
        "vault_track": vault_track,
        "data_feed_mode": data_feed_mode,
        "polygon_calls_remaining": _polygon_calls_remaining(),
        "institutional_block_accumulation": st.session_state.get(
            "forensic_institutional_tracker", {}
        ).get("institutional_block_accumulation", False),
        "form4_insider_summary": (
            st.session_state.get("forensic_form4_tracker", {}).get("form4_summary", "")
        ),
        "source_room": "forensic_pattern_lab",
        "state": vault_state,
        "deleted_at": None,
        "layout_match_pct": layout_match_pct,
        "anomaly_repeat_count": anomaly_repeat_count,
        "shelf_expires_at": shelf_expires_at or None,
        "structural_move_pct": round(float(structural_move_pct), 4),
        "text_matrix_string": matrix_blob,
        "forensic_dragnet_blob": dragnet_blob,
        "master_signature_json": master_sig,
        "metric_envelopes_json": env_json,
        "semantic_catalyst_json": sem_json,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return body
