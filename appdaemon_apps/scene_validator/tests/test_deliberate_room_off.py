"""Deliberate room off without a switch press: all scene lights off after activation."""

from datetime import datetime, timedelta, timezone

from scene_validator import all_expected_on_lights_switched_off
from test_off_validation_app import (
    LAMP_A, LAMP_B, SELECT, ambiguous_app, app, build_app, press, run_next, set_light,  # noqa: F401
)

T0 = datetime(2026, 11, 22, 18, 0, 0, tzinfo=timezone.utc)
A, B = "light.lamp_a", "light.lamp_b"


def light(state, offset):
    return {"state": state, "last_updated": T0 + timedelta(seconds=offset)}


# --- pure helper -------------------------------------------------------------

def test_helper_true_when_all_expected_on_lights_changed_to_off():
    assert all_expected_on_lights_switched_off(
        [A, B], {A: light("off", 1), B: light("off", 2)}, T0) is True


def test_helper_false_when_one_light_still_on():
    assert all_expected_on_lights_switched_off(
        [A, B], {A: light("off", 1), B: light("on", 2)}, T0) is False


def test_helper_false_when_off_light_unchanged_since_activation():
    assert all_expected_on_lights_switched_off(
        [A, B], {A: light("off", 1), B: light("off", -60)}, T0) is False


def test_helper_false_when_light_missing_or_unavailable():
    assert all_expected_on_lights_switched_off([A, B], {A: light("off", 1)}, T0) is False
    assert all_expected_on_lights_switched_off(
        [A, B], {A: light("off", 1), B: light("unavailable", 1)}, T0) is False


def test_helper_false_when_no_expected_on_lights():
    assert all_expected_on_lights_switched_off([], {A: light("off", 1)}, T0) is False


def test_helper_boundary_last_updated_equals_activation():
    assert all_expected_on_lights_switched_off([A], {A: light("off", 0)}, T0) is True


# --- app level ---------------------------------------------------------------

def activate(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})


def scene_turn_ons(app):
    return [kw for s, kw in app.service_calls if s == "scene/turn_on"]


def light_turn_ons(app):
    return [kw for s, kw in app.service_calls if s == "light/turn_on"]


def skip_logs(app):
    return [m for _l, m in app.logs if "[SKIP]" in m and "deliberate room off" in m]


def test_scene_then_all_lights_off_without_press_is_not_retriggered(app):
    activate(app)
    set_light(app, LAMP_A, "off", 1)
    set_light(app, LAMP_B, "off", 2)

    app.run_scheduled()

    assert scene_turn_ons(app) == []
    assert light_turn_ons(app) == []
    assert skip_logs(app)
    assert not any("[FAIL]" in m for _l, m in app.logs)


def test_scene_then_one_light_off_is_still_retriggered(app):
    activate(app)
    set_light(app, LAMP_A, "on", 1)
    set_light(app, LAMP_B, "off", 2)

    app.run_scheduled()

    assert scene_turn_ons(app)
    assert skip_logs(app) == []


def test_scene_missed_by_all_lights_is_still_retriggered(app):
    activate(app)
    set_light(app, LAMP_A, "off", -3600)
    set_light(app, LAMP_B, "off", -3600)

    app.run_scheduled()

    assert scene_turn_ons(app)
    assert skip_logs(app) == []


def spy_records(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "record_failure", lambda: calls.append("failure"))
    monkeypatch.setattr(app, "record_success", lambda: calls.append("success"))
    return calls


def test_all_off_during_level2_stops_escalation(app, monkeypatch):
    records = spy_records(app, monkeypatch)
    activate(app)
    set_light(app, LAMP_A, "on", 1)
    set_light(app, LAMP_B, "off", 2)
    run_next(app, "perform_scene_validation")
    assert scene_turn_ons(app)

    set_light(app, LAMP_A, "off", 3)
    set_light(app, LAMP_B, "off", 3)
    app.run_scheduled()

    assert light_turn_ons(app) == []
    assert skip_logs(app)
    assert records == []


def test_all_off_before_level3_stops_control(app, monkeypatch):
    records = spy_records(app, monkeypatch)
    activate(app)
    set_light(app, LAMP_A, "on", 1)
    set_light(app, LAMP_B, "off", 2)
    run_next(app, "perform_scene_validation")
    run_next(app, "perform_level2_validation")   # still failing: schedules Level 3
    assert any(name == "perform_level3_control" for name, _d, _kw in app.scheduled)
    assert light_turn_ons(app) == []

    set_light(app, LAMP_A, "off", 3)
    set_light(app, LAMP_B, "off", 3)
    run_next(app, "perform_level3_control")

    assert light_turn_ons(app) == []
    assert any("Level 3 control" in m for m in skip_logs(app))
    assert records == []


def test_deferred_scene_step_keeps_activated_at(ambiguous_app):
    app = ambiguous_app
    press(app)                                   # pending switch-press off check
    activate(app)
    activated = app.now

    run_next(app, "perform_scene_validation")    # deferred while the off check is pending

    deferred = [kw for name, _d, kw in app.scheduled if name == "perform_scene_validation"][-1]
    assert deferred.get("off_deferred") is True
    assert deferred["activated_at"] == activated
