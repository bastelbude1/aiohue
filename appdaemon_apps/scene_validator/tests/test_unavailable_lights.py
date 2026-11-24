"""Unreachable lights (unavailable/unknown/missing) are skipped in scene validation."""

import pytest

from test_off_validation_app import (  # noqa: F401
    LAMP_A, LAMP_B, SCENE, SELECT, app, run_next, set_light,
)


def activate(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})


def calls(app, service):
    return [kw for s, kw in app.service_calls if s == service]


def set_ok(app, entity, brightness=255):
    set_light(app, entity, "on", 1)
    app.states[entity] = "on"
    app.full_states[entity]["attributes"] = {"brightness": brightness}


def set_off(app, entity):
    set_light(app, entity, "off", -3600)
    app.states[entity] = "off"


def set_unreachable(app, entity, state="unavailable"):
    if state is None:
        app.full_states.pop(entity, None)
        app.states.pop(entity, None)
        return
    set_light(app, entity, state, 1)
    app.states[entity] = state


def spy_records(app):
    rec = {"success": 0, "failure": 0}
    app.record_success = lambda: rec.__setitem__("success", rec["success"] + 1)
    app.record_failure = lambda: rec.__setitem__("failure", rec["failure"] + 1)
    return rec


def has_log(app, text):
    return any(text in m for _l, m in app.logs)


def test_unavailable_light_is_skipped_and_scene_passes(app):
    set_ok(app, LAMP_A)
    set_unreachable(app, LAMP_B)
    activate(app)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert app.service_calls == []
    assert has_log(app, "[OK] Validation successful")
    assert has_log(app, f"[{SCENE}] [SKIP] {LAMP_B} unavailable - not validated")


@pytest.mark.parametrize("state", ["unknown", None])
def test_unknown_or_missing_light_is_skipped(app, state):
    set_ok(app, LAMP_A)
    set_unreachable(app, LAMP_B, state)
    activate(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, "[OK] Validation successful")
    assert has_log(app, f"[SKIP] {LAMP_B} unavailable - not validated")


def test_all_lights_unavailable_no_escalation_no_record(app):
    rec = spy_records(app)
    set_unreachable(app, LAMP_A)
    set_unreachable(app, LAMP_B, "unknown")
    activate(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, "[SKIP] all scene lights unavailable")
    assert rec == {"success": 0, "failure": 0}


def test_dynamic_scene_unavailable_light_is_skipped(app):
    app.attributes[SCENE] = {"is_dynamic": True}
    set_ok(app, LAMP_A, 20)
    set_unreachable(app, LAMP_B)
    activate(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, "[OK] Validation successful")
    assert has_log(app, f"[SKIP] {LAMP_B} unavailable - not validated")


@pytest.mark.parametrize("dynamic", [False, True])
def test_level3_never_controls_unavailable_light(app, dynamic):
    app.attributes[SCENE] = {"is_dynamic": dynamic}
    set_off(app, LAMP_A)
    set_unreachable(app, LAMP_B)
    activate(app)

    app.run_scheduled()

    commanded = [kw.get("entity_id") for s, kw in app.service_calls if s.startswith("light/")]
    assert commanded
    assert set(commanded) == {LAMP_A}
    assert has_log(app, f"[SKIP] {LAMP_B} unavailable - not validated")


@pytest.mark.parametrize("on_off_only", [False, True])
def test_control_skips_unreachable_directly(app, on_off_only):
    set_off(app, LAMP_A)
    set_unreachable(app, LAMP_B, "unknown")
    scene_data = app.find_scene_in_inventory(SCENE)

    assert app.control_lights_individually(scene_data, on_off_only=on_off_only) is True

    assert {kw["entity_id"] for _s, kw in app.service_calls} == {LAMP_A}


def test_real_failure_still_escalates_with_unavailable_present(app):
    set_ok(app, LAMP_A, 20)
    set_unreachable(app, LAMP_B)
    activate(app)

    run_next(app, "perform_scene_validation")

    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]


def test_control_skip_log_uses_scene_entity(app):
    set_off(app, LAMP_A)
    set_unreachable(app, LAMP_B)
    app.control_lights_individually(app.find_scene_in_inventory(SCENE), scene_entity=SCENE)
    assert has_log(app, f"[{SCENE}] [SKIP] {LAMP_B} unavailable - not validated")
