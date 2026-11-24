"""2.5.1 (PR #20 review): scene path fixes."""

from datetime import timedelta

from test_off_validation_app import (  # noqa: F401
    LAMP_A, LAMP_B, SCENE, SELECT, app, press, run_next,
)
from test_missed_only import activate, calls, has_log, light_targets, set_lamp
from test_restored_entities import app as restored_app, fresh, validations  # noqa: F401
from test_select_listener import SCENE as LISTENER_SCENE
from test_superseded import (  # noqa: F401
    SELECT as TWO_SCENE_SELECT, STANDARD, app as two_scene_app,
)

OLD_TS = "2026-11-22T10:00:00+00:00"


def set_at(app, entity, state, when, brightness=255):
    """Lamp state (plain and full) with last_updated = when."""
    app.states[entity] = state
    app.full_states[entity] = {
        "state": state,
        "last_updated": when.isoformat(),
        "attributes": {"brightness": brightness} if state == "on" else {},
    }


def scheduled(app, name):
    return [kw for n, _d, kw in app.scheduled if n == name]


# --- A1: scene old "unknown" -------------------------------------------------

def test_first_ha_activation_of_never_activated_scene_validates(restored_app):  # noqa: F811
    restored_app.on_scene_state_changed(LISTENER_SCENE, "state", "unknown",
                                        fresh(restored_app), {})

    assert validations(restored_app) == [LISTENER_SCENE]


def test_never_activated_scene_with_stale_timestamp_is_ignored(restored_app):  # noqa: F811
    stale = fresh(restored_app, -(restored_app.transition_delay + 1))

    restored_app.on_scene_state_changed(LISTENER_SCENE, "state", "unknown", stale, {})

    assert restored_app.scheduled == []


# --- A3/CR1: A -> B -> A runs one chain ----------------------------------------

def test_reactivated_scene_aborts_older_chain(two_scene_app):  # noqa: F811
    app = two_scene_app
    app.on_select_state_changed(TWO_SCENE_SELECT, "state", "unknown", "Arbeiten Standard", {})
    app.on_select_state_changed(TWO_SCENE_SELECT, "state", "Arbeiten Standard",
                                "Arbeiten Abends", {})
    app.on_select_state_changed(TWO_SCENE_SELECT, "state", "Arbeiten Abends",
                                "Arbeiten Standard", {})
    seqs = [kw["activation_seq"] for kw in scheduled(app, "perform_scene_validation")]
    assert len(seqs) == 2

    app.run_scheduled()

    turn_ons = [kw for s, kw in app.service_calls if s == "scene/turn_on"]
    assert turn_ons == [{"entity_id": STANDARD}]
    assert [kw["activation_seq"] for kw in scheduled(app, "perform_level2_validation")] \
        == [seqs[1]]
    assert has_log(app, f"[{STANDARD}] [SKIP] Validation - superseded by a newer activation "
                        "of the same scene")


def test_duplicate_reports_still_one_chain(app):  # noqa: F811
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    app.on_scene_state_changed(SCENE, "state", OLD_TS, app.get_now().isoformat(), {})
    activate(app)

    app.run_scheduled()

    assert len(scheduled(app, "perform_scene_validation")) == 1
    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]
    assert not has_log(app, "superseded by a newer activation of the same scene")


# --- A5: activated_at from the scene timestamp ---------------------------------

def test_activated_at_uses_scene_timestamp(app):  # noqa: F811
    t_activation = app.now
    app.now += timedelta(seconds=3)               # callback 3 s late
    set_at(app, LAMP_A, "on", t_activation + timedelta(seconds=1))
    set_at(app, LAMP_B, "off", t_activation + timedelta(seconds=0.5))  # reacted, but differs

    app.on_scene_state_changed(SCENE, "state", OLD_TS, t_activation.isoformat(), {})
    assert scheduled(app, "perform_scene_validation")[0]["activated_at"] == t_activation
    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, f"[SKIP] {LAMP_B} changed after activation")


def test_select_activation_keeps_get_now(app):  # noqa: F811
    activate(app)
    assert scheduled(app, "perform_scene_validation")[0]["activated_at"] == app.now


# --- CR4: the validator's own re-trigger ------------------------------------------

def test_own_retrigger_echo_does_not_veto_off_check(app):  # noqa: F811
    activate(app)                                  # t0
    set_lamp(app, LAMP_A, "off", -3600)            # both missed the scene command
    set_lamp(app, LAMP_B, "off", -3600)
    app.now += timedelta(seconds=5)
    run_next(app, "perform_scene_validation")      # Level 2 re-trigger at t0+5
    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]
    retrigger_ts = app.now.isoformat()

    app.now += timedelta(seconds=0.5)
    t_press = press(app)                           # definite room off
    app.now += timedelta(seconds=0.5)
    app.on_scene_state_changed(SCENE, "state", OLD_TS, retrigger_ts, {})  # echo after the press
    set_at(app, LAMP_A, "off", t_press + timedelta(seconds=0.3))
    set_at(app, LAMP_B, "on", t_press - timedelta(seconds=3600))  # missed the off

    run_next(app, "perform_off_check")

    assert not has_log(app, "Room off: scene activated")
    assert (("light/turn_off", {"entity_id": LAMP_B}) in app.service_calls)
    assert any(level == "DEBUG" and "own re-trigger" in m for level, m in app.logs)


def test_own_retrigger_echo_does_not_clear_debounce_or_record(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    run_next(app, "perform_scene_validation")
    owners_before = dict(app.light_last_activation)
    activation_at_before = dict(app.light_activation_at)

    app.now += timedelta(seconds=1)
    app.on_scene_state_changed(SCENE, "state", OLD_TS, app.now.isoformat(), {})

    assert app.light_last_activation == owners_before
    assert app.light_activation_at == activation_at_before
    assert SCENE in app.recent_validations
    assert len(scheduled(app, "perform_scene_validation")) == 1


def test_ha_activation_after_echo_window_still_validates(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    run_next(app, "perform_scene_validation")
    app.recent_validations.clear()

    app.now += timedelta(seconds=4)
    app.on_scene_state_changed(SCENE, "state", OLD_TS, app.now.isoformat(), {})

    assert len(scheduled(app, "perform_scene_validation")) == 2


# --- CR6: unresolved select supersedes -------------------------------------------

def test_unresolved_select_supersedes_older_validation(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    app.on_select_state_changed(SELECT, "state", "Standard", "NewSceneNotInInventory", {})

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert light_targets(app) == []
    assert has_log(app, f"superseded by newer activation of unresolved:{SELECT}")


# --- CR3: select options vs inventory ----------------------------------------------

def test_select_options_mismatch_declines(app):  # noqa: F811
    app.attributes[SELECT] = {"options": ["Standard", "Renamed elsewhere"]}

    activate(app)

    assert scheduled(app, "perform_scene_validation") == []
    assert any(level == "WARNING" and m == f"[WARN] {SELECT} options differ from inventory - "
               "not validated (regenerate inventory)" for level, m in app.logs)


def test_select_options_match_validates(app):  # noqa: F811
    app.attributes[SELECT] = {"options": ["Standard"]}

    activate(app)

    assert [kw["scene_entity"] for kw in scheduled(app, "perform_scene_validation")] == [SCENE]


def test_select_options_mismatch_supersedes_older_validation(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", -3600)
    app.attributes[SELECT] = {"options": ["Standard", "New"]}
    app.on_select_state_changed(SELECT, "state", "Other", "Standard", {})

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []


# --- CR8: whole-scene replay only when safe for every lamp ----------------------------

def test_passing_lamp_adjusted_by_owner_blocks_replay(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)       # missed
    set_lamp(app, LAMP_B, "on", 3)            # passing, but touched at +3 s (owner)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert light_targets(app) == [LAMP_A]
    level3 = scheduled(app, "perform_level3_control")
    assert [kw["only_entities"] for kw in level3] == [[LAMP_A]]


def test_passing_lamp_within_reaction_window_allows_replay(app):  # noqa: F811
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "on", 1.9)

    run_next(app, "perform_scene_validation")

    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]


# --- CR9: dynamic scene with legacy actions ---------------------------------------

def test_dynamic_legacy_scene_is_not_replayed(app):  # noqa: F811
    app.attributes[SCENE] = {"is_dynamic": True}
    app.find_scene_in_inventory(SCENE)["actions"] = ["ResourceIdentifier(...)"]
    activate(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, f"[ERROR] {SCENE} validation unusable - not escalated")


# --- A7: reverse map lookup ---------------------------------------------------------

def test_scene_light_rids_uses_reverse_map(app):  # noqa: F811
    app.hue_id_to_entity_id = {}

    assert app._scene_light_rids(SCENE) == ["a-light-a", "a-light-b"]
