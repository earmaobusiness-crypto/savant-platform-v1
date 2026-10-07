"""Same-session book memory so a later question can reconstruct the watch book.

Pulse writes a snapshot on every pass (~15s) from session start to finish
(Match%, state, Size$, fills, Arm). Kept until 16:00 ET the next calendar
day, then deleted. Not a forever archive.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MEM_DIR = Path(__file__).resolve().parent / "room3_data" / "day_memory"
PURGE_HOUR = 16
MIN_GAP_SEC = 0


def session_key(now: datetime | None = None) -> str:
    clock = now or datetime.now(ET)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ET)
    else:
        clock = clock.astimezone(ET)
    day = (clock - timedelta(days=1) if clock.hour < 4 else clock).date()
    return day.isoformat()


def _path(sess: str) -> Path:
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    return MEM_DIR / f"{sess}.jsonl"


def _keep_until(sess: str) -> datetime:
    day = datetime.strptime(sess, "%Y-%m-%d").replace(tzinfo=ET)
    return (day + timedelta(days=1)).replace(hour=PURGE_HOUR, minute=0, second=0, microsecond=0)


def _compact_line(line: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    import room3_watcher

    ticker = str(line.get("ticker") or "").upper()
    tf = str(line.get("timeframe") or "")
    kids = []
    for child in line.get("children") or []:
        if not isinstance(child, dict):
            continue
        kids.append(
            {
                "letter": str(child.get("letter") or child.get("strategy") or ""),
                "match": int(child.get("match_pct") or 0),
                "layout": str(child.get("layout_id") or "")[:16],
            }
        )
    return {
        "ticker": ticker,
        "tf": tf,
        "match": int(line.get("match_pct") or 0),
        "layout": str(line.get("nearest_layout") or "")[:16],
        "strategy": str(line.get("nearest_strategy") or "")[:24],
        "state": room3_watcher._display_state(line, book),
        "size": round(float(line.get("size_usd") or 0), 2),
        "why": str(line.get("patience_note") or room3_watcher._why_not_firing(line, book) or "")[:72],
        "children": kids,
    }


def _compact_trade(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or "")[:24],
        "ticker": str(row.get("ticker") or row.get("symbol") or "").upper(),
        "tf": str(row.get("matrix_timeframe") or row.get("timeframe") or row.get("tf") or ""),
        "letter": str(row.get("matrix_strategy") or row.get("strategy") or row.get("letter") or ""),
        "side": str(row.get("side") or ""),
        "pnl": round(float(row.get("pnl") or row.get("realized_pl") or 0), 2),
        "in": str(row.get("entry_time") or row.get("filled_at") or row.get("t_in") or "")[:19],
        "out": str(row.get("exit_time") or row.get("t_out") or "")[:19],
    }


def snapshot(ss: Any, *, now: datetime | None = None) -> dict[str, Any]:
    import room3_engine

    clock = now or datetime.now(ET)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ET)
    else:
        clock = clock.astimezone(ET)
    book = dict(ss.get("room3_watch_book") or {})
    hist = [r for r in (ss.get("room3_trade_history") or []) if isinstance(r, dict)]
    opens = [p for p in (ss.get("room3_open_positions") or []) if isinstance(p, dict)]
    lines = []
    for line in (book.get("lines") or {}).values():
        if isinstance(line, dict):
            lines.append(_compact_line(line, book))
    window = ""
    try:
        window = room3_engine.session_label(room3_engine.detect_session_window())
    except Exception:
        window = ""
    wins = sum(1 for r in hist if float(r.get("pnl") or r.get("realized_pl") or 0) > 0)
    pnl = sum(float(r.get("pnl") or r.get("realized_pl") or 0) for r in hist)
    return {
        "ts": clock.strftime("%H:%M:%S"),
        "iso": clock.isoformat(),
        "session": session_key(clock),
        "arm": bool(ss.get("room3_engine_armed")),
        "unattended": bool(ss.get("room3_unattended_armed")),
        "pause": bool(ss.get("room3_pause_entries")),
        "kill": bool(ss.get("room3_kill_flat")),
        "tradable": round(float(ss.get("room3_tradable_today") or 0), 2),
        "window": window,
        "belt": [str(t).upper() for t in (ss.get("room3_filter_universe") or []) if str(t).strip()],
        "equity": round(float(ss.get("room3_account_equity") or ss.get("room3_broker_equity") or 0), 2),
        "day_pnl": round(pnl, 2),
        "fills": len(hist),
        "wins": wins,
        "opens": [
            {
                "ticker": str(p.get("ticker") or p.get("symbol") or "").upper(),
                "qty": float(p.get("qty") or 0),
                "tf": str(p.get("timeframe") or p.get("tf") or ""),
                "letter": str(p.get("letter") or p.get("strategy") or ""),
            }
            for p in opens
        ],
        "log": [_compact_trade(r) for r in hist[-40:]],
        "lines": lines,
        "note": str(ss.get("room3_worker_note") or "")[:120],
    }


def _fp(snap: dict[str, Any]) -> str:
    bits = [
        str(int(snap.get("arm") or 0)),
        str(int(snap.get("unattended") or 0)),
        ",".join(snap.get("belt") or []),
        str(int(snap.get("fills") or 0)),
        str(int(snap.get("tradable") or 0)),
    ]
    for ln in snap.get("lines") or []:
        bits.append(
            f"{ln.get('ticker')}:{ln.get('tf')}:{ln.get('match')}:{ln.get('state')}:"
            f"{ln.get('strategy')}:{ln.get('size')}"
        )
        for kid in ln.get("children") or []:
            bits.append(f"c{kid.get('letter')}:{kid.get('match')}")
    return "|".join(bits)


def remember(ss: Any, *, now: datetime | None = None) -> Path | None:
    """Append one compact snapshot if the book changed or ~45s passed. Never raise into pulse."""
    try:
        purge(now=now)
        snap = snapshot(ss, now=now)
        sess = str(snap.get("session") or "")
        if not sess:
            return None
        path = _path(sess)
        last_fp = ""
        last_iso = ""
        if path.is_file():
            tail = path.read_text()[-4000:]
            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    prev = json.loads(line)
                except json.JSONDecodeError:
                    break
                last_fp = str(prev.get("_fp") or _fp(prev))
                last_iso = str(prev.get("iso") or "")
                break
        fp = _fp(snap)
        if MIN_GAP_SEC > 0 and fp == last_fp and last_iso:
            try:
                prev_t = datetime.fromisoformat(last_iso)
                clock = datetime.fromisoformat(str(snap["iso"]))
                if (clock - prev_t).total_seconds() < MIN_GAP_SEC:
                    return None
            except Exception:
                pass
        snap["_fp"] = fp
        with path.open("a") as fh:
            fh.write(json.dumps(snap, default=str) + "\n")
        return path
    except Exception:
        return None


def load_session(sess: str | None = None) -> list[dict[str, Any]]:
    key = sess or session_key()
    path = _path(key)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def between(start: str, end: str, *, sess: str | None = None) -> list[dict[str, Any]]:
    """Snapshots whose clock is start–end inclusive (HH:MM or HH:MM:SS)."""

    def _t(raw: str) -> time:
        parts = [int(x) for x in str(raw).strip().split(":")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return time(parts[0], parts[1], parts[2])

    t0, t1 = _t(start), _t(end)
    hit = []
    for row in load_session(sess):
        raw = str(row.get("ts") or "")
        try:
            clock = _t(raw)
        except Exception:
            continue
        if t0 <= clock <= t1:
            hit.append(row)
    return hit


def purge(*, now: datetime | None = None) -> list[str]:
    clock = now or datetime.now(ET)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ET)
    else:
        clock = clock.astimezone(ET)
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    gone = []
    for path in MEM_DIR.glob("*.jsonl"):
        sess = path.stem
        try:
            until = _keep_until(sess)
        except ValueError:
            continue
        if clock >= until:
            path.unlink(missing_ok=True)
            gone.append(sess)
    return gone
