"""
Matrix vault bridge — single Supabase config + local durability cache.

Supabase is the source of truth when configured. The local cache keeps
patterns/chat across refresh when cloud is offline or misconfigured.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

MATRIX_CHAT_LOG_TICKER = "_LAB_SESSION_"
MATRIX_CHAT_LOG_CATEGORY = "MATRIX_CHAT_LOG"
CACHE_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent
PROJECT_SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"
CACHE_PATH = PROJECT_ROOT / ".streamlit" / "matrix_vault_cache.json"
_PROJECT_SECRETS_CACHE: dict[str, str] | None = None


def _load_project_secrets() -> dict[str, str]:
    global _PROJECT_SECRETS_CACHE
    if _PROJECT_SECRETS_CACHE is not None:
        return _PROJECT_SECRETS_CACHE
    secrets: dict[str, str] = {}
    try:
        if PROJECT_SECRETS_PATH.is_file():
            for line in PROJECT_SECRETS_PATH.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                name, value = stripped.split("=", 1)
                secrets[name.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    _PROJECT_SECRETS_CACHE = secrets
    return secrets


def _secret_or_env(key: str, default: str = "") -> str:
    try:
        import streamlit as st

        val = st.secrets.get(key, default)
        if val not in (None, ""):
            return str(val).strip()
    except Exception:
        pass
    project_val = _load_project_secrets().get(key, "")
    if project_val not in (None, ""):
        return str(project_val).strip()
    return str(os.environ.get(key, default) or "").strip()


def _normalize_supabase_url(url: str) -> str:
    """Accept API URL, dashboard URL, or bare project ref — return project root."""
    clean = str(url or "").strip().strip('"').strip("'").rstrip("/")
    if not clean:
        return ""
    host_match = re.search(r"(https?://[a-z0-9]+\.supabase\.co)", clean, flags=re.IGNORECASE)
    if host_match:
        clean = host_match.group(1)
    elif "supabase.com/dashboard" in clean:
        match = re.search(r"/project/([a-z0-9]+)", clean, flags=re.IGNORECASE)
        if match:
            clean = f"https://{match.group(1)}.supabase.co"
    elif re.fullmatch(r"[a-z0-9]{8,32}", clean, flags=re.IGNORECASE):
        clean = f"https://{clean}.supabase.co"
    clean = re.sub(r"/rest/v1/?$", "", clean, flags=re.IGNORECASE).rstrip("/")
    return clean


def supabase_settings() -> dict[str, Any]:
    url = _normalize_supabase_url(_secret_or_env("SUPABASE_URL"))
    key = _secret_or_env("SUPABASE_KEY")
    table = _secret_or_env("SUPABASE_PATTERN_TABLE", "forensic_patterns") or "forensic_patterns"
    raw_url = _secret_or_env("SUPABASE_URL")
    url_misconfigured = bool(
        raw_url
        and (
            "supabase.com/dashboard" in raw_url
            or raw_url.rstrip("/").lower().endswith("/rest/v1")
            or (
                ".supabase.co" not in raw_url
                and not re.fullmatch(r"[a-z0-9]{8,32}", raw_url.strip(), flags=re.IGNORECASE)
            )
        )
    )
    return {
        "url": url,
        "key": key,
        "table": table,
        "ready": bool(url and key and ".supabase.co" in url),
        "missing": [name for name, val in (("SUPABASE_URL", url), ("SUPABASE_KEY", key)) if not val],
        "url_misconfigured": url_misconfigured,
        "raw_url": raw_url,
    }


def supabase_headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def supabase_status_message() -> str:
    cfg = supabase_settings()
    if cfg["ready"]:
        return f"Supabase connected · table `{cfg['table']}`"
    missing = ", ".join(cfg.get("missing") or ["SUPABASE_URL", "SUPABASE_KEY"])
    return (
        f"Supabase **not configured** — add {missing} to `.streamlit/secrets.toml` "
        f"(Dashboard → Project Settings → API). Patterns cannot persist to cloud until then."
    )


def _extract_raw_operator_notes(operator_context: str) -> str:
    """Strip auto-injected matrix blobs — compare only operator-typed notes."""
    ctx = str(operator_context or "").strip()
    for marker in (" | DAY_CONTEXT:", "DAY_CONTEXT:", " | TEXT_MATRIX|", "TEXT_MATRIX|", " | TRUST_TIER:", "MATRIX_META:"):
        if marker in ctx:
            ctx = ctx.split(marker)[0]
    return ctx.strip()


def _norm_vault_coord(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value or "").strip()


def _norm_vault_time(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def vault_pattern_fingerprint(
    *,
    ticker: str,
    entry_coordinate: Any = "",
    exit_coordinate: Any = "",
    entry_time: str = "",
    exit_time: str = "",
    timeframe_resolution: str = "",
    macro_weather_layout: str = "",
    execution_strategy: str = "",
    pattern_category: str = "",
    raw_operator_notes: str = "",
) -> str:
    """Identity key for duplicate deploy detection — same inputs = same pattern."""
    parts = [
        str(ticker or "").strip().upper(),
        _norm_vault_coord(entry_coordinate),
        _norm_vault_coord(exit_coordinate),
        _norm_vault_time(entry_time),
        _norm_vault_time(exit_time),
        str(timeframe_resolution or "").strip(),
        str(macro_weather_layout or "").strip().upper(),
        str(execution_strategy or "").strip().upper(),
        str(pattern_category or "VALIDATED").strip().upper(),
        str(raw_operator_notes or "").strip(),
    ]
    return "|".join(parts)


def vault_fingerprint_from_row(row: dict) -> str:
    raw_notes = str(row.get("_raw_operator_notes") or "").strip()
    if not raw_notes:
        raw_notes = _extract_raw_operator_notes(str(row.get("operator_context") or ""))
    return vault_pattern_fingerprint(
        ticker=str(row.get("ticker") or ""),
        entry_coordinate=row.get("entry_coordinate"),
        exit_coordinate=row.get("exit_coordinate"),
        entry_time=str(row.get("entry_time") or ""),
        exit_time=str(row.get("exit_time") or ""),
        timeframe_resolution=str(row.get("timeframe_resolution") or row.get("timeframe") or ""),
        macro_weather_layout=str(row.get("macro_weather_layout") or ""),
        execution_strategy=str(row.get("execution_strategy") or ""),
        pattern_category=str(row.get("pattern_category") or row.get("pattern_type") or ""),
        raw_operator_notes=raw_notes,
    )


def find_active_vault_duplicate(payload: dict, *, raw_operator_notes: str = "") -> dict | None:
    """Return an existing active vault row with the same forensic fingerprint, if any."""
    fingerprint = vault_pattern_fingerprint(
        ticker=str(payload.get("ticker") or ""),
        entry_coordinate=payload.get("entry_coordinate"),
        exit_coordinate=payload.get("exit_coordinate"),
        entry_time=str(payload.get("entry_time") or ""),
        exit_time=str(payload.get("exit_time") or ""),
        timeframe_resolution=str(payload.get("timeframe_resolution") or payload.get("timeframe") or ""),
        macro_weather_layout=str(payload.get("macro_weather_layout") or ""),
        execution_strategy=str(payload.get("execution_strategy") or ""),
        pattern_category=str(payload.get("pattern_category") or payload.get("pattern_type") or ""),
        raw_operator_notes=raw_operator_notes,
    )
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        return None

    for entry in load_local_cache().get("patterns") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ticker") or "").upper() != ticker:
            continue
        if str(entry.get("fingerprint") or "") == fingerprint:
            return {"ticker": ticker, "source": "local_cache", "fingerprint": fingerprint}

    cfg = supabase_settings()
    if not cfg["ready"]:
        return None
    status, body, err = supabase_rest(
        "GET",
        "",
        params=(
            f"?ticker=eq.{ticker}"
            f"&select=id,ticker,entry_coordinate,exit_coordinate,entry_time,exit_time,"
            f"timeframe_resolution,macro_weather_layout,execution_strategy,pattern_category,"
            f"pattern_type,operator_context,state"
            f"&order=timestamp.desc&limit=30"
        ),
        timeout=12,
    )
    if not status or err or not isinstance(body, list):
        return None
    for row in body:
        if not isinstance(row, dict):
            continue
        if str(row.get("state") or "").strip().lower() == "soft_deleted":
            continue
        if vault_fingerprint_from_row(row) == fingerprint:
            return row
    return None


def _empty_cache() -> dict:
    return {
        "v": CACHE_VERSION,
        "patterns": [],
        "chat_messages": [],
        "deploy_snapshot": {},
        "deploy_registry": [],
        "terminal": "",
        "updated_at": None,
    }


def load_local_cache() -> dict:
    try:
        if CACHE_PATH.is_file():
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return _empty_cache()


def save_local_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = dict(cache or {})
        cache["v"] = CACHE_VERSION
        cache["updated_at"] = datetime.now(timezone.utc).isoformat()
        CACHE_PATH.write_text(json.dumps(cache, default=str, indent=2), encoding="utf-8")
    except Exception:
        pass


def append_local_pattern(entry: dict) -> None:
    ticker = str(entry.get("ticker") or "").strip().upper()
    if not ticker or ticker == MATRIX_CHAT_LOG_TICKER:
        return
    fingerprint = str(entry.get("fingerprint") or "").strip()
    cache = load_local_cache()
    patterns = [row for row in (cache.get("patterns") or []) if isinstance(row, dict)]
    if fingerprint:
        patterns = [
            row
            for row in patterns
            if str(row.get("fingerprint") or "") != fingerprint
        ]
    else:
        patterns = [
            row
            for row in patterns
            if not (
                str(row.get("ticker") or "").upper() == ticker
                and str(row.get("saved_at") or "")[:16] == str(entry.get("saved_at") or "")[:16]
            )
        ]
    patterns.append(dict(entry))
    cache["patterns"] = patterns[-80:]
    save_local_cache(cache)


def clear_local_vault_cache(*, patterns: bool = True, deploy_registry: bool = True) -> None:
    """Wipe local pattern backup — used when operator clears the matrix vault."""
    cache = load_local_cache()
    if patterns:
        cache["patterns"] = []
    if deploy_registry:
        cache["deploy_registry"] = []
        cache["deploy_snapshot"] = {}
    save_local_cache(cache)


def remove_latest_local_pattern(*, ticker: str | None = None) -> bool:
    """Drop the most recent local backup row — optional ticker filter."""
    cache = load_local_cache()
    patterns = [row for row in (cache.get("patterns") or []) if isinstance(row, dict)]
    if not patterns:
        return False
    want = str(ticker or "").strip().upper()
    if want:
        for idx in range(len(patterns) - 1, -1, -1):
            row = patterns[idx]
            if str(row.get("ticker") or "").strip().upper() == want:
                patterns.pop(idx)
                cache["patterns"] = patterns
                save_local_cache(cache)
                return True
        return False
    patterns.pop()
    cache["patterns"] = patterns
    save_local_cache(cache)
    return True


def sync_local_lab_state(
    *,
    chat_messages: list | None = None,
    deploy_snapshot: dict | None = None,
    deploy_registry: list | None = None,
    terminal: str | None = None,
) -> None:
    cache = load_local_cache()
    if chat_messages is not None:
        cache["chat_messages"] = list(chat_messages)[-80:]
    if deploy_snapshot is not None:
        cache["deploy_snapshot"] = dict(deploy_snapshot)
    if deploy_registry is not None:
        cache["deploy_registry"] = list(deploy_registry)[-40:]
    if terminal is not None:
        cache["terminal"] = str(terminal)[:12000]
    save_local_cache(cache)


def local_pattern_rows() -> list[dict]:
    cache = load_local_cache()
    rows: list[dict] = []
    for entry in cache.get("patterns") or []:
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "macro_weather_layout": entry.get("layout"),
                "execution_strategy": entry.get("strategy"),
                "timeframe_resolution": entry.get("timeframe"),
                "structural_move_pct": entry.get("structural_move"),
                "timestamp": entry.get("saved_at"),
                "_source": "local_cache",
            }
        )
    return rows


def supabase_rest(
    method: str,
    path: str,
    *,
    params: str = "",
    json_body: Any = None,
    prefer: str | None = None,
    timeout: int = 12,
) -> tuple[int, Any, str | None]:
    cfg = supabase_settings()
    if not cfg["ready"]:
        return 0, None, "supabase_not_configured"
    headers = supabase_headers(cfg["key"])
    if prefer:
        headers["Prefer"] = prefer
    url = f"{cfg['url']}/rest/v1/{cfg['table']}{path}{params}"
    try:
        resp = requests.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
        body: Any
        if resp.text:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
        else:
            body = None
        err = None if resp.ok else f"HTTP {resp.status_code}: {str(body)[:240]}"
        return resp.status_code, body, err
    except Exception as exc:
        return 0, None, str(exc)


def supabase_probe() -> tuple[bool, str | None]:
    """Quick read test — returns (ok, error_message)."""
    status, body, err = supabase_rest(
        "GET",
        "",
        params="?select=ticker&limit=1",
        timeout=10,
    )
    if status and 200 <= status < 300:
        return True, None
    if err and ("<!DOCTYPE html>" in str(err) or "data-next-head" in str(err)):
        resolved = supabase_settings().get("url") or "unknown"
        return False, (
            f"wrong SUPABASE_URL in secrets (resolved to `{resolved}`). "
            "Set SUPABASE_URL = \"https://lvjfurlinzxzgczwoitp.supabase.co\" "
            "in Streamlit Cloud → Settings → Secrets."
        )
    return False, err or f"HTTP {status}"


def supabase_fetch_raw_rows(*, limit: int = 100) -> tuple[list[dict], str | None]:
    """Unfiltered table pull for inventory + trash counts."""
    status, body, err = supabase_rest(
        "GET",
        "",
        params=f"?select=*&order=timestamp.desc&limit={int(limit)}",
        timeout=12,
    )
    if not status or err:
        if err and ("<!DOCTYPE html>" in str(err) or "data-next-head" in str(err)):
            resolved = supabase_settings().get("url") or "unknown"
            return [], (
                f"wrong SUPABASE_URL in secrets (resolved to `{resolved}`). "
                "Set SUPABASE_URL = \"https://lvjfurlinzxzgczwoitp.supabase.co\" "
                "in Streamlit Cloud → Settings → Secrets."
            )
        return [], err
    if not isinstance(body, list):
        return [], "invalid_response"
    return body, None


def supabase_fetch_patterns(*, limit: int = 50) -> tuple[list[dict], str | None]:
    rows, err = supabase_fetch_raw_rows(limit=int(limit))
    if err:
        return [], err
    filtered: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == MATRIX_CHAT_LOG_TICKER:
            continue
        if str(row.get("pattern_category") or "").strip().upper() == MATRIX_CHAT_LOG_CATEGORY:
            continue
        if str(row.get("state") or "").strip().lower() == "soft_deleted":
            continue
        filtered.append(row)
    return filtered, None


def supabase_write_pattern(payload: dict) -> tuple[bool, str]:
    status, body, err = supabase_rest("POST", "", json_body=[payload], prefer="return=minimal")
    if status and 200 <= status < 300:
        return True, "INTERNET VAULT SYNC CONFIRMED"
    return False, err or f"write_failed:{body}"


def supabase_sync_chat_blob(chat_blob: str, terminal_snapshot: str) -> tuple[bool, str | None]:
    payload = {
        "ticker": MATRIX_CHAT_LOG_TICKER,
        "pattern_category": MATRIX_CHAT_LOG_CATEGORY,
        "operator_context": chat_blob,
        "quantum_report": terminal_snapshot[:12000],
        "source_room": "forensic_pattern_lab",
        "state": "active",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    status, body, err = supabase_rest(
        "GET",
        "",
        params=(
            f"?ticker=eq.{MATRIX_CHAT_LOG_TICKER}"
            f"&pattern_category=eq.{MATRIX_CHAT_LOG_CATEGORY}"
            f"&select=id&order=timestamp.desc&limit=1"
        ),
    )
    if status and 200 <= status < 300 and isinstance(body, list) and body:
        row_id = body[0].get("id")
        patch_status, _, patch_err = supabase_rest(
            "PATCH",
            "",
            params=f"?id=eq.{row_id}",
            json_body=payload,
            prefer="return=minimal",
        )
        ok = bool(patch_status and 200 <= patch_status < 300)
        return ok, patch_err
    post_status, _, post_err = supabase_rest(
        "POST",
        "",
        json_body=[payload],
        prefer="return=minimal",
    )
    ok = bool(post_status and 200 <= post_status < 300)
    return ok, post_err


def supabase_load_chat_blob() -> tuple[str, str, str | None]:
    status, body, err = supabase_rest(
        "GET",
        "",
        params=(
            f"?ticker=eq.{MATRIX_CHAT_LOG_TICKER}"
            f"&pattern_category=eq.{MATRIX_CHAT_LOG_CATEGORY}"
            f"&select=operator_context,quantum_report,timestamp"
            f"&order=timestamp.desc&limit=1"
        ),
    )
    if not status or err or not isinstance(body, list) or not body:
        return "", "", err
    row = body[0] if isinstance(body[0], dict) else {}
    return (
        str(row.get("operator_context") or ""),
        str(row.get("quantum_report") or ""),
        None,
    )
