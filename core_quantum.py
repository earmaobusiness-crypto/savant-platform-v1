"""
Savant Quant Terminal — core ingestion, coupling gates, and cloud-offloaded math.

v6.0: Regime-switching shell-cracking funnel (vibe → pgvector shell → strategy judge),
Massive REST-only datalink, fluid lookback lane assertions, 4-layer feature vector.
"""

import datetime
import json
import math
import os
import queue
import re
import statistics
import threading
import time
import urllib.parse
from xml.etree import ElementTree

import requests
import streamlit as st

import cloud_offload
import vault_bridge

try:
    import pandas as pd
except ImportError:
    pd = None

POLYGON_CALLS_PER_MINUTE = 5
POLYGON_REST_DATA_EMPTY = "POLYGON REST DATA EMPTY"
MASSIVE_PLAN_TIMEFRAME_BLOCKED = "MASSIVE PLAN TIMEFRAME BLOCKED"
MASSIVE_API_BASE = "https://api.massive.com"
MASSIVE_PUBLIC_HOST = "massive.com"
MASSIVE_API_BASES = (MASSIVE_API_BASE,)
MASSIVE_REST_COOLDOWN_SEC = 12
WEBSOCKET_STREAMING_DISABLED = True
REGIME_FUNNEL_VERSION = "6.0"
FIVE_MINUTE_DRAGNET_BARS = 36
ONE_MINUTE_DRAGNET_BARS = 5
FIFTEEN_MINUTE_DRAGNET_BARS = 48
REGIME_VIBE_LOOKBACK_SCALE = {
    "1-Minute": 1.0,
    "5-Minute": 2.5,
    "15-Minute": 4.0,
}
LOOKBACK_LANE_ASSERTIONS = {
    "1-Minute": ONE_MINUTE_DRAGNET_BARS,
    "5-Minute": FIVE_MINUTE_DRAGNET_BARS,
    "15-Minute": FIFTEEN_MINUTE_DRAGNET_BARS,
}
# Adaptive lookback — use all valid bars up to ideal depth; only trash if near-empty.
LOOKBACK_ADAPTIVE_MIN_BARS = {
    "1-Minute": 2,
    "5-Minute": 4,
    "15-Minute": 3,
}
FIVE_MINUTE_SYNTHETIC_SLIPPAGE_PCT = 1.0
LIQUIDITY_IGNITION_MIN_SHARES_PER_MINUTE = 10_000
REJECTED_DEAD_ZONE = "REJECTED_DEAD_ZONE"
WINDOW4_SYSTEM_IDLE_MSG = "🚫 SYSTEM IDLE — NO VALID REGIME MATCH"
REGIME_VIBE_NEWS_DEPTH_DAYS = {
    "1-Minute": 7,
    "5-Minute": 14,
    "15-Minute": 30,
}


class _MassiveIngestSerialQueue:
    """
    Thread-safe serial queue for Massive REST macro-requests.
    Enforces a global 12-second cooldown across all submitting threads.
    """

    def __init__(self) -> None:
        self._submit_queue: queue.Queue = queue.Queue()
        self._worker_lock = threading.Lock()
        self._worker_started = False
        self._last_pull_monotonic = 0.0

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker_started:
                return
            worker = threading.Thread(
                target=self._worker_loop,
                name="massive-ingest-worker",
                daemon=True,
            )
            worker.start()
            self._worker_started = True

    def _worker_loop(self) -> None:
        while True:
            job = self._submit_queue.get()
            if job is None:
                self._submit_queue.task_done()
                break
            fn, resp_q = job
            try:
                elapsed = time.monotonic() - self._last_pull_monotonic
                if self._last_pull_monotonic > 0 and elapsed < MASSIVE_REST_COOLDOWN_SEC:
                    time.sleep(MASSIVE_REST_COOLDOWN_SEC - elapsed)
                result = fn()
                self._last_pull_monotonic = time.monotonic()
                resp_q.put((result, None))
            except Exception as exc:
                resp_q.put((None, exc))
            finally:
                self._submit_queue.task_done()

    def execute(self, fn, *, timeout_sec: float = 180.0):
        self._ensure_worker()
        resp_q: queue.Queue = queue.Queue(maxsize=1)
        self._submit_queue.put((fn, resp_q))
        result, err = resp_q.get(timeout=timeout_sec)
        if err is not None:
            raise err
        return result


_MASSIVE_INGEST_QUEUE = _MassiveIngestSerialQueue()

PROCESSING_LANE_BARS = {
    "1-Minute": ONE_MINUTE_DRAGNET_BARS,
    "5-Minute": FIVE_MINUTE_DRAGNET_BARS,
    "15-Minute": FIFTEEN_MINUTE_DRAGNET_BARS,
}
POLYGON_SESSION_OPEN_HOUR = 4
POLYGON_SESSION_CLOSE_HOUR = 20
ALPHA_DECAY_ROLLING_N = 15
ALPHA_DECAY_MARGIN_FLOOR_PCT = 0.15
LAYOUT_SIGNATURE_MATCH_THRESHOLD = 85
ANOMALY_SHELF_DAYS = 30
ANOMALY_PERMANENT_MINT_COUNT = 5
TIMEFRAME_MARGIN_FLOORS = {
    "1-Minute": 1.0,
    "5-Minute": 6.0,
    "15-Minute": 5.0,
}
TIMEFRAME_BAR_MINUTES = {
    "1-Minute": 1,
    "5-Minute": 5,
    "15-Minute": 15,
}
EXECUTION_FRICTION_SLIPPAGE_MIN = 0.5
EXECUTION_FRICTION_SLIPPAGE_MAX = 1.5
HILL_BYPASS_LOCAL_BARS = 6
HILL_MARGIN_SHRINK_MIN_PCT = 0.25
HILL_DROP_MIN_PCT = 0.35
LOOKBACK_DELTAS = {
    "15-Minute": datetime.timedelta(hours=12),
}
# Extra session days pulled before operator start_date so dragnet lanes have enough bars.
LOOKBACK_FETCH_PADDING_DAYS = {
    "1-Minute": 1,
    "5-Minute": 1,
    "15-Minute": 2,
}
# Session quality — reject thin/gappy deploy days before vault mint.
SESSION_MIN_BAR_DENSITY = 0.45
SESSION_MIN_AVG_VOLUME_PER_BAR = 2_500
SESSION_SECTOR_ETF_SYMBOLS = ("XLK", "XLF", "XLE", "XLV", "XLU", "SPY")
# Strategy trust — promote only after repeatable wins (not one-off luck).
STRATEGY_TRUST_MIN_SAMPLES = 3
STRATEGY_TRUST_MIN_UNIQUE_TICKERS = 2
STRATEGY_TRUST_MIN_UNIQUE_SESSIONS = 2
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
DATA_FEED_MASSIVE_REST_1M = "massive_rest_1m"
DATA_FEED_POLYGON_1M = DATA_FEED_MASSIVE_REST_1M
RESAMPLE_RULES = {
    "1-Minute": "1min",
    "5-Minute": "5min",
    "15-Minute": "15min",
}
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


def _dataframe_is_empty(data_stream) -> bool:
    """Explicit empty check — never use truthiness on a DataFrame."""
    if data_stream is None or isinstance(data_stream, str):
        return True
    if pd is not None and isinstance(data_stream, pd.DataFrame):
        return data_stream.empty
    frame = _ensure_dataframe(data_stream)
    return frame is None or frame.empty


def _first_usable_dataframe(*candidates):
    """Return first non-empty DataFrame without ambiguous `df or other` syntax."""
    empty_fallback = None
    for item in candidates:
        if item is None:
            continue
        frame = item if isinstance(item, pd.DataFrame) else _ensure_dataframe(item)
        if not isinstance(frame, pd.DataFrame):
            continue
        if empty_fallback is None:
            empty_fallback = frame
        if not frame.empty:
            return frame
    return empty_fallback


def _flatten_ohlcv_frame(df):
    """Normalize MultiIndex OHLCV columns so Close/Volume accessors work."""
    if pd is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _is_placeholder_api_key(key: str) -> bool:
    low = str(key or "").strip().lower()
    if not low or len(low) < 8:
        return True
    return any(
        token in low
        for token in ("your-", "replace", "changeme", "api-key-here", "xxx", "placeholder")
    )


def _market_data_api_key_candidates() -> list[str]:
    """Collect valid Massive/Polygon keys — secrets, env, then operator fallback."""
    found: list[str] = []
    for name in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
        try:
            val = st.secrets[name]
            if val and not _is_placeholder_api_key(str(val)):
                found.append(str(val).strip())
        except Exception:
            continue
    for env_name in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
        val = os.environ.get(env_name)
        if val and not _is_placeholder_api_key(str(val)):
            found.append(str(val).strip())
    # Operator starter key — used only when secrets/env are missing or invalid.
    operator_key = "IJmCrEhTtXg2lAHbiY2BaBRCYRgBMs7G"
    if not _is_placeholder_api_key(operator_key):
        found.append(operator_key)
    deduped: list[str] = []
    for key in found:
        if key not in deduped:
            deduped.append(key)
    return deduped


def _resolve_market_data_api_key() -> str | None:
    keys = _market_data_api_key_candidates()
    return keys[0] if keys else None


def _massive_aggs_request(
    ticker_clean: str,
    *,
    start_date,
    end_date,
    api_key: str,
    api_base: str,
) -> tuple[dict | None, int, str]:
    """Single REST aggregates pull — date window + Bearer + apiKey (Massive/Polygon compatible)."""
    start_text = _session_date_value(start_date)
    end_text = _session_date_value(end_date) or start_text
    if not start_text or not end_text:
        return None, 0, "bad_session_dates"
    url = (
        f"{api_base.rstrip('/')}/v2/aggs/ticker/{ticker_clean}/range/1/minute/"
        f"{start_text}/{end_text}"
    )
    params = {
        "adjusted": "false",
        "sort": "asc",
        "limit": 50000,
        "apiKey": api_key,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        http_resp = requests.get(url, params=params, headers=headers, timeout=20)
        body_text = http_resp.text[:240]
        if not http_resp.ok:
            try:
                err_payload = http_resp.json()
                if isinstance(err_payload, dict):
                    detail = str(
                        err_payload.get("message")
                        or err_payload.get("error")
                        or err_payload.get("status")
                        or body_text
                    )
                    return err_payload, http_resp.status_code, detail
            except Exception:
                pass
            return None, http_resp.status_code, body_text
        payload = http_resp.json()
        if isinstance(payload, dict):
            return payload, http_resp.status_code, ""
        return None, http_resp.status_code, body_text
    except Exception as exc:
        return None, 0, str(exc)[:120]


def _massive_aggs_url(ticker_clean: str, from_ms: int, to_ms: int, api_key: str) -> str:
    """REST aggregates endpoint on Massive data servers (api.massive.com)."""
    return (
        f"{MASSIVE_API_BASE}/v2/aggs/ticker/{ticker_clean}/range/1/minute/"
        f"{from_ms}/{to_ms}?adjusted=false&sort=asc&limit=50000&apiKey={api_key}"
    )


def _session_date_value(raw_date) -> str | None:
    if raw_date is None:
        return None
    if hasattr(raw_date, "strftime"):
        return raw_date.strftime("%Y-%m-%d")
    text = str(raw_date).strip()
    return text[:10] if text else None


def _shift_session_date_backward(raw_date, days: int):
    """Move a deploy session date back N calendar days for extended lookback fetches."""
    if days <= 0:
        return raw_date
    text = _session_date_value(raw_date)
    if not text:
        return raw_date
    try:
        shifted = datetime.datetime.strptime(text, "%Y-%m-%d").date() - datetime.timedelta(
            days=days
        )
        if hasattr(raw_date, "strftime"):
            return shifted
        return shifted.isoformat()
    except ValueError:
        return raw_date


def _lookback_fetch_padding_days(timeframe_resolution: str) -> int:
    return int(LOOKBACK_FETCH_PADDING_DAYS.get(timeframe_resolution, 1))


def _polygon_session_bounds_ms(start_date, end_date) -> tuple[int, int] | None:
    """16-hour extended session window (4:00 AM – 8:00 PM ET) for submission dates."""
    start_text = _session_date_value(start_date)
    end_text = _session_date_value(end_date) or start_text
    if not start_text or not end_text:
        return None
    try:
        from zoneinfo import ZoneInfo

        et = ZoneInfo("America/New_York")
        start_day = datetime.datetime.strptime(start_text, "%Y-%m-%d")
        end_day = datetime.datetime.strptime(end_text, "%Y-%m-%d")
        session_open = start_day.replace(
            hour=POLYGON_SESSION_OPEN_HOUR, minute=0, second=0, microsecond=0, tzinfo=et
        )
        session_close = end_day.replace(
            hour=POLYGON_SESSION_CLOSE_HOUR, minute=0, second=0, microsecond=0, tzinfo=et
        )
        if session_close <= session_open:
            session_close = session_close + datetime.timedelta(days=1)
        return int(session_open.timestamp() * 1000), int(session_close.timestamp() * 1000)
    except ValueError:
        return None


def fetch_massive_session_1m_package(
    ticker_clean: str,
    *,
    start_date,
    end_date,
) -> tuple[list | None, str | None]:
    """
    Exactly ONE Massive REST aggregates HTTP request per stock/submission.
    Free Starter tier — REST historical pulls only (no WebSocket streaming).
    Returns (results_list, pipeline_signal) where signal is None, THROTTLE, or POLYGON_REST_DATA_EMPTY.
    """
    api_keys = _market_data_api_key_candidates()
    if not api_keys:
        st.session_state.r2_market_data_error = "MASSIVE_API_KEY_MISSING"
        return None, POLYGON_REST_DATA_EMPTY

    if not _polygon_call_available():
        return None, "THROTTLE"

    def _pull_once() -> tuple[list | None, str | None]:
        payload: dict | None = None
        last_status = 0
        last_detail = ""
        for api_key in api_keys:
            for api_base in MASSIVE_API_BASES:
                payload, last_status, last_detail = _massive_aggs_request(
                    ticker_clean,
                    start_date=start_date,
                    end_date=end_date,
                    api_key=api_key,
                    api_base=api_base,
                )
                if payload is not None and last_status == 200:
                    st.session_state.r2_market_data_error = None
                    st.session_state.r2_market_data_key_source = api_base
                    break
                if last_status == 401:
                    last_detail = "Unknown API Key"
                    continue
                if last_status == 429 or (
                    payload is not None
                    and str(payload.get("error", "")).lower().find("max requests") >= 0
                ):
                    st.session_state.polygon_calls_remaining = 0
                    st.session_state.polygon_lockout = True
                    return None, "THROTTLE"
            if payload is not None and last_status == 200:
                break

        if payload is None or last_status != 200:
            if last_status == 401:
                st.session_state.r2_market_data_error = (
                    "MASSIVE_HTTP_401|Unknown API Key — set MASSIVE_API_KEY in "
                    ".streamlit/secrets.toml"
                )
            elif last_status == 403 or "NOT_AUTHORIZED" in str(last_detail).upper():
                st.session_state.r2_market_data_error = (
                    "MASSIVE_HTTP_403|Same-day minute bars are not included on your "
                    "current Massive/Polygon plan — use a prior completed session date."
                )
                return None, MASSIVE_PLAN_TIMEFRAME_BLOCKED
            else:
                st.session_state.r2_market_data_error = (
                    f"MASSIVE_HTTP_{last_status}|{last_detail[:80]}"
                    if last_status
                    else f"MASSIVE_FETCH_ERR|{last_detail[:80]}"
                )
            return None, POLYGON_REST_DATA_EMPTY

        results = payload.get("results")
        if isinstance(results, list) and len(results) > 0:
            _consume_polygon_call()
            st.session_state.massive_last_pull_at = time.time()
            return results, None

        status = str(payload.get("status", "")).upper()
        error_text = str(payload.get("error") or payload.get("message") or "").lower()
        if status == "ERROR" and "max requests" in error_text:
            st.session_state.polygon_calls_remaining = 0
            st.session_state.polygon_lockout = True
            return None, "THROTTLE"
        st.session_state.r2_market_data_error = (
            f"MASSIVE_EMPTY_SESSION|{_session_date_value(start_date)}|results=0"
        )
        return None, POLYGON_REST_DATA_EMPTY

    try:
        return _MASSIVE_INGEST_QUEUE.execute(_pull_once)
    except queue.Empty:
        st.session_state.r2_market_data_error = "MASSIVE_QUEUE_TIMEOUT"
        return None, POLYGON_REST_DATA_EMPTY


fetch_polygon_session_1m_package = fetch_massive_session_1m_package


def _strip_dataframe_index_timezone(frame):
    """Strip exchange-native timezone metadata immediately after REST ingest."""
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    out = frame.copy()
    try:
        idx = out.index
        if getattr(idx, "tz", None) is not None:
            out.index = idx.tz_convert("America/New_York").tz_localize(None)
        else:
            out.index = out.index.tz_localize(None)
    except (TypeError, ValueError, AttributeError):
        try:
            out.index = out.index.tz_localize(None)
        except (TypeError, ValueError, AttributeError):
            pass
    return out


def _polygon_aggs_to_dataframe(results):
    """Convert Massive agg list into naive-timestamp OHLCV+VWAP frame in local RAM."""
    if pd is None or not isinstance(results, list) or not results:
        return None
    rows = []
    for bar in results:
        if not isinstance(bar, dict):
            continue
        ts_ms = bar.get("t")
        if ts_ms is None:
            continue
        ts = pd.to_datetime(float(ts_ms), unit="ms", utc=True)
        if hasattr(ts, "tz_convert"):
            ts = ts.tz_convert("America/New_York")
        ts = ts.tz_localize(None)
        rows.append(
            {
                "Datetime": ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                "Open": float(bar.get("o", 0) or 0),
                "High": float(bar.get("h", 0) or 0),
                "Low": float(bar.get("l", 0) or 0),
                "Close": float(bar.get("c", 0) or 0),
                "Volume": float(bar.get("v", 0) or 0),
                "VWAP": float(bar.get("vw", 0) or 0),
            }
        )
    if not rows:
        return None
    frame = pd.DataFrame(rows).set_index("Datetime")
    frame = _strip_dataframe_index_timezone(frame)
    return frame if not frame.empty else None


def resample_ohlcv_bars(frame_1m, rule: str):
    """Local Pandas resample — 1 API credit already spent on the 1m package."""
    frame = _ensure_dataframe(frame_1m)
    if frame is None:
        return None
    try:
        agg_map = {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
        if "VWAP" in frame.columns:
            vol = frame["Volume"].astype(float).fillna(0.0)
            vwap_num = (frame["VWAP"].astype(float).fillna(0.0) * vol).resample(rule).sum()
            vwap_den = vol.resample(rule).sum()
            resampled = frame.resample(rule).agg(agg_map)
            resampled["VWAP"] = (vwap_num / vwap_den.replace(0.0, float("nan"))).fillna(
                resampled["Close"]
            )
        else:
            resampled = frame.resample(rule).agg(agg_map)
        resampled = resampled.dropna(subset=["Close"], how="any")
        return _strip_dataframe_index_timezone(resampled) if not resampled.empty else None
    except Exception:
        return None


def _resolve_track_from_1m(frame_1m, timeframe_resolution: str):
    if timeframe_resolution == "1-Minute":
        return frame_1m
    remote = cloud_offload.remote_resample_track(frame_1m, timeframe_resolution)
    if remote is not None and is_usable_data_stream(remote):
        st.session_state.r2_resample_lane = "cloud_compute"
        return remote
    if cloud_offload.cloud_offload_strict() and cloud_offload.cloud_compute_enabled():
        return None
    rule = RESAMPLE_RULES.get(timeframe_resolution, "15min")
    st.session_state.r2_resample_lane = "local_fallback"
    return resample_ohlcv_bars(frame_1m, rule)


def get_room2_polygon_pipeline(
    ticker,
    *,
    start_date,
    end_date,
    timeframe_resolution: str = "15-Minute",
):
    """
    Room 2 institutional datalink — one Polygon 1m macro-request per submission,
    local resample to 5m/15m tracks, timezone stripped on ingest.
    """
    ticker_clean = str(ticker).strip().upper()
    if not ticker_clean:
        return POLYGON_REST_DATA_EMPTY

    fetch_pad_days = _lookback_fetch_padding_days(timeframe_resolution)
    fetch_start_date = _shift_session_date_backward(start_date, fetch_pad_days)
    cache_key = (
        f"{ticker_clean}|{_session_date_value(fetch_start_date)}"
        f"|{_session_date_value(end_date)}|pad={fetch_pad_days}"
    )
    cached_key = st.session_state.get("r2_polygon_session_key")
    frame_1m = st.session_state.get("r2_polygon_1m_ram")

    if cached_key != cache_key or not is_usable_data_stream(frame_1m):
        polygon_bars, polygon_signal = fetch_polygon_session_1m_package(
            ticker_clean,
            start_date=fetch_start_date,
            end_date=end_date,
        )
        if polygon_signal == "THROTTLE":
            st.session_state.polygon_lockout = True
            return "THROTTLE"
        if polygon_signal == MASSIVE_PLAN_TIMEFRAME_BLOCKED:
            return MASSIVE_PLAN_TIMEFRAME_BLOCKED
        if polygon_signal == POLYGON_REST_DATA_EMPTY or not polygon_bars:
            st.session_state.r2_micro_feed_source = DATA_FEED_POLYGON_1M
            return POLYGON_REST_DATA_EMPTY
        frame_1m = _polygon_aggs_to_dataframe(polygon_bars)
        if not is_usable_data_stream(frame_1m):
            return POLYGON_REST_DATA_EMPTY
        frame_1m = _strip_dataframe_index_timezone(frame_1m)
        st.session_state.r2_polygon_1m_ram = frame_1m
        st.session_state.r2_polygon_session_key = cache_key
        st.session_state.r2_micro_feed_source = DATA_FEED_POLYGON_1M

    track = _resolve_track_from_1m(frame_1m, timeframe_resolution)
    if not is_usable_data_stream(track):
        return POLYGON_REST_DATA_EMPTY

    # Do not RAM-cap the 1m track here. Trimming to the last N minutes of the
    # session drops every bar before operator Start Time and trips
    # PRE-STORAGE TRASH (got 0 on 1-Minute). Temporal fence + dragnet already
    # keep only lookback-through-exit bars after ingest.
    if timeframe_resolution == "1-Minute" and is_usable_data_stream(track):
        st.session_state.r2_local_ram_bar_count = len(track)
    st.session_state.r2_processor_lane = (
        PROCESSOR_LANE_LOCAL_STRIKE
        if timeframe_resolution == "1-Minute"
        else PROCESSOR_LANE_CLOUD
    )
    st.session_state.r2_timeframe_track_bars = len(track)
    return track


def _cached_polygon_1m_frame():
    return st.session_state.get("r2_polygon_1m_ram")


def timeframe_margin_floor(timeframe_resolution: str) -> float:
    return float(TIMEFRAME_MARGIN_FLOORS.get(timeframe_resolution, 1.0))


def validate_operator_timeframe_fit(
    start_dt: datetime.datetime | None,
    end_dt: datetime.datetime | None,
    timeframe_resolution: str,
) -> dict:
    """
    Operator window must span at least one bar on the selected track.
    e.g. 8:31–8:35 (4 min) cannot run on 5-Minute or 15-Minute — use 1-Minute.
    """
    bar_minutes = int(TIMEFRAME_BAR_MINUTES.get(timeframe_resolution, 15))
    if start_dt is None or end_dt is None or end_dt <= start_dt:
        return {
            "passed": False,
            "window_minutes": 0,
            "bar_minutes": bar_minutes,
            "suggested_timeframe": "1-Minute",
            "message": "Invalid operator start/end window.",
        }
    window_minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
    passed = window_minutes >= bar_minutes
    if window_minutes < 5:
        suggested = "1-Minute"
    elif window_minutes < 15:
        suggested = "1-Minute" if timeframe_resolution == "15-Minute" else "5-Minute"
    else:
        suggested = timeframe_resolution if passed else "5-Minute"
    message = ""
    if not passed:
        message = (
            f"Operator window is {window_minutes} minute(s) — too short for "
            f"{timeframe_resolution} (needs at least {bar_minutes} minute(s)). "
            f"Switch to {suggested}."
        )
    return {
        "passed": passed,
        "window_minutes": window_minutes,
        "bar_minutes": bar_minutes,
        "suggested_timeframe": suggested,
        "message": message,
    }


def _ensure_dataframe(data_stream):
    if pd is None:
        return None
    if isinstance(data_stream, pd.DataFrame) and not data_stream.empty:
        return _flatten_ohlcv_frame(data_stream)
    return None


def pad_datastream_gaps(data_stream):
    """v2 pipeline — no horizontal pre-market padding; return raw Polygon bars."""
    frame = _ensure_dataframe(data_stream)
    return frame if frame is not None else data_stream


def _dynamic_bar_dragnet_window(
    data_stream,
    start_dt: datetime.datetime | None,
    bar_count: int,
):
    """
    Boundary-less relative bar lookback anchored at operator Start Time.
    Never truncates at session walls — pulls the prior N bars seamlessly.
    """
    frame = _ensure_dataframe(data_stream)
    if frame is None or start_dt is None or bar_count <= 0:
        return None, None
    try:
        bars_up_to_start = frame[frame.index <= start_dt]
        if not isinstance(bars_up_to_start, pd.DataFrame) or bars_up_to_start.empty:
            return None, None
        window = bars_up_to_start.tail(bar_count)
        if window.empty:
            return None, None
        return window.index[0], window
    except Exception:
        return None, None


def _dynamic_1m_dragnet_window(data_stream, start_dt: datetime.datetime | None):
    """Strict 5-minute / 5-bar lookback on the 1m track from operator Start Time."""
    return _dynamic_bar_dragnet_window(data_stream, start_dt, ONE_MINUTE_DRAGNET_BARS)


def _dynamic_5m_dragnet_window(data_stream, start_dt: datetime.datetime | None):
    """
    Boundary-less 3-hour / 36-bar lookback on the 5m track, anchored at operator Start Time.
    Crosses regular/post-market seamlessly — never truncates at the 4:00 PM wall.
    """
    return _dynamic_bar_dragnet_window(data_stream, start_dt, FIVE_MINUTE_DRAGNET_BARS)


def _dynamic_15m_dragnet_window(data_stream, start_dt: datetime.datetime | None):
    """Boundary-less 12-hour / 48-bar lookback on the 15m track from operator Start Time."""
    return _dynamic_bar_dragnet_window(data_stream, start_dt, FIFTEEN_MINUTE_DRAGNET_BARS)


def _calibrated_lookback_start(
    end_dt: datetime.datetime,
    timeframe_resolution: str,
    *,
    start_dt: datetime.datetime | None = None,
    data_stream=None,
):
    """Timeframe-isolated forensic lookback — 1m: 5 bars, 5m: 36 bars, both from Start Time."""
    if end_dt is None:
        return None
    if timeframe_resolution == "1-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_1m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "5-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_5m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "15-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_15m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "1-Minute" and start_dt is not None:
        return start_dt - datetime.timedelta(minutes=ONE_MINUTE_DRAGNET_BARS)
    if timeframe_resolution == "15-Minute":
        return end_dt - LOOKBACK_DELTAS["15-Minute"]
    delta = LOOKBACK_DELTAS.get(timeframe_resolution, datetime.timedelta(hours=1))
    return end_dt - delta


def _clamp_inner_move_window(
    start_dt: datetime.datetime | None,
    end_dt: datetime.datetime | None,
    timeframe_resolution: str,
) -> datetime.datetime | None:
    """1m runway is capped by the 5-bar dragnet from Start Time — no extra timedelta clamp."""
    return start_dt


def _research_dragnet_lookback_start(
    end_dt: datetime.datetime | None,
    timeframe_resolution: str,
    *,
    start_dt: datetime.datetime | None = None,
    data_stream=None,
) -> datetime.datetime | None:
    """
    Full-session dragnet for Room 2 research — 1m/5m use boundary-less bar windows from Start Time.
    """
    if end_dt is None:
        return None
    if timeframe_resolution == "1-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_1m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "5-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_5m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "15-Minute" and start_dt is not None:
        lookback_start, _ = _dynamic_15m_dragnet_window(data_stream, start_dt)
        if lookback_start is not None:
            return lookback_start
    if timeframe_resolution == "15-Minute":
        return end_dt - LOOKBACK_DELTAS["15-Minute"]
    return _calibrated_lookback_start(
        end_dt, timeframe_resolution, start_dt=start_dt, data_stream=data_stream
    )


def compute_metric_envelopes(
    data_stream,
    end_dt: datetime.datetime | None,
    lookback_start_dt: datetime.datetime | None,
) -> dict:
    """
    Flexible std-dev envelopes for cold metrics — volume, velocity, spread.
    Offloaded to cloud compute when CLOUD_COMPUTE_URL is configured.
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

        start_iso = (
            lookback_start_dt.isoformat() if lookback_start_dt is not None else None
        )
        end_iso = end_dt.isoformat() if end_dt is not None else None
        remote = cloud_offload.remote_metric_envelopes(
            window,
            lookback_start=start_iso,
            end_dt=end_iso,
        )
        if remote:
            return remote
        if cloud_offload.cloud_offload_strict() and cloud_offload.cloud_compute_enabled():
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
    """Deprecated — local FinBERT removed in v3.4 cloud migration."""
    return None


def finbert_sentiment_score(text: str) -> float:
    """Serverless FinBERT coordinate via Hugging Face Inference API."""
    return cloud_offload.hf_sentiment_score(text)


def _parse_iso_timestamp(ts) -> datetime.datetime | None:
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def _catalyst_filing_ignition_gap_minutes(
    filings: list[dict],
    volatility_ignition_ts,
) -> float | None:
    """Fluid time-gap delta between SEC filing drop and volatility ignition minute."""
    ignition_dt = _parse_iso_timestamp(volatility_ignition_ts)
    if ignition_dt is None or not filings:
        return None
    best_gap: float | None = None
    for filing in filings:
        fd = filing.get("filing_date")
        if not fd:
            continue
        try:
            filing_dt = datetime.datetime.strptime(str(fd), "%Y-%m-%d")
        except ValueError:
            continue
        gap_min = abs((ignition_dt - filing_dt).total_seconds()) / 60.0
        if best_gap is None or gap_min < best_gap:
            best_gap = gap_min
    return round(best_gap, 2) if best_gap is not None else None


def score_semantic_catalyst_stream(
    headlines: list[str],
    filing_texts: list[str] | None = None,
    *,
    filing_records: list[dict] | None = None,
    volatility_ignition_ts=None,
) -> dict:
    """
    SEC / headline text-to-vector lane — Hugging Face Serverless inference only.
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
            "semantic_mode": "hf_serverless",
            "headline_count": 0,
            "filing_count": 0,
            "catalyst_gap_minutes": None,
            "catalyst_gap_score": 0.0,
        }
    scores = cloud_offload.hf_sentiment_batch(all_texts)
    aggregate = round(sum(scores) / len(scores), 4) if scores else 0.0
    headline_scores = scores[: len(clean_headlines)]
    filing_scores = scores[len(clean_headlines) :]
    message_velocity = round(
        len(all_texts) / max(1.0, math.log1p(sum(len(h) for h in all_texts) / 80)), 3
    )
    audience_scale = round(statistics.mean([len(h) for h in all_texts]), 2)
    impact_weight = round(abs(aggregate) * (1.0 + math.log1p(message_velocity)), 4)
    mode = "hf_serverless" if cloud_offload.huggingface_enabled() else "hf_unconfigured"
    catalyst_gap_minutes = _catalyst_filing_ignition_gap_minutes(
        list(filing_records or []),
        volatility_ignition_ts,
    )
    catalyst_gap_score = 0.0
    if catalyst_gap_minutes is not None:
        catalyst_gap_score = round(max(0.0, 1.0 - min(catalyst_gap_minutes, 1440.0) / 1440.0), 4)
        impact_weight = round(impact_weight * (1.0 + catalyst_gap_score), 4)
    return {
        "finbert_sentiment_score": aggregate,
        "headline_sentiment_scores": headline_scores,
        "filing_sentiment_scores": filing_scores,
        "message_velocity": message_velocity,
        "audience_scale": audience_scale,
        "impact_weight": impact_weight,
        "semantic_mode": mode,
        "headline_count": len(clean_headlines),
        "filing_count": len(clean_filings),
        "catalyst_gap_minutes": catalyst_gap_minutes,
        "catalyst_gap_score": catalyst_gap_score,
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
    """Options sweep proxy — Polygon-only pipeline; chain data deferred to cloud research."""
    _ = ticker
    return {"status": "UNAVAILABLE", "reason": "polygon_only_pipeline_v2"}


def run_full_day_forensic_dragnet(
    *,
    ticker: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
    start_date=None,
    start_time: str = "",
) -> dict:
    """
    Room 2 forensic dragnet — slices cached Polygon 1m RAM, resampled locally.
    5m uses boundary-less 36-bar window from operator Start Time.
    """
    if timeframe_resolution not in DRAGNET_TIMEFRAMES:
        return {}
    ticker_clean = str(ticker).strip().upper()
    end_dt = _parse_session_datetime(end_date, end_time)
    if end_dt is None:
        return {}
    start_dt = _parse_session_datetime(start_date, start_time) if start_date else None

    frame_1m = _cached_polygon_1m_frame()
    track = _resolve_track_from_1m(frame_1m, timeframe_resolution) if frame_1m is not None else None
    dragnet_start = _research_dragnet_lookback_start(
        end_dt,
        timeframe_resolution,
        start_dt=start_dt,
        data_stream=track,
    )
    dragnet_frame = None
    if track is not None and dragnet_start is not None:
        try:
            sliced = track[(track.index <= end_dt) & (track.index >= dragnet_start)]
            if isinstance(sliced, pd.DataFrame) and not sliced.empty:
                dragnet_frame = sliced
        except Exception:
            dragnet_frame = None

    _, baseline_window = (
        _dynamic_5m_dragnet_window(track, start_dt)
        if timeframe_resolution == "5-Minute" and start_dt is not None
        else (None, None)
    )
    envelopes = compute_metric_envelopes(
        _first_usable_dataframe(baseline_window, dragnet_frame, track),
        end_dt,
        dragnet_start,
    )
    headlines = _fetch_research_news_headlines(ticker_clean, limit=24)
    semantic = score_semantic_catalyst_stream(headlines)
    form4 = _scrape_form4_insider_buys(ticker_clean)
    regulatory = _scrape_sec_regulatory_dragnet(ticker_clean)
    institutional = _detect_institutional_block_accumulation(
        ticker_clean,
        _first_usable_dataframe(dragnet_frame, track),
        timeframe_resolution,
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
    1m >= 1.0%, 5m >= 6.0% (strict alpha), 15m >= 5.0%.
    When net_margin_pct is present, friction-adjusted margin must clear the floor.
    """
    out = dict(quality or {})
    tf = str(out.get("timeframe_resolution") or "15-Minute")
    floor_pct = float(out.get("floor_pct") or timeframe_margin_floor(tf))
    move_pct = float(out.get("structural_move_pct") or 0.0)
    friction_pct = float(out.get("execution_friction_buffer_pct") or 0.0)
    net_margin_pct = out.get("net_margin_pct")
    if net_margin_pct is not None:
        effective_move = float(net_margin_pct)
    elif friction_pct > 0:
        effective_move = move_pct - friction_pct
        out["net_margin_pct"] = round(effective_move, 4)
    else:
        effective_move = move_pct
    passed = effective_move >= floor_pct
    tf_fit = out.get("timeframe_fit") or {}
    if tf_fit and not tf_fit.get("passed", True):
        passed = False
    out["floor_pct"] = floor_pct
    out["passed"] = passed
    out["trashed"] = not passed
    if not passed:
        if tf_fit and not tf_fit.get("passed", True):
            out["trash_reason"] = tf_fit.get("message") or "timeframe_window_mismatch"
        elif friction_pct > 0 and net_margin_pct is not None:
            out["trash_reason"] = (
                f"BELOW_NET_ALPHA_FLOOR|gross={move_pct:.4f}%|"
                f"friction={friction_pct:.4f}%|net={effective_move:.4f}%|"
                f"required={floor_pct:.1f}%|tf={tf}"
            )
        else:
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
    if window is None or _dataframe_is_empty(window):
        return None, None
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


def _candidate_velocity_spike_anchor(window) -> tuple[object | None, float | None]:
    """Candidate B — bar with the sharpest price-velocity spike vs rolling std envelope."""
    if window is None or _dataframe_is_empty(window) or "Close" not in window.columns:
        return None, None
    closes = window["Close"].astype(float)
    if len(closes) < 2:
        idx = window.index[0]
        return idx, float(closes.iloc[0])
    velocity = closes.pct_change().abs() * 100.0
    roll = min(5, len(velocity))
    vel_mean = velocity.rolling(window=roll, min_periods=1).mean().fillna(0.0)
    vel_std = velocity.rolling(window=roll, min_periods=1).std().fillna(0.0)
    envelope = (vel_mean + vel_std).replace(0.0, float("nan"))
    spike_score = (velocity / envelope).fillna(0.0)
    idx = spike_score.idxmax()
    return idx, float(window.loc[idx, "Close"])


def _immediate_structural_low_after(window, anchor_idx, bars_ahead: int = HILL_BYPASS_LOCAL_BARS):
    """Next localized swing low immediately after a candidate bar."""
    if anchor_idx is None or window.empty:
        return None, None
    try:
        pos = window.index.get_loc(anchor_idx)
        if isinstance(pos, slice):
            pos = pos.start or 0
        elif hasattr(pos, "__len__") and not isinstance(pos, int):
            pos = int(pos[0]) if len(pos) else 0
        forward = window.iloc[int(pos) + 1 : int(pos) + 1 + bars_ahead]
        if not isinstance(forward, pd.DataFrame) or forward.empty:
            return None, None
        if "Low" in forward.columns:
            lows = forward["Low"].astype(float)
            low_idx = lows.idxmin()
            return low_idx, float(forward.loc[low_idx, "Low"])
        closes = forward["Close"].astype(float)
        low_idx = closes.idxmin()
        return low_idx, float(closes.loc[low_idx])
    except Exception:
        return None, None


def _hill_trap_shrinks_margin(
    window,
    anchor_idx,
    anchor_price: float,
    exit_price: float | None,
) -> bool:
    """True when a short-lived hill peak collapses margin vs the next structural low."""
    if anchor_price is None or exit_price is None or anchor_price <= 0:
        return False
    if window is None or _dataframe_is_empty(window):
        return False
    _, low_price = _immediate_structural_low_after(window, anchor_idx)
    if low_price is None or low_price >= anchor_price:
        return False
    drop_pct = (float(anchor_price) - float(low_price)) / float(anchor_price) * 100.0
    margin_at_peak = _entry_margin_pct(anchor_price, exit_price)
    margin_at_low = _entry_margin_pct(low_price, exit_price)
    shrink = margin_at_peak - margin_at_low
    return drop_pct >= HILL_DROP_MIN_PCT and shrink >= HILL_MARGIN_SHRINK_MIN_PCT


def _three_hour_baseline_envelope(window) -> dict:
    """3-hour rolling dragnet volume mean/std envelope for liquidity ignition guard."""
    if window is None or (isinstance(window, pd.DataFrame) and window.empty):
        return {"mean": 0.0, "std": 0.0, "floor": 0.0}
    frame = window if isinstance(window, pd.DataFrame) else _ensure_dataframe(window)
    if frame is None or "Volume" not in frame.columns:
        return {"mean": 0.0, "std": 0.0, "floor": 0.0}
    vols = frame["Volume"].astype(float).fillna(0.0)
    if vols.empty:
        return {"mean": 0.0, "std": 0.0, "floor": 0.0}
    mu = float(vols.mean())
    sigma = float(vols.std()) if len(vols) > 1 else 0.0
    return {"mean": mu, "std": sigma, "floor": max(0.0, mu - sigma)}


def _local_volume_at(window, bar_idx) -> float:
    if bar_idx is None or window is None or _dataframe_is_empty(window):
        return 0.0
    if "Volume" not in window.columns:
        return 0.0
    try:
        return float(window.loc[bar_idx, "Volume"])
    except Exception:
        return 0.0


def _passes_absolute_volume_floor(window, bar_idx) -> bool:
    """Dual-filter guard — raw share volume must clear 10k shares/min institutional floor."""
    return _local_volume_at(window, bar_idx) >= LIQUIDITY_IGNITION_MIN_SHARES_PER_MINUTE


def _volatility_ignition_anchor(window, search_from_idx=None) -> tuple[object | None, float | None]:
    """
    Volatility Ignition — price velocity breaks above std envelope on expanding volume.
    """
    if (
        window is None
        or _dataframe_is_empty(window)
        or "Close" not in window.columns
        or "Volume" not in window.columns
    ):
        return None, None
    subset = window
    if search_from_idx is not None:
        try:
            subset = window[window.index >= search_from_idx]
        except Exception:
            subset = window
    if subset.empty or len(subset) < 2:
        return None, None
    closes = subset["Close"].astype(float)
    vols = subset["Volume"].astype(float).fillna(0.0)
    velocity = closes.pct_change().abs() * 100.0
    roll = min(5, len(subset))
    vel_mean = velocity.rolling(window=roll, min_periods=1).mean().fillna(0.0)
    vel_std = velocity.rolling(window=roll, min_periods=1).std().fillna(0.0)
    vol_mean = vols.rolling(window=roll, min_periods=1).mean().fillna(0.0)
    vol_std = vols.rolling(window=roll, min_periods=1).std().fillna(0.0)
    for idx in subset.index:
        v = velocity.loc[idx] if idx in velocity.index else float("nan")
        if pd.isna(v):
            continue
        env_high = float(vel_mean.loc[idx] + vel_std.loc[idx])
        vol_expand = float(vols.loc[idx]) >= float(vol_mean.loc[idx] + 0.5 * vol_std.loc[idx])
        raw_vol = float(vols.loc[idx])
        if (
            env_high > 0
            and float(v) > env_high
            and vol_expand
            and raw_vol >= LIQUIDITY_IGNITION_MIN_SHARES_PER_MINUTE
        ):
            return idx, float(subset.loc[idx, "Close"])
    return None, None


def evaluate_liquidity_ignition_guard(window) -> dict:
    """
    Dual-filter liquidity probe — velocity envelope break on sub-10k volume → REJECTED_DEAD_ZONE.
    """
    if (
        window is None
        or _dataframe_is_empty(window)
        or "Close" not in window.columns
        or "Volume" not in window.columns
    ):
        return {"status": "NO_SIGNAL", "reason": None}
    closes = window["Close"].astype(float)
    vols = window["Volume"].astype(float).fillna(0.0)
    velocity = closes.pct_change().abs() * 100.0
    roll = min(5, len(window))
    vel_mean = velocity.rolling(window=roll, min_periods=1).mean().fillna(0.0)
    vel_std = velocity.rolling(window=roll, min_periods=1).std().fillna(0.0)
    vol_mean = vols.rolling(window=roll, min_periods=1).mean().fillna(0.0)
    vol_std = vols.rolling(window=roll, min_periods=1).std().fillna(0.0)
    for idx in window.index:
        v = velocity.loc[idx] if idx in velocity.index else float("nan")
        if pd.isna(v):
            continue
        env_high = float(vel_mean.loc[idx] + vel_std.loc[idx])
        raw_vol = float(vols.loc[idx])
        vol_expand = raw_vol >= float(vol_mean.loc[idx] + 0.5 * vol_std.loc[idx])
        velocity_break = env_high > 0 and float(v) > env_high
        if velocity_break and vol_expand:
            if raw_vol < LIQUIDITY_IGNITION_MIN_SHARES_PER_MINUTE:
                return {
                    "status": REJECTED_DEAD_ZONE,
                    "reason": REJECTED_DEAD_ZONE,
                    "bar_index": idx,
                    "raw_volume": raw_vol,
                }
            return {
                "status": "IGNITION_CONFIRMED",
                "reason": None,
                "bar_index": idx,
                "raw_volume": raw_vol,
            }
    return {"status": "NO_SIGNAL", "reason": None}


def _execution_friction_buffer_pct(
    window,
    *,
    timeframe_resolution: str = "",
) -> float:
    """Simulated slippage buffer (0.5%–1.5%) from spread thickness; 5m hard 1.0% floor."""
    if window is None or (isinstance(window, pd.DataFrame) and window.empty):
        base = EXECUTION_FRICTION_SLIPPAGE_MIN
    elif not isinstance(window, pd.DataFrame):
        base = EXECUTION_FRICTION_SLIPPAGE_MIN
    elif "High" not in window.columns or "Low" not in window.columns or "Close" not in window.columns:
        base = EXECUTION_FRICTION_SLIPPAGE_MIN
    else:
        spread_pct = (
            (window["High"].astype(float) - window["Low"].astype(float))
            / window["Close"].astype(float).replace(0.0, float("nan"))
            * 100.0
        )
        mean_spread = float(spread_pct.mean(skipna=True) or 0.0)
        lo_sp, hi_sp = 0.05, 1.5
        t = max(0.0, min(1.0, (mean_spread - lo_sp) / (hi_sp - lo_sp)))
        base = EXECUTION_FRICTION_SLIPPAGE_MIN + t * (
            EXECUTION_FRICTION_SLIPPAGE_MAX - EXECUTION_FRICTION_SLIPPAGE_MIN
        )
    if str(timeframe_resolution).strip() == "5-Minute":
        return max(float(base), FIVE_MINUTE_SYNTHETIC_SLIPPAGE_PCT)
    return float(base)


def _candidate_manual_anchor(window, manual_entry_dt) -> tuple[object | None, float | None]:
    """Operator-clicked coordinate — reference only; hill-bypass may reject if on a trap."""
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
    baseline_window=None,
) -> dict:
    """
    Multi-candidate adaptive entry optimizer with hill bypass + liquidity ignition guard.
    A = volume peak, B = velocity spike, C = macro structural low.
    Hill traps on A/B force rewind to C; illiquid C shifts to volatility ignition minute.
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
    vel_idx, vel_price = _candidate_velocity_spike_anchor(window)
    struct_idx, struct_price = _candidate_structure_baseline(window, vol_idx)
    manual_idx, manual_price = _candidate_manual_anchor(window, manual_entry_dt)
    baseline_env = _three_hour_baseline_envelope(
        _first_usable_dataframe(baseline_window, window)
    )

    idx_by_label = {
        "volume_std_anchor": vol_idx,
        "velocity_spike_anchor": vel_idx,
        "structure_baseline": struct_idx,
        "manual_anchor": manual_idx,
    }
    price_by_label = {
        "volume_std_anchor": vol_price,
        "velocity_spike_anchor": vel_price,
        "structure_baseline": struct_price,
        "manual_anchor": manual_price,
    }

    raw_candidates = (
        ("volume_std_anchor", vol_idx, vol_price),
        ("velocity_spike_anchor", vel_idx, vel_price),
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
        disqualified_reason = None
        qualified = margin >= floor
        if not qualified:
            disqualified_reason = "below_floor_late_chase"
        elif label in ("volume_std_anchor", "velocity_spike_anchor"):
            if _hill_trap_shrinks_margin(window, ts, price, raw_exit):
                qualified = False
                disqualified_reason = "hill_trap_macro_rewind"
        elif label == "structure_baseline":
            local_vol = _local_volume_at(window, ts)
            if local_vol < float(baseline_env.get("floor", 0.0)):
                qualified = False
                disqualified_reason = "illiquid_dead_zone"
            elif not _passes_absolute_volume_floor(window, ts):
                qualified = False
                disqualified_reason = "below_10k_share_floor"
        scored.append(
            {
                "id": label,
                "timestamp": str(ts),
                "price": round(float(price), 6),
                "margin_pct": round(margin, 4),
                "qualified": qualified,
                "disqualified_reason": disqualified_reason,
            }
        )

    hill_rewind = False
    liquidity_ignition = False
    qualified = [c for c in scored if c.get("qualified") and c.get("price") is not None]

    winner_label: str | None = None
    winner_ts: str | None = None
    winner_price: float | None = None

    if qualified:
        winner = min(qualified, key=lambda c: (float(c["price"]), str(c["timestamp"])))
        winner_label = winner["id"]
        winner_ts = winner["timestamp"]
        winner_price = float(winner["price"])
        winner_idx = idx_by_label.get(winner_label)
        if winner_label in ("volume_std_anchor", "velocity_spike_anchor"):
            if _hill_trap_shrinks_margin(window, winner_idx, winner_price, raw_exit):
                hill_rewind = True
                struct_c = next((c for c in scored if c["id"] == "structure_baseline"), None)
                if struct_c and struct_c.get("price") is not None:
                    struct_margin = _entry_margin_pct(struct_c["price"], raw_exit)
                    if struct_margin >= floor:
                        local_vol = _local_volume_at(window, struct_idx)
                        if local_vol >= float(baseline_env.get("floor", 0.0)):
                            winner_label = "structure_baseline"
                            winner_ts = struct_c["timestamp"]
                            winner_price = float(struct_c["price"])
                        else:
                            ign_idx, ign_price = _volatility_ignition_anchor(window, struct_idx)
                            if ign_idx is not None and ign_price is not None:
                                ign_margin = _entry_margin_pct(ign_price, raw_exit)
                                if ign_margin >= floor:
                                    winner_label = "volatility_ignition"
                                    winner_ts = str(ign_idx)
                                    winner_price = float(ign_price)
                                    liquidity_ignition = True
        elif winner_label == "structure_baseline":
            local_vol = _local_volume_at(window, struct_idx)
            if local_vol < float(baseline_env.get("floor", 0.0)):
                ign_idx, ign_price = _volatility_ignition_anchor(window, struct_idx)
                if ign_idx is not None and ign_price is not None:
                    ign_margin = _entry_margin_pct(ign_price, raw_exit)
                    if ign_margin >= floor:
                        winner_label = "volatility_ignition"
                        winner_ts = str(ign_idx)
                        winner_price = float(ign_price)
                        liquidity_ignition = True
                    else:
                        winner_label = None
                        winner_ts = None
                        winner_price = None

    ignition_search_from = struct_idx or vol_idx
    if winner_label == "structure_baseline" and struct_idx is not None:
        ignition_search_from = struct_idx
    elif hill_rewind and struct_idx is not None:
        ignition_search_from = struct_idx

    saved_winner = {
        "label": winner_label,
        "ts": winner_ts,
        "price": winner_price,
        "liquidity_ignition": liquidity_ignition,
    }

    ign_idx, ign_price = _volatility_ignition_anchor(window, ignition_search_from)
    if ign_idx is not None and ign_price is not None:
        ign_margin = _entry_margin_pct(ign_price, raw_exit)
        if ign_margin >= floor:
            winner_label = "volatility_ignition"
            winner_ts = str(ign_idx)
            winner_price = float(ign_price)
            liquidity_ignition = True
        elif saved_winner.get("price") is not None:
            winner_label = saved_winner["label"]
            winner_ts = saved_winner["ts"]
            winner_price = float(saved_winner["price"])
            liquidity_ignition = bool(saved_winner["liquidity_ignition"])
    elif saved_winner.get("price") is not None:
        winner_label = saved_winner["label"]
        winner_ts = saved_winner["ts"]
        winner_price = float(saved_winner["price"])
        liquidity_ignition = bool(saved_winner["liquidity_ignition"])

    if winner_price is None and manual_idx is not None and manual_price is not None:
        manual_margin = _entry_margin_pct(manual_price, raw_exit)
        if manual_margin >= floor and not _hill_trap_shrinks_margin(
            window, manual_idx, manual_price, raw_exit
        ):
            winner_label = "manual_anchor"
            winner_ts = str(manual_idx)
            winner_price = float(manual_price)

    if winner_price is None or winner_label is None:
        st.session_state.room2_entry_optimizer = {
            "selected_candidate": None,
            "candidates": scored,
            "floor_pct": floor,
            "downhill_pivot": False,
            "hill_bypass_rewind": hill_rewind,
            "liquidity_ignition": False,
            "three_hour_volume_envelope": baseline_env,
        }
        return {**empty_result, "candidates": scored}

    winner_margin = _entry_margin_pct(winner_price, raw_exit)
    if winner_margin < floor:
        st.session_state.room2_entry_optimizer = {
            "selected_candidate": None,
            "candidates": scored,
            "floor_pct": floor,
            "downhill_pivot": False,
            "hill_bypass_rewind": hill_rewind,
            "liquidity_ignition": False,
            "three_hour_volume_envelope": baseline_env,
        }
        return {**empty_result, "candidates": scored}
    meta = {
        "selected_candidate": winner_label,
        "candidates": scored,
        "floor_pct": floor,
        "downhill_pivot": winner_label not in ("volume_std_anchor", "velocity_spike_anchor"),
        "hill_bypass_rewind": hill_rewind,
        "liquidity_ignition": liquidity_ignition,
        "three_hour_volume_envelope": baseline_env,
        "volatility_ignition_entry_price": round(float(winner_price), 6),
        "volatility_ignition_timestamp": winner_ts,
        "winner_margin_pct": round(winner_margin, 4),
        "manual_anchor_reference": (
            {"timestamp": str(manual_idx), "price": round(float(manual_price), 6)}
            if manual_idx is not None and manual_price is not None
            else None
        ),
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
    Genetic cross-reference — high overlap merges via Supabase RPC on database servers.
    """
    _ = library
    spatial = compute_spatial_layout_match(snapshot_vec)
    overlap = max(int(spatial_match_pct or 0), int(spatial.get("spatial_match_pct") or 0))

    merged = cloud_offload.rpc_merge_layout_signature(
        snapshot_vec,
        match_threshold=LAYOUT_SIGNATURE_MATCH_THRESHOLD / 100.0,
        noise_epsilon=NOISE_DIM_EPSILON,
    )
    if merged and isinstance(merged.get("master_signature"), list):
        sig = [float(x) for x in merged["master_signature"]]
        return {
            "master_signature": sig,
            "layout_id": str(merged.get("layout_id") or "PURGATORY_PENDING"),
            "overlap_pct": int(merged.get("overlap_pct") or overlap),
            "noise_discarded": bool(merged.get("noise_discarded")),
            "dimensions_trashed": int(merged.get("dimensions_trashed") or 0),
            "pure_overlap_dims": int(merged.get("pure_overlap_dims") or 0),
        }

    if overlap >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        nearest = str(spatial.get("nearest_layout_id") or "NEW_LAYOUT")
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
    Bars after exit are stripped; 1m uses 5-bar / 5m uses 36-bar dragnet from Start Time.
    """
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return data_stream, {}

    end_dt = _parse_session_datetime(end_date, end_time)
    if end_dt is None:
        return frame, {}

    start_dt = _parse_session_datetime(start_date, start_time)
    lookback_start = _calibrated_lookback_start(
        end_dt,
        timeframe_resolution,
        start_dt=start_dt,
        data_stream=frame,
    )
    if start_dt is not None and lookback_start is not None and start_dt < lookback_start:
        lookback_start = start_dt

    adaptive_edge = False
    try:
        if not frame.empty:
            first_ts = frame.index.min()
            if lookback_start is not None and first_ts is not None and lookback_start < first_ts:
                lookback_start = first_ts
                adaptive_edge = True
    except Exception:
        pass

    try:
        if lookback_start is not None:
            fenced = frame[(frame.index <= end_dt) & (frame.index >= lookback_start)]
        else:
            fenced = frame[frame.index <= end_dt]
        if isinstance(fenced, pd.DataFrame) and not fenced.empty:
            frame = fenced
    except Exception:
        pass

    meta = {
        "temporal_fence_end": end_dt.isoformat(),
        "lookback_start": lookback_start.isoformat() if lookback_start is not None and hasattr(lookback_start, "isoformat") else (str(lookback_start) if lookback_start else None),
        "adaptive_data_edge": adaptive_edge,
        "timeframe_resolution": timeframe_resolution,
        "five_minute_dragnet_bars": FIVE_MINUTE_DRAGNET_BARS
        if timeframe_resolution == "5-Minute"
        else None,
        "one_minute_dragnet_bars": ONE_MINUTE_DRAGNET_BARS
        if timeframe_resolution == "1-Minute"
        else None,
    }
    lane_check = validate_regime_lookback_lanes(
        frame,
        start_date=start_date,
        start_time=start_time,
        timeframe_resolution=timeframe_resolution,
    )
    meta["lookback_lane"] = lane_check
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
    Operator-first quality gate — only two decisions:
    1) Window must fit the selected bar size (1m/5m/15m).
    2) Net move inside the operator window must clear the tiered floor.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    end_dt = _parse_session_datetime(end_date, end_time)
    start_dt = _parse_session_datetime(start_date, start_time)
    timeframe_fit = validate_operator_timeframe_fit(start_dt, end_dt, timeframe_resolution)

    operator_spike = _operator_window_spike_metrics(data_stream, start_dt, end_dt)
    structural_move_pct = float(operator_spike.get("envelope_move_pct") or 0.0)
    ignition_price = operator_spike.get("window_low")
    exit_price = operator_spike.get("window_high")
    ignition_ts = operator_spike.get("low_ts")
    exit_anchor_ts = operator_spike.get("high_ts")
    raw_exit_price = _price_at_datetime(data_stream, end_dt)

    if start_dt is not None and end_dt is not None:
        start_px = _price_at_datetime(data_stream, start_dt)
        end_px = raw_exit_price
        if start_px and end_px and start_px > 0:
            coord_move = abs((end_px - start_px) / start_px * 100)
            if coord_move > structural_move_pct:
                structural_move_pct = coord_move
                ignition_price = start_px
                exit_price = end_px
                ignition_ts = str(start_dt)
                exit_anchor_ts = str(end_dt)

    lookback_start = _calibrated_lookback_start(
        end_dt,
        timeframe_resolution,
        start_dt=start_dt,
        data_stream=data_stream,
    ) if end_dt else None
    gate_window = _lookback_window_frame(data_stream, end_dt, lookback_start)
    friction_pct = _execution_friction_buffer_pct(
        gate_window,
        timeframe_resolution=timeframe_resolution,
    )
    net_margin_pct = round(structural_move_pct - friction_pct, 4)
    passed = bool(timeframe_fit.get("passed")) and net_margin_pct >= floor_pct
    quality = {
        "passed": passed,
        "trashed": not passed,
        "structural_move_pct": round(structural_move_pct, 4),
        "execution_friction_buffer_pct": round(friction_pct, 4),
        "net_margin_pct": net_margin_pct,
        "floor_pct": floor_pct,
        "anchor_timestamp": str(ignition_ts) if ignition_ts is not None else None,
        "anchor_price": ignition_price,
        "volatility_ignition_entry_price": ignition_price,
        "volatility_ignition_timestamp": str(ignition_ts) if ignition_ts is not None else None,
        "exit_price": exit_price,
        "raw_exit_price": raw_exit_price,
        "exit_anchor_timestamp": exit_anchor_ts,
        "timeframe_resolution": timeframe_resolution,
        "lookback_start": str(lookback_start) if lookback_start else None,
        "entry_candidate_selected": "operator_window_envelope",
        "operator_window_envelope": True,
        "operator_spike_metrics": operator_spike,
        "timeframe_fit": timeframe_fit,
        "trash_reason": (
            timeframe_fit.get("message")
            if not timeframe_fit.get("passed")
            else None
        ),
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
    ledger_kwargs = {
        key: kwargs[key]
        for key in (
            "ticker",
            "macro_weather_layout",
            "execution_strategy",
            "timeframe_resolution",
            "margin_pct",
            "pattern_category",
            "layout_match_pct",
            "structural_move_pct",
        )
        if key in kwargs
    }
    ok, _detail = record_strategy_execution(**ledger_kwargs)
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
    """Cloud-stream macro refresh — uses cached Polygon 1m RAM when available."""
    ticker_clean = str(ticker or "").strip().upper()
    if not ticker_clean:
        return
    frame_1m = _cached_polygon_1m_frame()
    bars = resample_ohlcv_bars(frame_1m, "15min") if frame_1m is not None else None
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


def _polygon_call_available() -> bool:
    _init_polygon_rate_monitor()
    return int(st.session_state.polygon_calls_remaining) > 0


def _polygon_throttle_seconds_remaining() -> int:
    _init_polygon_rate_monitor()
    elapsed = time.time() - float(st.session_state.polygon_rate_window_start)
    return max(0, int(60 - elapsed))


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


def _twenty_day_volume_baseline(ticker: str, data_stream=None) -> float:
    """Session-volume proxy baseline — Polygon-only pipeline (no secondary daily fetch)."""
    volumes = _volume_series_from_data_stream(data_stream)
    if volumes is None:
        return 0.0
    if pd is not None and isinstance(volumes, pd.Series) and not volumes.empty:
        return float(volumes.mean()) * max(1, BARS_PER_SESSION.get("15m", 26))
    if isinstance(volumes, list) and volumes:
        return float(sum(volumes) / len(volumes)) * max(1, BARS_PER_SESSION.get("15m", 26))
    return 0.0


def _detect_institutional_block_accumulation(ticker: str, data_stream, interval: str) -> dict:
    """
    Free institutional proxy tracker: flags block accumulation when any active
    execution-window bar exceeds 300% above the 20-day volume baseline.
    """
    baseline_daily = _twenty_day_volume_baseline(ticker, data_stream)
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


def apply_local_strike_ram_cap(
    data_stream,
    cap_minutes: int = LOCAL_1M_RAM_CAP_MINUTES,
    *,
    start_dt: datetime.datetime | None = None,
    end_dt: datetime.datetime | None = None,
):
    """
    Optional 1m RAM trim around the operator window.
    Must keep bars before Start Time (dragnet lookback). Never trim to
    "last N minutes of the whole session" — that wipes pre-start context.
    """
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return data_stream
    try:
        lookback_pad = datetime.timedelta(
            minutes=max(int(cap_minutes), ONE_MINUTE_DRAGNET_BARS)
        )
        if start_dt is not None and end_dt is not None and end_dt >= start_dt:
            left = start_dt - lookback_pad
            right = end_dt
            trimmed = frame[(frame.index >= left) & (frame.index <= right)]
        elif start_dt is not None:
            left = start_dt - lookback_pad
            trimmed = frame[frame.index >= left]
        else:
            # No operator anchor — keep full frame (safe default for forensic deploy).
            st.session_state.r2_local_ram_bar_count = len(frame)
            return frame
        if isinstance(trimmed, pd.DataFrame) and not trimmed.empty:
            st.session_state.r2_local_ram_bar_count = len(trimmed)
            return trimmed
    except Exception:
        pass
    return frame


def _fetch_research_news_headlines(ticker: str, *, limit: int = 8) -> list[str]:
    """Cloud-side news wire for Room 2 deep research — RSS only (Polygon-only pipeline)."""
    headlines: list[str] = []
    ticker_clean = str(ticker).strip().upper()
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
    start_dt = _parse_session_datetime(start_date, start_time)
    lookback_start = (
        _calibrated_lookback_start(
            end_dt,
            timeframe_resolution,
            start_dt=start_dt,
            data_stream=data_stream,
        )
        if end_dt
        else None
    )
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
            start_date=start_date,
            start_time=start_time,
        )
        dragnet_start = _research_dragnet_lookback_start(
            end_dt,
            timeframe_resolution,
            start_dt=start_dt,
            data_stream=data_stream,
        )
        frame_1m = _cached_polygon_1m_frame()
        track = (
            _resolve_track_from_1m(frame_1m, timeframe_resolution)
            if frame_1m is not None
            else _ensure_dataframe(data_stream)
        )
        if track is not None and dragnet_start is not None and end_dt is not None:
            try:
                sliced = track[(track.index <= end_dt) & (track.index >= dragnet_start)]
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

    interval_token = {"1-Minute": "1m", "5-Minute": "5m", "15-Minute": "15m"}.get(
        timeframe_resolution, "15m"
    )
    try:
        institutional = dragnet_blob.get("institutional") or _detect_institutional_block_accumulation(
            ticker_clean, audit_frame, interval_token
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
    ignition_ts = quality.get("volatility_ignition_timestamp") or quality.get("anchor_timestamp")
    if st.session_state.get("room2_sentiment_suppressed"):
        semantic_catalyst = {
            "finbert_sentiment_score": 0.0,
            "message_velocity": 0.0,
            "audience_scale": 0.0,
            "impact_weight": 0.0,
            "semantic_mode": "suppressed_chart_coupling_lock",
            "headline_count": 0,
            "filing_count": 0,
            "suppressed": True,
        }
    else:
        semantic_catalyst = dragnet_blob.get("semantic_catalyst") or score_semantic_catalyst_stream(
            news_headlines,
            filing_texts=filing_texts,
            filing_records=sec_dragnet.get("filings") or [],
            volatility_ignition_ts=ignition_ts,
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
    *,
    start_date=None,
    end_date=None,
    timeframe_resolution: str | None = None,
):
    """
  Room 2 datalink — Polygon 1m macro-request + local resample (v2 pipeline).
    Legacy interval/micro_fast_track kwargs retained for app compatibility.
    """
    _ = (force_yfinance_only, micro_fast_track, interval)
    tf = timeframe_resolution or {
        "1m": "1-Minute",
        "5m": "5-Minute",
        "15m": "15-Minute",
    }.get(str(interval).lower(), "15-Minute")
    if start_date is None or end_date is None:
        return POLYGON_REST_DATA_EMPTY
    return _get_room2_polygon_pipeline_with_macro(
        ticker,
        start_date=start_date,
        end_date=end_date,
        timeframe_resolution=tf,
        update_institutional_tracker=update_institutional_tracker,
    )


def _get_room2_polygon_pipeline_with_macro(
    ticker,
    *,
    start_date,
    end_date,
    timeframe_resolution: str,
    update_institutional_tracker: bool = True,
):
    data_stream = get_room2_polygon_pipeline(
        ticker,
        start_date=start_date,
        end_date=end_date,
        timeframe_resolution=timeframe_resolution,
    )
    if is_pipeline_signal(data_stream, "THROTTLE", POLYGON_REST_DATA_EMPTY):
        return data_stream

    if not is_usable_data_stream(data_stream):
        return POLYGON_REST_DATA_EMPTY

    interval_token = {"1-Minute": "1m", "5-Minute": "5m", "15-Minute": "15m"}.get(
        timeframe_resolution, "15m"
    )
    if update_institutional_tracker and timeframe_resolution != "1-Minute":
        fetch_cloud_macro_intelligence(str(ticker).strip().upper(), interval_token, data_stream)
    elif update_institutional_tracker:
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


def _get_historical_interval_data_impl(
    ticker,
    interval="15m",
    update_institutional_tracker=True,
    force_yfinance_only=False,
    micro_fast_track=False,
    *,
    start_date=None,
    end_date=None,
    timeframe_resolution: str | None = None,
):
    return get_historical_interval_data(
        ticker,
        interval=interval,
        update_institutional_tracker=update_institutional_tracker,
        force_yfinance_only=force_yfinance_only,
        micro_fast_track=micro_fast_track,
        start_date=start_date,
        end_date=end_date,
        timeframe_resolution=timeframe_resolution,
    )


def get_historical_5m_data(ticker, *, start_date=None, end_date=None):
    """Polygon 1m macro-fetch + local 5m resample."""
    return get_historical_interval_data(
        ticker,
        interval="5m",
        update_institutional_tracker=False,
        start_date=start_date,
        end_date=end_date,
        timeframe_resolution="5-Minute",
    )


def get_historical_15m_data(ticker, *, start_date=None, end_date=None):
    """Polygon 1m macro-fetch + local 15m resample."""
    return get_historical_interval_data(
        ticker,
        interval="15m",
        start_date=start_date,
        end_date=end_date,
        timeframe_resolution="15-Minute",
    )


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


def build_four_layer_feature_vector(
    velocity: dict,
    metric_envelopes: dict | None,
    *,
    vwap_bias_pct: float = 0.0,
    sec_coordinate: float = 0.0,
    math_block: dict | None = None,
) -> list[float]:
    """
    4-Layer Feature Vector — Price Velocity, Volume σ Envelopes, native VWAP, SEC coordinate.
    SEC / FinBERT axis hard-clamped to [-1.0, +1.0].
    """
    env = metric_envelopes or {}
    vol_env = env.get("volume") or env.get("Volume") or {}
    mb = math_block or {}
    sec = max(-1.0, min(1.0, float(sec_coordinate)))
    return [
        float(velocity.get("session_velocity_pct", 0.0)),
        float(velocity.get("peak_bar_velocity_pct", 0.0)),
        float(velocity.get("mean_bar_velocity_pct", 0.0)),
        float(vol_env.get("sigma") or vol_env.get("std") or 0.0),
        float(vol_env.get("z_score") or vol_env.get("z") or 0.0),
        round(float(vwap_bias_pct), 4),
        sec,
        float(mb.get("pearson_r", 0.0)),
    ]


def extract_forensic_feature_vector(
    velocity: dict,
    math_block: dict,
    finbert_sentiment: float = 0.0,
    metric_envelopes: dict | None = None,
    vwap_bias_pct: float = 0.0,
) -> list[float]:
    """Snapshot vector for spatial cross-correlation — 4-layer fusion for pgvector shell match."""
    return build_four_layer_feature_vector(
        velocity,
        metric_envelopes,
        vwap_bias_pct=vwap_bias_pct,
        sec_coordinate=finbert_sentiment,
        math_block=math_block,
    )


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
    """Cosine spatial clustering — executed on Supabase, not in local RAM."""
    _ = library
    remote = cloud_offload.rpc_match_layout_spatial(snapshot_vec)
    if remote:
        st.session_state.r2_spatial_lane = "supabase_rpc"
        return remote

    if cloud_offload.cloud_offload_strict() and cloud_offload.supabase_configured():
        return {
            "spatial_match_pct": 0,
            "cosine_similarity": 0.0,
            "euclidean_distance": 999.0,
            "nearest_layout_id": "NEW_LAYOUT",
        }

    st.session_state.r2_spatial_lane = "local_fallback"
    index = list(st.session_state.get("layout_master_matrix_index") or [])
    best_cosine = 0.0
    best_euclidean = 999.0
    nearest_layout = "NEW_LAYOUT"
    for entry in index:
        stored = entry.get("vector") or []
        if not stored:
            continue
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
    """Layout registry metadata only — vectors persist in Supabase vault, not local RAM."""
    _ = vector
    index = list(st.session_state.get("layout_master_matrix_index", []))
    index.insert(
        0,
        {
            "layout_id": layout_id,
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
        if not layout_id:
            continue
        dedupe = f"{layout_id}|{row.get('timeframe_resolution')}|{row.get('ticker')}"
        if dedupe in seen:
            continue
        seen.add(dedupe)
        index.append(
            {
                "layout_id": layout_id,
                "ticker": str(row.get("ticker") or "").upper(),
                "timeframe_resolution": str(row.get("timeframe_resolution") or ""),
                "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
            }
        )

    st.session_state.layout_master_matrix_index = index[:256]
    st.session_state.layout_library_hydrated_cloud = True
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
    layout_count = len(st.session_state.get("layout_master_matrix_index") or [])
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
            headers=_supabase_rest_headers(),
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
        "layout_vector_count": layout_count,
        "layout_registry": (st.session_state.get("layout_master_matrix_index") or [])[:48],
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


def _room1_lane_tail(frame, bar_count: int):
    """Return the trailing N-bar lane window from a resampled frame."""
    lane = _ensure_dataframe(frame)
    if lane is None or lane.empty or bar_count <= 0:
        return None
    return lane.tail(bar_count)


def fetch_room1_yahoo_tape_snapshot(ticker: str) -> dict:
    """Room 1 live tape — Yahoo chart API (no Polygon budget)."""
    ticker_clean = str(ticker or "").strip().upper()
    empty = {
        "ok": False,
        "ticker": ticker_clean,
        "price": 0.0,
        "pct_change": 0.0,
        "volume": 0,
        "vwap_native": 0.0,
        "name": ticker_clean or "Unknown",
    }
    if not ticker_clean:
        return empty
    sym = urllib.parse.quote(ticker_clean, safe="")
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": "1m", "range": "1d"},
            headers={"User-Agent": "SavantApprentice/1.0"},
            timeout=10,
        )
        if not resp.ok:
            return empty
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return empty
        meta = result[0].get("meta") or {}
        quote = (result[0].get("indicators") or {}).get("quote", [{}])[0]
        closes = [float(c) for c in (quote.get("close") or []) if c is not None]
        volumes = [int(float(v)) for v in (quote.get("volume") or []) if v is not None]
        highs = [float(h) for h in (quote.get("high") or []) if h is not None]
        lows = [float(lo) for lo in (quote.get("low") or []) if lo is not None]
        price = float(
            meta.get("regularMarketPrice")
            or (closes[-1] if closes else 0.0)
            or 0.0
        )
        prev = float(
            meta.get("chartPreviousClose")
            or meta.get("previousClose")
            or (closes[-2] if len(closes) > 1 else price)
            or price
        )
        pct = ((price - prev) / prev * 100.0) if prev else 0.0
        raw_vol = int(
            meta.get("regularMarketVolume")
            or (volumes[-1] if volumes else 0)
            or 0
        )
        if highs and lows:
            vwap_native = (highs[-1] + lows[-1] + price) / 3.0
        else:
            vwap_native = price
        name = str(
            meta.get("longName") or meta.get("shortName") or meta.get("symbol") or ticker_clean
        )
        return {
            "ok": True,
            "ticker": ticker_clean,
            "price": price,
            "pct_change": round(pct, 4),
            "volume": raw_vol,
            "vwap_native": round(vwap_native, 4),
            "name": name,
        }
    except Exception:
        return empty


def run_room1_yahoo_tape_dragnet(ticker: str, user_query: str = "") -> dict:
    """Lightweight Room 1 dragnet — Yahoo tape + headlines (Polygon-free)."""
    ticker_clean = str(ticker or "").strip().upper()
    snap = fetch_room1_yahoo_tape_snapshot(ticker_clean)
    if not snap.get("ok"):
        return {
            "ok": False,
            "ticker": ticker_clean,
            "payload_string": f"12L|TK:{ticker_clean}|YAHOO:EMPTY",
            "report_block": f"ROOM1_LIVE_DRAGNET|TK:{ticker_clean}|STATUS:YAHOO_EMPTY",
            "headlines": [],
        }
    price = float(snap.get("price") or 0.0)
    pct = float(snap.get("pct_change") or 0.0)
    raw_vol = int(snap.get("volume") or 0)
    vwap_native = float(snap.get("vwap_native") or 0.0)
    headlines = _fetch_research_news_headlines(ticker_clean, limit=6)
    headline_preview = " | ".join(headlines[:4]) if headlines else "NONE"
    sec_dragnet = _scrape_sec_regulatory_dragnet(ticker_clean, days=30)
    sec_preview = ", ".join(
        f"{f.get('form')}@{f.get('filing_date')}" for f in (sec_dragnet.get("filings") or [])[:4]
    ) or "NONE"
    payload_string = (
        f"12L|TK:{ticker_clean}|SRC:YAHOO_FINANCE|CO:{snap.get('name', ticker_clean)}|"
        f"P:{price:.2f}|CHG:{pct:+.2f}%|V:{raw_vol:,}|VW:{vwap_native:.2f}|"
        f"SEC:{sec_preview}|WIRE:{headline_preview}"
    )
    report_lines = [
        f"ROOM1_LIVE_DRAGNET|TK:{ticker_clean}|SRC:yahoo_finance",
        f"LIVE_PRICE:{price:.4f}",
        f"LIVE_CHG_PCT:{pct:+.4f}",
        f"LIVE_VOL:{raw_vol}",
        f"SESS_VWAP_PROXY:{vwap_native:.4f}",
        f"SEC_TIMELINE:{sec_preview}",
        f"LIVE_HEADLINES:{headline_preview}",
    ]
    if user_query.strip():
        report_lines.append(f"OPERATOR_QUERY:{user_query.strip()[:240]}")
    result = {
        "ok": True,
        "ticker": ticker_clean,
        "payload_string": payload_string,
        "report_block": " | ".join(report_lines),
        "headlines": headlines,
        "price": price,
        "pct_change": pct,
        "volume": raw_vol,
        "vwap_native": vwap_native,
        "name": snap.get("name", ticker_clean),
        "data_source": "yahoo_finance",
    }
    st.session_state.room1_live_dragnet = result
    return result


def run_room1_operator_dragnet(ticker: str, user_query: str = "") -> dict:
    """Room 1 — yfinance only. Polygon/Massive is reserved for Room 2 deploys."""
    return run_room1_yahoo_tape_dragnet(ticker, user_query=user_query)


def run_room1_live_massive_dragnet(ticker: str, user_query: str = "") -> dict:
    ticker_clean = str(ticker).strip().upper()
    today = datetime.date.today()
    empty = {
        "ok": False,
        "ticker": ticker_clean,
        "payload_string": f"12L|TK:{ticker_clean}|MASSIVE:EMPTY|SEC:UNAVAILABLE",
        "report_block": f"ROOM1_LIVE_DRAGNET|TK:{ticker_clean}|STATUS:MASSIVE_EMPTY",
        "headlines": [],
    }

    frame_1m = get_historical_interval_data(
        ticker_clean,
        interval="1m",
        update_institutional_tracker=False,
        start_date=today,
        end_date=today,
        timeframe_resolution="1-Minute",
    )
    if is_pipeline_signal(frame_1m, "THROTTLE", POLYGON_REST_DATA_EMPTY):
        err = str(st.session_state.get("r2_market_data_error") or "MASSIVE_THROTTLE")
        empty["report_block"] = f"ROOM1_LIVE_DRAGNET|TK:{ticker_clean}|FAULT:{err}"
        return empty
    if not is_usable_data_stream(frame_1m):
        return empty

    frame_5m = resample_ohlcv_bars(frame_1m, "5min")
    frame_15m = resample_ohlcv_bars(frame_1m, "15min")
    lane_5m = _room1_lane_tail(frame_5m, FIVE_MINUTE_DRAGNET_BARS)
    lane_15m = _room1_lane_tail(frame_15m, FIFTEEN_MINUTE_DRAGNET_BARS)

    end_5m = lane_5m.index[-1] if lane_5m is not None and not lane_5m.empty else None
    start_5m = lane_5m.index[0] if lane_5m is not None and not lane_5m.empty else None
    end_15m = lane_15m.index[-1] if lane_15m is not None and not lane_15m.empty else None
    start_15m = lane_15m.index[0] if lane_15m is not None and not lane_15m.empty else None

    env_5m = compute_metric_envelopes(lane_5m, end_5m, start_5m) if lane_5m is not None else {}
    env_15m = compute_metric_envelopes(lane_15m, end_15m, start_15m) if lane_15m is not None else {}
    velocity_5m = _compute_price_velocity_metrics(lane_5m if lane_5m is not None else frame_1m)
    velocity_15m = _compute_price_velocity_metrics(lane_15m if lane_15m is not None else frame_1m)

    price = float(frame_1m["Close"].iloc[-1])
    prev = float(frame_1m["Close"].iloc[-2]) if len(frame_1m) > 1 else price
    pct = ((price - prev) / prev * 100.0) if prev else 0.0
    raw_vol = int(float(frame_1m["Volume"].iloc[-1] or 0))
    vwap_native = float(frame_1m["VWAP"].iloc[-1]) if "VWAP" in frame_1m.columns else 0.0
    if not vwap_native and "High" in frame_1m.columns and "Low" in frame_1m.columns:
        vwap_native = (float(frame_1m["High"].iloc[-1]) + float(frame_1m["Low"].iloc[-1]) + price) / 3.0
    vwap_15m = (
        float(lane_15m["VWAP"].iloc[-1])
        if lane_15m is not None and "VWAP" in lane_15m.columns
        else vwap_native
    )
    vwap_bias_pct = ((price - vwap_15m) / vwap_15m * 100.0) if vwap_15m else 0.0

    vol_sigma_5m = float((env_5m.get("volume") or {}).get("sigma") or 0.0)
    vol_sigma_15m = float((env_15m.get("volume") or {}).get("sigma") or 0.0)

    struct_low_price = None
    ignition_price = None
    if lane_5m is not None and not lane_5m.empty:
        vol_idx, _ = _candidate_volume_std_anchor(lane_5m)
        struct_idx, struct_price = _candidate_structure_baseline(lane_5m, vol_idx)
        if struct_price is not None:
            struct_low_price = round(float(struct_price), 4)
        ign_idx, ign_px = _volatility_ignition_anchor(lane_5m, struct_idx or vol_idx)
        if ign_px is not None:
            ignition_price = round(float(ign_px), 4)

    sec_dragnet = _scrape_sec_regulatory_dragnet(ticker_clean, days=30)
    form4 = _scrape_form4_insider_buys(ticker_clean)
    headlines = _fetch_research_news_headlines(ticker_clean, limit=6)
    filing_texts = [
        f"SEC {f.get('form', 'FILING')} filed {f.get('filing_date', '')}"
        for f in (sec_dragnet.get("filings") or [])
    ]
    semantic = score_semantic_catalyst_stream(headlines, filing_texts=filing_texts)
    finbert_score = float(semantic.get("finbert_sentiment_score") or 0.0)

    sec_preview = ", ".join(
        f"{f.get('form')}@{f.get('filing_date')}" for f in (sec_dragnet.get("filings") or [])[:5]
    ) or "NONE"
    headline_preview = " | ".join(headlines[:4]) if headlines else "NONE"

    bars_5m = len(lane_5m) if lane_5m is not None else 0
    bars_15m = len(lane_15m) if lane_15m is not None else 0

    payload_string = (
        f"12L|TK:{ticker_clean}|SRC:MASSIVE_REST+SEC_EDGAR|"
        f"P:{price:.2f}|CHG:{pct:+.2f}%|V:{raw_vol:,}|VW:{vwap_native:.2f}|"
        f"LANE_5M_BARS:{bars_5m}|LANE_15M_BARS:{bars_15m}|"
        f"L1_VEL_5M:{velocity_5m.get('session_velocity_pct')}%|"
        f"L1_PEAK_VEL:{velocity_5m.get('peak_bar_velocity_pct')}%|"
        f"L2_VOL_SIGMA_5M:{vol_sigma_5m:.4f}|L2_VOL_SIGMA_15M:{vol_sigma_15m:.4f}|"
        f"L3_VWAP_15M:{vwap_15m:.2f}|L3_VWAP_BIAS:{vwap_bias_pct:+.2f}%|"
        f"L4_STRUCT_LOW:{struct_low_price}|L4_IGNITION:{ignition_price}|"
        f"FINBERT:{finbert_score}|SEC:{sec_preview}|WIRE:{headline_preview}|"
        f"FORM4:{form4.get('form4_summary', 'N/A')}"
    )

    report_lines = [
        f"ROOM1_LIVE_DRAGNET|TK:{ticker_clean}|SRC:massive.com+SEC_EDGAR",
        f"LANE_5M:{bars_5m}/{FIVE_MINUTE_DRAGNET_BARS}_bars_3h",
        f"LANE_15M:{bars_15m}/{FIFTEEN_MINUTE_DRAGNET_BARS}_bars_12h",
        f"L1_SESSION_VEL_5M:{velocity_5m.get('session_velocity_pct')}%",
        f"L1_PEAK_VEL_5M:{velocity_5m.get('peak_bar_velocity_pct')}%",
        f"L1_SESSION_VEL_15M:{velocity_15m.get('session_velocity_pct')}%",
        f"L2_VOL_SIGMA_5M:{vol_sigma_5m}",
        f"L2_VOL_SIGMA_15M:{vol_sigma_15m}",
        f"L3_VWAP_15M:{vwap_15m:.4f}",
        f"L3_VWAP_BIAS_PCT:{vwap_bias_pct:.4f}",
        f"L4_CANDIDATE_C_LOW:{struct_low_price}",
        f"L4_VOLATILITY_IGNITION:{ignition_price}",
        f"FINBERT_SEC_COORD:{finbert_score}",
        f"SEC_TIMELINE:{sec_preview}",
        f"FORM4:{form4.get('form4_summary', 'N/A')}",
        f"LIVE_HEADLINES:{headline_preview}",
    ]
    if user_query.strip():
        report_lines.append(f"OPERATOR_QUERY:{user_query.strip()[:240]}")

    report_block = " | ".join(report_lines)
    result = {
        "ok": True,
        "ticker": ticker_clean,
        "payload_string": payload_string,
        "report_block": report_block,
        "headlines": headlines,
        "lane_5m_bars": bars_5m,
        "lane_15m_bars": bars_15m,
        "velocity_5m": velocity_5m,
        "velocity_15m": velocity_15m,
        "metric_envelopes_5m": env_5m,
        "metric_envelopes_15m": env_15m,
        "vwap_bias_pct": round(vwap_bias_pct, 4),
        "candidate_c_low": struct_low_price,
        "volatility_ignition_price": ignition_price,
        "sec_dragnet": sec_dragnet,
        "form4": form4,
        "semantic": semantic,
        "price": price,
        "pct_change": round(pct, 4),
        "volume": raw_vol,
        "vwap_native": round(vwap_native, 4),
    }
    st.session_state.room1_live_dragnet = result
    return result


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
    Delegates live price physics to Massive 3h/12h lanes before vault spatial match.
    """
    ticker_clean = str(ticker).strip().upper()
    live = run_room1_live_massive_dragnet(ticker_clean, user_query=user_query)
    vault_map = fetch_readonly_vault_reference_map()

    data_stream = get_historical_interval_data(
        ticker_clean,
        interval="15m",
        update_institutional_tracker=False,
    )
    if live.get("ok"):
        velocity = live.get("velocity_15m") or live.get("velocity_5m") or {}
    else:
        velocity = _compute_price_velocity_metrics(data_stream)
    math_block = _room1_quick_math_block(data_stream)

    headlines = live.get("headlines") or _fetch_research_news_headlines(ticker_clean, limit=8)
    sec_dragnet = live.get("sec_dragnet") or _scrape_sec_regulatory_dragnet(ticker_clean)
    form4 = live.get("form4") or _scrape_form4_insider_buys(ticker_clean)
    semantic = live.get("semantic") or score_semantic_catalyst_stream(
        headlines,
        filing_texts=[
            f"SEC {f.get('form', 'FILING')} filed {f.get('filing_date', '')}"
            for f in (sec_dragnet.get("filings") or [])
        ],
    )
    finbert_score = float(semantic.get("finbert_sentiment_score") or 0.0)

    live_vec = extract_forensic_feature_vector(velocity, math_block, finbert_score)
    spatial = compute_spatial_layout_match(live_vec)

    top_alignments = cloud_offload.rpc_top_layout_alignments(live_vec, limit=5)
    if not top_alignments and not cloud_offload.cloud_offload_strict():
        library = vault_map.get("layout_registry") or []
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
        live.get("report_block", "") if live.get("ok") else "LIVE_DRAGNET:FAILED",
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


def format_operator_session_timestamp(dt: datetime.datetime | None) -> str | None:
    """Canonical operator clock string aligned to stripped bar index (YYYY-MM-DD HH:MM:SS)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_operator_boundaries(
    start_date,
    start_time: str,
    end_date,
    end_time: str,
) -> tuple[datetime.datetime | None, datetime.datetime | None, str | None, str | None]:
    """Parse and normalize operator Start/Exit to naive ET strings matching the bar index."""
    start_dt = _parse_session_datetime(start_date, start_time)
    end_dt = _parse_session_datetime(end_date, end_time)
    return (
        start_dt,
        end_dt,
        format_operator_session_timestamp(start_dt),
        format_operator_session_timestamp(end_dt),
    )


def validate_chart_data_coupling(data_stream, quality: dict | None = None) -> dict:
    """
    Coupling lock — chart lane must have bars before SEC/vault writes.
    Move quality is decided solely by the operator-window margin floor.
    """
    quality = dict(quality or {})
    frame = _ensure_dataframe(data_stream)
    reasons: list[str] = []

    if _dataframe_is_empty(frame):
        reasons.append("chart_empty")

    total_volume = 0.0
    if frame is not None and not frame.empty and "Volume" in frame.columns:
        total_volume = float(frame["Volume"].astype(float).fillna(0.0).sum())
        if total_volume <= 0:
            reasons.append("zero_volume")

    passed = len(reasons) == 0
    return {
        "passed": passed,
        "trashed": not passed,
        "chart_coupling_ok": passed,
        "flatline": False,
        "zero_velocity": False,
        "total_volume": round(total_volume, 0),
        "rejection_reasons": reasons,
        "trash_reason": "|".join(reasons) if reasons else None,
    }


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


def _processing_timestamp() -> str:
    now = datetime.datetime.now()
    return now.strftime("%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


def reset_processing_heartbeat() -> None:
    """Clear Window 1 and arm live processor telemetry."""
    st.session_state.matrix_processing_active = True
    st.session_state.matrix_processing_logs = []
    st.session_state.quantum_terminal_output = ""


def emit_processing_heartbeat(line: str, *, detail: str = "") -> None:
    """Append a timestamped log line the instant local CPU finishes a pipeline stage."""
    if line:
        entry = f"[{_processing_timestamp()}] {line}"
        if detail:
            entry = f"{entry}\n   └ {detail}"
    elif detail:
        entry = f"   └ {detail}"
    else:
        return
    logs = list(st.session_state.get("matrix_processing_logs") or [])
    logs.append(entry)
    st.session_state.matrix_processing_logs = logs
    st.session_state.quantum_terminal_output = "\n".join(logs)


def flash_processing_fault(message: str) -> None:
    """Hard-stop fault — bypass visuals and show the error immediately."""
    clear_window1_visual_state()
    st.session_state.matrix_processing_active = False
    st.session_state.matrix_processing_logs = []
    st.session_state.quantum_terminal_output = message


def clear_window1_visual_state() -> None:
    st.session_state.matrix_window1_charts_html = ""
    st.session_state.matrix_window1_rejection_text = ""


def publish_window1_visual_charts(html: str) -> None:
    """Store pre-gate chart HTML once Massive ingest succeeds."""
    st.session_state.matrix_window1_charts_html = html
    st.session_state.matrix_window1_rejection_text = ""


def publish_window1_rejection_overlay(message: str) -> None:
    """Companion rejection banner — keeps charts visible underneath."""
    st.session_state.matrix_window1_rejection_text = message
    st.session_state.matrix_processing_active = False
    st.session_state.matrix_processing_logs = []
    st.session_state.quantum_terminal_output = message


def is_critical_window1_fault(message: str) -> bool:
    """Connection/auth/syntax faults that bypass the visual chart stream."""
    text = str(message or "").upper()
    markers = (
        "MASSIVE_HTTP_401",
        "HTTP_401",
        "UNKNOWN API KEY",
        "PROCESSOR FAULT",
        "THROTTLE",
        "POLYGON REST DATA EMPTY",
        "DATALINK: NO_DATA",
        "DATALINK: FENCE_EMPTY",
    )
    return any(m in text for m in markers)


def _chart_lane_baseline_window(
    data_stream,
    *,
    timeframe_resolution: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
):
    end_dt = _parse_session_datetime(end_date, end_time)
    start_dt = _parse_session_datetime(start_date, start_time)
    if timeframe_resolution == "1-Minute" and start_dt is not None:
        _, window = _dynamic_1m_dragnet_window(data_stream, start_dt)
        return window
    if timeframe_resolution == "5-Minute" and start_dt is not None:
        _, window = _dynamic_5m_dragnet_window(data_stream, start_dt)
        return window
    if end_dt is not None:
        lookback_start = _calibrated_lookback_start(
            end_dt,
            timeframe_resolution,
            start_dt=start_dt,
            data_stream=data_stream,
        )
        if lookback_start is not None:
            return _lookback_window_frame(data_stream, end_dt, lookback_start)
    return _ensure_dataframe(data_stream)


def _svg_polyline(values: list[float], *, width: int, height: int, stroke: str) -> str:
    if not values:
        return ""
    vmin = float(min(values))
    vmax = float(max(values))
    span = vmax - vmin or 1.0
    n = len(values)
    points: list[str] = []
    for i, raw in enumerate(values):
        x = 2 + (i / max(n - 1, 1)) * (width - 4)
        y = height - 2 - ((float(raw) - vmin) / span) * (height - 4)
        points.append(f"{x:.1f},{y:.1f}")
    return (
        f'<polyline fill="none" stroke="{stroke}" stroke-width="1.6" '
        f'points="{" ".join(points)}"/>'
    )


def _svg_volume_envelope_grid(
    volumes: list[float],
    *,
    mu: float,
    sigma: float,
    width: int = 400,
    height: int = 88,
) -> str:
    if not volumes:
        return ""
    import html as html_mod

    max_v = max(float(max(volumes)), mu + sigma, 1.0)
    n = len(volumes)
    slot = (width - 8) / max(n, 1)
    bar_w = max(2.0, slot - 1.0)
    parts: list[str] = []
    ceil_v = mu + sigma
    floor_v = max(0.0, mu - sigma)
    ceil_y = height - 4 - (ceil_v / max_v) * (height - 10)
    floor_y = height - 4 - (floor_v / max_v) * (height - 10)
    parts.append(
        f'<rect x="2" y="{ceil_y:.1f}" width="{width - 4}" height="{max(1.0, floor_y - ceil_y):.1f}" '
        f'fill="rgba(52,199,89,0.07)" stroke="none"/>'
    )
    parts.append(
        f'<line x1="2" y1="{ceil_y:.1f}" x2="{width - 2}" y2="{ceil_y:.1f}" '
        f'stroke="#5BD975" stroke-width="1" stroke-dasharray="5,4" opacity="0.75"/>'
    )
    parts.append(
        f'<line x1="2" y1="{floor_y:.1f}" x2="{width - 2}" y2="{floor_y:.1f}" '
        f'stroke="#5BD975" stroke-width="1" stroke-dasharray="5,4" opacity="0.75"/>'
    )
    for i, vol in enumerate(volumes):
        h = (float(vol) / max_v) * (height - 10)
        x = 4 + i * slot
        y = height - 4 - h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'fill="#145A2A" stroke="#34C759" stroke-width="0.45" opacity="0.92"/>'
        )
    legend = (
        f"μ={mu:,.0f} σ={sigma:,.0f} · envelope "
        f"[{floor_v:,.0f} – {ceil_v:,.0f}]"
    )
    return (
        f'<div class="w1-chart-row w1-chart-volume">'
        f'<div class="w1-chart-label">INDICATOR BAR GRID · 3H VOLUME σ-ENVELOPE</div>'
        f'<svg class="w1-chart-svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="{height}" preserveAspectRatio="none">{"".join(parts)}</svg>'
        f'<div class="w1-chart-meta">{html_mod.escape(legend)}</div></div>'
    )


def build_window1_visual_charts_html(
    data_stream,
    *,
    ticker: str,
    timeframe_resolution: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
) -> str:
    """
    Pre-gate visual stack for Window 1 — close trajectory, VWAP anchor, volume σ-grid.
  Rendered immediately after successful Massive ingest, before ignition gates.
    """
    import html as html_mod

    frame = _ensure_dataframe(data_stream)
    if frame is None or frame.empty or "Close" not in frame.columns:
        return ""

    baseline = _chart_lane_baseline_window(
        data_stream,
        timeframe_resolution=timeframe_resolution,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
    )
    envelope = _three_hour_baseline_envelope(baseline)
    if baseline is not None and not _dataframe_is_empty(baseline):
        remote_env = cloud_offload.remote_volume_envelope(
            cloud_offload.dataframe_to_bars(baseline)
        )
        if remote_env:
            envelope = remote_env

    closes = frame["Close"].astype(float).tolist()
    if "VWAP" in frame.columns:
        vwaps = frame["VWAP"].astype(float).tolist()
    else:
        vwaps = closes[:]
    volumes = (
        frame["Volume"].astype(float).tolist()
        if "Volume" in frame.columns
        else [0.0] * len(closes)
    )

    width = 400
    close_line = _svg_polyline(closes, width=width, height=52, stroke="#34C759")
    vwap_line = _svg_polyline(vwaps, width=width, height=52, stroke="#7AE582")
    vol_grid = _svg_volume_envelope_grid(
        volumes,
        mu=float(envelope.get("mean", 0.0)),
        sigma=float(envelope.get("std", 0.0)),
        width=width,
        height=88,
    )

    try:
        t0 = frame.index[0].strftime("%H:%M")
        t1 = frame.index[-1].strftime("%H:%M")
        span_label = f"{t0} → {t1} · {len(frame)} bars"
    except Exception:
        span_label = f"{len(frame)} bars"

    ticker_clean = html_mod.escape(str(ticker or "").strip().upper())
    tf_clean = html_mod.escape(str(timeframe_resolution))
    close_bounds = f"{min(closes):.2f} → {max(closes):.2f}"
    vwap_bounds = f"{min(vwaps):.2f} → {max(vwaps):.2f}"

    return (
        '<div class="w1-visual-shell">'
        f'<div class="w1-visual-title">▸ {ticker_clean} · {tf_clean} · {html_mod.escape(span_label)}</div>'
        '<div class="w1-chart-row">'
        '<div class="w1-chart-label">CHART LINE 1 · CLOSE TRAJECTORY</div>'
        f'<svg class="w1-chart-svg" viewBox="0 0 {width} 52" width="100%" height="52" '
        f'preserveAspectRatio="none">{close_line}</svg>'
        f'<div class="w1-chart-meta">{html_mod.escape(close_bounds)}</div>'
        "</div>"
        '<div class="w1-chart-row">'
        '<div class="w1-chart-label">CHART LINE 2 · MASSIVE VWAP (vw) ANCHOR</div>'
        f'<svg class="w1-chart-svg" viewBox="0 0 {width} 52" width="100%" height="52" '
        f'preserveAspectRatio="none">{vwap_line}</svg>'
        f'<div class="w1-chart-meta">{html_mod.escape(vwap_bounds)}</div>'
        "</div>"
        f"{vol_grid}"
        "</div>"
    )


def complete_processing_heartbeat(final_terminal: str) -> None:
    """Snap final validated readout when live computations conclude."""
    st.session_state.matrix_processing_active = False
    st.session_state.quantum_terminal_output = final_terminal


def processing_lane_bar_target(timeframe_resolution: str) -> int:
    return int(PROCESSING_LANE_BARS.get(timeframe_resolution, FIVE_MINUTE_DRAGNET_BARS))


def _rsi_last(closes, period: int = 14) -> float | None:
    if closes is None or len(closes) < period + 1:
        return None
    try:
        delta = closes.astype(float).diff()
        gain = delta.clip(lower=0).rolling(window=period, min_periods=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period, min_periods=period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        val = rsi.iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None
    except Exception:
        return None


def _sma_last(closes, period: int = 20) -> float | None:
    if closes is None or len(closes) < period:
        return None
    try:
        val = closes.astype(float).rolling(window=period, min_periods=period).mean().iloc[-1]
        return round(float(val), 4) if pd.notna(val) else None
    except Exception:
        return None


def _session_boundary_digest_logs(frame) -> list[str]:
    """Emit boundary-crossing digests when the lane spans session walls."""
    logs: list[str] = []
    if frame is None or _dataframe_is_empty(frame):
        return logs
    prev_date = None
    prev_hour = None
    for ts in frame.index:
        try:
            cur_date = ts.date()
            cur_hour = ts.hour
        except Exception:
            continue
        if prev_date is not None and cur_date != prev_date:
            logs.append(
                f"🌉 midnight roll at {ts.strftime('%Y-%m-%d %H:%M')} — "
                "multi-hour lane stitched across session wall"
            )
        elif prev_hour is not None and cur_hour != prev_hour and cur_date == prev_date:
            logs.append(
                f"🕐 hour boundary {prev_hour:02d}→{cur_hour:02d} at "
                f"{ts.strftime('%H:%M')} — macro brick resampled"
            )
        prev_date = cur_date
        prev_hour = cur_hour
    return logs


def emit_parsing_telemetry(
    data_stream,
    *,
    timeframe_resolution: str,
    bar_count: int,
    start_norm: str | None = None,
    end_norm: str | None = None,
) -> None:
    """Log parsing/resampling work proportional to the active lane depth."""
    emit_processing_heartbeat(
        "⚙️ PARSING: Normalizing timezones, dropping metadata, and restructuring lookback lane arrays...",
        detail=(
            f"{bar_count} bars · {timeframe_resolution} lane · "
            f"window {start_norm or '?'} → {end_norm or '?'}"
        ),
    )
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return
    if timeframe_resolution == "1-Minute":
        for i, ts in enumerate(frame.index[:processing_lane_bar_target(timeframe_resolution)], start=1):
            emit_processing_heartbeat(
                "",
                detail=f"strike lane [{i}/{bar_count}] @ {ts.strftime('%H:%M')} tz-stripped",
            )
    elif timeframe_resolution == "5-Minute":
        indices = list(frame.index)
        checkpoints = sorted(
            {0, len(indices) // 4, len(indices) // 2, (3 * len(indices)) // 4, len(indices) - 1}
        )
        for pos in checkpoints:
            if pos < 0 or pos >= len(indices):
                continue
            ts = indices[pos]
            emit_processing_heartbeat(
                "",
                detail=f"relative lane [{pos + 1}/{bar_count}] @ {ts.strftime('%H:%M')} resampled",
            )
    else:
        for boundary in _session_boundary_digest_logs(frame):
            emit_processing_heartbeat("", detail=boundary)
        indices = list(frame.index)
        stride = max(1, len(indices) // 6)
        for pos in range(0, len(indices), stride):
            ts = indices[pos]
            emit_processing_heartbeat(
                "",
                detail=f"macro lane [{pos + 1}/{bar_count}] @ {ts.strftime('%m-%d %H:%M')} digested",
            )


def emit_calculating_telemetry(
    data_stream,
    *,
    timeframe_resolution: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
) -> dict:
    """
    Run local 4-layer feature math and emit logs as each array completes.
    Returns the 3-hour volume envelope dict for downstream ignition checks.
    """
    emit_processing_heartbeat(
        "🧮 CALCULATING: Generating relative 3-hour volume standard deviation envelopes, "
        "RSI indices, and SMA vectors...",
    )
    end_dt = _parse_session_datetime(end_date, end_time)
    start_dt = _parse_session_datetime(start_date, start_time)
    frame = _ensure_dataframe(data_stream)
    bar_count = len(frame) if frame is not None and not frame.empty else 0

    baseline_window = None
    if timeframe_resolution == "1-Minute" and start_dt is not None:
        _, baseline_window = _dynamic_1m_dragnet_window(data_stream, start_dt)
    elif timeframe_resolution == "5-Minute" and start_dt is not None:
        _, baseline_window = _dynamic_5m_dragnet_window(data_stream, start_dt)
    elif end_dt is not None:
        lookback_start = _calibrated_lookback_start(
            end_dt, timeframe_resolution, start_dt=start_dt, data_stream=data_stream
        )
        if lookback_start is not None:
            baseline_window = _lookback_window_frame(data_stream, end_dt, lookback_start)

    envelope = _three_hour_baseline_envelope(baseline_window)
    emit_processing_heartbeat(
        "",
        detail=(
            f"3h volume σ-envelope μ={envelope['mean']:.0f} σ={envelope['std']:.0f} "
            f"floor={envelope['floor']:.0f}"
        ),
    )

    if frame is not None and "Close" in frame.columns:
        closes = frame["Close"]
        rsi_val = _rsi_last(closes)
        if rsi_val is not None:
            emit_processing_heartbeat("", detail=f"RSI(14) terminal vector = {rsi_val}")
        sma20 = _sma_last(closes, 20)
        if sma20 is not None:
            emit_processing_heartbeat("", detail=f"SMA(20) local array terminus = {sma20:.4f}")
        sma50 = _sma_last(closes, min(50, len(closes)))
        if sma50 is not None and sma50 != sma20:
            emit_processing_heartbeat("", detail=f"SMA({min(50, len(closes))}) stack = {sma50:.4f}")

    workload_steps = {
        "1-Minute": max(1, min(bar_count, ONE_MINUTE_DRAGNET_BARS)),
        "5-Minute": max(4, min(bar_count // 9, 8)),
        "15-Minute": max(6, min(bar_count // 8, 12)),
    }
    steps = workload_steps.get(timeframe_resolution, 4)
    for step in range(1, steps + 1):
        emit_processing_heartbeat(
            "",
            detail=f"feature layer {step}/{steps} fused · {bar_count} bar covariance lane",
        )

    return envelope


def emit_digesting_telemetry(
    *,
    ticker: str,
    finbert_score: float | None = None,
    filing_count: int = 0,
    headline_count: int = 0,
) -> None:
    """Log SEC / FinBERT digestion as corporate text matrices are scored."""
    emit_processing_heartbeat(
        "🧠 DIGESTING: Processing SEC corporate text files through local FinBERT coordinate matrices...",
        detail=f"{ticker.upper()} · {filing_count} SEC filings · {headline_count} headline vectors",
    )
    if finbert_score is not None:
        emit_processing_heartbeat(
            "",
            detail=f"FinBERT sentiment coordinate = {finbert_score:+.3f}",
        )


# Legacy cinematic API — kept so older app.py builds on Streamlit Cloud do not crash
# when core_quantum is deployed ahead of app.py. New code uses emit_processing_heartbeat().
_LEGACY_TELEMETRY_DELAYS = {"1-Minute": 0.05, "5-Minute": 0.15, "15-Minute": 0.30}


def telemetry_show_delay_for_timeframe(timeframe_resolution: str) -> float:
    return float(_LEGACY_TELEMETRY_DELAYS.get(timeframe_resolution, 0.15))


def arm_cinematic_telemetry_show(
    *,
    lines: list[str],
    delay_sec: float,
    pending_deploy: dict | None = None,
) -> None:
    st.session_state.matrix_telemetry_show_active = True
    st.session_state.matrix_telemetry_lines = list(lines)
    st.session_state.matrix_telemetry_delay_sec = float(delay_sec)
    st.session_state.matrix_telemetry_pending_deploy = pending_deploy or {}
    st.session_state.matrix_telemetry_revealed_lines = []
    st.session_state.matrix_telemetry_line_index = 0
    st.session_state.matrix_telemetry_last_tick = time.time()
    st.session_state.matrix_cascade_active = False
    st.session_state.matrix_satellites_ready = False
    st.session_state.quantum_terminal_output = ""


def tick_cinematic_telemetry_show() -> str:
    if not st.session_state.get("matrix_telemetry_show_active"):
        return "idle"

    lines = st.session_state.get("matrix_telemetry_lines") or []
    idx = int(st.session_state.get("matrix_telemetry_line_index") or 0)
    delay = float(st.session_state.get("matrix_telemetry_delay_sec") or 0.15)
    now = time.time()
    last = float(st.session_state.get("matrix_telemetry_last_tick") or now)
    revealed = list(st.session_state.get("matrix_telemetry_revealed_lines") or [])

    if idx >= len(lines):
        st.session_state.matrix_telemetry_show_active = False
        return "complete"

    if now - last >= delay:
        revealed.append(lines[idx])
        idx += 1
        st.session_state.matrix_telemetry_line_index = idx
        st.session_state.matrix_telemetry_revealed_lines = revealed
        st.session_state.matrix_telemetry_last_tick = now

    if idx >= len(lines):
        st.session_state.matrix_telemetry_show_active = False
        return "complete"

    return "running"


def stream_payload_to_vault(payload: dict) -> tuple[bool, str, dict | None]:
    """Direct secure Supabase REST anchor to live Postgres cloud table."""
    coupling = st.session_state.get("room2_chart_coupling") or {}
    quality = st.session_state.get("room2_playbook_quality") or {}
    if not coupling.get("passed") or not quality.get("passed"):
        return False, "VAULT BLOCKED — chart coupling or quality gate failed (PRE-STORAGE TRASH).", None

    def _is_numeric_coordinate(value) -> bool:
        if value in (None, ""):
            return False
        try:
            float(str(value).replace(",", "").strip())
            return True
        except (TypeError, ValueError):
            return False

    def _sanitize_legacy_coordinate_fields(row: dict) -> dict:
        """Legacy forensic_patterns stores prices in *_coordinate and datetimes in *_time."""
        row = dict(row)
        for coord_key, time_key in (
            ("entry_coordinate", "entry_time"),
            ("exit_coordinate", "exit_time"),
        ):
            val = row.get(coord_key)
            if val in (None, ""):
                continue
            if _is_numeric_coordinate(val):
                try:
                    row[coord_key] = float(str(val).replace(",", "").strip())
                except (TypeError, ValueError):
                    row.pop(coord_key, None)
                continue
            dt_str = str(val).strip()
            if dt_str and not str(row.get(time_key) or "").strip():
                row[time_key] = dt_str
            row.pop(coord_key, None)
        return row

    def _align_legacy_forensic_pattern_row(body: dict) -> dict:
        """Map new vault fields onto legacy NOT NULL columns (pattern_type, trigger_timestamp)."""
        row = dict(body)
        ts = row.get("timestamp") or row.get("trigger_timestamp")
        if ts:
            row.setdefault("trigger_timestamp", ts)
            row.setdefault("timestamp", ts)
        category = row.get("pattern_category") or row.get("pattern_type") or "VALIDATED"
        row.setdefault("pattern_type", str(category)[:50])
        row.setdefault("pattern_category", str(category))
        tf = row.get("timeframe_resolution") or row.get("timeframe") or "15-Minute"
        row.setdefault("timeframe", str(tf)[:10])
        row.setdefault("timeframe_resolution", str(tf))
        return _sanitize_legacy_coordinate_fields(row)

    payload = _align_legacy_forensic_pattern_row(payload)
    raw_operator_notes = str(payload.pop("_raw_operator_notes", "") or "").strip()
    phase2_route = vault_bridge.evaluate_phase2_deploy_route(
        payload,
        raw_operator_notes=raw_operator_notes,
        layout_match_pct=int(payload.get("layout_match_pct") or 0),
    )
    try:
        st.session_state.room2_phase2_route = phase2_route
    except Exception:
        pass
    if phase2_route.get("action") == "skip_duplicate":
        ticker = str(payload.get("ticker") or "UNKNOWN").upper()
        return True, (
            f"VAULT DEDUP — {phase2_route.get('message') or f'identical {ticker} pattern already in the matrix.'}"
        ), {"ticker": ticker, "id": phase2_route.get("duplicate_row_id")}
    duplicate = vault_bridge.find_active_vault_duplicate(
        payload,
        raw_operator_notes=raw_operator_notes,
    )
    if duplicate:
        ticker = str(payload.get("ticker") or "UNKNOWN").upper()
        return True, (
            f"VAULT DEDUP — identical {ticker} pattern already in the matrix "
            f"(same ticker, window, coordinates, layout, strategy, and notes). "
            "Skipped redundant copy."
        ), duplicate

    cfg = vault_bridge.supabase_settings()
    if not cfg["ready"]:
        return False, (
            "VAULT SYNC FAILED — Supabase is not configured. "
            "Add SUPABASE_URL and SUPABASE_KEY to secrets. Pattern was NOT saved."
        ), None

    supabase_url = cfg["url"]
    supabase_key = cfg["key"]
    table = cfg["table"]
    extended_fields = (
        "timeframe_resolution",
        "macro_weather_layout",
        "execution_strategy",
        "buffer_context_window",
        "vault_track",
        "data_feed_mode",
        "deleted_at",
        "layout_match_pct",
        "anomaly_repeat_count",
        "structural_move_pct",
        "text_matrix_string",
        "forensic_dragnet_blob",
        "master_signature_json",
        "metric_envelopes_json",
        "semantic_catalyst_json",
        "day_context_json",
        "strategy_trust_tier",
        "form4_insider_summary",
        "institutional_block_accumulation",
        "polygon_calls_remaining",
    )

    def _first_inserted_row(body) -> dict | None:
        if isinstance(body, list) and body and isinstance(body[0], dict):
            return body[0]
        if isinstance(body, dict) and body.get("id") is not None:
            return body
        return None

    def _post(body: dict):
        return requests.post(
            f"{supabase_url}/rest/v1/{table}",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            json=[body],
            timeout=12,
        )

    def _finalize_save(saved_row: dict | None, base_msg: str) -> tuple[bool, str, dict | None]:
        route = {}
        try:
            route = dict(st.session_state.get("room2_phase2_collective_route") or {})
        except Exception:
            route = {}
        if saved_row and route:
            _, post_note = vault_bridge.apply_phase2_post_save(payload, route)
            if post_note:
                base_msg = f"{base_msg} · {post_note}"
        return True, base_msg, saved_row

    try:
        resp = _post(payload)
        if resp.ok:
            saved_row = _first_inserted_row(resp.json())
            return _finalize_save(
                saved_row,
                (
                    f"INTERNET VAULT SYNC CONFIRMED — `{table}` anchored for "
                    f"{payload.get('ticker', 'UNKNOWN')} @ {payload.get('timestamp', 'UTC')}."
                ),
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
                saved_row = _first_inserted_row(retry.json())
                return _finalize_save(
                    saved_row,
                    (
                        f"INTERNET VAULT SYNC CONFIRMED — `{table}` anchored (compact schema fallback) "
                        f"for {payload.get('ticker', 'UNKNOWN')}."
                    ),
                )
            return False, f"Vault upload failed: {retry.status_code} {retry.text}", None

        return False, f"Vault upload failed: {resp.status_code} {resp.text}", None
    except Exception as exc:
        return False, f"Vault upload failed: {exc}", None


def _lookback_lane_dragnet(
    data_stream,
    start_dt: datetime.datetime | None,
    timeframe_resolution: str,
):
    """Resolve the strict bar dragnet for the active timeframe lane."""
    if timeframe_resolution == "1-Minute":
        return _dynamic_1m_dragnet_window(data_stream, start_dt)
    if timeframe_resolution == "5-Minute":
        return _dynamic_5m_dragnet_window(data_stream, start_dt)
    if timeframe_resolution == "15-Minute":
        return _dynamic_15m_dragnet_window(data_stream, start_dt)
    return _dynamic_bar_dragnet_window(
        data_stream,
        start_dt,
        LOOKBACK_LANE_ASSERTIONS.get(timeframe_resolution, ONE_MINUTE_DRAGNET_BARS),
    )


def validate_regime_lookback_lanes(
    data_stream,
    *,
    start_date,
    start_time: str,
    timeframe_resolution: str,
) -> dict:
    """
    Adaptive lookback lanes — ideal depth is 1m=5, 5m=36, 15m=48 bars before Start Time.
    Thin low-cap tapes use every valid bar available and stop at the data edge.
    Only trash when bars fall below LOOKBACK_ADAPTIVE_MIN_BARS (near-empty).
    Purgatory / incubation handle weak spatial matches — not a full deploy cancel.
    """
    required = int(LOOKBACK_LANE_ASSERTIONS.get(timeframe_resolution, ONE_MINUTE_DRAGNET_BARS))
    min_bars = int(LOOKBACK_ADAPTIVE_MIN_BARS.get(timeframe_resolution, 3))
    start_dt = _parse_session_datetime(start_date, start_time)
    lookback_start, window = _lookback_lane_dragnet(data_stream, start_dt, timeframe_resolution)
    actual = 0
    if isinstance(window, pd.DataFrame) and not window.empty:
        actual = len(window)
    adaptive = actual < required
    effective_bars = actual
    passed = actual >= min_bars
    coverage_pct = int(round((actual / required) * 100)) if required else 0

    lookback_start_iso = None
    if lookback_start is not None:
        try:
            lookback_start_iso = (
                lookback_start.isoformat()
                if hasattr(lookback_start, "isoformat")
                else str(lookback_start)
            )
        except Exception:
            lookback_start_iso = str(lookback_start)

    if passed and adaptive:
        st.session_state.room2_lookback_adaptive = {
            "timeframe_resolution": timeframe_resolution,
            "ideal_bars": required,
            "actual_bars": actual,
            "effective_bars": effective_bars,
            "coverage_pct": coverage_pct,
            "lookback_start": lookback_start_iso,
        }
        emit_processing_heartbeat(
            f"📉 ADAPTIVE LOOKBACK — {timeframe_resolution}: using {actual}/{required} bars "
            f"({coverage_pct}% of ideal depth). Thin tape — analysis stops at valid data edge.",
            detail=f"start={start_time}|min={min_bars}",
        )
    else:
        st.session_state.pop("room2_lookback_adaptive", None)

    return {
        "passed": passed,
        "trashed": not passed,
        "adaptive": adaptive and passed,
        "required_bars": required,
        "actual_bars": actual,
        "effective_bars": effective_bars,
        "min_bars": min_bars,
        "coverage_pct": coverage_pct,
        "timeframe_resolution": timeframe_resolution,
        "lookback_start": lookback_start_iso,
        "rejection_reasons": [] if passed else [f"lookback_lane_min_{min_bars}_fail"],
        "trash_reason": None
        if passed
        else f"LOOKBACK_LANE|min={min_bars}|got={actual}|tf={timeframe_resolution}",
    }


def validate_pgvector_regime_match(query_vector: list[float] | None = None) -> dict:
    """
    Hard-coded pgvector cosine gate — Window 4 requires >= 85% and non-flatlined dataset.
    """
    vec = [float(x) for x in (query_vector or []) if x is not None]
    if not vec:
        return {
            "valid": False,
            "spatial_match_pct": 0,
            "cosine_similarity": 0.0,
            "flatlined": True,
            "reason": "empty_vector",
        }
    remote = cloud_offload.rpc_match_layout_spatial(vec) or {}
    pct = int(remote.get("spatial_match_pct") or 0)
    cos = float(remote.get("cosine_similarity") or 0.0)
    flatlined = pct <= 0 and cos <= 0.001
    valid = (not flatlined) and pct >= LAYOUT_SIGNATURE_MATCH_THRESHOLD
    return {
        "valid": valid,
        "spatial_match_pct": pct,
        "cosine_similarity": round(cos, 4),
        "flatlined": flatlined,
        "nearest_layout_id": str(remote.get("nearest_layout_id") or "NEW_LAYOUT"),
        "engine": str(remote.get("engine") or "array_rpc"),
        "reason": None if valid else ("flatlined_dataset" if flatlined else "below_85pct_match"),
    }


def window4_instant_fault_text() -> str | None:
    """Raw fault string for instant Window 4 / processor flash — no AI paraphrase."""
    api_err = str(st.session_state.get("r2_market_data_error") or "").strip()
    report = str(st.session_state.get("room2_quantum_report") or "").strip()
    rejection = str(st.session_state.get("matrix_window1_rejection_text") or "").strip()
    if "MASSIVE_HTTP_401" in api_err:
        return api_err
    if "[PROCESSOR FAULT]" in report or "PROCESSOR FAULT" in report:
        return report
    if rejection and ("PRE-STORAGE TRASH" in rejection or "no_volume_ignition" in rejection):
        if "VAULT SYNC OK" in report or "INTERNET VAULT SYNC CONFIRMED" in report:
            return None
        terminal = str(st.session_state.get("quantum_terminal_output") or "")
        if "VAULT SYNC OK" in terminal or "INTERNET VAULT SYNC CONFIRMED" in terminal:
            return None
        return rejection
    if api_err and api_err.startswith("MASSIVE_HTTP_"):
        return api_err
    return None


def window4_regime_gate_open() -> bool:
    """True only after a validated deploy with pgvector match >= 85% and no active fault."""
    if window4_instant_fault_text():
        return False
    proc = st.session_state.get("room2_processor") or {}
    if proc.get("active"):
        return False
    if not st.session_state.get("window4_regime_valid"):
        return False
    return int(st.session_state.get("window4_spatial_match_pct") or 0) >= LAYOUT_SIGNATURE_MATCH_THRESHOLD


def _sync_window4_regime_flags(
    *,
    match_pct: int,
    valid: bool,
) -> None:
    st.session_state.window4_spatial_match_pct = int(match_pct)
    st.session_state.window4_regime_valid = bool(valid) and int(match_pct) >= LAYOUT_SIGNATURE_MATCH_THRESHOLD


def _pearson_correlation(series_a: list[float], series_b: list[float]) -> float:
    n = min(len(series_a), len(series_b))
    if n < 5:
        return 0.0
    x, y = series_a[-n:], series_b[-n:]
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den_x = sum((xi - mx) ** 2 for xi in x) ** 0.5
    den_y = sum((yi - my) ** 2 for yi in y) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


MARKET_WEATHER_CACHE_SEC = 60
LAYOUT_CROSS_MATCH_FLEX_PCT = 70
MARKET_WEATHER_MACRO_SYMBOLS = (
    ("SPY", "SPY"),
    ("^VIX", "VIX"),
    ("GC=F", "GOLD"),
    ("CL=F", "OIL"),
    ("^TNX", "RATES"),
)


def _fetch_yahoo_close_series(
    symbol: str,
    *,
    range_: str = "5d",
    interval: str = "5m",
) -> list[float]:
    """Lightweight macro tape — no extra pip dependency."""
    sym = urllib.parse.quote(str(symbol).strip(), safe="")
    if not sym:
        return []
    try:
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
            params={"interval": interval, "range": range_},
            headers={"User-Agent": "SavantApprentice/1.0"},
            timeout=10,
        )
        if not resp.ok:
            return []
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return []
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close") or []
        return [float(c) for c in closes if c is not None]
    except Exception:
        return []


def fetch_symbol_velocity_series(symbol: str, periods: int = 20) -> list[float]:
    """Bar-over-bar % velocity for macro cross-asset correlation."""
    closes = _fetch_yahoo_close_series(symbol, range_="5d", interval="5m")
    if len(closes) < 3:
        return []
    velocities: list[float] = []
    for idx in range(1, len(closes)):
        prev = closes[idx - 1]
        if prev:
            velocities.append((closes[idx] - prev) / prev * 100.0)
    return velocities[-periods:]


def fetch_distinct_layout_folders() -> list[str]:
    """Active layout buckets minted in Supabase."""
    headers = _supabase_rest_headers()
    if not headers:
        return []
    table = _supabase_table_name()
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}",
            headers=headers,
            params={
                "select": "macro_weather_layout",
                "macro_weather_layout": "not.is.null",
                "vault_track": "eq.track_1_validated",
                "or": "(state.is.null,state.eq.active,state.eq.incubation)",
                "limit": "256",
            },
            timeout=12,
        )
        if not resp.ok or not isinstance(resp.json(), list):
            return []
        seen: set[str] = set()
        folders: list[str] = []
        for row in resp.json():
            label = str(row.get("macro_weather_layout") or "").strip()
            if label and label not in seen:
                seen.add(label)
                folders.append(label)
        return sorted(folders)
    except Exception:
        return []


def _weather_mood_from_macro(
    *,
    spy_velocity: float,
    vix_velocity: float,
    vol_sigma: float,
) -> tuple[str, str]:
    """Return (weather_mood label, vibe_profile token)."""
    if vix_velocity >= 0.35 or vol_sigma >= 2.0:
        return "Risk-Off Volatile", "expansion"
    if vix_velocity <= -0.15 and spy_velocity >= 0.05:
        return "Risk-On Expansion", "expansion"
    if abs(spy_velocity) <= 0.04 and vol_sigma <= 0.35:
        return "Tight Range", "compressed"
    if spy_velocity >= 0.08:
        return "Risk-On Drift", "neutral"
    if spy_velocity <= -0.08:
        return "Risk-Off Slide", "expansion"
    return "Mixed Session", "neutral"


def compute_market_weather_snapshot(*, ticker: str = "", force_refresh: bool = False) -> dict:
    """
    Market-weather footprint — how the broad tape feels before layout routing.
    Layout buckets represent this weather; strategies nest inside each bucket.
    """
    now = time.time()
    cached = st.session_state.get("market_weather_snapshot") or {}
    if (
        not force_refresh
        and cached.get("fetched_at_epoch")
        and (now - float(cached["fetched_at_epoch"])) < MARKET_WEATHER_CACHE_SEC
    ):
        return cached

    spy_vel = fetch_symbol_velocity_series("SPY")
    vix_vel = fetch_symbol_velocity_series("^VIX")
    ticker_vel = fetch_symbol_velocity_series(str(ticker).strip().upper()) if ticker else []

    spy_session = sum(spy_vel[-12:]) if spy_vel else 0.0
    vix_session = sum(vix_vel[-12:]) if vix_vel else 0.0
    vol_sigma = statistics.pstdev(spy_vel) if len(spy_vel) >= 3 else 0.0
    weather_mood, vibe_profile = _weather_mood_from_macro(
        spy_velocity=spy_session,
        vix_velocity=vix_session,
        vol_sigma=vol_sigma,
    )

    macro_correlations: dict[str, float] = {}
    base = ticker_vel or spy_vel
    if len(base) >= 5:
        for sym, label in MARKET_WEATHER_MACRO_SYMBOLS:
            macro_vel = fetch_symbol_velocity_series(sym)
            if len(macro_vel) >= 5:
                n = min(len(base), len(macro_vel))
                macro_correlations[label] = round(
                    _pearson_correlation(base[-n:], macro_vel[-n:]), 4
                )

    weather_vec = build_four_layer_feature_vector(
        {
            "session_velocity_pct": spy_session,
            "peak_bar_velocity_pct": max(spy_vel) if spy_vel else 0.0,
            "mean_bar_velocity_pct": statistics.mean(spy_vel) if spy_vel else 0.0,
        },
        {"volume": {"sigma": vol_sigma, "z_score": vol_sigma}},
        vwap_bias_pct=spy_session,
        sec_coordinate=max(-1.0, min(1.0, vix_session / 5.0)),
    )
    spatial = compute_spatial_layout_match(weather_vec)
    folders = fetch_distinct_layout_folders()

    snapshot = {
        "fetched_at_epoch": now,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "weather_mood": weather_mood,
        "vibe_profile": vibe_profile,
        "spy_session_velocity_pct": round(spy_session, 4),
        "vix_session_velocity_pct": round(vix_session, 4),
        "vol_sigma": round(vol_sigma, 4),
        "macro_correlations": macro_correlations,
        "layout_folders": folders,
        "spatial": spatial,
        "nearest_weather_layout": str(spatial.get("nearest_layout_id") or "NEW_LAYOUT"),
        "spatial_match_pct": int(spatial.get("spatial_match_pct") or 0),
        "ticker": str(ticker or "").strip().upper(),
    }
    st.session_state.market_weather_snapshot = snapshot
    st.session_state.cross_asset_correlation_context = (
        "XASSET_CORR|"
        + "|".join(f"{k}:{v:+.3f}" for k, v in macro_correlations.items())
        if macro_correlations
        else "XASSET_CORR:MACRO_ONLY"
    )
    return snapshot


def mint_market_weather_layout_label(*, vibe_profile: str, weather_mood: str) -> str:
    """Mint numbered layout bucket — weather footprint first, strategies follow."""
    folders = fetch_distinct_layout_folders()
    max_num = 0
    for label in folders:
        match = re.search(r"(\d+)", label)
        if match:
            max_num = max(max_num, int(match.group(1)))
    vibe_token = {
        "expansion": "Volatile",
        "compressed": "Tight",
        "neutral": "Neutral",
    }.get(str(vibe_profile or "neutral"), "Neutral")
    return f"Layout {max_num + 1} — {vibe_token} / {weather_mood}"


def resolve_layout_with_market_weather(
    layout_id: str,
    *,
    vibe_profile: str,
    weather: dict | None = None,
    spatial_match_pct: int = 0,
) -> str:
    """
    Layout bucket = market weather footprint.
    Match existing bucket when spatial math aligns; otherwise mint a new numbered layout.
    """
    layout = str(layout_id or "NEW_LAYOUT").strip()
    if layout not in ("NEW_LAYOUT", "PURGATORY_PENDING", ""):
        return layout

    wx = weather or st.session_state.get("market_weather_snapshot") or {}
    nearest = str(wx.get("nearest_weather_layout") or "NEW_LAYOUT")
    wx_match = int(wx.get("spatial_match_pct") or spatial_match_pct or 0)

    if nearest not in ("NEW_LAYOUT", "PURGATORY_PENDING", "") and wx_match >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        return nearest
    if wx_match >= LAYOUT_SIGNATURE_MATCH_THRESHOLD and nearest not in ("NEW_LAYOUT", "PURGATORY_PENDING"):
        return nearest

    return mint_market_weather_layout_label(
        vibe_profile=vibe_profile,
        weather_mood=str(wx.get("weather_mood") or "Mixed Session"),
    )


def _expected_bars_in_operator_window(
    start_dt: datetime.datetime | None,
    end_dt: datetime.datetime | None,
    timeframe_resolution: str,
) -> int:
    if start_dt is None or end_dt is None or end_dt <= start_dt:
        return 0
    minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
    if timeframe_resolution == "1-Minute":
        return max(1, minutes)
    if timeframe_resolution == "5-Minute":
        return max(1, minutes // 5)
    if timeframe_resolution == "15-Minute":
        return max(1, minutes // 15)
    return max(1, minutes // 15)


def _operator_window_frame(
    data_stream,
    *,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
):
    frame = _ensure_dataframe(data_stream)
    if frame is None:
        return None
    start_dt = _parse_session_datetime(start_date, start_time)
    end_dt = _parse_session_datetime(end_date, end_time)
    if start_dt is None or end_dt is None:
        return frame
    try:
        window = frame[(frame.index >= start_dt) & (frame.index <= end_dt)]
        return window if not window.empty else None
    except Exception:
        return frame


def _trim_operator_window_to_liquid_core(window):
    """Skip thin/gappy edges — scan from the first bar with usable volume."""
    if window is None or _dataframe_is_empty(window) or "Volume" not in window.columns:
        return window
    vols = window["Volume"].astype(float).fillna(0.0)
    if float(vols.max() or 0.0) <= 0.0:
        return window
    floor_vol = max(500.0, float(vols.median() or 0.0) * 0.2)
    liquid = vols >= floor_vol
    if not bool(liquid.any()):
        liquid = vols > 0
    if not bool(liquid.any()):
        return window
    first_ix = liquid[liquid].index[0]
    last_ix = liquid[liquid].index[-1]
    return window.loc[first_ix:last_ix]


def _operator_window_spike_metrics(
    data_stream,
    start_dt: datetime.datetime | None,
    end_dt: datetime.datetime | None,
) -> dict:
    """
    Measure the rally envelope inside the operator-drawn window (low -> high).
    """
    empty = {
        "envelope_move_pct": 0.0,
        "peak_giveback_pct": 0.0,
        "window_minutes": 0,
        "window_low": None,
        "window_high": None,
        "end_close": None,
        "low_ts": None,
        "high_ts": None,
        "trimmed_bars": 0,
    }
    frame = _ensure_dataframe(data_stream)
    if frame is None or start_dt is None or end_dt is None or end_dt <= start_dt:
        return empty
    try:
        window = frame[(frame.index >= start_dt) & (frame.index <= end_dt)]
        if not isinstance(window, pd.DataFrame) or window.empty:
            return empty
        raw_bars = len(window)
        window = _trim_operator_window_to_liquid_core(window)
        if not isinstance(window, pd.DataFrame) or window.empty:
            return empty
        if "Low" not in window.columns or "High" not in window.columns:
            return empty
        lows = window["Low"].astype(float)
        highs = window["High"].astype(float)
        low_ts = lows.idxmin()
        high_ts = highs.idxmax()
        window_low = float(lows.min())
        window_high = float(highs.max())
        end_close = float(window["Close"].astype(float).iloc[-1])
        if window_low <= 0 or window_high <= 0:
            return empty
        envelope_move_pct = (window_high - window_low) / window_low * 100.0
        peak_giveback_pct = (
            (window_high - end_close) / window_high * 100.0
            if end_close < window_high
            else 0.0
        )
        window_minutes = max(1, int((end_dt - start_dt).total_seconds() // 60))
        return {
            "envelope_move_pct": round(envelope_move_pct, 4),
            "peak_giveback_pct": round(peak_giveback_pct, 4),
            "window_minutes": window_minutes,
            "window_low": round(window_low, 6),
            "window_high": round(window_high, 6),
            "end_close": round(end_close, 6),
            "low_ts": str(low_ts),
            "high_ts": str(high_ts),
            "trimmed_bars": max(0, raw_bars - len(window)),
        }
    except Exception:
        return empty


def evaluate_session_data_quality(
    data_stream,
    *,
    ticker: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
) -> dict:
    """
    Liquidity / density gate — only trustworthy session days enter the pattern library.
    """
    window = _operator_window_frame(
        data_stream,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
    )
    start_dt = _parse_session_datetime(start_date, start_time)
    end_dt = _parse_session_datetime(end_date, end_time)
    expected = _expected_bars_in_operator_window(start_dt, end_dt, timeframe_resolution)
    actual = len(window) if window is not None and not window.empty else 0
    density = round(actual / expected, 4) if expected else 0.0

    avg_volume = 0.0
    gap_pct = 0.0
    if window is not None and not window.empty:
        if "Volume" in window.columns:
            vols = window["Volume"].astype(float).fillna(0.0)
            avg_volume = float(vols.mean() or 0.0)
        if "Open" in window.columns and "Close" in window.columns and len(window) >= 2:
            opens = window["Open"].astype(float)
            closes = window["Close"].astype(float)
            prev_close = float(closes.iloc[0])
            first_open = float(opens.iloc[0])
            if prev_close > 0:
                gap_pct = round(abs((first_open - prev_close) / prev_close * 100.0), 4)

    density_ok = density >= SESSION_MIN_BAR_DENSITY
    volume_ok = avg_volume >= SESSION_MIN_AVG_VOLUME_PER_BAR
    passed = density_ok and volume_ok and actual >= 3
    reasons: list[str] = []
    if not density_ok:
        reasons.append(f"low_bar_density|{density:.2f}<{SESSION_MIN_BAR_DENSITY}")
    if not volume_ok:
        reasons.append(f"thin_volume|avg={int(avg_volume)}")
    if actual < 3:
        reasons.append("operator_window_too_thin")

    return {
        "passed": passed,
        "trashed": not passed,
        "ticker": str(ticker or "").strip().upper(),
        "actual_bars": actual,
        "expected_bars": expected,
        "bar_density": density,
        "avg_volume_per_bar": round(avg_volume, 2),
        "session_gap_pct": gap_pct,
        "rejection_reasons": reasons,
        "trash_reason": "|".join(reasons) if reasons else None,
    }


def build_day_context_envelope(
    *,
    ticker: str,
    data_stream,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
) -> dict:
    """
    Full-day fingerprint context — weather, VIX, sector rhyme, gap, session quality.
    Stored on every deploy so patterns compound with what that day felt like.
    """
    ticker_clean = str(ticker or "").strip().upper()
    weather = compute_market_weather_snapshot(ticker=ticker_clean)
    session_quality = evaluate_session_data_quality(
        data_stream,
        ticker=ticker_clean,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
        timeframe_resolution=timeframe_resolution,
    )
    ticker_vel = fetch_symbol_velocity_series(ticker_clean)
    sector_rhymes: dict[str, float] = {}
    if len(ticker_vel) >= 5:
        for sym in SESSION_SECTOR_ETF_SYMBOLS:
            macro_vel = fetch_symbol_velocity_series(sym)
            if len(macro_vel) >= 5:
                n = min(len(ticker_vel), len(macro_vel))
                sector_rhymes[sym] = round(_pearson_correlation(ticker_vel[-n:], macro_vel[-n:]), 4)

    vix_vel = fetch_symbol_velocity_series("^VIX")
    vix_session = round(sum(vix_vel[-12:]), 4) if vix_vel else 0.0

    envelope = {
        "ticker": ticker_clean,
        "session_date": _session_date_value(start_date),
        "timeframe_resolution": timeframe_resolution,
        "weather_mood": weather.get("weather_mood"),
        "vibe_profile": weather.get("vibe_profile"),
        "spy_session_velocity_pct": weather.get("spy_session_velocity_pct"),
        "vix_session_velocity_pct": vix_session,
        "macro_correlations": weather.get("macro_correlations") or {},
        "sector_rhymes": sector_rhymes,
        "session_gap_pct": session_quality.get("session_gap_pct", 0.0),
        "bar_density": session_quality.get("bar_density", 0.0),
        "avg_volume_per_bar": session_quality.get("avg_volume_per_bar", 0.0),
        "session_quality_passed": bool(session_quality.get("passed")),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    st.session_state.room2_day_context = envelope
    return envelope


def _fetch_strategy_vault_samples(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> list[dict]:
    headers = _supabase_rest_headers()
    if not headers:
        return []
    layout = str(macro_weather_layout or "").strip()
    strategy = str(execution_strategy or "").strip()
    if not layout or not strategy:
        return []
    table = _supabase_table_name()
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}",
            headers=headers,
            params={
                "select": "ticker,timestamp,structural_move_pct,state",
                "macro_weather_layout": f"eq.{layout}",
                "execution_strategy": f"eq.{strategy}",
                "timeframe_resolution": f"eq.{timeframe_resolution}",
                "or": "(state.is.null,state.eq.active,state.eq.incubation)",
                "order": "timestamp.desc",
                "limit": "64",
            },
            timeout=15,
        )
        if resp.ok and isinstance(resp.json(), list):
            return resp.json()
    except Exception:
        pass
    return []


def evaluate_strategy_trust_promotion(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
    ticker: str,
    session_date,
    margin_pct: float,
) -> dict:
    """
    Promote strategy to TRUSTED only after repeatable wins across names/sessions.
    First saves stay incubation candidates until the library proves repetition.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    current_win = float(margin_pct or 0.0) >= floor_pct
    rows = _fetch_strategy_vault_samples(
        macro_weather_layout=macro_weather_layout,
        execution_strategy=execution_strategy,
        timeframe_resolution=timeframe_resolution,
    )
    tickers: set[str] = set()
    sessions: set[str] = set()
    wins = 0
    for row in rows:
        move = float(row.get("structural_move_pct") or 0.0)
        if move < floor_pct * 0.85:
            continue
        wins += 1
        tick = str(row.get("ticker") or "").strip().upper()
        if tick:
            tickers.add(tick)
        ts = str(row.get("timestamp") or "")[:10]
        if ts:
            sessions.add(ts)

    ticker_clean = str(ticker or "").strip().upper()
    session_key = _session_date_value(session_date) or ""
    projected_wins = wins + (1 if current_win else 0)
    projected_tickers = set(tickers)
    if current_win and ticker_clean:
        projected_tickers.add(ticker_clean)
    projected_sessions = set(sessions)
    if session_key:
        projected_sessions.add(session_key)

    trusted = (
        projected_wins >= STRATEGY_TRUST_MIN_SAMPLES
        and len(projected_tickers) >= STRATEGY_TRUST_MIN_UNIQUE_TICKERS
        and len(projected_sessions) >= STRATEGY_TRUST_MIN_UNIQUE_SESSIONS
    )
    tier = "trusted" if trusted else "candidate"
    remaining = max(0, STRATEGY_TRUST_MIN_SAMPLES - projected_wins)
    message = (
        f"Strategy **{execution_strategy}** promoted to **TRUSTED** "
        f"({projected_wins} wins · {len(projected_tickers)} tickers · "
        f"{len(projected_sessions)} sessions)."
        if trusted
        else (
            f"Strategy **{execution_strategy}** saved as **CANDIDATE** — "
            f"{remaining} more verified win(s) needed across "
            f"{STRATEGY_TRUST_MIN_UNIQUE_TICKERS}+ tickers / "
            f"{STRATEGY_TRUST_MIN_UNIQUE_SESSIONS}+ sessions for TRUSTED status."
        )
    )
    return {
        "trust_tier": tier,
        "trusted": trusted,
        "projected_wins": projected_wins,
        "unique_tickers": len(projected_tickers),
        "unique_sessions": len(projected_sessions),
        "message": message,
        "vault_state": "active" if trusted else VAULT_STATE_INCUBATION,
    }


def route_room3_tactical_scan(
    *,
    ticker: str,
    timeframe_resolution: str = "15-Minute",
) -> dict:
    """
    RESERVED — future Room 3 live execution router (not exposed in UI yet).
    Reads market weather, aligns layout bucket, surfaces in-bucket strategies,
    and allows flexible cross-layout strategy borrow when cosine alignment is close enough.
    """
    import self_surgery

    ticker_clean = str(ticker or "").strip().upper()
    if not ticker_clean:
        return {"ok": False, "error": "Ticker required for tactical scan."}

    weather = compute_market_weather_snapshot(ticker=ticker_clean, force_refresh=True)
    ticker_vel = fetch_symbol_velocity_series(ticker_clean)
    if len(ticker_vel) < 5:
        return {
            "ok": False,
            "error": f"Insufficient tape for {ticker_clean} — try a more liquid symbol.",
            "market_weather": weather,
        }

    live_vec = build_four_layer_feature_vector(
        {
            "session_velocity_pct": sum(ticker_vel[-12:]),
            "peak_bar_velocity_pct": max(ticker_vel),
            "mean_bar_velocity_pct": statistics.mean(ticker_vel),
        },
        {"volume": {"sigma": statistics.pstdev(ticker_vel) if len(ticker_vel) >= 3 else 0.0}},
        vwap_bias_pct=sum(ticker_vel[-6:]),
        sec_coordinate=max(-1.0, min(1.0, float(weather.get("vix_session_velocity_pct") or 0.0) / 5.0)),
    )
    spatial = compute_spatial_layout_match(live_vec)
    match_pct = int(spatial.get("spatial_match_pct") or 0)
    primary_layout = resolve_layout_with_market_weather(
        str(spatial.get("nearest_layout_id") or "NEW_LAYOUT"),
        vibe_profile=str(weather.get("vibe_profile") or "neutral"),
        weather=weather,
        spatial_match_pct=match_pct,
    )

    ranked_layouts = cloud_offload.rpc_top_layout_alignments(live_vec, limit=6)
    if not ranked_layouts:
        ranked_layouts = [
            {
                "layout_id": primary_layout,
                "cosine_similarity": float(spatial.get("cosine_similarity") or 0.0),
                "spatial_match_pct": match_pct,
            }
        ]

    primary_strategies = fetch_layout_shell_strategies(
        primary_layout,
        timeframe_resolution=timeframe_resolution,
    )
    strategy_rows: list[dict] = []
    seen: set[str] = set()
    for row in primary_strategies:
        label = str(row.get("execution_strategy") or "").strip()
        tf = str(row.get("timeframe_resolution") or timeframe_resolution).strip()
        if not label:
            continue
        key = f"{label}|{tf}"
        if key in seen:
            continue
        seen.add(key)
        blocked = self_surgery.is_live_execution_blocked(
            parent_layout_id=primary_layout,
            strategy_label=label,
            timeframe_resolution=tf,
        )
        stored_vec = _parse_master_signature_from_row(row)
        cos = _cosine_similarity(live_vec, stored_vec) if stored_vec else 0.0
        strategy_rows.append(
            {
                "strategy_label": label,
                "timeframe_resolution": tf,
                "layout_id": primary_layout,
                "source": "primary_layout",
                "cosine_to_live": round(cos, 4),
                "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
                "live_execution_blocked": blocked,
            }
        )

    flex_rows: list[dict] = []
    for entry in ranked_layouts:
        alt_layout = str(entry.get("layout_id") or entry.get("macro_weather_layout") or "").strip()
        if not alt_layout or alt_layout == primary_layout:
            continue
        alt_pct = int(
            round(float(entry.get("cosine_similarity") or 0.0) * 100)
            if entry.get("cosine_similarity") is not None
            else int(entry.get("spatial_match_pct") or 0)
        )
        if alt_pct < LAYOUT_CROSS_MATCH_FLEX_PCT:
            continue
        for row in fetch_layout_shell_strategies(alt_layout, timeframe_resolution=timeframe_resolution):
            label = str(row.get("execution_strategy") or "").strip()
            tf = str(row.get("timeframe_resolution") or timeframe_resolution).strip()
            if not label:
                continue
            key = f"{label}|{tf}"
            if key in seen:
                continue
            seen.add(key)
            stored_vec = _parse_master_signature_from_row(row)
            cos = _cosine_similarity(live_vec, stored_vec) if stored_vec else 0.0
            if cos * 100 < LAYOUT_CROSS_MATCH_FLEX_PCT:
                continue
            blocked = self_surgery.is_live_execution_blocked(
                parent_layout_id=alt_layout,
                strategy_label=label,
                timeframe_resolution=tf,
            )
            flex_rows.append(
                {
                    "strategy_label": label,
                    "timeframe_resolution": tf,
                    "layout_id": alt_layout,
                    "source": "cross_layout_flex",
                    "layout_match_pct": alt_pct,
                    "cosine_to_live": round(cos, 4),
                    "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
                    "live_execution_blocked": blocked,
                }
            )

    flex_rows.sort(key=lambda row: float(row.get("cosine_to_live") or 0.0), reverse=True)
    recommended = next(
        (row for row in strategy_rows if not row.get("live_execution_blocked")),
        next((row for row in flex_rows if not row.get("live_execution_blocked")), None),
    )

    result = {
        "ok": True,
        "ticker": ticker_clean,
        "timeframe_resolution": timeframe_resolution,
        "market_weather": weather,
        "primary_layout": primary_layout,
        "layout_match_pct": match_pct,
        "weather_mood": weather.get("weather_mood"),
        "vibe_profile": weather.get("vibe_profile"),
        "primary_strategies": strategy_rows,
        "flex_strategies": flex_rows[:6],
        "recommended_strategy": recommended,
        "ranked_layouts": ranked_layouts,
        "live_execution_halted": bool(st.session_state.get("room2_live_execution_halted")),
    }
    st.session_state.room3_router_result = result
    return result


def fetch_layout_shell_strategies(
    layout_id: str,
    *,
    timeframe_resolution: str = "",
) -> list[dict]:
    """Query cloud vault for all strategies inside a Master Layout Container shell."""
    layout_clean = str(layout_id or "").strip()
    if not layout_clean or layout_clean in ("NEW_LAYOUT", "PURGATORY_PENDING"):
        return []
    headers = _supabase_rest_headers()
    if not headers:
        return []
    table = _supabase_table_name()
    params: dict = {
        "select": (
            "id,ticker,macro_weather_layout,execution_strategy,timeframe_resolution,"
            "structural_move_pct,master_signature_json,entry_coordinate,exit_coordinate,state"
        ),
        "macro_weather_layout": f"eq.{layout_clean}",
        "vault_track": "eq.track_1_validated",
        "or": "(state.is.null,state.eq.active)",
        "order": "timestamp.desc",
        "limit": "64",
    }
    if timeframe_resolution:
        params["timeframe_resolution"] = f"eq.{timeframe_resolution}"
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/{table}",
            headers=headers,
            params=params,
            timeout=20,
        )
        if resp.ok and isinstance(resp.json(), list):
            return resp.json()
    except Exception:
        pass
    return []


def run_global_vibe_check(
    data_stream,
    *,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
    research_audit: dict | None = None,
    math_block: dict | None = None,
) -> dict:
    """
    Stage 1 — Global Vibe Check: scale lookback/news depth by timeframe, map Master Layout.
    """
    end_dt = _parse_session_datetime(end_date, end_time)
    start_dt = _parse_session_datetime(start_date, start_time)
    scale = float(REGIME_VIBE_LOOKBACK_SCALE.get(timeframe_resolution, 1.0))
    velocity = _compute_price_velocity_metrics(data_stream)
    lookback_start = _calibrated_lookback_start(
        end_dt,
        timeframe_resolution,
        start_dt=start_dt,
        data_stream=data_stream,
    )
    metric_envelopes = compute_metric_envelopes(data_stream, end_dt, lookback_start)
    vwap_bias_pct = 0.0
    frame = _ensure_dataframe(data_stream)
    if frame is not None and not frame.empty and "VWAP" in frame.columns and "Close" in frame.columns:
        last_vw = float(frame["VWAP"].iloc[-1] or 0.0)
        last_close = float(frame["Close"].iloc[-1] or 0.0)
        if last_vw:
            vwap_bias_pct = (last_close - last_vw) / last_vw * 100.0

    audit = research_audit or st.session_state.get("room2_deep_research_audit") or {}
    semantic = audit.get("semantic_catalyst") or {}
    sec_coord = max(-1.0, min(1.0, float(semantic.get("finbert_sentiment_score") or 0.0)))
    mb = math_block or st.session_state.get("room2_last_math_block") or {}

    feature_vec = build_four_layer_feature_vector(
        velocity,
        metric_envelopes,
        vwap_bias_pct=vwap_bias_pct,
        sec_coordinate=sec_coord,
        math_block=mb,
    )
    spatial = compute_spatial_layout_match(feature_vec)
    layout_id = str(spatial.get("nearest_layout_id") or "NEW_LAYOUT")
    match_pct = int(spatial.get("spatial_match_pct") or 0)
    if match_pct < LAYOUT_SIGNATURE_MATCH_THRESHOLD and layout_id == "NEW_LAYOUT":
        layout_id = "PURGATORY_PENDING"

    vol_sigma = float((metric_envelopes.get("volume") or {}).get("sigma") or 0.0)
    if vol_sigma >= 2.0:
        vibe = "expansion"
    elif vol_sigma <= 0.35:
        vibe = "compressed"
    else:
        vibe = "neutral"

    weather = compute_market_weather_snapshot(ticker=str(st.session_state.get("r2_good_ticker") or ""))
    weather_vibe = str(weather.get("vibe_profile") or vibe)
    if weather_vibe in ("expansion", "compressed", "neutral"):
        vibe = weather_vibe

    layout_id = resolve_layout_with_market_weather(
        layout_id,
        vibe_profile=vibe,
        weather=weather,
        spatial_match_pct=match_pct,
    )
    if match_pct < LAYOUT_SIGNATURE_MATCH_THRESHOLD and str(spatial.get("nearest_layout_id") or "") in (
        "NEW_LAYOUT",
        "PURGATORY_PENDING",
    ):
        layout_id = str(layout_id or "PURGATORY_PENDING")

    news_depth_days = int(REGIME_VIBE_NEWS_DEPTH_DAYS.get(timeframe_resolution, 7))
    scaled_lookback_hours = round(3.0 * scale, 2)

    return {
        "stage": "global_vibe_check",
        "master_layout_container": layout_id,
        "vibe_profile": vibe,
        "market_weather": weather,
        "weather_mood": weather.get("weather_mood"),
        "lookback_scale": scale,
        "scaled_lookback_hours": scaled_lookback_hours,
        "news_depth_days": news_depth_days,
        "news_depth_scale": round(scale * 1.5, 2),
        "feature_vector": feature_vec,
        "spatial": spatial,
        "metric_envelopes": metric_envelopes,
        "velocity": velocity,
        "sec_coordinate": sec_coord,
        "vwap_bias_pct": round(vwap_bias_pct, 4),
        "spatial_match_pct": match_pct,
    }


def crack_layout_shell(
    layout_id: str,
    snapshot_vec: list[float],
    *,
    timeframe_resolution: str,
) -> dict:
    """
    Stage 2 — Crack the Shell: pgvector cosine match + internal strategy library reveal.
    """
    shell_match = cloud_offload.rpc_match_layout_spatial(snapshot_vec) or compute_spatial_layout_match(
        snapshot_vec
    )
    resolved_layout = str(layout_id or shell_match.get("nearest_layout_id") or "NEW_LAYOUT")
    rows = fetch_layout_shell_strategies(resolved_layout, timeframe_resolution=timeframe_resolution)
    if not rows and timeframe_resolution:
        rows = fetch_layout_shell_strategies(resolved_layout, timeframe_resolution="")

    internal_library: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        strategy = str(row.get("execution_strategy") or "").strip()
        tf = str(row.get("timeframe_resolution") or "").strip()
        if not strategy:
            continue
        key = f"{strategy}|{tf}"
        if key in seen:
            continue
        seen.add(key)
        stored_vec = _parse_master_signature_from_row(row)
        cos = _cosine_similarity(snapshot_vec, stored_vec) if stored_vec else 0.0
        internal_library.append(
            {
                "strategy_label": strategy,
                "timeframe_resolution": tf,
                "structural_move_pct": float(row.get("structural_move_pct") or 0.0),
                "cosine_to_live": round(cos, 4),
                "reference_ticker": str(row.get("ticker") or "").upper(),
                "entry_coordinate": row.get("entry_coordinate"),
                "exit_coordinate": row.get("exit_coordinate"),
                "row_id": row.get("id"),
            }
        )

    return {
        "stage": "shell_crack",
        "shell_layout_id": resolved_layout,
        "shell_cosine": float(shell_match.get("cosine_similarity") or 0.0),
        "shell_match_pct": int(shell_match.get("spatial_match_pct") or 0),
        "internal_strategies": internal_library,
        "strategy_count": len(internal_library),
        "pgvector_engine": shell_match.get("engine", "array_rpc"),
    }


def judge_layout_strategies(
    shell: dict,
    *,
    data_stream,
    quality: dict,
    timeframe_resolution: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
) -> dict:
    """
    Stage 3 — Strategy Filtering & Judgement: discard misaligned shell strategies,
    lock onto hill-interceptor / liquidity-ignition action, enforce alpha floor.
    """
    floor_pct = timeframe_margin_floor(timeframe_resolution)
    live_quality = dict(quality or {})
    net_margin = float(
        live_quality.get("net_margin_pct")
        or live_quality.get("structural_move_pct")
        or 0.0
    )
    entry_opt = live_quality.get("entry_optimizer") or st.session_state.get("room2_entry_optimizer") or {}

    if entry_opt.get("hill_bypass_rewind") or live_quality.get("hill_bypass_rewind"):
        action_mechanic = "over_the_hill_interceptor_candidate_c"
    elif entry_opt.get("liquidity_ignition") or live_quality.get("liquidity_ignition"):
        action_mechanic = "liquidity_ignition_guard"
    else:
        action_mechanic = str(entry_opt.get("selected_candidate") or "structure_baseline")

    scored: list[dict] = []
    for candidate in shell.get("internal_strategies") or []:
        row = dict(candidate)
        tf = str(row.get("timeframe_resolution") or "")
        if tf and tf != timeframe_resolution:
            row["judgement"] = "discarded_timeframe_isolation"
            row["score"] = 0.0
            scored.append(row)
            continue
        hist_move = float(row.get("structural_move_pct") or 0.0)
        if hist_move < floor_pct * 0.85:
            row["judgement"] = "discarded_macro_misalignment"
            row["score"] = 0.0
            scored.append(row)
            continue
        if net_margin < floor_pct:
            row["judgement"] = "discarded_live_alpha_floor"
            row["score"] = 0.0
            scored.append(row)
            continue
        cos = float(row.get("cosine_to_live") or 0.0)
        row["score"] = round(cos * 0.55 + min(net_margin / 100.0, 1.0) * 0.45, 4)
        row["judgement"] = "qualified"
        scored.append(row)

    qualified = [row for row in scored if row.get("judgement") == "qualified"]
    shell_layout = str(shell.get("shell_layout_id") or "NEW_LAYOUT")
    shell_match_pct = int(shell.get("shell_match_pct") or 0)

    if qualified:
        winner = max(qualified, key=lambda row: float(row.get("score") or 0.0))
        selected_strategy = str(winner.get("strategy_label") or "")
    else:
        selected_strategy = resolve_matrix_strategy_id(
            layout_id=shell_layout,
            timeframe_resolution=timeframe_resolution,
            spatial_match_pct=shell_match_pct,
        )

    passed_alpha = net_margin >= floor_pct
    return {
        "stage": "strategy_judgement",
        "selected_strategy": selected_strategy,
        "action_mechanic": action_mechanic,
        "alpha_floor_pct": floor_pct,
        "net_margin_pct": round(net_margin, 4),
        "passed_alpha_floor": passed_alpha,
        "candidates_evaluated": len(scored),
        "candidates_qualified": len(qualified),
        "judgement_log": scored,
        "trashed": not passed_alpha,
        "trash_reason": None if passed_alpha else f"BELOW_ALPHA_FLOOR_{floor_pct}|net={net_margin:.4f}",
    }


def run_regime_switching_funnel(
    data_stream,
    *,
    ticker: str,
    start_date,
    start_time: str,
    end_date,
    end_time: str,
    timeframe_resolution: str,
    quality: dict | None = None,
    research_audit: dict | None = None,
    math_block: dict | None = None,
) -> dict:
    """
    v6.0 Master Controller — three-stage regime-switching shell-cracking funnel.
    Replaces the legacy linear layout→save loop for strategy selection.
    """
    lane = validate_regime_lookback_lanes(
        data_stream,
        start_date=start_date,
        start_time=start_time,
        timeframe_resolution=timeframe_resolution,
    )
    if not lane.get("passed"):
        _sync_window4_regime_flags(match_pct=0, valid=False)
        return {
            "funnel_version": REGIME_FUNNEL_VERSION,
            "trashed": True,
            "trash_message": (
                f"🗑️ PRE-STORAGE TRASH — Insufficient chart data: need at least "
                f"{lane.get('min_bars')} bars before Start Time, got {lane.get('actual_bars')} "
                f"on {timeframe_resolution} track."
            ),
            "lane_validation": lane,
        }

    quality = dict(quality or st.session_state.get("room2_playbook_quality") or {})
    stage1 = run_global_vibe_check(
        data_stream,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
        timeframe_resolution=timeframe_resolution,
        research_audit=research_audit,
        math_block=math_block,
    )
    stage2 = crack_layout_shell(
        stage1["master_layout_container"],
        stage1["feature_vector"],
        timeframe_resolution=timeframe_resolution,
    )
    stage3 = judge_layout_strategies(
        stage2,
        data_stream=data_stream,
        quality=quality,
        timeframe_resolution=timeframe_resolution,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
    )

    pg_gate = validate_pgvector_regime_match(stage1["feature_vector"])
    match_pct = int(
        pg_gate.get("spatial_match_pct")
        or stage2.get("shell_match_pct")
        or stage1.get("spatial_match_pct")
        or 0
    )
    regime_valid = bool(pg_gate.get("valid")) and bool(stage3.get("passed_alpha_floor"))
    _sync_window4_regime_flags(match_pct=match_pct, valid=regime_valid)

    result = {
        "funnel_version": REGIME_FUNNEL_VERSION,
        "ticker": str(ticker or "").upper(),
        "lane_validation": lane,
        "stage1_vibe": stage1,
        "stage2_shell": stage2,
        "stage3_judgement": stage3,
        "pgvector_gate": pg_gate,
        "master_layout_container": stage1["master_layout_container"],
        "execution_strategy": stage3["selected_strategy"],
        "action_mechanic": stage3["action_mechanic"],
        "feature_vector": stage1["feature_vector"],
        "spatial": stage1["spatial"],
        "market_weather": stage1.get("market_weather") or {},
        "weather_mood": stage1.get("weather_mood"),
        "trashed": bool(stage3.get("trashed")),
        "trash_message": stage3.get("trash_reason"),
        "window4_regime_valid": regime_valid,
        "window4_spatial_match_pct": match_pct,
    }
    st.session_state.room2_regime_funnel = result
    emit_processing_heartbeat(
        "🧭 REGIME FUNNEL v6.0 — Global vibe mapped · shell cracked · strategy judged",
        detail=(
            f"Layout={result['master_layout_container']} · "
            f"Vibe={stage1.get('vibe_profile')} · "
            f"Shell={stage2.get('strategy_count', 0)} strategies · "
            f"Winner={result['execution_strategy']} · "
            f"Mechanic={result['action_mechanic']}"
        ),
    )
    return result


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

    timeframe_resolution = str(st.session_state.get("r2_timeframe_mode", "15-Minute"))
    research_audit = st.session_state.get("room2_deep_research_audit") or {}
    finbert_score = float(
        (research_audit.get("semantic_catalyst") or {}).get("finbert_sentiment_score", 0.0)
    )
    lookback_start = _calibrated_lookback_start(
        end_dt,
        timeframe_resolution,
        start_dt=start_dt,
        data_stream=data_stream,
    )
    metric_envelopes = compute_metric_envelopes(data_stream, end_dt, lookback_start)
    vwap_bias_pct = 0.0
    frame = _ensure_dataframe(data_stream)
    if frame is not None and not frame.empty and "VWAP" in frame.columns and "Close" in frame.columns:
        last_vw = float(frame["VWAP"].iloc[-1] or 0.0)
        last_close = float(frame["Close"].iloc[-1] or 0.0)
        if last_vw:
            vwap_bias_pct = (last_close - last_vw) / last_vw * 100.0

    funnel = run_regime_switching_funnel(
        data_stream,
        ticker=resolved_ticker,
        start_date=start_date,
        start_time=start_time,
        end_date=end_date,
        end_time=end_time,
        timeframe_resolution=timeframe_resolution,
        quality=quality,
        research_audit=research_audit,
        math_block=math_block,
    )
    if funnel.get("trashed"):
        trash_msg = funnel.get("trash_message") or (
            f"🗑️ PRE-STORAGE TRASH — Regime funnel rejected ({funnel.get('trash_message')})."
        )
        st.session_state.room2_regime_funnel = funnel
        return trash_msg

    spatial = funnel.get("spatial") or {}
    stage1 = funnel.get("stage1_vibe") or {}
    stage2 = funnel.get("stage2_shell") or {}
    stage3 = funnel.get("stage3_judgement") or {}
    snapshot_vec = funnel.get("feature_vector") or build_four_layer_feature_vector(
        velocity,
        metric_envelopes,
        vwap_bias_pct=vwap_bias_pct,
        sec_coordinate=finbert_score,
        math_block=math_block,
    )
    blended_match = max(
        int(math_block.get("match_probability") or 0),
        int(spatial.get("spatial_match_pct") or 0),
        int(stage2.get("shell_match_pct") or 0),
    )
    if finbert_score < -0.25 and blended_match >= LAYOUT_SIGNATURE_MATCH_THRESHOLD:
        blended_match = LAYOUT_SIGNATURE_MATCH_THRESHOLD - 1

    genetic = extract_master_signature_vector(snapshot_vec, blended_match)
    master_vec = genetic.get("master_signature") or snapshot_vec
    st.session_state.room2_master_signature = genetic
    math_block["match_probability"] = blended_match
    math_block["spatial_match_pct"] = spatial.get("spatial_match_pct", 0)
    math_block["cosine_similarity"] = spatial.get("cosine_similarity", 0.0)
    math_block["euclidean_distance"] = spatial.get("euclidean_distance", 999.0)
    math_block["nearest_layout_id"] = (
        funnel.get("master_layout_container")
        or genetic.get("layout_id")
        or spatial.get("nearest_layout_id")
    )
    math_block["master_overlap_pct"] = genetic.get("overlap_pct", 0)
    math_block["regime_funnel_version"] = REGIME_FUNNEL_VERSION
    math_block["vibe_profile"] = stage1.get("vibe_profile")
    math_block["shell_strategy_count"] = stage2.get("strategy_count", 0)
    math_block["selected_strategy"] = funnel.get("execution_strategy")
    math_block["action_mechanic"] = funnel.get("action_mechanic")
    math_block["judgement_qualified"] = stage3.get("candidates_qualified", 0)
    st.session_state.room2_spatial_cluster = spatial
    st.session_state.room2_last_math_block = math_block
    st.session_state.room2_funnel_execution_strategy = funnel.get("execution_strategy")

    register_id = str(
        layout_block_id
        or funnel.get("master_layout_container")
        or genetic.get("layout_id")
        or spatial.get("nearest_layout_id", "NEW_LAYOUT")
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
    day_context_json: str = "",
    strategy_trust_tier: str = "candidate",
) -> dict:
    """Package Room 2 deck parameters for Internet Vault streaming."""
    notes = operator_notes.strip()
    matrix_blob = str(text_matrix_string or st.session_state.get("room2_text_matrix_string", "")).strip()
    if matrix_blob and "TEXT_MATRIX|" not in notes:
        notes = f"{notes} | {matrix_blob}".strip(" |") if notes else matrix_blob

    day_blob = day_context_json or json.dumps(
        st.session_state.get("room2_day_context") or {}, default=str
    )
    if day_blob and day_blob != "{}" and "DAY_CONTEXT:" not in notes:
        notes = f"{notes} | DAY_CONTEXT:{day_blob}".strip(" |") if notes else f"DAY_CONTEXT:{day_blob}"
    if strategy_trust_tier and "TRUST_TIER:" not in notes:
        notes = f"{notes} | TRUST_TIER:{strategy_trust_tier}".strip(" |")

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
        "strategy_trust_tier": str(strategy_trust_tier or "candidate"),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if day_blob and day_blob != "{}":
        body["day_context_json"] = day_blob
    body["_raw_operator_notes"] = operator_notes.strip()
    return body
