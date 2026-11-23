"""Dynamic scenes (is_dynamic) are validated and corrected on/off only."""

from datetime import timedelta

from test_off_validation_app import (  # noqa: F401
    LAMP_A, LAMP_B, SCENE, SELECT, ambiguous_app, app, press, run_next, set_light,
)


def activate(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})


def calls(app, service):
    return [kw for s, kw in app.service_calls if s == service]


def set_off(app, entity, offset=-3600):
    set_light(app, entity, "off", offset)
    app.states[entity] = "off"


def set_brightness(app, entity, brightness, offset=1):
    set_light(app, entity, "on", offset)
    app.states[entity] = "on"
    app.full_states[entity]["attributes"] = {"brightness": brightness}


def make_dynamic(app, value=True):
    app.attributes[SCENE] = {"is_dynamic": value}


def test_dynamic_scene_wrong_brightness_is_ok(app):
    make_dynamic(app)
    activate(app)
    set_brightness(app, LAMP_A, 20)
    set_brightness(app, LAMP_B, 30)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert calls(app, "light/turn_on") == []
    assert any("[OK] Validation successful" in m for _l, m in app.logs)
    assert any(m.endswith("[INFO] Dynamic scene - checking on/off only") for _l, m in app.logs)


def test_dynamic_scene_lamp_off_is_retriggered(app):
    make_dynamic(app)
    activate(app)
    set_brightness(app, LAMP_A, 20)
    set_off(app, LAMP_B)

    run_next(app, "perform_scene_validation")

    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]


def test_dynamic_scene_level3_switches_on_without_color(app):
    make_dynamic(app)
    activate(app)
    set_brightness(app, LAMP_A, 20)
    set_off(app, LAMP_B)

    app.run_scheduled()

    turn_ons = calls(app, "light/turn_on")
    assert turn_ons == [{"entity_id": LAMP_B}]
    assert calls(app, "light/turn_off") == []


def test_static_scene_wrong_brightness_still_fails(app):
    for attrs in ({"is_dynamic": False}, {}):
        app.service_calls.clear()
        app.attributes[SCENE] = attrs
        app.last_validation_failures = []
        set_brightness(app, LAMP_A, 20)
        set_brightness(app, LAMP_B, 255)
        scene_data = app.find_scene_in_inventory(SCENE)

        assert app.validate_scene_state(SCENE, scene_data) is False
        assert "brightness" in app.last_validation_failures

    activate(app)
    app.run_scheduled()
    assert calls(app, "scene/turn_on")
    assert calls(app, "light/turn_on")[0].get("brightness")


def test_dynamic_scene_expected_off_light_on_is_switched_off_in_level3(app):
    make_dynamic(app)
    inv_scene = app.find_scene_in_inventory(SCENE)
    inv_scene["actions"][1]["action"] = {"on": {"on": False}}
    activate(app)
    set_brightness(app, LAMP_A, 20)
    set_brightness(app, LAMP_B, 40)

    app.run_scheduled()

    assert {"entity_id": LAMP_B} in calls(app, "light/turn_off")
    assert calls(app, "light/turn_on") == []


def test_deferred_dynamic_step_keeps_on_off_only(ambiguous_app):
    app = ambiguous_app
    make_dynamic(app)
    press(app)                                   # pending switch-press off check
    app.now += timedelta(seconds=0.5)
    activate(app)
    set_brightness(app, LAMP_A, 20, 0.3)
    set_off(app, LAMP_B)
    app.callbacks = [c for c in app.callbacks
                     if c[0].__name__ != "perform_scene_validation"]
    scene_data = app.find_scene_in_inventory(SCENE)

    app.perform_level3_control({"scene_entity": SCENE, "scene_data": scene_data,
                                "on_off_only": True})
    deferred = [kw for name, _d, kw in app.scheduled if name == "perform_level3_control"][-1]
    assert deferred["on_off_only"] is True
    assert deferred["off_deferred"] is True

    app.run_scheduled()                          # off-check skipped, deferred step runs

    forbidden = {"brightness", "xy_color", "color_temp_kelvin"}
    assert app.service_calls
    assert not any(forbidden & set(kw) for _s, kw in app.service_calls)
    assert calls(app, "light/turn_on") == [{"entity_id": LAMP_B}]
