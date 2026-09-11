"""Hunt / Handle / Purgatoria — operator Good/Bad compile."""

import tempfile
from pathlib import Path

import room3_review_learn as rl

_tmp = Path(tempfile.mkdtemp()) / "review_learn.json"
rl.LEARN_PATH = _tmp


class _S:
    def __init__(self):
        self.layout_master_matrix_index = []
        self.room3_review_learn = rl.empty_state()
        self.room3_fill_meta_by_ticker = {}
        self.room3_repertoire_cache = None

    def get(self, k, default=None):
        return getattr(self, k, default)

    def pop(self, k, default=None):
        if hasattr(self, k):
            val = getattr(self, k)
            delattr(self, k)
            return val
        return default

    def __contains__(self, k):
        return hasattr(self, k)

    def __setitem__(self, k, v):
        setattr(self, k, v)

    def __getitem__(self, k):
        return getattr(self, k)


def _trade(i, ticker="TNON", vote_fields=None):
    row = {
        "id": f"t-{ticker}-{i}",
        "ticker": ticker,
        "strategy": "5A (1M)",
        "matrix_strategy": "5A (1M)",
        "timeframe": "1m",
        "matrix_timeframe": "1m",
        "layout_id": "L1",
        "matrix_layout": "L1",
    }
    if vote_fields:
        row.update(vote_fields)
    return row


def test_dash_card_does_not_ingest():
    ss = _S()
    out = rl.process_operator_vote(
        ss,
        {
            "id": "dash-1",
            "ticker": "TNON",
            "strategy": "Alpaca",
            "timeframe": "—",
        },
        "good",
    )
    assert out["observation"] is None
    assert rl.overlay_match_floor_delta(ss, "L1", "5A (1M)", "1m") == 0


def test_good_extra_waits_for_three():
    ss = _S()
    t = _trade(1, vote_fields={"rvol": 3.2})
    rl.process_operator_vote(ss, t, "good")
    ov = rl._overlay_for(ss, "L1", "5A (1M)", "1m")
    assert "rvol_high" not in (ov.get("traits_good") or [])
    for i in range(2, 4):
        rl.process_operator_vote(ss, _trade(i, vote_fields={"rvol": 3.2}), "good")
    ov = rl._overlay_for(ss, "L1", "5A (1M)", "1m")
    assert "rvol_high" in (ov.get("traits_good") or [])
    assert int(ov.get("match_floor_delta") or 0) == 0


def test_bad_handle_applies_immediately_limit():
    ss = _S()
    out = rl.process_operator_vote(ss, _trade(1), "bad")
    applied = [a for a in (out.get("applied") or []) if a.get("ok")]
    assert any(a.get("layer") == "handle" for a in applied)
    style = rl.resolved_order_style(ss, "5A (1M)", "1m", layout_id="L1")
    assert style == "limit"
    assert rl.overlay_match_floor_delta(ss, "L1", "5A (1M)", "1m") == 0


def test_hunt_bad_needs_two_tickers():
    ss = _S()
    rl.process_operator_vote(ss, _trade(1, "TNON"), "bad")
    rl.process_operator_vote(ss, _trade(2, "TNON"), "bad")
    ov = rl._overlay_for(ss, "L1", "5A (1M)", "1m")
    assert int(ov.get("hunt_caution") or 0) == 0
    rl.process_operator_vote(ss, _trade(3, "GELS"), "bad")
    ov = rl._overlay_for(ss, "L1", "5A (1M)", "1m")
    assert int(ov.get("hunt_caution") or 0) >= 1
    assert rl.force_patient_entry(ss, "L1", "5A (1M)", "1m") is True


if __name__ == "__main__":
    test_dash_card_does_not_ingest()
    test_good_extra_waits_for_three()
    test_bad_handle_applies_immediately_limit()
    test_hunt_bad_needs_two_tickers()
    print("ok")
