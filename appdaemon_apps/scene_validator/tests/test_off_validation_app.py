"""App wiring for room-off validation: switch press -> check room lights -> escalate."""

import json
from datetime import timedelta

import pytest

from scene_validator import SceneValidator
from test_off_jobs import BTN_ENTITY, make_inventory, registry, rule

SELECT = "select.room_office_scene"
SCENE = "scene.room_office_standard"
LAMP_A = "light.lamp_a"
LAMP_B = "light.lamp_b"
ROOM_ID = "a-room"


def scene_item():
    return {
        "id": "scene-1",
        "type": "scene",
        "metadata": {"name": "Standard"},
        "group": {"rid": ROOM_ID, "rtype": "room"},
        "actions": [
            {"target": {"rid": "a-light-a", "rtype": "light"},
             "action": {"on": {"on": True}, "dimming": {"brightness": 100.0}}},
            {"target": {"rid": "a-light-b", "rtype": "light"},
             "action": {"on": {"on": True}, "dimming": {"brightness": 100.0}}},
        ],
    }


def off_rule():
    return rule(1002, {"on": False})


def scene_rule():
    return rule(1002, {"scene": "scene-1"})


def build_app(tmp_path, rules=None, off_validation=..., with_v1=True, reg=None):
    rules = {"1": off_rule()} if rules is None else rules
    inv = make_inventory(rules)
    inv["bridge_info"] = {"config": {"name": "Bridge_Test"}}
    inv["resources"]["scenes"] = {"items": [scene_item()]}
    if not with_v1:
        del inv["resources"]["v1"]
    inventory_dir = tmp_path / "inventories"
    inventory_dir.mkdir()
    (inventory_dir / "bridge.json").write_text(json.dumps(inv))

    reg = registry() if reg is None else reg
    entities = [{"entity_id": e, "unique_id": u, "platform": "hue"} for u, e in reg.items()]
    entities += [
        {"entity_id": SCENE, "unique_id": "scene-1", "platform": "hue"},
        {"entity_id": SELECT, "unique_id": f"{ROOM_ID}_scene_select", "platform": "hue"},
    ]
    registry_file = tmp_path / "core.entity_registry"
    registry_file.write_text(json.dumps({"data": {"entities": entities}}))

    app = SceneValidator(states={SCENE: "unknown", SELECT: "unknown"})
    app.args = {"inventory_dir": str(inventory_dir), "entity_registry_path": str(registry_file)}
    if off_validation is ...:
        off_validation = {"enabled": True, "rooms": ["Room_Office"]}
    if off_validation is not None:
        app.args["off_validation"] = off_validation
    app.full_states = {}
    app.initialize()
    return app


@pytest.fixture
def app(tmp_path):
    return build_app(tmp_path)


@pytest.fixture
def ambiguous_app(tmp_path):
    return build_app(tmp_path, rules={"1": off_rule(), "2": scene_rule()})


def set_light(app, entity, state, offset):
    """Light state with last_updated = now + offset seconds (ISO string, like AppDaemon)."""
    app.full_states[entity] = {
        "state": state,
        "last_updated": (app.now + timedelta(seconds=offset)).isoformat(),
        "attributes": {"brightness": 255} if state == "on" else {},
    }


def event_state(state, event_type="short_release"):
    """Full event entity state, as AppDaemon passes it with attribute="all"."""
    return {"state": state, "attributes": {"event_type": event_type}}


def press(app, event_type="short_release", offset=0.0):
    t_press = app.now + timedelta(seconds=offset)
    app.on_switch_event(BTN_ENTITY, "all", event_state("2026-11-22T10:00:00+00:00"),
                        event_state(t_press.isoformat(), event_type), {})
    return t_press


def turn_offs(app):
    return [kw.get("entity_id") for s, kw in app.service_calls if s == "light/turn_off"]


def switch_listeners(app):
    return [e for name, e in app.listeners if name == "on_switch_event"]


def warns(app, text):
    return [m for _lvl, m in app.logs if "[WARN]" in m and text in m]


def run_next(app, name):
    """Run the first pending callback with the given name."""
    for i, (callback, kwargs) in enumerate(app.callbacks):
        if callback.__name__ == name:
            app.callbacks.pop(i)
            callback(kwargs)
            return
    raise AssertionError(f"no pending {name}")


# --- startup -----------------------------------------------------------------

def test_listens_to_switch_buttons_of_enabled_rooms_only(tmp_path):
    app = build_app(tmp_path)
    assert switch_listeners(app) == [BTN_ENTITY]
    assert any("Monitoring 1 switch button(s) for room-off jobs (Room_Office)" in m
               for _lvl, m in app.logs)

    other = tmp_path / "other"
    other.mkdir()
    app = build_app(other, off_validation={"enabled": True, "rooms": ["Room_Other"]})
    assert switch_listeners(app) == []


def test_old_inventory_disables_off_validation_with_warning(tmp_path):
    app = build_app(tmp_path, with_v1=False)
    assert switch_listeners(app) == []
    assert warns(app, "off validation disabled: inventory has no v1 rules (regenerate inventory)")
    assert ("on_scene_state_changed", SCENE) in app.listeners
    assert ("on_select_state_changed", SELECT) in app.listeners


def test_off_validation_disabled_by_default(tmp_path):
    app = build_app(tmp_path, off_validation=None)
    assert switch_listeners(app) == []
    assert app.off_validation_enabled is False


def test_unknown_configured_room_warns(tmp_path):
    app = build_app(tmp_path, off_validation={"enabled": True, "rooms": ["Room_Missing"]})
    assert warns(app, "off validation: room 'Room_Missing' has no switch off-rule "
                      "(check name or use room id)")
    assert switch_listeners(app) == []


def test_room_matched_by_id(tmp_path):
    app = build_app(tmp_path, off_validation={"enabled": True, "rooms": [ROOM_ID]})
    assert switch_listeners(app) == [BTN_ENTITY]
    assert not warns(app, "has no switch off-rule")


def test_room_without_registered_lights_is_not_listened_to(tmp_path):
    app = build_app(tmp_path, reg={"a-button": BTN_ENTITY})
    assert switch_listeners(app) == []
    assert len(warns(app, "no lights in the entity registry")) == 1


# --- press handling ----------------------------------------------------------

def test_missed_lamp_is_switched_off_after_press(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert ("light/turn_off", {"entity_id": LAMP_B}) in app.service_calls
    assert LAMP_A not in turn_offs(app)


def test_all_lamps_off_logs_ok_and_sends_nothing(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    app.run_scheduled()

    assert turn_offs(app) == []
    assert any("[OK]" in m and "Room off" in m for _lvl, m in app.logs)


def test_other_event_type_is_ignored(app):
    press(app, event_type="long_release")
    assert app.scheduled == []


def test_scene_step_press_sends_nothing(ambiguous_app):
    app = ambiguous_app
    press(app)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []
    assert any("[SKIP]" in m and "scene" in m for _lvl, m in app.logs)


def test_scene_reported_before_press_still_counts_as_scene_step(ambiguous_app):
    app = ambiguous_app
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.now += timedelta(seconds=0.5)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []


def test_ambiguous_press_without_evidence_sends_nothing(ambiguous_app):
    app = ambiguous_app
    press(app)
    set_light(app, LAMP_A, "on", -3600)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []


def test_restored_event_state_after_restart_is_ignored(app):
    t = app.now.isoformat()

    app.on_switch_event(BTN_ENTITY, "all", event_state("unavailable"), event_state(t), {})
    stale = (app.now - timedelta(seconds=60)).isoformat()
    app.on_switch_event(BTN_ENTITY, "all", event_state("2026-11-22T10:00:00+00:00"),
                        event_state(stale), {})

    assert app.scheduled == []


def test_switch_listener_gets_full_state(app):
    assert app.listener_kwargs[("on_switch_event", BTN_ENTITY)] == {"attribute": "all"}


def test_event_type_is_taken_from_triggering_state(app):
    # The entity already moved on to short_release; the triggering change was initial_press
    app.attributes[BTN_ENTITY] = {"event_type": "short_release"}
    app.on_switch_event(BTN_ENTITY, "all", event_state("2026-11-22T10:00:00+00:00"),
                        event_state(app.now.isoformat(), "initial_press"), {})
    assert app.scheduled == []


def test_attribute_only_change_is_not_a_press(app):
    t = app.now.isoformat()
    app.on_switch_event(BTN_ENTITY, "all", event_state(t, "initial_press"),
                        event_state(t, "short_release"), {})
    assert app.scheduled == []


def test_newer_press_replaces_pending_check(app):
    press(app)
    app.now += timedelta(seconds=2)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    level2 = [m for _lvl, m in app.logs if "LEVEL 2" in m and "Room off" in m]
    assert len(level2) == 1


def test_unavailable_lights_are_left_out(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    app.full_states[LAMP_B] = {"state": "unavailable", "last_updated": app.now.isoformat()}

    app.run_scheduled()

    assert turn_offs(app) == []
    assert len(warns(app, LAMP_B)) == 1


def test_no_usable_light_state_skips_check(app):
    press(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert any("[SKIP]" in m and "no light state" in m for _lvl, m in app.logs)


def test_open_circuit_breaker_blocks_off_commands(app):
    app.circuit_breaker_state = "OPEN"
    app.circuit_breaker_opened_at = __import__("time").time()
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []


def test_rate_limit_blocks_off_commands(app):
    app.max_validations_per_minute = 0
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []


# --- escalation ----------------------------------------------------------------

def test_level2_success_needs_no_level3(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")
    assert turn_offs(app) == [LAMP_B]

    set_light(app, LAMP_B, "off", 6)
    app.run_scheduled()

    assert turn_offs(app) == [LAMP_B]
    assert any("[OK]" in m and "Room off" in m for _lvl, m in app.logs)


def test_lamp_still_on_gets_level3_then_fail(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)
    failures_before = app.circuit_breaker_failures

    app.run_scheduled()

    assert turn_offs(app) == [LAMP_B, LAMP_B]
    assert any("[FAIL]" in m and "Room off" in m for _lvl, m in app.logs)
    assert app.circuit_breaker_failures == failures_before + 1


def test_scene_during_escalation_stops_level3(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")

    app.now += timedelta(seconds=6)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    run_next(app, "perform_off_level3")

    assert turn_offs(app) == [LAMP_B]


def test_lamp_switched_on_by_owner_after_level2_is_left_alone(app):
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")

    set_light(app, LAMP_B, "on", 6)  # owner switched it on again
    app.run_scheduled()

    assert turn_offs(app) == [LAMP_B]


# --- supersede -----------------------------------------------------------------

def scene_turn_ons(app):
    return [kw.get("entity_id") for s, kw in app.service_calls if s == "scene/turn_on"]


def test_room_off_supersedes_pending_scene_validation(app):
    app.now -= timedelta(seconds=10)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.now += timedelta(seconds=10)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    app.run_scheduled()

    assert scene_turn_ons(app) == []
    assert any("[SKIP]" in m and "superseded" in m and "off:Room_Office" in m
               for _lvl, m in app.logs)


def test_confirmed_ambiguous_room_off_supersedes_pending_scene_validation(ambiguous_app):
    app = ambiguous_app
    app.now -= timedelta(seconds=10)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.now += timedelta(seconds=10)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    run_next(app, "perform_off_check")
    app.run_scheduled()

    assert scene_turn_ons(app) == []


def test_ambiguous_press_does_not_claim_lights_before_evidence(ambiguous_app):
    app = ambiguous_app
    app.now -= timedelta(seconds=10)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.now += timedelta(seconds=10)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    # Scene validation runs before the off-check confirmed anything: no claim yet,
    # the scene step is only deferred until the off-check has decided
    run_next(app, "perform_scene_validation")

    assert all(owner == SCENE for _seq, owner in app.light_last_activation.values())
    assert scene_turn_ons(app) == []
    assert any("[SKIP] Validation deferred - pending room-off check for Room_Office" in m
               for _lvl, m in app.logs)


# --- conditional off-rules -----------------------------------------------------

def test_conditional_sole_off_rule_without_evidence_sends_nothing(tmp_path):
    r = off_rule()
    r["conditions"].append(
        {"address": "/config/localtime", "operator": "in", "value": "T22:00:00/T06:00:00"})
    app = build_app(tmp_path, rules={"1": r})
    press(app)  # condition false on the bridge: nothing happens
    set_light(app, LAMP_A, "on", -3600)
    set_light(app, LAMP_B, "on", -3600)

    app.run_scheduled()

    assert turn_offs(app) == []


# --- pending room-off defers scene steps ----------------------------------------

def test_scene_then_quick_room_off_does_not_retrigger_scene(ambiguous_app):
    app = ambiguous_app
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})  # t0
    app.now += timedelta(seconds=2)
    press(app)                                  # t0+2: owner switches the room off
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    # real time order: scene validation (t0+5) before the off-check (t0+7)
    run_next(app, "perform_scene_validation")
    assert scene_turn_ons(app) == []
    deferred = [d for name, d, _kw in app.scheduled if name == "perform_scene_validation"][-1]
    assert deferred > 0

    app.run_scheduled()

    assert scene_turn_ons(app) == []
    assert any("[SKIP]" in m and "superseded" in m and "off:Room_Office" in m
               for _lvl, m in app.logs)


def test_scene_validation_proceeds_after_off_check_skipped(ambiguous_app):
    app = ambiguous_app
    press(app)
    app.now += timedelta(seconds=0.5)
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})  # scene step
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    run_next(app, "perform_scene_validation")   # deferred: off-check still pending
    app.run_scheduled()

    starts = [m for _lvl, m in app.logs if m == f"Starting validation: {SCENE}"]
    assert len(starts) == 1
    assert any("[SKIP]" in m and "scene step" in m for _lvl, m in app.logs)
    assert scene_turn_ons(app) == [SCENE]       # normal Level 2 re-trigger
    assert turn_offs(app) == []


def test_scene_step_is_deferred_at_most_once(ambiguous_app):
    app = ambiguous_app
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.now += timedelta(seconds=2)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    run_next(app, "perform_scene_validation")
    run_next(app, "perform_scene_validation")   # off-check still not run (e.g. delayed)

    starts = [m for _lvl, m in app.logs if m == f"Starting validation: {SCENE}"]
    assert len(starts) == 1


def test_unresolved_select_option_still_counts_as_scene_step(ambiguous_app):
    app = ambiguous_app
    press(app)
    app.on_select_state_changed(SELECT, "state", "unknown", "NewSceneNotInInventory", {})
    set_light(app, LAMP_A, "off", 0.3)   # scene step turns A off
    set_light(app, LAMP_B, "on", -3600)  # B already at scene target -> no update

    app.run_scheduled()

    assert turn_offs(app) == []
    assert warns(app, "Could not resolve 'NewSceneNotInInventory'")
    assert any("[SKIP]" in m and "scene step" in m for _lvl, m in app.logs)
