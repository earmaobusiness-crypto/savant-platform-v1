"""
Automated Purgatory Recycling & Balancing Core — additive strategy lifecycle layer.
Non-destructive to temporal fence, blinding, or core vault schemas.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import streamlit as st

import requests

import core_quantum

PURGATORY_TRACK_INCUBATION = "track_a_incubation"
PURGATORY_TRACK_REPAIR_BAY = "track_b_repair_bay"
REPAIR_BAY_MAX_DAYS = 60
RECOVERY_SAMPLES_REQUIRED = 2
RECOVERY_VECTOR_ALIGN_MIN = 0.72
ENVELOPE_GAP_MAX_PCT = 35.0


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _profile_key(parent_layout_id: str, strategy_label: str, timeframe_resolution: str) -> str:
    return "|".join(
        (
            str(parent_layout_id or "").strip(),
            str(strategy_label or "").strip(),
            str(timeframe_resolution or "").strip(),
        )
    )


def ensure_purgatory_hub_session() -> None:
    st.session_state.setdefault("purgatory_repair_bay", {})
    st.session_state.setdefault("purgatory_hub_events", [])


def is_live_execution_blocked(
    *,
    parent_layout_id: str,
    strategy_label: str,
    timeframe_resolution: str,
) -> bool:
    """Capital gate locked while strategy rests in Repair Bay (Track B)."""
    ensure_purgatory_hub_session()
    key = _profile_key(parent_layout_id, strategy_label, timeframe_resolution)
    profile = st.session_state.purgatory_repair_bay.get(key)
    return bool(profile and not profile.get("reminted", False))


def _unique_ticker_count(tickers: list[str]) -> int:
    return len({str(t).strip().upper() for t in tickers if str(t).strip()})


def _recovery_tickers_valid(tickers: list[str]) -> bool:
    """Multi-stock verification — block re-mint when duplicate tickers pollute the sample."""
    unique = _unique_ticker_count(tickers)
    if unique < RECOVERY_SAMPLES_REQUIRED:
        return False
    return unique == len([t for t in tickers if str(t).strip()])


def _supabase_headers() -> dict:
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


def sync_repair_bay_profile_to_cloud(profile: dict) -> bool:
    """Persist Repair Bay profile to strategy_repair_profiles when table exists."""
    headers = _supabase_headers()
    if not headers or not profile:
        return False
    key = _profile_key(
        str(profile.get("parent_layout_id") or ""),
        str(profile.get("strategy_label") or ""),
        str(profile.get("timeframe_resolution") or ""),
    )
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        payload = {
            "profile_key": key,
            "parent_layout_id": profile.get("parent_layout_id"),
            "strategy_label": profile.get("strategy_label"),
            "timeframe_resolution": profile.get("timeframe_resolution"),
            "profile_json": profile,
            "live_execution_enabled": bool(profile.get("live_execution_enabled")),
            "demoted_at": profile.get("demoted_at"),
            "expires_at": profile.get("expires_at"),
        }
        resp = requests.post(
            f"{supabase_url}/rest/v1/strategy_repair_profiles",
            headers={**headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
            timeout=12,
        )
        return resp.ok
    except Exception:
        return False


def hydrate_repair_bay_from_cloud() -> int:
    """Load benched Repair Bay profiles from Supabase on boot."""
    if st.session_state.get("repair_bay_cloud_hydrated"):
        return len(st.session_state.get("purgatory_repair_bay") or {})
    st.session_state.repair_bay_cloud_hydrated = True
    headers = _supabase_headers()
    if not headers:
        return 0
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.get(
            f"{supabase_url}/rest/v1/strategy_repair_profiles"
            "?select=profile_key,profile_json,expires_at,reminted_at"
            "&reminted_at=is.null"
            "&order=demoted_at.desc&limit=120",
            headers=headers,
            timeout=15,
        )
        if not resp.ok:
            return 0
        rows = resp.json() if isinstance(resp.json(), list) else []
    except Exception:
        return 0

    bay = dict(st.session_state.get("purgatory_repair_bay") or {})
    for row in rows:
        profile = row.get("profile_json") or {}
        profile_key = row.get("profile_key") or ""
        if isinstance(profile, dict) and profile_key and not profile.get("reminted"):
            bay[profile_key] = profile
    st.session_state.purgatory_repair_bay = bay
    return len(bay)


def purge_expired_repair_bay_cloud() -> int:
    """SQL hard-delete for Repair Bay zombies older than 60 days."""
    headers = _supabase_headers()
    if not headers:
        return 0
    cutoff = _utcnow().isoformat()
    try:
        supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
        resp = requests.delete(
            f"{supabase_url}/rest/v1/strategy_repair_profiles",
            headers=headers,
            params={"expires_at": f"lt.{cutoff}", "reminted_at": "is.null"},
            timeout=12,
        )
        return 1 if resp.ok else 0
    except Exception:
        return 0


def _vector_align_score(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return core_quantum._cosine_similarity(a, b)


def _effective_margin_from_quality(quality: dict) -> tuple[float, float, float]:
    """Return (gross_move, friction_buffer, net_margin) for elevated gate checks."""
    gross = float(quality.get("structural_move_pct") or 0.0)
    friction = float(quality.get("execution_friction_buffer_pct") or 0.0)
    net = quality.get("net_margin_pct")
    if net is None:
        net = gross - friction if friction > 0 else gross
    return gross, friction, float(net)


def _analyze_breakdown_deltas(
    benched: dict,
    *,
    metric_envelopes: dict | None,
    feature_vector: list[float] | None,
    structural_move_pct: float,
    floor_pct: float,
    net_margin_pct: float | None = None,
    execution_friction_buffer_pct: float | None = None,
) -> dict:
    """Isolate fluid variables that diverged vs the benched Historical Observation Profile."""
    snapshot_env = benched.get("metric_envelopes") or {}
    fresh_env = metric_envelopes or {}
    effective_margin = (
        float(net_margin_pct)
        if net_margin_pct is not None
        else float(structural_move_pct)
    )
    deltas: dict[str, Any] = {
        "structural_move_pct": round(float(structural_move_pct), 4),
        "net_margin_pct": round(effective_margin, 4),
        "execution_friction_buffer_pct": round(float(execution_friction_buffer_pct or 0.0), 4),
        "floor_pct": round(float(floor_pct), 4),
        "below_floor": effective_margin < floor_pct,
        "shifted_fields": [],
    }
    for field in ("volume", "velocity_pct", "spread_pct"):
        old_band = snapshot_env.get(field) or {}
        new_band = fresh_env.get(field) or {}
        if not old_band or not new_band:
            continue
        old_mid = float(old_band.get("mid") or 0.0)
        new_mid = float(new_band.get("mid") or 0.0)
        if old_mid <= 0:
            continue
        drift_pct = abs((new_mid - old_mid) / old_mid * 100)
        if drift_pct >= ENVELOPE_GAP_MAX_PCT:
            deltas["shifted_fields"].append(
                {
                    "field": field,
                    "drift_pct": round(drift_pct, 2),
                    "benched_mid": old_mid,
                    "fresh_mid": new_mid,
                }
            )
    benched_vec = benched.get("master_signature") or []
    fresh_vec = feature_vector or []
    align = _vector_align_score(benched_vec, fresh_vec)
    deltas["vector_align_score"] = round(align, 4)
    deltas["velocity_decay"] = align < RECOVERY_VECTOR_ALIGN_MIN
    return deltas


def demote_strategy_to_repair_bay(
    retro: dict,
    *,
    parent_layout_id: str,
    strategy_label: str,
    timeframe_resolution: str,
    master_signature: list[float] | None = None,
    metric_envelopes: dict | None = None,
) -> dict | None:
    """
    Track B — hands-free demotion when rolling 15-trade window breaches floor.
    Live execution stripped; read-only Historical Observation Profile in Repair Bay.
    """
    if not retro.get("halt_live_execution"):
        return None

    ensure_purgatory_hub_session()
    key = _profile_key(parent_layout_id, strategy_label, timeframe_resolution)
    now = _utcnow()
    expires = now + datetime.timedelta(days=REPAIR_BAY_MAX_DAYS)

    profile = {
        "track": PURGATORY_TRACK_REPAIR_BAY,
        "parent_layout_id": parent_layout_id,
        "strategy_label": strategy_label,
        "timeframe_resolution": timeframe_resolution,
        "timeline_key": retro.get("timeline_key", key),
        "historical_observation": True,
        "live_execution_enabled": False,
        "demoted_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "root_cause": retro.get("root_cause"),
        "recommended_action": retro.get("recommended_action"),
        "avg_margin_pct": retro.get("avg_margin_pct", 0.0),
        "floor_pct": retro.get("floor_pct", 0.0),
        "master_signature": list(master_signature or []),
        "metric_envelopes": dict(metric_envelopes or {}),
        "recovery_samples": 0,
        "recovery_tickers": [],
        "reminted": False,
        "breakdown_last": {},
    }
    st.session_state.purgatory_repair_bay[key] = profile
    st.session_state.room2_live_execution_halted = True
    sync_repair_bay_profile_to_cloud(profile)

    action = retro.get("recommended_action") or "DEMOTE"
    msg = (
        f"🔧 REPAIR BAY — {strategy_label} demoted from {parent_layout_id}. "
        f"Live execution locked · 60-day recycle window · action={action}."
    )
    events = list(st.session_state.get("purgatory_hub_events", []))
    events.insert(0, msg)
    st.session_state.purgatory_hub_events = events[:12]
    st.session_state.purgatory_shelf_active = True
    st.session_state.purgatory_shelf_message = build_hub_display_message()
    return profile


def _remint_strategy_from_repair_bay(
    key: str,
    profile: dict,
    *,
    ticker: str,
    quality: dict,
    metric_envelopes: dict | None,
    feature_vector: list[float] | None,
    entry_time: str,
    exit_time: str,
) -> dict:
    """Automated override — restored profitability re-mints strategy into parent layout."""
    ensure_purgatory_hub_session()
    merged_signature = profile.get("master_signature") or []
    fresh_vec = feature_vector or []
    if merged_signature and fresh_vec and len(merged_signature) == len(fresh_vec):
        merged_signature = [
            round((a + b) / 2.0, 6) for a, b in zip(merged_signature, fresh_vec)
        ]

    reminted = {
        **profile,
        "reminted": True,
        "live_execution_enabled": True,
        "reminted_at": _utcnow().isoformat(),
        "remint_ticker": ticker,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "structural_move_pct": quality.get("structural_move_pct"),
        "master_signature": merged_signature,
        "metric_envelopes": dict(metric_envelopes or profile.get("metric_envelopes") or {}),
    }
    st.session_state.purgatory_repair_bay.pop(key, None)
    st.session_state.room2_live_execution_halted = False
    headers = _supabase_headers()
    if headers:
        try:
            supabase_url = st.secrets["SUPABASE_URL"].rstrip("/")
            requests.patch(
                f"{supabase_url}/rest/v1/strategy_repair_profiles",
                headers=headers,
                params={"profile_key": f"eq.{key}"},
                json={
                    "reminted_at": _utcnow().isoformat(),
                    "live_execution_enabled": True,
                    "profile_json": reminted,
                },
                timeout=12,
            )
            requests.patch(
                f"{supabase_url}/rest/v1/forensic_patterns",
                headers=headers,
                params={
                    "macro_weather_layout": f"eq.{profile.get('parent_layout_id')}",
                    "execution_strategy": f"eq.{profile.get('strategy_label')}",
                    "timeframe_resolution": f"eq.{profile.get('timeframe_resolution')}",
                },
                json={"state": "active"},
                timeout=12,
            )
        except Exception:
            pass

    msg = (
        f"✅ AUTO RE-MINT — {profile.get('strategy_label')} restored to "
        f"{profile.get('parent_layout_id')} after genetic recycling "
        f"({profile.get('recovery_samples')} fresh cross-matches)."
    )
    events = list(st.session_state.get("purgatory_hub_events", []))
    events.insert(0, msg)
    st.session_state.purgatory_hub_events = events[:12]
    st.session_state.purgatory_shelf_message = build_hub_display_message()
    return reminted


def attempt_genetic_recycling_on_fresh_deploy(
    *,
    ticker: str,
    parent_layout_id: str,
    strategy_label: str,
    timeframe_resolution: str,
    quality: dict,
    metric_envelopes: dict | None = None,
    master_signature: list[float] | None = None,
    feature_vector: list[float] | None = None,
    entry_time: str = "",
    exit_time: str = "",
) -> dict | None:
    """
    Cross-reference fresh Room 2 winning data against benched Repair Bay profiles
  anchored to the same parent layout geometry (no cross-layout drift).
    """
    ensure_purgatory_hub_session()
    if not quality.get("passed"):
        return None

    coupling = st.session_state.get("room2_chart_coupling") or {}
    if not coupling.get("passed"):
        return None

    floor_pct = float(
        quality.get("floor_pct") or core_quantum.timeframe_margin_floor(timeframe_resolution)
    )
    _, friction, net_margin = _effective_margin_from_quality(quality)
    if net_margin < floor_pct:
        return None

    bay = dict(st.session_state.get("purgatory_repair_bay") or {})
    if not bay:
        return None

    ticker_up = str(ticker).strip().upper()
    for key, profile in list(bay.items()):
        if profile.get("reminted"):
            continue
        if str(profile.get("parent_layout_id")) != str(parent_layout_id):
            continue

        breakdown = _analyze_breakdown_deltas(
            profile,
            metric_envelopes=metric_envelopes,
            feature_vector=feature_vector,
            structural_move_pct=float(quality.get("structural_move_pct") or 0.0),
            floor_pct=floor_pct,
            net_margin_pct=net_margin,
            execution_friction_buffer_pct=friction,
        )
        profile["breakdown_last"] = breakdown

        align = float(breakdown.get("vector_align_score") or 0.0)
        if align < RECOVERY_VECTOR_ALIGN_MIN:
            st.session_state.purgatory_repair_bay[key] = profile
            continue

        tickers = list(profile.get("recovery_tickers") or [])
        if ticker_up in tickers:
            profile["breakdown_last"] = breakdown
            st.session_state.purgatory_repair_bay[key] = profile
            continue
        tickers.append(ticker_up)
        profile["recovery_tickers"] = tickers
        profile["recovery_samples"] = int(profile.get("recovery_samples", 0)) + 1
        st.session_state.purgatory_repair_bay[key] = profile
        sync_repair_bay_profile_to_cloud(profile)

        if profile["recovery_samples"] >= RECOVERY_SAMPLES_REQUIRED:
            if not _recovery_tickers_valid(tickers):
                msg = (
                    f"⛔ RE-MINT BLOCKED — {profile.get('strategy_label')} needs "
                    f"{RECOVERY_SAMPLES_REQUIRED} unique tickers; duplicates rejected."
                )
                events = list(st.session_state.get("purgatory_hub_events", []))
                events.insert(0, msg)
                st.session_state.purgatory_hub_events = events[:12]
                continue
            return _remint_strategy_from_repair_bay(
                key,
                profile,
                ticker=ticker_up,
                quality=quality,
                metric_envelopes=metric_envelopes,
                feature_vector=feature_vector,
                entry_time=entry_time,
                exit_time=exit_time,
            )

    return None


def purge_expired_repair_bay_profiles() -> int:
    """Anti-zombie 60-day hard limit on Track B demoted profiles."""
    ensure_purgatory_hub_session()
    purge_expired_repair_bay_cloud()
    now = _utcnow()
    removed = 0
    bay = dict(st.session_state.get("purgatory_repair_bay") or {})
    for key, profile in list(bay.items()):
        expires_raw = profile.get("expires_at")
        if not expires_raw:
            continue
        try:
            expires = datetime.datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        if now > expires and not profile.get("reminted"):
            bay.pop(key, None)
            removed += 1
    st.session_state.purgatory_repair_bay = bay
    return removed


def process_post_mortem_demotion(
    retro: dict,
    *,
    parent_layout_id: str,
    strategy_label: str,
    timeframe_resolution: str,
) -> dict | None:
    """Hook after rolling 15-trade post-mortem — auto-demote on floor breach."""
    genetic = st.session_state.get("room2_master_signature") or {}
    audit = st.session_state.get("room2_deep_research_audit") or {}
    return demote_strategy_to_repair_bay(
        retro,
        parent_layout_id=parent_layout_id,
        strategy_label=strategy_label,
        timeframe_resolution=timeframe_resolution,
        master_signature=genetic.get("master_signature"),
        metric_envelopes=audit.get("metric_envelopes"),
    )


def build_hub_display_message() -> str:
    """Two-way Purgatory hub readout — Track A incubation + Track B repair bay."""
    ensure_purgatory_hub_session()
    incubation = st.session_state.get("anomaly_incubation_registry") or {}
    track_a = len(incubation)
    bay = st.session_state.get("purgatory_repair_bay") or {}
    track_b = sum(1 for p in bay.values() if not p.get("reminted"))
    lines = [
        f"TWO-WAY PURGATORY HUB — Track A (incubation): {track_a} · "
        f"Track B (repair bay): {track_b}",
    ]
    events = st.session_state.get("purgatory_hub_events") or []
    if events:
        lines.append(events[0])
    elif track_b == 0 and track_a == 0:
        lines.append(
            "STANDBY — Sub-85% setups incubate 30 days (Track A). "
            "Floor-breached strategies auto-bench 60 days (Track B)."
        )
    return " · ".join(lines)


def sync_repair_bay_to_session_blob() -> str:
    """Compact JSON blob for optional MATRIX_META / cloud durability fallback."""
    ensure_purgatory_hub_session()
    return json.dumps(
        {
            "repair_bay": st.session_state.get("purgatory_repair_bay", {}),
            "events": st.session_state.get("purgatory_hub_events", [])[:6],
        },
        default=str,
    )
