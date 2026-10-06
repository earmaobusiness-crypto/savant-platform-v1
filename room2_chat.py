"""Chat door into Room 2.

Operator reviews here (belt → blind sim → clocks / good / bad).
Capture writes a purgatory pack onto the same shelf Room 2 counts.
Does not mint a live letter. The dated 2026-10-06 S1 dump is a snapshot,
not this capture path.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import room3_precursor as precursor

ET = ZoneInfo("America/New_York")
PACK_DIR = Path(__file__).resolve().parent / "room3_data" / "room2_packs"
PACK_DIR.mkdir(parents=True, exist_ok=True)


def _clock(raw: str) -> time:
    parts = str(raw).strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def _bars_to_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    idx = []
    rows = []
    for b in bars:
        ts = b["ts"]
        if getattr(ts, "tzinfo", None) is not None:
            ts = ts.astimezone(ET).replace(tzinfo=None)
        idx.append(ts)
        rows.append(
            {
                "Open": float(b.get("o") or 0),
                "High": float(b.get("h") or 0),
                "Low": float(b.get("l") or 0),
                "Close": float(b.get("c") or 0),
                "Volume": float(b.get("v") or 0),
            }
        )
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def _slice_bars(bars: list[dict[str, Any]], start: time, end: time) -> list[dict[str, Any]]:
    out = []
    for b in bars:
        ts = b["ts"]
        t = ts.astimezone(ET).time() if getattr(ts, "tzinfo", None) else ts.time()
        if start <= t <= end:
            out.append(b)
    return out


def pack_path(ticker: str, sess: date, tf: str, start: str, end: str) -> Path:
    name = f"{sess.isoformat()}-{ticker.upper()}-{tf}-{start.replace(':','')}-{end.replace(':','')}.json"
    return PACK_DIR / name


def capture(
    *,
    ticker: str,
    sess: date,
    tf: str,
    start: str,
    end: str,
    bars: list[dict[str, Any]],
    note: str = "",
    detect: str = "",
    source: str = "chat_review",
) -> dict[str, Any]:
    """Store one operator window as a Room 2 purgatory pack. Not a letter."""
    tf_n = precursor.tf_token(tf)
    t0, t1 = _clock(start), _clock(end)
    window_bars = _slice_bars(bars, t0, t1)
    if not window_bars:
        raise ValueError(f"no bars {ticker} {sess} {tf_n} {start}-{end}")
    window = _bars_to_frame(window_bars)
    full = _bars_to_frame(bars)
    pack = precursor.extra_pack(ticker, tf=tf_n, as_of=sess, window=window, full_day=full)
    vector = precursor.tape_vector(window)
    start_dt = datetime.combine(sess, t0)
    end_dt = datetime.combine(sess, t1)
    body = {
        "state": "purgatory",
        "source": source,
        "ticker": str(ticker).upper(),
        "session": sess.isoformat(),
        "tf": tf_n,
        "start": start,
        "end": end,
        "note": note,
        "detect": detect,
        "layout_id": "Purgatory",
        "strategy": f"Purgatory ({tf_n.upper()})",
        "vector": vector,
        "precursor_pack": pack,
        "n_bars": len(window_bars),
        "open": float(window_bars[0].get("o") or 0),
        "high": max(float(b.get("h") or 0) for b in window_bars),
        "low": min(float(b.get("l") or 0) for b in window_bars),
        "close": float(window_bars[-1].get("c") or 0),
        "captured_at": datetime.now(ET).isoformat(),
        "live": False,
    }
    path = pack_path(ticker, sess, tf_n, start, end)
    path.write_text(json.dumps(body, indent=2, default=str) + "\n")
    _ = start_dt, end_dt
    return {"path": str(path), "pack": body}


def list_packs(ticker: str | None = None) -> list[dict[str, Any]]:
    out = []
    for path in sorted(PACK_DIR.glob("*.json")):
        try:
            row = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(row, dict) or row.get("state") != "purgatory":
            continue
        if ticker and str(row.get("ticker") or "").upper() != str(ticker).upper():
            continue
        row["_file"] = str(path)
        out.append(row)
    return out
