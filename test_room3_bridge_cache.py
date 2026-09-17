"""Room 3 vault gulp is memoized so reconnects don't wait on Supabase twice."""

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


def test_second_vault_fetch_does_not_hit_network():
    rows = [{"macro_weather_layout": "1", "ticker": "FAMI"}]
    with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
        with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
            with patch.object(b.requests, "get", return_value=_Resp(rows)) as get:
                first = b._fetch_vault_rows()
                second = b._fetch_vault_rows()
    assert first == rows
    assert second is first
    assert get.call_count == 1
    assert get.call_args.kwargs.get("timeout") == b.VAULT_FETCH_TIMEOUT_SEC


def test_failed_network_falls_back_to_cache_file(tmp_path, monkeypatch):
    cache = tmp_path / "matrix_vault_cache.json"
    cache.write_text('{"patterns": [{"macro_weather_layout": "2", "ticker": "BIAF"}]}', encoding="utf-8")
    monkeypatch.setattr(b, "CACHE_PATH", cache)
    with patch.object(b, "_load_secrets", return_value={"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "k"}):
        with patch.object(b, "_supabase_headers", return_value={"apikey": "k"}):
            with patch.object(b.requests, "get", side_effect=TimeoutError("slow")):
                out = b._fetch_vault_rows()
    assert out[0]["ticker"] == "BIAF"
