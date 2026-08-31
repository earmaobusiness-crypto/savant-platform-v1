"""
Reshuffle Room 2 letters from precursor DNA.

Same TF only. Packs that cosine ≥85% sit together.
n≥3 → live letter. n<3 → purgatory (not traded).
Does not delete rows. Snapshot first.

  python3 room3_recluster.py --dry-run
  python3 room3_recluster.py --write
"""

from __future__ import annotations

import argparse
import json
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import room3_bridge
import room3_matrix
import room3_precursor as precursor
import vault_bridge

REPORT_PATH = Path(__file__).resolve().parent / "room3_data" / "recluster_report.json"
LIVE_MIN = 3
PACK_COSINE = 0.85
LAYOUT_COSINE = 0.70
TF_TAG = {"1m": "1M", "5m": "5M", "15m": "15M"}
TF_VAULT = {"1m": "1-Minute", "5m": "5-Minute", "15m": "15-Minute"}


def _vec(row: dict[str, Any]) -> list[float]:
    blob = row.get("master_signature_json")
    parsed = room3_bridge._parse_master_signature(blob)
    if parsed and any(abs(float(x or 0)) > 1e-9 for x in parsed):
        return [float(x) for x in parsed[: room3_bridge.VECTOR_DIM]]
    return []


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = max(len(v) for v in vectors)
    out: list[float] = []
    for i in range(dim):
        vals = [v[i] for v in vectors if len(v) > i]
        out.append(sum(vals) / len(vals) if vals else 0.0)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    return room3_matrix.cosine_similarity(a, b)


def _cluster(items: list[dict[str, Any]], thresh: float) -> list[list[int]]:
    """Complete linkage: merge only if every pair across the two groups is ≥ thresh."""
    n = len(items)
    clusters: list[list[int]] = [[i] for i in range(n)]
    if n <= 1:
        return clusters
    vecs = [it["vec"] for it in items]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        sim[i][i] = 1.0
        for j in range(i + 1, n):
            c = _cosine(vecs[i], vecs[j])
            sim[i][j] = sim[j][i] = c
    while True:
        best_i = best_j = -1
        best = thresh
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                pair_min = 1.0
                for a in clusters[i]:
                    for b in clusters[j]:
                        if sim[a][b] < pair_min:
                            pair_min = sim[a][b]
                            if pair_min < thresh:
                                break
                    if pair_min < thresh:
                        break
                if pair_min >= best:
                    best = pair_min
                    best_i, best_j = i, j
        if best_i < 0:
            break
        clusters[best_i] = clusters[best_i] + clusters[best_j]
        del clusters[best_j]
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def _letter(idx: int) -> str:
    letters = string.ascii_uppercase
    if idx < 26:
        return letters[idx]
    return letters[idx // 26 - 1] + letters[idx % 26]


def _plan_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    usable: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        vec = _vec(row)
        win = precursor.window_from_row(row)
        tf = (win or {}).get("tf") or precursor.tf_token(
            str(row.get("timeframe_resolution") or row.get("timeframe") or "")
        )
        if not vec or tf not in ("1m", "5m", "15m") or not row.get("id"):
            skipped += 1
            continue
        usable.append(
            {
                "row": row,
                "id": str(row.get("id")),
                "ticker": str(row.get("ticker") or "").upper(),
                "tf": tf,
                "vec": vec,
                "prior_layout": str(row.get("macro_weather_layout") or ""),
                "prior_strategy": str(row.get("execution_strategy") or ""),
            }
        )

    assignments: list[dict[str, Any]] = []
    live_strats: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"skipped_no_dna": skipped, "by_tf": {}}

    for tf in ("15m", "5m", "1m"):
        group = [it for it in usable if it["tf"] == tf]
        clusters = _cluster(group, PACK_COSINE) if group else []
        tf_live = 0
        tf_purg = 0
        for idxs in clusters:
            members = [group[i] for i in idxs]
            n = len(members)
            tickers = sorted({m["ticker"] for m in members})
            rec = {
                "tf": tf,
                "n": n,
                "tickers": tickers,
                "members": members,
                "centroid": _centroid([m["vec"] for m in members]),
                "live": n >= LIVE_MIN,
            }
            if rec["live"]:
                live_strats.append(rec)
                tf_live += 1
            else:
                tf_purg += 1
                rec["layout"] = "Purgatory"
                rec["strategy"] = f"P{tf_purg} ({TF_TAG[tf]})"
                rec["state"] = "incubation"
                rec["tier"] = "candidate"
                assignments.append(rec)
        summary["by_tf"][tf] = {
            "rows": len(group),
            "clusters": len(clusters),
            "live_letters": tf_live,
            "purgatory_clusters": tf_purg,
        }

    layout_groups = _cluster(
        [{"vec": s["centroid"]} for s in live_strats],
        LAYOUT_COSINE,
    ) if live_strats else []
    layout_groups.sort(key=lambda g: -sum(live_strats[i]["n"] for i in g))

    for layout_idx, gidx in enumerate(layout_groups, start=1):
        family = [live_strats[i] for i in gidx]
        family.sort(key=lambda s: (-s["n"], s["tf"]))
        letter_n = {"1m": 0, "5m": 0, "15m": 0}
        for strat in family:
            tf = strat["tf"]
            ch = _letter(letter_n[tf])
            letter_n[tf] += 1
            strat["layout"] = f"Layout {layout_idx}"
            strat["strategy"] = f"{layout_idx}{ch} ({TF_TAG[tf]})"
            strat["state"] = "active"
            strat["tier"] = "live"
            assignments.append(strat)

    summary["usable"] = len(usable)
    summary["live_letters"] = sum(1 for a in assignments if a.get("live"))
    summary["purgatory_clusters"] = sum(1 for a in assignments if not a.get("live"))
    summary["layouts"] = len(layout_groups)
    return assignments, summary


def _stamp_signature(row: dict[str, Any], plan: dict[str, Any]) -> str:
    raw = row.get("master_signature_json")
    blob: dict[str, Any] = {}
    if isinstance(raw, dict):
        blob = dict(raw)
    elif isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                blob = parsed
        except Exception:
            blob = {}
    blob["prior_layout"] = plan["prior_layout"]
    blob["prior_strategy"] = plan["prior_strategy"]
    blob["reclustered_at"] = datetime.now(timezone.utc).isoformat()
    blob["recluster_live"] = bool(plan["live"])
    return json.dumps(blob, default=str)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reshuffle letters from precursor DNA.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    write = bool(args.write) and not args.dry_run

    rows, err = vault_bridge.supabase_fetch_patterns(limit=5000)
    if err:
        print(f"vault fetch failed: {err}", file=sys.stderr)
        return 1
    assignments, summary = _plan_rows(rows or [])
    print(json.dumps(summary, indent=2))
    print("--- live letters ---")
    for a in assignments:
        if not a.get("live"):
            continue
        ticks = ",".join(a["tickers"][:8])
        extra = f"+{len(a['tickers'])-8}" if len(a["tickers"]) > 8 else ""
        print(f"  {a['layout']}  {a['strategy']}  n={a['n']}  {ticks}{extra}")
    print("--- purgatory (n<3) ---")
    for a in assignments:
        if a.get("live"):
            continue
        ticks = ",".join(a["tickers"])
        print(f"  {a['strategy']}  n={a['n']}  {ticks}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": summary,
        "letters": [
            {
                "layout": a["layout"],
                "strategy": a["strategy"],
                "tf": a["tf"],
                "n": a["n"],
                "live": bool(a.get("live")),
                "tickers": a["tickers"],
            }
            for a in assignments
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not write:
        print("dry-run only — no vault writes")
        return 0

    snap, snap_msg = vault_bridge.export_vault_snapshot(note="before precursor recluster")
    print("snapshot", snap_msg, snap)
    if snap is None:
        print("refusing to write without snapshot", file=sys.stderr)
        return 1

    patched = 0
    failed = 0
    for a in assignments:
        for member in a["members"]:
            row = member["row"]
            fields = {
                "macro_weather_layout": a["layout"],
                "execution_strategy": a["strategy"],
                "state": a["state"],
                "strategy_trust_tier": a["tier"],
                "master_signature_json": _stamp_signature(
                    row,
                    {
                        "prior_layout": member["prior_layout"],
                        "prior_strategy": member["prior_strategy"],
                        "live": bool(a.get("live")),
                    },
                ),
            }
            ok, perr = vault_bridge.patch_pattern_row(member["id"], fields)
            if ok:
                patched += 1
            else:
                failed += 1
                print(f"  PATCH fail {member['ticker']} {member['id']}: {perr}")
    print(json.dumps({"patched": patched, "failed": failed}))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
