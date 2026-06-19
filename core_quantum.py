import datetime
import json
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
    "5-Minute": datetime.timedelta(hours=6),
    "15-Minute": datetime.timedelta(hours=1),
}
ROOT_CAUSE_FRICTION = "execution_friction_slippage"
ROOT_CAUSE_STRUCTURAL_DECAY = "structural_alpha_decay"
EXECUTION_HALTED_STATE = "execution_halted"
VAULT_STATE_INCUBATION = "incubation"
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
    delta = LOOKBACK_DELTAS.get(timeframe_resolution, datetime.timedelta(hours=1))
    return end_dt - delta


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


def hunt_volume_anchor(data_stream, exit_dt: datetime.datetime, lookback_start_dt):
    """Walk backward from exit to find the original volume-cluster trigger bar."""
    frame = _ensure_dataframe(data_stream)
    if frame is None or exit_dt is None or lookback_start_dt is None:
        return None, None
    try:
        window = frame[(frame.index <= exit_dt) & (frame.index >= lookback_start_dt)]
        if not isinstance(window, pd.DataFrame) or window.empty:
            return None, None
        if "Volume" in window.columns and window["Volume"].sum() > 0:
            anchor_idx = window["Volume"].idxmax()
        else:
            anchor_idx = window.index[0]
        anchor_price = float(window.loc[anchor_idx, "Close"])
        return anchor_idx, anchor_price
    except Exception:
        return None, None


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
    lookback_start = _calibrated_lookback_start(end_dt, timeframe_resolution) if end_dt else None
    anchor_ts, anchor_price = hunt_volume_anchor(data_stream, end_dt, lookback_start)
    exit_price = _price_at_datetime(data_stream, end_dt)

    structural_move_pct = 0.0
    if anchor_price and exit_price and anchor_price > 0:
        structural_move_pct = abs((exit_price - anchor_price) / anchor_price * 100)

    passed = structural_move_pct >= floor_pct
    return {
        "passed": passed,
        "trashed": not passed,
        "structural_move_pct": round(structural_move_pct, 4),
        "floor_pct": floor_pct,
        "anchor_timestamp": str(anchor_ts) if anchor_ts is not None else None,
        "anchor_price": anchor_price,
        "exit_price": exit_price,
        "timeframe_resolution": timeframe_resolution,
    }


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
    status = "STABLE"

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
            diagnosis = (
                "Live execution HALTED — post-mortem: execution friction / slippage. "
                "Core signature remains viable; adjust entry window positioning."
            )
        else:
            root_cause = ROOT_CAUSE_STRUCTURAL_DECAY
            diagnosis = (
                "Live execution HALTED — post-mortem: structural alpha decay. "
                "Pattern systematically broken; decommission parameters and mint Strategy v2."
            )
    elif count >= ALPHA_DECAY_ROLLING_N and avg_margin < floor_pct:
        status = "EVOLVING"
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
        "evolving": status in (EXECUTION_HALTED_STATE, "EVOLVING"),
        "halt_live_execution": halt_live,
        "root_cause": root_cause,
        "diagnosis": diagnosis,
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
    return retro


def evaluate_alpha_decay(
    *,
    macro_weather_layout: str,
    execution_strategy: str,
    timeframe_resolution: str,
) -> dict:
    """
    Rolling last-N margin monitor — returns EVOLVING when average edge drops below floor.
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
    evolving = count >= ALPHA_DECAY_ROLLING_N and avg_margin < floor_pct
    status = "EVOLVING" if evolving else ("WATCH" if count >= 5 else "STABLE")
    return {
        "status": status,
        "timeline_key": timeline_key,
        "sample_count": count,
        "avg_margin_pct": avg_margin,
        "floor_pct": floor_pct,
        "window": ALPHA_DECAY_ROLLING_N,
        "evolving": evolving,
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


def extract_forensic_feature_vector(velocity: dict, math_block: dict) -> list[float]:
    """Four-layer snapshot vector for spatial cross-correlation against layout library."""
    return [
        float(velocity.get("session_velocity_pct", 0.0)),
        float(velocity.get("peak_bar_velocity_pct", 0.0)),
        float(velocity.get("mean_bar_velocity_pct", 0.0)),
        float(velocity.get("window_amplitude_pct", 0.0)),
        float(math_block.get("pearson_r", 0.0)),
        float(math_block.get("wave_amplitude_pct", 0.0)),
        min(float(math_block.get("bar_count", 0)) / 100.0, 10.0),
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
    st.session_state.layout_master_matrix_index = index[:48]


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

    snapshot_vec = extract_forensic_feature_vector(velocity, math_block)
    spatial = compute_spatial_layout_match(snapshot_vec)
    blended_match = max(int(math_block.get("match_probability") or 0), spatial["spatial_match_pct"])
    math_block["match_probability"] = blended_match
    math_block["spatial_match_pct"] = spatial["spatial_match_pct"]
    math_block["cosine_similarity"] = spatial["cosine_similarity"]
    math_block["euclidean_distance"] = spatial["euclidean_distance"]
    math_block["nearest_layout_id"] = spatial["nearest_layout_id"]
    st.session_state.room2_spatial_cluster = spatial
    st.session_state.room2_last_math_block = math_block

    if layout_block_id or resolved_ticker:
        register_layout_vector_in_master_index(
            layout_id=str(layout_block_id or spatial["nearest_layout_id"]),
            vector=snapshot_vec,
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
) -> dict:
    """Package Room 2 deck parameters for Internet Vault streaming."""
    body = {
        "ticker": ticker.upper(),
        "pattern_category": (pattern_category or "UNCLASSIFIED").strip().upper(),
        "entry_coordinate": entry_coordinate,
        "exit_coordinate": exit_coordinate,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "operator_context": operator_notes.strip(),
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
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return body
