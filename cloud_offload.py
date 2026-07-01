"""
Distributed cloud offload client — keeps the Streamlit terminal a thin viewer.

Routes heavy resampling, metric envelopes, FinBERT inference, and spatial
vector matching to external cloud hosts (Render/Railway compute + Supabase RPC +
Hugging Face Serverless).
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

try:
    import pandas as pd
except ImportError:
    pd = None

FINBERT_MODEL_ID = "ProsusAI/finbert"
HF_INFERENCE_URL = f"https://api-inference.huggingface.co/models/{FINBERT_MODEL_ID}"
CLOUD_COMPUTE_TIMEOUT = 45
SUPABASE_RPC_TIMEOUT = 20


def _config(key: str, default: str = "") -> str:
    try:
        import streamlit as st

        val = st.secrets.get(key, default)
        if val not in (None, ""):
            return str(val)
    except Exception:
        pass
    return str(os.environ.get(key, default) or "")


def cloud_compute_url() -> str:
    return _config("CLOUD_COMPUTE_URL", "").rstrip("/")


def cloud_compute_enabled() -> bool:
    return bool(cloud_compute_url())


def huggingface_token() -> str:
    return _config("HUGGINGFACE_API_TOKEN", _config("HF_API_TOKEN", ""))


def huggingface_enabled() -> bool:
    return bool(huggingface_token())


def supabase_configured() -> bool:
    return bool(_config("SUPABASE_URL", "") and _config("SUPABASE_KEY", ""))


def cloud_offload_strict() -> bool:
    raw = _config("CLOUD_OFFLOAD_STRICT", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def offload_status() -> dict[str, Any]:
    return {
        "cloud_compute": cloud_compute_enabled(),
        "cloud_compute_url": cloud_compute_url() or None,
        "hf_serverless": huggingface_enabled(),
        "supabase_rpc": supabase_configured(),
        "strict_mode": cloud_offload_strict(),
        "viewer_mode": cloud_compute_enabled() and huggingface_enabled() and supabase_configured(),
    }


def _supabase_headers() -> dict[str, str]:
    key = _config("SUPABASE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _supabase_rpc(function_name: str, payload: dict) -> dict | list | None:
    if not supabase_configured():
        return None
    base = _config("SUPABASE_URL", "").rstrip("/")
    try:
        resp = requests.post(
            f"{base}/rest/v1/rpc/{function_name}",
            headers=_supabase_headers(),
            json=payload,
            timeout=SUPABASE_RPC_TIMEOUT,
        )
        if resp.ok:
            body = resp.json()
            return body if body is not None else None
    except Exception:
        pass
    return None


def dataframe_to_bars(frame) -> list[dict]:
    if frame is None or pd is None:
        return []
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    rows: list[dict] = []
    for ts, row in frame.iterrows():
        try:
            stamp = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        except Exception:
            stamp = str(ts)
        rows.append(
            {
                "t": stamp,
                "Open": float(row.get("Open", row.get("open", 0)) or 0),
                "High": float(row.get("High", row.get("high", 0)) or 0),
                "Low": float(row.get("Low", row.get("low", 0)) or 0),
                "Close": float(row.get("Close", row.get("close", 0)) or 0),
                "Volume": float(row.get("Volume", row.get("volume", 0)) or 0),
                "VWAP": float(row.get("VWAP", row.get("vwap", row.get("Close", 0))) or 0),
            }
        )
    return rows


def bars_to_dataframe(rows: list[dict]):
    if pd is None or not rows:
        return None
    try:
        stamps = []
        records = []
        for row in rows:
            ts = pd.to_datetime(row.get("t"))
            if hasattr(ts, "tz_localize") and getattr(ts, "tzinfo", None) is not None:
                ts = ts.tz_localize(None)
            stamps.append(ts)
            records.append(
                {
                    "Open": float(row.get("Open", 0) or 0),
                    "High": float(row.get("High", 0) or 0),
                    "Low": float(row.get("Low", 0) or 0),
                    "Close": float(row.get("Close", 0) or 0),
                    "Volume": float(row.get("Volume", 0) or 0),
                    "VWAP": float(row.get("VWAP", row.get("Close", 0)) or 0),
                }
            )
        frame = pd.DataFrame(records, index=pd.DatetimeIndex(stamps))
        return frame if not frame.empty else None
    except Exception:
        return None


def remote_resample_track(frame_1m, timeframe_resolution: str):
    """Offload multi-timeframe resample to cloud compute host."""
    if not cloud_compute_enabled() or frame_1m is None:
        return None
    bars = dataframe_to_bars(frame_1m)
    if not bars:
        return None
    try:
        resp = requests.post(
            f"{cloud_compute_url()}/v1/resample",
            json={"bars": bars, "timeframe_resolution": timeframe_resolution},
            timeout=CLOUD_COMPUTE_TIMEOUT,
        )
        if resp.ok:
            payload = resp.json()
            return bars_to_dataframe(payload.get("bars") or [])
    except Exception:
        pass
    return None


def remote_metric_envelopes(
    frame,
    *,
    lookback_start: str | None = None,
    end_dt: str | None = None,
) -> dict | None:
    if not cloud_compute_enabled() or frame is None:
        return None
    bars = dataframe_to_bars(frame)
    if not bars:
        return None
    try:
        resp = requests.post(
            f"{cloud_compute_url()}/v1/metric-envelopes",
            json={
                "bars": bars,
                "lookback_start": lookback_start,
                "end_dt": end_dt,
            },
            timeout=CLOUD_COMPUTE_TIMEOUT,
        )
        if resp.ok:
            env = resp.json().get("metric_envelopes")
            return env if isinstance(env, dict) else None
    except Exception:
        pass
    return None


def remote_volume_envelope(bars: list[dict]) -> dict | None:
    if not cloud_compute_enabled() or not bars:
        return None
    try:
        resp = requests.post(
            f"{cloud_compute_url()}/v1/volume-envelope",
            json={"bars": bars},
            timeout=CLOUD_COMPUTE_TIMEOUT,
        )
        if resp.ok:
            env = resp.json().get("envelope")
            return env if isinstance(env, dict) else None
    except Exception:
        pass
    return None


def hf_sentiment_score(text: str) -> float:
    scores = hf_sentiment_batch([text])
    return float(scores[0]) if scores else 0.0


def hf_sentiment_batch(texts: list[str]) -> list[float]:
    """Serverless FinBERT — no local torch/transformers."""
    clean = [str(t).strip() for t in texts if str(t).strip()]
    if not clean:
        return []
    if not huggingface_enabled():
        return [0.0] * len(clean)

    token = huggingface_token()
    headers = {"Authorization": f"Bearer {token}"}
    scores: list[float] = []
    for text in clean:
        try:
            resp = requests.post(
                HF_INFERENCE_URL,
                headers=headers,
                json={"inputs": text[:512]},
                timeout=30,
            )
            if not resp.ok:
                scores.append(0.0)
                continue
            raw = resp.json()
            rows = raw[0] if raw and isinstance(raw, list) and raw and isinstance(raw[0], list) else raw
            if not isinstance(rows, list):
                rows = [rows]
            pos = neg = 0.0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("label", "")).lower()
                prob = float(row.get("score", 0.0))
                if "positive" in label:
                    pos = prob
                elif "negative" in label:
                    neg = prob
            scores.append(round(max(-1.0, min(1.0, pos - neg)), 4))
        except Exception:
            scores.append(0.0)
    return scores


def rpc_match_layout_spatial(query_vector: list[float]) -> dict | None:
    """Cosine spatial match executed inside Supabase — vectors never cached locally."""
    if not query_vector or not supabase_configured():
        return None
    body = _supabase_rpc("match_layout_spatial", {"query_vector": query_vector})
    if isinstance(body, dict):
        return {
            "spatial_match_pct": int(body.get("spatial_match_pct") or 0),
            "cosine_similarity": float(body.get("cosine_similarity") or 0.0),
            "euclidean_distance": float(body.get("euclidean_distance") or 999.0),
            "nearest_layout_id": str(body.get("nearest_layout_id") or "NEW_LAYOUT"),
        }
    return None


def rpc_top_layout_alignments(query_vector: list[float], *, limit: int = 5) -> list[dict]:
    if not query_vector or not supabase_configured():
        return []
    body = _supabase_rpc(
        "top_layout_alignments",
        {"query_vector": query_vector, "row_limit": int(limit)},
    )
    if isinstance(body, list):
        ranked = sorted(
            [row for row in body if isinstance(row, dict)],
            key=lambda row: float(row.get("cosine_similarity") or 0.0),
            reverse=True,
        )
        return ranked[: max(1, int(limit))]
    return []


def rpc_merge_layout_signature(
    query_vector: list[float],
    *,
    match_threshold: float = 0.85,
    noise_epsilon: float = 0.18,
) -> dict | None:
    if not query_vector or not supabase_configured():
        return None
    body = _supabase_rpc(
        "merge_layout_signature",
        {
            "query_vector": query_vector,
            "match_threshold": float(match_threshold),
            "noise_epsilon": float(noise_epsilon),
        },
    )
    return body if isinstance(body, dict) else None
