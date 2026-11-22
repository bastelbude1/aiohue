"""Deliberate room off without a switch press: all scene lights off after activation."""

from datetime import datetime, timedelta, timezone

from scene_validator import all_expected_on_lights_switched_off
from test_off_validation_app import (
    LAMP_A, LAMP_B, SELECT, app, build_app, run_next, set_light,  # noqa: F401
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


def test_all_off_during_level2_stops_escalation(app):
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
