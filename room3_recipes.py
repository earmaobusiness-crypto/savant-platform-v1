"""
Room 3 strategy recipes — lookback + sensors per layout·strategy·TF.

Room 2 used long nets to *discover* DNA. Room 3 only needs strategy-sized
lookback to *recognize* it, then 30s snapshots to finish the puzzle.

Shared sensors across strategies on a ticker are fetched once per tick.
"""

from __future__ import annotations

import math
import re
from typing import Any

# 5A (15M) / 1D (15M) — the letter’s own TF token. Wins over a stale vault clock.
_STRATEGY_TF_TOKEN = re.compile(r"\(\s*(1|5|15)\s*M\s*\)", re.IGNORECASE)
_PURGATORY_LETTER = re.compile(r"^P\d+\b", re.IGNORECASE)

# Default lookback (minutes of tape) when vault doesn't spell it out.
DEFAULT_LOOKBACK_MIN: dict[str, int] = {
    "1m": 20,
    "5m": 60,
    "15m": 120,  # ~2h — typical 15m signal window, not Room 2's multi-day net
}
MAX_LOOKBACK_MIN: dict[str, int] = {
    "1m": 60,
    "5m": 180,
    "15m": 240,
}
# Chart + VWAP always. Named catalysts plus hyper-vol extras (not keyword-gated).
# Operator names SEC/volume/price/news/social; we also pack what those names need.
BASE_SENSORS = ("charts", "vwap", "rvol")
SHARED_CATALYST_SENSORS = (
    "sec",
    "news",
    "social",
    "float",
    "short_interest",
    "dilution",
    "halt",
    "spread",
)
# Extra tells by TF — hyper-volatile names; 15m gets the deepest brew.
TF_EXTRA_SENSORS: dict[str, tuple[str, ...]] = {
    "1m": ("prints", "bid_ask"),
    "5m": ("premarket_rvol", "float_rotation"),
    "15m": ("offering", "insider", "borrow", "sector", "days_to_cover"),
}
OPTIONAL_SENSORS = SHARED_CATALYST_SENSORS + (
    "prints",
    "bid_ask",
    "premarket_rvol",
    "float_rotation",
    "offering",
    "insider",
    "borrow",
    "sector",
    "days_to_cover",
)
# Three similar packs before a letter is a live strategy (purgatory until then).
STRATEGY_MINT_MIN_SAVES = 3


def normalize_tf(raw: str) -> str:
    named = strategy_tf_token(raw)
    if named:
        return named
    s = str(raw or "").strip().lower().replace(" ", "")
    if s in {"1", "1m", "1min", "1minute", "m1"}:
        return "1m"
    if s in {"5", "5m", "5min", "5minute", "m5"}:
        return "5m"
    if s in {"15", "15m", "15min", "15minute", "m15"}:
        return "15m"
    if "15" in s:
        return "15m"
    if s.startswith("5") or "5m" in s:
        return "5m"
    if s.startswith("1") or "1m" in s:
        return "1m"
    return "5m"


def strategy_tf_token(strategy: str) -> str:
    """TF printed on a matrix letter, e.g. 5A (15M) → 15m. Empty if unlabeled."""
    match = _STRATEGY_TF_TOKEN.search(str(strategy or ""))
    if not match:
        return ""
    return {"1": "1m", "5": "5m", "15": "15m"}[match.group(1)]


def recipe_timeframe(
    *,
    strategy: str = "",
    timeframe: str = "",
    timeframe_norm: str = "",
    timeframe_resolution: str = "",
) -> str:
    """
    Timeframe this DNA actually belongs to.

    The letter’s parenthetical (15M / 5M / 1M) wins over timeframe_norm.
    That stops a 1m watch from matching a bin whose clock says 1m but whose
    name is 5A (15M) — CRE Aug 26: 1m ticket, 15M sticker.
    """
    named = strategy_tf_token(strategy)
    if named:
        return named
    for raw in (timeframe_norm, timeframe, timeframe_resolution):
        text = str(raw or "").strip()
        if not text:
            continue
        tf = normalize_tf(text)
        if tf in ("1m", "5m", "15m"):
            return tf
    if str(strategy or "").strip():
        tf = normalize_tf(strategy)
        if tf in ("1m", "5m", "15m"):
            return tf
    return ""


def strategy_tf_agrees(strategy: str, watch_tf: str) -> bool:
    """False when the letter names a different TF than the live watch."""
    named = strategy_tf_token(strategy)
    want = normalize_tf(watch_tf) if str(watch_tf or "").strip() else ""
    if not named or want not in ("1m", "5m", "15m"):
        return True
    return named == want


def is_purgatory_letter(layout_id: str = "", strategy: str = "") -> bool:
    """Incubation packs sit. They are not live strategies and must not match or fire."""
    lid = str(layout_id or "").strip()
    lid_l = lid.lower()
    if "purgatory" in lid_l or _PURGATORY_LETTER.match(lid):
        return True
    strat = str(strategy or "").strip()
    if "purgatory" in strat.lower() or _PURGATORY_LETTER.match(strat):
        return True
    return False


def scrub_purgatory_line(line: dict[str, Any]) -> bool:
    """Blank incubation stamps. Drop queued tickets. Leave a live fill in place."""
    if not isinstance(line, dict):
        return False
    changed = False
    layout = str(line.get("nearest_layout") or "")
    strat = str(line.get("nearest_strategy") or "")
    in_trade = str(line.get("state") or "") == "in"
    if is_purgatory_letter(layout, strat):
        line["nearest_layout"] = "—"
        line["nearest_strategy"] = "—"
        if not in_trade:
            line["match_pct"] = 0
            line["size_usd"] = 0.0
            line["size_qty"] = 0.0
            line["patience"] = False
            line.pop("patience_note", None)
        changed = True
    entry_layout = str(line.get("entry_layout") or "")
    entry_strat = str(line.get("entry_strategy") or "")
    sig = line.get("entry_signal") if isinstance(line.get("entry_signal"), dict) else {}
    sig_layout = str(sig.get("layout_id") or "")
    sig_strat = str(sig.get("strategy") or "")
    queued = is_purgatory_letter(entry_layout, entry_strat) or is_purgatory_letter(
        sig_layout, sig_strat
    )
    if not queued:
        return changed
    if in_trade:
        line["entry_layout"] = "—"
        line["entry_strategy"] = "—"
        if sig:
            sig["layout_id"] = "—"
            sig["strategy"] = "—"
        return True
    line["state"] = "watching"
    line["sticky"] = False
    line.pop("sticky_until", None)
    line["entry_signal"] = None
    line["exit_signal"] = None
    for key in (
        "entry_layout",
        "entry_strategy",
        "entry_price",
        "entry_qty",
        "entry_match_pct",
        "entry_structural_move_pct",
        "entry_order_id",
    ):
        line.pop(key, None)
    line["nearest_layout"] = "—"
    line["nearest_strategy"] = "—"
    line["match_pct"] = 0
    line["size_usd"] = 0.0
    line["size_qty"] = 0.0
    return True


def minutes_to_bars(tf: str, minutes: int) -> int:
    tf = normalize_tf(tf)
    minutes = max(1, int(minutes or 1))
    if tf == "1m":
        return max(5, minutes)
    if tf == "5m":
        return max(4, int(math.ceil(minutes / 5.0)))
    return max(3, int(math.ceil(minutes / 15.0)))


def recipe_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
) -> dict[str, Any]:
    """
    Build a recipe for one layout·strategy·TF bucket.

    Heuristics until vault stores explicit recipes:
      - TF default lookback
      - always pack catalyst + hyper-vol extras (not keyword-gated)
      - larger stored trips get a bit more tape + patience
    """
    tf = normalize_tf(timeframe)
    strat = str(strategy or "").strip()
    layout = str(layout_id or "").strip()
    blob = f"{strat} {layout}".lower()

    lookback = int(DEFAULT_LOOKBACK_MIN.get(tf, 60))
    sensors: list[str] = list(BASE_SENSORS)
    for s in SHARED_CATALYST_SENSORS:
        if s not in sensors:
            sensors.append(s)
    for s in TF_EXTRA_SENSORS.get(tf, ()):
        if s not in sensors:
            sensors.append(s)

    if any(k in blob for k in ("sec", "filing", "8-k", "8k", "10-q", "10q", "earnings")):
        lookback = max(lookback, int(DEFAULT_LOOKBACK_MIN.get(tf, 60) * 1.25))

    move = abs(float(structural_move_pct or 0))
    if move >= 8.0:
        lookback = int(lookback * 1.35)
    elif move >= 4.0:
        lookback = int(lookback * 1.15)

    cap = int(MAX_LOOKBACK_MIN.get(tf, 180))
    lookback = max(5, min(cap, lookback))
    bars = minutes_to_bars(tf, lookback)

    cadence = cadence_for(
        strat,
        tf,
        layout_id=layout,
        structural_move_pct=move,
    )
    return {
        "layout_id": layout,
        "strategy": strat or "—",
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": bars,
        "sensors": sensors,
        "pulse_seconds": cadence["pulse_seconds"],
        "extra_refresh_seconds": cadence["extra_refresh_seconds"],
        "order_style": order_style_for(
            strat, tf, layout_id=layout, structural_move_pct=move
        ),
        # If DNA is warm but incomplete — keep watching; stock may lag the pattern.
        "patience": True,
        "patience_match_floor": 70,
    }


def order_style_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
) -> str:
    """
    Market only when waiting would miss the print. Otherwise limit (less slippage,
    Yahoo/Alpaca lag). 1m is a prior for pops, not a hard rule — 5m/15m can pop too.
    Outside RTH the broker still forces a limit.
    """
    tf = normalize_tf(timeframe)
    if tf == "1m":
        return "market"
    if tf == "5m" and _letter_head(strategy) in {"1A", "1B", "5A", "1C", "9A", "5B", "2B", "5C", "8A", "6A", "2C", "2D", "2A", "1D", "4A", "6B", "8B", "3A", "9B"}:
        return "market"
    if tf == "15m" and _letter_head(strategy) in {"1A", "1B", "1C", "1D", "2A", "2B", "6A", "9A"}:
        return "market"
    blob = f"{strategy} {layout_id}".lower()
    patient = (
        "vwap",
        "pullback",
        "reversion",
        "mean rev",
        "fade",
        "swing",
        "range",
        "dip",
        "reclaim",
        "flag",
        "patient",
        "limit",
    )
    pop = (
        "scalp",
        "sniper",
        "pop",
        "spike",
        "burst",
        "chase",
        "impulse",
        "flush",
        "squeeze",
        "blast",
        "gap and go",
        "gap&go",
    )
    if any(k in blob for k in patient):
        return "limit"
    if any(k in blob for k in pop):
        return "market"
    _ = structural_move_pct
    return "limit"


def cadence_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
    in_trade: bool = False,
) -> dict[str, int]:
    """
    Revisit interval after the first lookback paint.
    15m lives on 5–10m checks (a closed bar), not a 15s clip.
    5m typical ~1–5m. 1m pops stay short.
    """
    tf = normalize_tf(timeframe)
    style = order_style_for(
        strategy,
        tf,
        layout_id=layout_id,
        structural_move_pct=structural_move_pct,
    )
    pop = style == "market"
    if tf == "1m":
        pulse = 15 if pop else 60
        extras = 120 if pop else 180
    elif tf == "5m":
        pulse = 60 if pop else 300
        extras = 180 if pop else 300
    else:
        pulse = 300 if pop else 600
        extras = 300 if pop else 600
    if in_trade:
        if tf == "1m":
            pulse = min(int(pulse), 15)
        elif tf == "5m":
            pulse = min(int(pulse), 60)
        else:
            pulse = min(int(pulse), 300)
    return {"pulse_seconds": int(pulse), "extra_refresh_seconds": int(extras)}


def _letter_head(strategy: str) -> str:
    raw = str(strategy or "").strip().upper()
    return raw.split("(")[0].strip().replace(" ", "")


# --- Pooled exits (locked 2026-09-21) -------------------------------------
# Per-letter targets/stops are not estimable from the data that exists. The
# 20,196 nominations behind them collapse to 233 stock-days, and the best 1%
# of outcomes carry 43% of all gain — fat tails on ~30 independent episodes
# per letter. Every per-letter fit died out of sample.
#
# These two numbers per TF are fitted across ALL 233 stock-days and chosen on
# the MEDIAN old day (so one tail day cannot pick them). Per-trade edge, old
# -> untouched fresh days: 15m +8.3% -> +5.9% · 5m +1.28% -> +1.29% ·
# 1m +1.20% -> +1.19%. First thing that transferred.
#
# The letter still decides WHETHER to enter. It no longer decides the exit.
POOLED_EXITS_ON = True
POOLED_EXITS: dict[str, tuple[float, float]] = {
    "15m": (30.0, 10.0),  # target %, hard stop %
    "5m": (8.0, 8.0),
    "1m": (25.0, 10.0),
}
# Caps stay on so $0 letters still do not fire. Working tickets are $2M-scale
# (1m $100k · 5m $200k · 15m $300k). A smaller Set $ uses the TF slot instead
# — the cap only binds when the slot is bigger than the ticket.
LETTER_CAPS_ON = True

# Fat-tape Handle (locked 2026-09-22). Same letter. This temperament.
# Last bar ≥4.5% → wider stop, 20-minute hold or letter-flip, wick fill,
# another shot allowed. Not a TNON gene and not +20% as the exit.
FAT_BAR_PCT = 4.5
FAT_STOP_MIN_PCT = 8.0
FAT_HOLD_MINUTES = 20
FAT_WICK_LOC = 0.40


def last_bar_range_pct(slices: list[dict[str, Any]] | None) -> float:
    last = (slices or [None])[-1] or {}
    c = float(last.get("c") or 0)
    h = float(last.get("h") or 0)
    lo = float(last.get("l") or 0)
    if c <= 0:
        return 0.0
    return (h - lo) / c * 100.0


def tape_is_fat(slices: list[dict[str, Any]] | None) -> bool:
    return last_bar_range_pct(slices) + 1e-12 >= FAT_BAR_PCT


def fat_stop_pct(slices: list[dict[str, Any]] | None) -> float:
    return max(FAT_STOP_MIN_PCT, last_bar_range_pct(slices))


def wick_fill_px(slices: list[dict[str, Any]] | None, last_px: float = 0.0) -> float:
    """Buy the wick, not the close."""
    last = (slices or [None])[-1] or {}
    lo = float(last.get("l") or 0)
    if lo > 0:
        return lo
    return float(last_px or last.get("c") or 0)


def wick_touch_ok(
    slices: list[dict[str, Any]] | None,
    last_px: float,
    *,
    bar_complete: bool = False,
) -> bool:
    """Completed bars already printed the wick. A live bar waits for the low."""
    if not tape_is_fat(slices):
        return True
    if bar_complete:
        return True
    last = (slices or [None])[-1] or {}
    lo = float(last.get("l") or 0)
    hi = float(last.get("h") or 0)
    if lo <= 0 or hi <= lo:
        return True
    px = float(last_px or last.get("c") or 0)
    if px <= 0:
        return True
    return px <= lo + FAT_WICK_LOC * (hi - lo)


def letter_flipped(entry_letter: str, now_letter: str) -> bool:
    a = _letter_head(entry_letter)
    b = _letter_head(now_letter)
    return bool(a and b and a != b)


def apply_fat_to_handle(
    payload: dict[str, Any],
    slices: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Overlay fat-tape temperament on a Handle stamp. DNA / letter stay."""
    out = dict(payload or {})
    if not tape_is_fat(slices):
        return out
    stop = fat_stop_pct(slices)
    out["fat_tape"] = True
    out["first_of_day"] = False
    out["cool_sec"] = 0
    out["entry"] = "wick"
    out["order_style_rth"] = "limit"
    out["stop"] = "hard_pct"
    out["stop_floor_pct"] = float(stop)
    out.pop("stop_cap_pct", None)
    out.pop("target_pct", None)
    out["exit_tgt_px"] = 0.0
    out["hold_minutes"] = FAT_HOLD_MINUTES
    out["exit_on_letter_flip"] = True
    out["exit_source"] = "fat_tape"
    return out


def pooled_exit_pcts(timeframe: str = "") -> tuple[float, float] | None:
    """(target %, hard stop %) for this TF, or None when pooled exits are off."""
    if not POOLED_EXITS_ON:
        return None
    return POOLED_EXITS.get(normalize_tf(timeframe))


# Ticket cap vs Trading-today growth. None = TF slot may grow. 0 = do not fire.
# Keyed to the letters the live detector actually nominates (nearest ≥85% on
# as-of vault DNA), not to the extras-as-detect sim. 10-day $2M ice book
# (Jul 30–31, Sep 1–3/10–11/15–17). Resize only from a larger size pile.
_5M_FULL_SLOT = frozenset({"1A", "8A", "1B", "9A", "2B"})
_15M_FULL_SLOT = frozenset({"1A", "2B"})
_1M_FULL_SLOT = frozenset({"3G", "3B", "7B"})
_LETTER_MAX_TICKET_USD: dict[tuple[str, str], float] = {
    ("5m", "1C"): 200_000.0,
    ("5m", "5B"): 200_000.0,
    ("5m", "5C"): 0.0,
    ("5m", "6A"): 200_000.0,
    ("5m", "3A"): 0.0,
    ("5m", "4A"): 0.0,
    ("15m", "8B"): 0.0,
    ("15m", "9A"): 300_000.0,
}
# Comfortable $2M tickets. Scale-down: TF slot is smaller than these, so it wins.
_UNSIZED_5M_CAP = 200_000.0
_UNSIZED_1M_CAP = 100_000.0
_UNSIZED_15M_CAP = 300_000.0


def letter_max_ticket_usd(timeframe: str = "", strategy: str = "") -> float | None:
    """Per-letter ticket ceiling. Extra Trading-today cash stays for uncapped letters."""
    tf = normalize_tf(timeframe)
    head = _letter_head(strategy)
    if not LETTER_CAPS_ON:
        return None
    if not head or head.startswith("P"):
        return None
    keyed = _LETTER_MAX_TICKET_USD.get((tf, head))
    if keyed is not None:
        return float(keyed)
    if tf == "5m":
        if head in _5M_FULL_SLOT:
            return None
        return float(_UNSIZED_5M_CAP)
    if tf == "1m":
        if head in _1M_FULL_SLOT:
            return None
        return float(_UNSIZED_1M_CAP)
    if tf == "15m":
        if head in _15M_FULL_SLOT:
            return None
        return float(_UNSIZED_15M_CAP)
    return None


def handle_execution_for(
    strategy: str = "",
    timeframe: str = "5m",
    *,
    layout_id: str = "",
    structural_move_pct: float = 0.0,
) -> dict[str, Any]:
    """
    Live Handle stamped onto a vault layout bucket. DNA vector is unchanged.
    1m fill-now after Hunt extra (2026-09-20). 5m all live letters fill-now after Hunt extra.
    15m 1A/1B/1C/1D/2A/2B/6A/9A fill-now after Hunt extra. 8A/8B (15M) still dip-hold.
    Other 5m/15m placeholder still dip-hold.
    Ticket cap: letter_max_ticket_usd — extra book does not flow into letters
    that went red at $2M on the Jul/Sep size pile.
    Fat tape (last bar ≥4.5%) is applied live from slices, not here.
    """
    _ = layout_id
    tf = normalize_tf(timeframe)
    head = _letter_head(strategy)

    def _finish(payload: dict[str, Any]) -> dict[str, Any]:
        cap = letter_max_ticket_usd(tf, head)
        if cap is not None:
            payload["max_ticket_usd"] = float(cap)
        pooled = pooled_exit_pcts(tf)
        if pooled:
            target, stop = pooled
            payload["target_pct"] = float(target)
            payload["stop"] = "hard_pct"
            payload["stop_floor_pct"] = float(stop)
            payload["stop_cap_pct"] = float(stop)
            payload["exit_source"] = "pooled_tf"
        return payload
    specialized_1m = frozenset({"5B", "2A", "1A", "2D", "2B", "2C", "3A", "4A", "3B", "5A", "7A", "3C", "4D", "4B", "6A", "4C", "4E", "6B", "3D", "7B", "3G", "3F", "8A", "7C", "3E", "6C"})
    specialized_5m = frozenset({"1A", "1B", "5A", "1C", "9A", "5B", "2B", "5C", "8A", "6A", "2C", "2D", "2A", "1D", "4A", "6B", "8B", "3A", "9B"})
    specialized_15m = frozenset({"1A", "1B", "1C", "1D", "2A", "2B", "6A", "9A"})
    base: dict[str, Any] = {
        "tf": tf,
        "letter": str(strategy or "").strip() or head,
        "first_of_day": True,
        "cool_sec": 15 * 60,
        "stop": "lookback_low",
        "stop_floor_pct": 2.0,
        "source": "room3_handle",
        "vault_dna_mutated": False,
    }
    if tf == "1m":
        base["stop_cap_pct"] = 3.5
        base.update(
            {
                "entry": "fill_now",
                "order_style_rth": "market",
                "order_style_outside_rth": "limit",
                "skip_until": "09:45",
            }
        )
        if head in ("2A", "2C", "3A", "1A", "3B", "4B", "3F", "8A", "7C", "3E", "6C"):
            base["skip_until"] = "10:00"
        if head == "5B":
            base["target_pct"] = 16.5
        elif head == "2A":
            base["target_pct"] = 10.0
        elif head == "1A":
            base["target_pct"] = "trip_12_trail_12 / violent_12 / mild_8"
        elif head == "2D":
            base["target_pct"] = 6.5
        elif head == "2B":
            base["target_pct"] = 6.0
        elif head == "2C":
            base["target_pct"] = 10.0
        elif head == "3A":
            base["target_pct"] = 10.0
            base["stop_floor_pct"] = 3.5
            base["no_new_after"] = "12:00"
        elif head == "4A":
            base["target_pct"] = 6.0
        elif head == "3B":
            base["target_pct"] = 16.0
            base["stop_floor_pct"] = 3.5
        elif head == "5A":
            base["target_pct"] = 10.0
        elif head == "7A":
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 3.5
        elif head == "3C":
            base["target_pct"] = 16.0
            base["stop_floor_pct"] = 3.5
        elif head == "4D":
            base["target_pct"] = 8.0
        elif head == "4B":
            base["target_pct"] = 16.0
        elif head == "6A":
            base["target_pct"] = 16.0
            base["stop_floor_pct"] = 3.5
        elif head == "4C":
            base["target_pct"] = 6.0
        elif head == "4E":
            base["target_pct"] = 8.5
        elif head == "6B":
            base["target_pct"] = 15.5
            base["stop_floor_pct"] = 3.5
        elif head == "3D":
            base["target_pct"] = 14.0
            base["stop_floor_pct"] = 3.5
        elif head == "7B":
            base["target_pct"] = 12.5
            base["stop_floor_pct"] = 3.5
        elif head == "3G":
            base["target_pct"] = 10.0
            base["stop_floor_pct"] = 3.5
        elif head == "3F":
            base["target_pct"] = 12.5
            base["stop_floor_pct"] = 3.5
        elif head == "8A":
            base["target_pct"] = 12.5
            base["stop_floor_pct"] = 3.5
        elif head == "7C":
            base["target_pct"] = 18.0
            base["stop_floor_pct"] = 3.5
        elif head == "3E":
            base["target_pct"] = 17.0
            base["stop_floor_pct"] = 3.5
        elif head == "6C":
            base["target_pct"] = 14.0
            base["stop_floor_pct"] = 3.5
        else:
            move = abs(float(structural_move_pct or 0))
            base["target_pct"] = round(move * 0.5, 4) if move > 0 else 0.0
            base["specialized"] = False
        if head in specialized_1m:
            base["specialized"] = True
        base["name_shots_max"] = 3
        return _finish(base)
    if tf == "5m" and head in specialized_5m:
        base.update(
            {
                "entry": "fill_now",
                "order_style_rth": "market",
                "order_style_outside_rth": "limit",
                "specialized": True,
                "lookback_bars": 3,
            }
        )
        if head == "1A":
            base["skip_until"] = "09:45"
            base["target_pct"] = 16.0
            base["stop_floor_pct"] = 2.0
        elif head == "1B":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 3.5
        elif head == "1C":
            base["skip_until"] = "09:45"
            base["target_pct"] = 14.0
            base["stop_floor_pct"] = 2.0
        elif head == "9A":
            base["skip_until"] = "09:45"
            base["target_pct"] = 7.5
            base["stop_floor_pct"] = 2.0
        elif head == "5B":
            base["skip_until"] = "10:00"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "2B":
            base["skip_until"] = "09:45"
            base["target_pct"] = 10.0
            base["stop_floor_pct"] = 2.0
        elif head == "5C":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 3.5
        elif head == "8A":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "6A":
            base["skip_until"] = "10:00"
            base["target_pct"] = 9.0
            base["stop_floor_pct"] = 3.5
        elif head == "2C":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "2D":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "2A":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "1D":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "4A":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head in ("6B", "8B", "3A"):
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        elif head == "9B":
            base["skip_until"] = "09:45"
            base["target_pct"] = 8.0
            base["stop_floor_pct"] = 2.0
        else:
            base["skip_until"] = "10:00"
            base["target_pct"] = 6.5
            base["stop_floor_pct"] = 3.5
        return _finish(base)
    if tf == "15m" and head in specialized_15m:
        base.update(
            {
                "entry": "fill_now",
                "order_style_rth": "market",
                "order_style_outside_rth": "limit",
                "specialized": True,
                "lookback_bars": 3,
                "skip_until": "",
                "stop_floor_pct": 2.0,
            }
        )
        if head == "1A":
            base["target_pct"] = 8.0
        else:
            base["target_pct"] = 12.0
        return _finish(base)
    dip = 0.006 if tf == "5m" else 0.008
    if tf == "5m":
        base["skip_until"] = "09:45"
    else:
        base["skip_until"] = ""
    move = abs(float(structural_move_pct or 0))
    if tf == "15m":
        tgt = 12.0
    elif tf == "5m":
        tgt = round(move * 0.75, 4) if move > 0 else 0.0
    else:
        tgt = round(move * 0.5, 4) if move > 0 else 0.0
    base.update(
        {
            "entry": "dip_hold",
            "dip_frac": dip,
            "order_style_rth": "limit",
            "order_style_outside_rth": "limit",
            "target_pct": tgt,
            "specialized": False,
        }
    )
    if tf == "5m":
        base["trail_after_target_pct"] = 8.0
        base["exit"] = "trail_8_after_target"
    return _finish(base)


def attach_recipe(layout_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(layout_entry or {})
    tf = str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "5m")
    strat = str(entry.get("strategy") or "")
    layout = str(entry.get("layout_id") or "")
    move = float(entry.get("structural_move_pct") or 0)
    entry["recipe"] = recipe_for(
        strat,
        tf,
        layout_id=layout,
        structural_move_pct=move,
    )
    entry["handle_execution"] = handle_execution_for(
        strat,
        tf,
        layout_id=layout,
        structural_move_pct=move,
    )
    return entry


def plan_for_timeframe(
    layouts: list[dict[str, Any]] | None,
    timeframe: str,
) -> dict[str, Any]:
    """
    Across all recipes on this TF: max lookback, union of sensors.
    Shared fetches run once; each strategy still scores its own window.
    """
    tf = normalize_tf(timeframe)
    recipes: list[dict[str, Any]] = []
    for entry in layouts or []:
        entry_tf = normalize_tf(
            str(entry.get("timeframe_norm") or entry.get("timeframe_resolution") or "")
        )
        if entry_tf and entry_tf != tf:
            continue
        rec = entry.get("recipe")
        if not isinstance(rec, dict):
            rec = recipe_for(
                str(entry.get("strategy") or ""),
                tf,
                layout_id=str(entry.get("layout_id") or ""),
                structural_move_pct=float(entry.get("structural_move_pct") or 0),
            )
        recipes.append(rec)

    if not recipes:
        recipes = [recipe_for("", tf)]

    lookback = max(int(r.get("lookback_minutes") or 0) for r in recipes)
    bars = max(int(r.get("bars_keep") or 0) for r in recipes)
    sensors: list[str] = []
    seen: set[str] = set()
    for r in recipes:
        for s in r.get("sensors") or []:
            s = str(s).strip().lower()
            if s and s not in seen:
                seen.add(s)
                sensors.append(s)
    for s in BASE_SENSORS:
        if s not in seen:
            sensors.insert(0, s)
            seen.add(s)

    pulses = [int(r.get("pulse_seconds") or 60) for r in recipes] or [60]
    extras = [int(r.get("extra_refresh_seconds") or 300) for r in recipes] or [300]
    return {
        "timeframe": tf,
        "lookback_minutes": lookback,
        "bars_keep": max(bars, minutes_to_bars(tf, lookback)),
        "sensors": sensors,
        "pulse_seconds": min(pulses),
        "extra_refresh_seconds": min(extras),
        "recipes": recipes,
        "strategy_count": len(recipes),
    }


def empty_sensor_pack(ticker: str) -> dict[str, Any]:
    pack: dict[str, Any] = {
        "ticker": str(ticker or "").upper(),
        "charts": {"ok": False, "note": "pending"},
        "vwap": {"ok": False, "note": "pending"},
        "shared": True,
    }
    for name in OPTIONAL_SENSORS:
        pack[name] = {"ok": None, "note": "pending — hyper-vol extra"}
    return pack


def recipes_need_sensor(recipes: list[dict[str, Any]], sensor: str) -> bool:
    s = str(sensor or "").lower()
    return any(s in (r.get("sensors") or []) for r in recipes)
