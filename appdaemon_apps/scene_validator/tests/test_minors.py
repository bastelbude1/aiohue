"""2.5.0 minors: unmapped lamps, non-Hue scenes, rate limit after filtering."""

from datetime import timedelta

from test_off_validation_app import LAMP_A, SCENE, SELECT, build_app
from test_off_jobs import BTN_ENTITY  # noqa: I001
from test_scene_filters import LABELLED, PLAIN, activate as activate_scene, make_app  # noqa: F401


def set_lamp(app, entity, state, offset, brightness=255):
    app.states[entity] = state
    app.full_states[entity] = {
        "state": state,
        "last_updated": (app.now + timedelta(seconds=offset)).isoformat(),
        "attributes": {"brightness": brightness} if state == "on" else {},
    }


def unmapped_b_app(tmp_path):
    # Lamp B ("a-light-b") of the scene has no entity registry entry
    return build_app(tmp_path, reg={"a-button": BTN_ENTITY, "a-light-a": LAMP_A})


def has_log(app, text):
    return any(text in m for _l, m in app.logs)


def test_unmapped_scene_lamp_is_skipped_not_failure(tmp_path):
    app = unmapped_b_app(tmp_path)
    set_lamp(app, LAMP_A, "on", 1)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, f"[{SCENE}] [SKIP] a-light-b not mapped")
    assert has_log(app, "[OK] Validation successful")
    assert not has_log(app, "Could not map Hue ID")


def test_unmapped_lamp_does_not_fail_level3_control(tmp_path):
    app = unmapped_b_app(tmp_path)
    set_lamp(app, LAMP_A, "off", -3600)
    scene_data = app.find_scene_in_inventory(SCENE)

    assert app.control_lights_individually(scene_data, scene_entity=SCENE) is True
    assert [kw["entity_id"] for _s, kw in app.service_calls] == [LAMP_A]


def test_non_hue_scene_is_skipped_before_validation(make_app):  # noqa: F811
    app = make_app({})
    app.logs.clear()

    activate_scene(app, "scene.script_made_scene")

    assert app.scheduled == []
    assert not any(level in ("WARNING", "ERROR") for level, _m in app.logs)
    assert any(level == "DEBUG" and "scene.script_made_scene" in m for level, m in app.logs)
    assert app.validation_timestamps == []


def test_rate_limit_consumed_only_after_filtering(make_app):  # noqa: F811
    app = make_app({"exclude_uids": ["aaaa"]})
    app.max_validations_per_minute = 1

    activate_scene(app, LABELLED)            # filtered out: must not use the budget
    assert app.validation_timestamps == []
    assert LABELLED not in app.scene_validation_timestamps or \
        app.scene_validation_timestamps[LABELLED] == []

    activate_scene(app, PLAIN)

    assert [kw["scene_entity"] for n, _d, kw in app.scheduled
            if n == "perform_scene_validation"] == [PLAIN]
