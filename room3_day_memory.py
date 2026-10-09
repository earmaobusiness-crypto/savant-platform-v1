"""Same-session book memory so a later question can reconstruct the watch book.

Pulse writes while the session is live (Arm / Set $ / belt / opens): Match%,
state, Size$, fills, Arm. On change immediately; otherwise about once a
minute. Only while that session box is ticked (pre-market, market hours,
post-market). A box that is off is skipped, including a gap in the middle,
and the next ticked box starts again if names, Arm, or Set $ are still up.
Stops at 8:00 PM. Kept until 20:00 ET the next calendar day, then deleted.
Operator Room 3 has no tape UI. Agent reads Cloud ?hub=3&mem=1.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MEM_DIR = Path(__file__).resolve().parent / "room3_data" / "day_memory"
PURGE_HOUR = 20
LIVE_KEEP_SEC = 60


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
    last = {}
    slices = [s for s in (line.get("slices") or []) if isinstance(s, dict)]
    if slices:
        bar = slices[-1]
        last = {
            "c": round(float(bar.get("c") or 0), 4),
            "h": round(float(bar.get("h") or 0), 4),
            "l": round(float(bar.get("l") or 0), 4),
            "v": round(float(bar.get("v") or 0), 0),
        }
    return {
        "ticker": ticker,
        "tf": tf,
        "match": int(line.get("match_pct") or 0),
        "layout": str(line.get("nearest_layout") or "")[:16],
        "strategy": str(line.get("nearest_strategy") or "")[:24],
        "state": room3_watcher._display_state(line, book),
        "size": round(float(line.get("size_usd") or 0), 2),
        "feed": str(line.get("feed") or "")[:12],
        "fat": bool(line.get("fat_tape")),
        "bar_done": bool(line.get("_fat_bar_complete")),
        "last": last,
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
        "qty": round(float(row.get("qty") or 0), 4),
        "entry": round(float(row.get("entry_price") or row.get("entry_px") or 0), 4),
        "exit": round(float(row.get("exit_price") or row.get("exit_px") or 0), 4),
        "pnl": round(float(row.get("pnl") or row.get("realized_pl") or row.get("pnl_usd") or 0), 2),
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
        window = room3_engine.session_label(room3_engine.detect_session_window(clock))
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
        "gates": sorted(str(x) for x in (ss.get("room3_allowed_sessions") or [])),
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
        str(int(snap.get("pause") or 0)),
        str(snap.get("window") or ""),
        ",".join(snap.get("belt") or []),
        str(int(snap.get("fills") or 0)),
        str(int(snap.get("tradable") or 0)),
        str(int(snap.get("day_pnl") or 0)),
        ",".join(snap.get("gates") or []),
    ]
    for op in snap.get("opens") or []:
        bits.append(f"o{op.get('ticker')}:{op.get('tf')}:{op.get('letter')}:{op.get('qty')}")
    for ln in snap.get("lines") or []:
        bits.append(
            f"{ln.get('ticker')}:{ln.get('tf')}:{ln.get('match')}:{ln.get('state')}:"
            f"{ln.get('strategy')}:{ln.get('size')}:{ln.get('feed')}:{ln.get('fat')}:"
            f"{(ln.get('last') or {}).get('c')}:{ln.get('why')}"
        )
        for kid in ln.get("children") or []:
            bits.append(f"c{kid.get('letter')}:{kid.get('match')}")
    return "|".join(bits)


def _gate_open(ss: Any, clock: datetime) -> bool:
    """True only inside a session box the operator left ticked."""
    import room3_engine

    window = room3_engine.detect_session_window(clock)
    if window == room3_engine.SESSION_CLOSED:
        return False
    allowed = {str(x) for x in (ss.get("room3_allowed_sessions") or [])}
    return window in allowed


def _window_closed(snap: dict[str, Any]) -> bool:
    return str(snap.get("window") or "").strip().lower().startswith("closed")


def _watching(snap: dict[str, Any]) -> bool:
    return bool(snap.get("belt") or snap.get("opens"))


def _warming(snap: dict[str, Any]) -> bool:
    """Arm / Set $ before the first name. Not overnight Arm after flatten."""
    if _watching(snap) or _window_closed(snap) or snap.get("ended"):
        return False
    return bool(snap.get("arm") or float(snap.get("tradable") or 0) > 0)


def _last_row(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    tail = data[-120000:] if len(data) > 120000 else data
    for line in reversed(tail.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            prev = json.loads(line)
        except json.JSONDecodeError:
            break
        if isinstance(prev, dict):
            return prev
    return None


def _keep_alive_due(prev: dict[str, Any] | None, snap: dict[str, Any]) -> bool:
    if not prev:
        return True
    last_iso = str(prev.get("iso") or "")
    if not last_iso:
        return True
    try:
        prev_t = datetime.fromisoformat(last_iso)
        clock = datetime.fromisoformat(str(snap["iso"]))
        return (clock - prev_t).total_seconds() >= LIVE_KEEP_SEC
    except Exception:
        return True


def remember(ss: Any, *, now: datetime | None = None) -> Path | None:
    """Append a compact snapshot while the session is live. Never raise into pulse."""
    try:
        purge(now=now)
        clock = now or datetime.now(ET)
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=ET)
        else:
            clock = clock.astimezone(ET)
        snap = snapshot(ss, now=clock)
        sess = str(snap.get("session") or "")
        if not sess:
            return None
        path = _path(sess)
        prev = _last_row(path)
        if not _gate_open(ss, clock):
            if (
                prev
                and not prev.get("gate_off")
                and (prev.get("had_watch") or _watching(prev) or prev.get("arm"))
            ):
                snap["gate_off"] = True
                snap["_fp"] = _fp(snap)
                with path.open("a") as fh:
                    fh.write(json.dumps(snap, default=str) + "\n")
                return path
            return None
        watching = _watching(snap)
        ever = bool(
            prev
            and (prev.get("ended") or prev.get("had_watch") or _watching(prev))
        )
        warming = (not ever) and _warming(snap)
        if watching or warming:
            fp = _fp(snap)
            last_fp = str((prev or {}).get("_fp") or (_fp(prev) if prev else ""))
            if prev and fp == last_fp and not _keep_alive_due(prev, snap):
                return None
            if watching:
                snap["had_watch"] = True
            snap["_fp"] = fp
        elif prev and _watching(prev):
            snap["ended"] = True
            snap["_fp"] = _fp(snap)
        else:
            return None
        with path.open("a") as fh:
            fh.write(json.dumps(snap, default=str) + "\n")
        return path
    except Exception:
        return None


def kept_sessions(*, now: datetime | None = None) -> list[str]:
    """Session files still on disk. Today's file, plus yesterday until 20:00 ET."""
    purge(now=now)
    if not MEM_DIR.is_dir():
        return []
    return sorted(p.stem for p in MEM_DIR.glob("*.jsonl"))


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


def as_text(rows: list[dict[str, Any]], *, limit: int = 0) -> str:
    """Human tape for a later question. limit 0 = the whole session."""
    chunk = rows[-limit:] if limit and len(rows) > limit else rows
    out = []
    for row in chunk:
        belt = ",".join(row.get("belt") or []) or "—"
        arm = "ARMED" if row.get("arm") else "DISARMED"
        un = " unattended" if row.get("unattended") else ""
        wr = ""
        fills = int(row.get("fills") or 0)
        wins = int(row.get("wins") or 0)
        if fills:
            wr = f" WR {wins}/{fills}"
        gates = ",".join(row.get("gates") or []) or "—"
        out.append(
            f"{row.get('ts')} {arm}{un} ${row.get('tradable') or 0:.0f} "
            f"gates {gates} pnl ${row.get('day_pnl') or 0:+.0f}{wr} belt {belt}"
        )
        for ln in row.get("lines") or []:
            last = ln.get("last") or {}
            px = f" @{last.get('c')}" if last.get("c") else ""
            fat = " fat" if ln.get("fat") else ""
            feed = f" {ln.get('feed')}" if ln.get("feed") else ""
            out.append(
                f"  {ln.get('ticker')} {ln.get('tf')} {ln.get('strategy')} "
                f"{ln.get('match')}% {ln.get('state')} ${ln.get('size') or 0:.0f}"
                f"{feed}{fat}{px} {ln.get('why') or ''}".rstrip()
            )
            for kid in ln.get("children") or []:
                out.append(
                    f"    {kid.get('letter')} {kid.get('match')}% {kid.get('layout')}"
                )
        for tr in (row.get("log") or [])[-8:]:
            if not tr.get("ticker"):
                continue
            out.append(
                f"  FILL {tr.get('ticker')} {tr.get('tf')} {tr.get('letter')} "
                f"{tr.get('entry') or ''}→{tr.get('exit') or ''} ${tr.get('pnl') or 0:+.2f}"
            )
        for op in row.get("opens") or []:
            out.append(
                f"  OPEN {op.get('ticker')} {op.get('tf')} {op.get('letter')} qty {op.get('qty')}"
            )
    if limit and len(rows) > limit:
        out.insert(0, f"… {len(rows) - limit} earlier snaps omitted")
    return "\n".join(out) if out else "no tape yet"


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
