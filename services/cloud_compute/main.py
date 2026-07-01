"""
Savant Cloud Compute — deploy to Render / Railway / any ASGI host.

Offloads pandas resampling, metric envelopes, and volume σ-bands from the
local Streamlit terminal.
"""

from __future__ import annotations

import statistics
from typing import Any

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Savant Cloud Compute", version="3.4.0")

RESAMPLE_RULES = {
    "1-Minute": "1min",
    "5-Minute": "5min",
    "15-Minute": "15min",
}


class ResampleRequest(BaseModel):
    bars: list[dict[str, Any]]
    timeframe_resolution: str = "15-Minute"


class MetricEnvelopeRequest(BaseModel):
    bars: list[dict[str, Any]]
    lookback_start: str | None = None
    end_dt: str | None = None


class VolumeEnvelopeRequest(BaseModel):
    bars: list[dict[str, Any]]


def _bars_to_frame(bars: list[dict]) -> pd.DataFrame | None:
    if not bars:
        return None
    stamps = []
    records = []
    for row in bars:
        ts = pd.to_datetime(row.get("t"))
        if getattr(ts, "tzinfo", None) is not None:
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


def _frame_to_bars(frame: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for ts, row in frame.iterrows():
        rows.append(
            {
                "t": ts.isoformat(),
                "Open": float(row["Open"]),
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"]),
                "Volume": float(row["Volume"]),
                "VWAP": float(row.get("VWAP", row["Close"])),
            }
        )
    return rows


def _resample(frame: pd.DataFrame, rule: str) -> pd.DataFrame | None:
    agg_map = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    vol = frame["Volume"].astype(float).fillna(0.0)
    vwap_num = (frame["VWAP"].astype(float).fillna(0.0) * vol).resample(rule).sum()
    vwap_den = vol.resample(rule).sum()
    out = frame.resample(rule).agg(agg_map)
    out["VWAP"] = (vwap_num / vwap_den.replace(0.0, float("nan"))).fillna(out["Close"])
    out = out.dropna(subset=["Close"], how="any")
    return out if not out.empty else None


def _metric_envelopes(frame: pd.DataFrame) -> dict:
    envelopes: dict = {}
    if "Volume" in frame.columns:
        vols = frame["Volume"].astype(float).dropna()
        if len(vols) >= 2:
            mu = float(vols.mean())
            sigma = float(vols.std(ddof=0))
            envelopes["volume"] = {
                "low": round(max(0.0, mu - sigma), 0),
                "mid": round(mu, 0),
                "high": round(mu + sigma, 0),
                "sigma": round(sigma, 2),
            }
    closes = frame["Close"].astype(float)
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
        (frame["High"] - frame["Low"]) / frame["Close"].replace(0, pd.NA) * 100
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


def _volume_envelope(frame: pd.DataFrame) -> dict:
    vols = frame["Volume"].astype(float).fillna(0.0)
    if vols.empty:
        return {"mean": 0.0, "std": 0.0, "floor": 0.0}
    mu = float(vols.mean())
    sigma = float(vols.std()) if len(vols) > 1 else 0.0
    return {"mean": mu, "std": sigma, "floor": max(0.0, mu - sigma)}


@app.get("/health")
def health():
    return {"status": "ok", "engine": "savant-cloud-compute", "version": "3.4.0"}


@app.post("/v1/resample")
def resample_track(req: ResampleRequest):
    frame = _bars_to_frame(req.bars)
    if frame is None:
        return {"bars": [], "bar_count": 0}
    if req.timeframe_resolution == "1-Minute":
        out = frame
    else:
        rule = RESAMPLE_RULES.get(req.timeframe_resolution, "15min")
        out = _resample(frame, rule)
        if out is None:
            return {"bars": [], "bar_count": 0}
    bars = _frame_to_bars(out)
    return {"bars": bars, "bar_count": len(bars), "timeframe_resolution": req.timeframe_resolution}


@app.post("/v1/metric-envelopes")
def metric_envelopes(req: MetricEnvelopeRequest):
    frame = _bars_to_frame(req.bars)
    if frame is None:
        return {"metric_envelopes": {}}
    if req.lookback_start and req.end_dt:
        try:
            start = pd.to_datetime(req.lookback_start)
            end = pd.to_datetime(req.end_dt)
            frame = frame[(frame.index >= start) & (frame.index <= end)]
        except Exception:
            pass
    return {"metric_envelopes": _metric_envelopes(frame)}


@app.post("/v1/volume-envelope")
def volume_envelope(req: VolumeEnvelopeRequest):
    frame = _bars_to_frame(req.bars)
    if frame is None or "Volume" not in frame.columns:
        return {"envelope": {"mean": 0.0, "std": 0.0, "floor": 0.0}}
    return {"envelope": _volume_envelope(frame)}
