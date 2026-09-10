"""Cloud pulse — Arm+belt keeps trading after the tab dies."""

import room3_pulse


def _reset_bag(data=None):
    room3_pulse._BAG = room3_pulse.PulseState(data or {})
    return room3_pulse._BAG


def test_pulse_state_duck_types_session():
    ss = room3_pulse.PulseState()
    ss.room3_lots = [{"ticker": "MIMI", "qty": 10}]
    ss["room3_cash_claimed"] = 0.0
    assert ss.get("room3_lots")[0]["ticker"] == "MIMI"
    assert "room3_cash_claimed" in ss
    assert ss.room3_cash_claimed == 0.0


def test_mark_unattended_requires_arm_and_belt():
    _reset_bag()
    ss = room3_pulse.PulseState(
        {
            "room3_engine_armed": True,
            "room3_kill_flat": False,
            "room3_filter_universe": ["GELS"],
        }
    )
    room3_pulse.mark_unattended(ss)
    assert ss.get("room3_unattended_armed") is True
    assert room3_pulse.bag().get("room3_unattended_armed") is True
    assert room3_pulse.bag().get("room3_engine_armed") is True


def test_fresh_disarmed_session_does_not_kill_live_pulse():
    _reset_bag(
        {
            "room3_unattended_armed": True,
            "room3_engine_armed": True,
            "room3_filter_universe": ["GELS", "MIMI"],
        }
    )
    fresh = room3_pulse.PulseState(
        {
            "room3_engine_armed": False,
            "room3_kill_flat": False,
            "room3_unattended_armed": False,
            "room3_filter_universe": [],
        }
    )
    room3_pulse.mark_unattended(fresh)
    assert room3_pulse.bag().get("room3_unattended_armed") is True
    assert room3_pulse.bag().get("room3_filter_universe") == ["GELS", "MIMI"]


def test_operator_disarm_stops_unattended():
    _reset_bag(
        {
            "room3_unattended_armed": True,
            "room3_engine_armed": True,
            "room3_filter_universe": ["SPWR"],
        }
    )
    ss = room3_pulse.PulseState(
        {
            "room3_engine_armed": False,
            "room3_kill_flat": False,
            "room3_unattended_armed": True,
            "room3_filter_universe": ["SPWR"],
        }
    )
    room3_pulse.mark_unattended(ss)
    assert ss.get("room3_unattended_armed") is False
    assert room3_pulse.bag().get("room3_unattended_armed") is False
    assert room3_pulse.bag().get("room3_engine_armed") is False


def test_kill_stops_unattended():
    _reset_bag()
    ss = room3_pulse.PulseState(
        {
            "room3_engine_armed": True,
            "room3_kill_flat": True,
            "room3_filter_universe": ["GIPR"],
        }
    )
    room3_pulse.mark_unattended(ss)
    assert ss.get("room3_unattended_armed") is False
    assert room3_pulse.bag().get("room3_engine_armed") is False


def test_session_must_be_flat_when_closed():
    ss = room3_pulse.PulseState(
        {"room3_allowed_sessions": ["rth", "postmarket"]}
    )
    # Weekend or after 20:00 ET is SESSION_CLOSED — do not assert clock.
    # Post-off must flatten in post.
    ss.room3_allowed_sessions = ["rth"]
    import room3_engine

    if room3_engine.detect_session_window() == room3_engine.SESSION_POST:
        assert room3_pulse._session_must_be_flat(ss) is True
    if room3_engine.detect_session_window() == room3_engine.SESSION_CLOSED:
        assert room3_pulse._session_must_be_flat(ss) is True


if __name__ == "__main__":
    test_pulse_state_duck_types_session()
    test_mark_unattended_requires_arm_and_belt()
    test_fresh_disarmed_session_does_not_kill_live_pulse()
    test_operator_disarm_stops_unattended()
    test_kill_stops_unattended()
    test_session_must_be_flat_when_closed()
    print("ok")
