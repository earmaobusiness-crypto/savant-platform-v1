"""Room 3 vault gulp is memoized so reconnects don't wait on Supabase twice."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import room3_bridge as b


class _Resp:
    def __init__(self, rows):
        self.ok = True
        self._rows = rows

    def json(self):
        return self._rows


def setup_function():
    b._reset_vault_rows_mem()


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fresh_ts() -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=2))


def _stale_ts() -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(hours=169))


def test_centroid_window_is_168_hours():
    assert b.CENTROID_WINDOW_SEC == 604800
    assert b.CENTROID_WINDOW_SEC // 3600 == 168


def test_second_vault_fetch_does_not_hit_network():
    rows = [{"macro_weather_layout": "1", "ticker": "FAMI", "timestamp": _fresh_ts()}]
    with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
        with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
            with patch.object(b.requests, "get", return_value=_Resp(rows)) as get:
                first = b._fetch_vault_rows()
                second = b._fetch_vault_rows()
    assert first == rows
    assert second is first
    assert get.call_count == 1
    assert get.call_args.kwargs.get("timeout") == b.VAULT_FETCH_TIMEOUT_SEC
    url = str(get.call_args.args[0])
    assert "timestamp" in url
    assert "timestamp=gte." in url


def test_fetch_drops_rows_outside_168h_before_ram():
    fresh = {"macro_weather_layout": "1", "ticker": "FAMI", "timestamp": _fresh_ts()}
    stale = {"macro_weather_layout": "1", "ticker": "OLD", "timestamp": _stale_ts()}
    with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
        with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
            with patch.object(b.requests, "get", return_value=_Resp([fresh, stale])):
                out = b._fetch_vault_rows()
    assert [r["ticker"] for r in out] == ["FAMI"]


def test_failed_network_falls_back_to_cache_file():
    b._reset_vault_rows_mem()
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "matrix_vault_cache.json"
        cache.write_text(
            json.dumps(
                {
                    "patterns": [
                        {
                            "macro_weather_layout": "2",
                            "ticker": "BIAF",
                            "timestamp": _fresh_ts(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch.object(b, "CACHE_PATH", cache):
            with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
                with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
                    with patch.object(b.requests, "get", side_effect=TimeoutError("slow")):
                        out = b._fetch_vault_rows()
        assert out[0]["ticker"] == "BIAF"


def test_cache_fallback_starves_stale_rows():
    b._reset_vault_rows_mem()
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "matrix_vault_cache.json"
        cache.write_text(
            json.dumps(
                {
                    "patterns": [
                        {
                            "macro_weather_layout": "2",
                            "ticker": "OLD",
                            "timestamp": _stale_ts(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with patch.object(b, "CACHE_PATH", cache):
            with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
                with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
                    with patch.object(b.requests, "get", side_effect=TimeoutError("slow")):
                        out = b._fetch_vault_rows()
        assert out == []


def test_aggregate_starves_bucket_with_no_in_window_saves():
    sig = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.1]
    stale = {
        "macro_weather_layout": "1",
        "execution_strategy": "1A (1M)",
        "timeframe_resolution": "1m",
        "master_signature_json": {"master_signature": sig},
        "timestamp": _stale_ts(),
        "structural_move_pct": 12.0,
    }
    assert b._aggregate_rows_into_layouts([stale]) == []


def test_aggregate_stamps_window_and_in_window_pattern_count():
    sig = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0, 0.1]
    fresh = {
        "macro_weather_layout": "1",
        "execution_strategy": "1A (1M)",
        "timeframe_resolution": "1m",
        "master_signature_json": {"master_signature": sig},
        "timestamp": _fresh_ts(),
        "structural_move_pct": 12.0,
    }
    stale = {
        **fresh,
        "timestamp": _stale_ts(),
        "ticker": "OLD",
    }
    layouts = b._aggregate_rows_into_layouts([fresh, stale])
    assert len(layouts) == 1
    entry = layouts[0]
    assert int(entry["window_hours"]) == 168
    assert int(entry["pattern_count"]) == 1
    assert str(entry["window_start"]).endswith("Z")
    assert entry["vector"][:8] == sig
