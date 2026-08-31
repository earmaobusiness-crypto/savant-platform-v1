"""
Replay old Room 2 windows into precursor DNA + hyper-vol extras.

Does not wipe rows. Does not change layout/strategy letters.
Writes master_signature_json (before-pack) onto the same id.

  python3 room3_replay.py --dry-run --limit 5
  python3 room3_replay.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import vault_bridge
import room3_precursor as precursor

PROGRESS_PATH = Path(__file__).resolve().parent / "room3_data" / "replay_progress.json"


def _load_progress() -> dict[str, Any]:
    try:
        if PROGRESS_PATH.is_file():
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"done_ids": [], "failed": []}


def _save_progress(blob: dict[str, Any]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(blob, indent=2), encoding="utf-8")


def replay_row(row: dict[str, Any], *, write: bool) -> dict[str, Any]:
    win = precursor.window_from_row(row)
    if not win:
        return {"ok": False, "skip": "no_window", "ticker": row.get("ticker")}
    ticker = win["ticker"]
    tf = win["tf"]
    sess = win["session_date"]
    frame = precursor.load_session_bars(ticker, sess, tf)
    window, fence = precursor.precursor_window(frame, win["start_dt"], tf)
    vector = precursor.tape_vector(window)
    if not vector:
        return {
            "ok": False,
            "skip": "no_tape",
            "ticker": ticker,
            "tf": tf,
            "session_date": str(sess),
        }
    pack = precursor.extra_pack(
        ticker,
        tf=tf,
        as_of=sess,
        window=window,
        full_day=frame,
    )
    blob = precursor.build_signature_blob(
        vector=vector,
        pack=pack,
        window_meta=win,
        existing=row.get("master_signature_json"),
    )
    result = {
        "ok": True,
        "ticker": ticker,
        "tf": tf,
        "session_date": str(sess),
        "row_id": win.get("row_id"),
        "vector": vector,
        "sec_filings": (pack.get("sec") or {}).get("filings") or [],
        "extras_on": [
            k
            for k, v in pack.items()
            if isinstance(v, dict) and v.get("ok") is True
        ],
        "fence": str(fence),
        "wrote": False,
    }
    if write and win.get("row_id"):
        ok, err = vault_bridge.patch_pattern_row(
            win["row_id"],
            {"master_signature_json": blob},
        )
        result["wrote"] = bool(ok)
        if not ok:
            result["ok"] = False
            result["skip"] = f"patch:{err}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill precursor DNA on saved windows.")
    parser.add_argument("--write", action="store_true", help="PATCH vault rows")
    parser.add_argument("--dry-run", action="store_true", help="Compute only (default)")
    parser.add_argument("--limit", type=int, default=0, help="Max rows this run")
    parser.add_argument("--force", action="store_true", help="Re-replay already stamped rows")
    args = parser.parse_args(argv)
    write = bool(args.write) and not args.dry_run

    rows, err = vault_bridge.supabase_fetch_patterns(limit=5000)
    if err:
        print(f"vault fetch failed: {err}", file=sys.stderr)
        return 1
    progress = _load_progress()
    done = set(str(x) for x in (progress.get("done_ids") or []))
    stats = {
        "rows": len(rows or []),
        "replayed": 0,
        "wrote": 0,
        "skipped": 0,
        "failed": 0,
        "already": 0,
    }
    print(f"vault rows: {stats['rows']}  write={write}")
    for row in rows or []:
        rid = str(row.get("id") or "")
        if args.limit and stats["replayed"] + stats["failed"] + stats["skipped"] >= args.limit:
            break
        if not args.force and (rid in done or precursor.already_replayed(row)):
            stats["already"] += 1
            continue
        result = replay_row(row, write=write)
        tag = str(result.get("ticker") or "?")
        sess = result.get("session_date") or ""
        tf = result.get("tf") or ""
        if result.get("ok"):
            stats["replayed"] += 1
            if result.get("wrote"):
                stats["wrote"] += 1
                if rid:
                    done.add(rid)
            extras = ",".join(result.get("extras_on") or [])[:80]
            print(
                f"  {tag} {sess} {tf}  vec={result.get('vector')}  extras={extras}"
            )
        else:
            why = str(result.get("skip") or "fail")
            if why == "no_window":
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                progress.setdefault("failed", []).append(
                    {"id": rid, "ticker": tag, "why": why}
                )
            print(f"  SKIP {tag} {sess} {tf}  {why}")
        if write and stats["wrote"] and stats["wrote"] % 10 == 0:
            progress["done_ids"] = sorted(done)
            _save_progress(progress)
    progress["done_ids"] = sorted(done)
    progress["stats"] = stats
    _save_progress(progress)
    print(json.dumps(stats))
    return 0 if stats["failed"] < max(5, stats["rows"] // 4) else 2


if __name__ == "__main__":
    raise SystemExit(main())
