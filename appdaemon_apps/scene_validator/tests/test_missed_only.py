"""C2/C3: only lamps that missed the scene command are corrected.

A failing lamp is "missed" if it shows no update since the activation
(last_updated < activated_at - 1 s). A lamp updated after the activation was
changed by the owner or by Hue and is left alone.
"""

from datetime import datetime, timedelta, timezone

from scene_validator import classify_scene_failures
from test_off_validation_app import (  # noqa: F401
    LAMP_A, LAMP_B, SCENE, SELECT, ambiguous_app, app, press, run_next,
)

T0 = datetime(2026, 11, 22, 18, 0, 0, tzinfo=timezone.utc)
A, B, C = "light.lamp_a", "light.lamp_b", "light.lamp_c"


# --- pure helper -------------------------------------------------------------

def lamp(state, offset):
    return {"state": state, "last_updated": T0 + timedelta(seconds=offset)}


def test_classify_missed_and_changed():
    missed, changed = classify_scene_failures(
        [A, B], {A: lamp("off", -3600), B: lamp("off", 2)}, T0)
    assert missed == [A]
    assert changed == [B]


def test_classify_one_second_boundary():
    # exactly activated_at - 1 s counts as an update (changed); older is missed
    missed, changed = classify_scene_failures(
        [A, B], {A: lamp("off", -1), B: {"state": "off",
                                         "last_updated": T0 - timedelta(seconds=1, microseconds=1)}},
        T0)
    assert missed == [B]
    assert changed == [A]


def test_classify_lamp_missing_from_states_is_neither():
    missed, changed = classify_scene_failures([A, C], {A: lamp("off", -60)}, T0)
    assert missed == [A]
    assert changed == []


def test_classify_only_failing_lamps_are_classified():
    missed, changed = classify_scene_failures([], {A: lamp("off", -60), B: lamp("on", 2)}, T0)
    assert (missed, changed) == ([], [])


# --- app level ---------------------------------------------------------------

def set_lamp(app, entity, state, offset, brightness=255):
    """Lamp state for both plain and full get_state (FakeHass reads them separately)."""
    app.states[entity] = state
    app.full_states[entity] = {
        "state": state,
        "last_updated": (app.now + timedelta(seconds=offset)).isoformat(),
        "attributes": {"brightness": brightness} if state == "on" else {},
    }


def activate(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})


def calls(app, service):
    return [kw for s, kw in app.service_calls if s == service]


def light_targets(app):
    return [kw.get("entity_id") for s, kw in app.service_calls if s.startswith("light/")]


def has_log(app, text):
    return any(text in m for _l, m in app.logs)


def spy_records(app):
    rec = []
    app.record_success = lambda: rec.append("success")
    app.record_failure = lambda: rec.append("failure")
    return rec


def test_owner_switches_lamp_off_after_activation_is_left_alone(app):
    rec = spy_records(app)
    activate(app)
    set_lamp(app, LAMP_A, "on", 1)
    set_lamp(app, LAMP_B, "off", 2)   # owner switched it off after the activation

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert light_targets(app) == []
    assert has_log(app, f"[SKIP] {LAMP_B} changed after activation")
    assert has_log(app, "[OK] nothing to correct (only owner/Hue changes)")
    assert rec == []


def test_lamp_missed_command_is_corrected(app):
    activate(app)
    set_lamp(app, LAMP_A, "on", 1)
    set_lamp(app, LAMP_B, "off", -3600)   # no update since long before the activation

    run_next(app, "perform_scene_validation")

    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]


def test_mixed_missed_and_changed_level3_commands_only_missed(app):
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)       # missed
    set_lamp(app, LAMP_B, "on", 30, 128)      # owner dimmed it after the activation

    app.run_scheduled()

    assert light_targets(app)
    assert set(light_targets(app)) == {LAMP_A}
    # Spec amendment (b): Level 2 runs only if every failing lamp is missed
    assert calls(app, "scene/turn_on") == []
    assert has_log(app, f"[SKIP] {LAMP_B} changed after activation")


def test_changed_off_lamp_blocks_level2_retrigger_but_missed_lamp_gets_level3(app):
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)   # missed
    set_lamp(app, LAMP_B, "off", 2)       # owner switched it off

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert set(light_targets(app)) == {LAMP_A}
    assert calls(app, "light/turn_on")[0]["entity_id"] == LAMP_A


def test_inventory_outdated_warns_and_does_not_override(app):
    rec = spy_records(app)
    activate(app)
    set_lamp(app, LAMP_A, "on", 1)
    set_lamp(app, LAMP_B, "on", 2, 128)   # reacted to the scene, but at 50%, inventory says 100%

    app.run_scheduled()

    assert app.service_calls == []
    assert any(level == "WARNING" and f"{SCENE} {LAMP_B} differs from inventory after reacting"
               " - inventory may be outdated" in m for level, m in app.logs)
    assert has_log(app, f"[SKIP] {LAMP_B} changed after activation")
    assert rec == []


def test_owner_change_after_transition_window_does_not_warn(app):
    activate(app)
    set_lamp(app, LAMP_A, "on", 1)
    set_lamp(app, LAMP_B, "on", app.transition_delay + 30, 128)   # owner dimmed later

    app.run_scheduled()

    assert app.service_calls == []
    assert not has_log(app, "inventory may be outdated")


def test_level2_revalidation_treats_newly_updated_lamp_as_changed(app):
    activate(app)
    set_lamp(app, LAMP_A, "on", 1)
    set_lamp(app, LAMP_B, "off", -3600)   # missed
    run_next(app, "perform_scene_validation")
    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]

    set_lamp(app, LAMP_B, "on", 7, 128)   # updated after the activation, but not as the inventory says
    app.run_scheduled()

    assert light_targets(app) == []
    assert has_log(app, f"[SKIP] {LAMP_B} changed after activation")
    assert has_log(app, "[OK] nothing to correct (only owner/Hue changes)")


def test_level3_skips_lamp_changed_after_level2_validation(app):
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    run_next(app, "perform_scene_validation")
    run_next(app, "perform_level2_validation")     # both still missed: Level 3 scheduled
    level3 = [kw for n, _d, kw in app.scheduled if n == "perform_level3_control"][-1]
    assert sorted(level3["only_entities"]) == [LAMP_A, LAMP_B]

    set_lamp(app, LAMP_B, "on", 9, 60)              # owner changed B before Level 3
    run_next(app, "perform_level3_control")

    assert light_targets(app) == [LAMP_A]


def test_level3_final_validation_judges_only_commanded_lamps(app, monkeypatch):
    rec = spy_records(app)
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)       # missed
    set_lamp(app, LAMP_B, "on", 30, 128)      # owner dimmed it
    run_next(app, "perform_scene_validation")
    run_next(app, "perform_level3_control")
    assert light_targets(app) == [LAMP_A]

    set_lamp(app, LAMP_A, "on", 12)           # Level 3 worked; B stays at the owner's 50%
    app.run_scheduled()

    assert has_log(app, "[OK] Level 3 successful")
    assert rec == ["success"]


def test_deferred_level3_keeps_only_entities(ambiguous_app):
    app = ambiguous_app
    press(app)                                 # pending room-off check on the scene lights
    scene_data = app.find_scene_in_inventory(SCENE)

    app.perform_level3_control({"scene_entity": SCENE, "scene_data": scene_data,
                                "activated_at": app.now, "only_entities": [LAMP_A]})

    deferred = [kw for n, _d, kw in app.scheduled if n == "perform_level3_control"][-1]
    assert deferred["off_deferred"] is True
    assert deferred["only_entities"] == [LAMP_A]


def test_control_only_entities_static_and_on_off_only(app):
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    scene_data = app.find_scene_in_inventory(SCENE)

    for on_off_only in (False, True):
        app.service_calls.clear()
        assert app.control_lights_individually(scene_data, on_off_only=on_off_only,
                                               scene_entity=SCENE, only_entities={LAMP_B})
        assert light_targets(app) == [LAMP_B]
