"""2.5.1 (PR #20 review): room-off path fixes."""

from datetime import timedelta

import pytest

from test_off_jobs import BTN_ENTITY
from test_off_validation_app import (  # noqa: F401
    LAMP_A, LAMP_B, ROOM_ID, SCENE, SELECT, ambiguous_app, app, event_state, press, run_next,
    set_light, turn_offs,
)


def activate(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})


def has_log(app, text):
    return any(text in m for _l, m in app.logs)


def starts(app):
    return [m for _l, m in app.logs if m == f"Starting validation: {SCENE}"]


def spy_records(app):
    rec = []
    app.record_success = lambda: rec.append("success")
    app.record_failure = lambda: rec.append("failure")
    return rec


# --- A2: switch event old "unknown" --------------------------------------------

def test_first_press_on_new_event_entity_is_checked(app):  # noqa: F811
    app.on_switch_event(BTN_ENTITY, "all", event_state("unknown"),
                        event_state(app.now.isoformat()), {})

    assert [n for n, _d, _kw in app.scheduled] == ["perform_off_check"]


def test_restored_press_with_old_unknown_is_rejected_by_age(app):  # noqa: F811
    stale = (app.now - timedelta(seconds=60)).isoformat()
    app.on_switch_event(BTN_ENTITY, "all", event_state("unknown"), event_state(stale), {})

    assert app.scheduled == []


# --- A4/CR10: deferral waits for the real off check -------------------------------

def test_late_press_delivery_still_defers_until_off_check(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    activate(app)                                  # t0: validation due t0+5
    app.now += timedelta(seconds=4)
    t_press = press(app, offset=-2)                # press at t0+2, delivered at t0+4
    set_light(app, LAMP_A, "off", -2 + 0.3)        # room off confirmed by evidence
    set_light(app, LAMP_B, "off", -2 + 0.4)
    assert app.off_check_due[ROOM_ID] == app.now + timedelta(seconds=app.off_check_delay)
    assert t_press < app.now

    app.run_timed()

    names = [n for n, _t in app.run_log]
    off_index = names.index("perform_off_check")
    scene_runs = [i for i, n in enumerate(names) if n == "perform_scene_validation"]
    assert scene_runs[-1] > off_index
    assert starts(app) == []
    assert has_log(app, "superseded by newer activation of off:Room_Office")


def test_scene_step_is_deferred_at_most_three_times(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    activate(app)
    app.now += timedelta(seconds=2)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)

    for _ in range(4):                             # off-check never runs (e.g. delayed)
        run_next(app, "perform_scene_validation")

    deferred = [m for _l, m in app.logs if "Validation deferred - pending room-off" in m]
    assert len(deferred) == 3
    assert len(starts(app)) == 1
    assert has_log(app, f"[{SCENE}] [SKIP] Validation deferral limit reached - proceeding "
                        "while room-off check still pending")
    assert not has_log(app, "overdue")


def test_deferral_stops_10s_after_off_check_due(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    activate(app)
    app.now += timedelta(seconds=2)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "off", 0.4)
    run_next(app, "perform_scene_validation")      # deferred once

    app.now = app.off_check_due[ROOM_ID] + timedelta(seconds=10)
    run_next(app, "perform_scene_validation")

    assert len(starts(app)) == 1
    assert has_log(app, "overdue")


def test_off_check_evaluation_clears_pending(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    press(app)
    set_light(app, LAMP_A, "on", -3600)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")             # no evidence: skipped, but evaluated

    assert ROOM_ID not in app.off_check_due
    assert app._pending_off_wait(SCENE) is None


def test_off_check_scheduling_failure_clears_pending(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    original = app.run_in

    def failing_run_in(callback, delay, **kwargs):
        if callback.__name__ == "perform_off_check":
            raise RuntimeError("scheduler down")
        return original(callback, delay, **kwargs)
    app.run_in = failing_run_in

    press(app)

    assert ROOM_ID not in app.off_check_due
    assert app._pending_off_wait(SCENE) is None


# --- CR11: older scene must not veto a definite press ------------------------------

def test_scene_half_second_before_definite_press_does_not_veto(app):  # noqa: F811
    activate(app)
    app.now += timedelta(seconds=0.5)
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    run_next(app, "perform_off_check")

    assert turn_offs(app) == [LAMP_B]
    assert not has_log(app, "Room off: scene activated")


def test_scene_after_definite_press_still_vetoes(app):  # noqa: F811
    press(app)
    app.now += timedelta(seconds=0.5)
    activate(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)

    run_next(app, "perform_off_check")

    assert turn_offs(app) == []
    assert has_log(app, "Room off: scene activated")


# --- CR12: evidence tied to the press ------------------------------------------------

def test_owner_change_4s_after_press_is_not_evidence(ambiguous_app):  # noqa: F811
    app = ambiguous_app
    press(app)
    set_light(app, LAMP_A, "off", 4)               # owner switched A off in the app
    set_light(app, LAMP_B, "on", -3600)
    app.now += timedelta(seconds=5)

    run_next(app, "perform_off_check")

    assert turn_offs(app) == []
    assert has_log(app, "no off evidence")


# --- CR2: no verified-off success without an observation ------------------------------

@pytest.mark.parametrize("step", ["perform_off_level3", "perform_off_final_check"])
def test_off_followup_with_unreachable_target_records_nothing(app, step):  # noqa: F811
    press(app)
    set_light(app, LAMP_A, "off", 0.3)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")
    if step == "perform_off_final_check":
        run_next(app, "perform_off_level3")        # B still on: Level 3 sent
    rec = spy_records(app)
    app.full_states[LAMP_B] = {"state": "unavailable", "last_updated": app.now.isoformat()}
    sent = list(turn_offs(app))

    run_next(app, step)

    assert rec == []
    assert turn_offs(app) == sent
    assert has_log(app, "[SKIP] Room off check inconclusive - target lamp(s) unreachable")
    assert not app.callbacks


def test_partly_observed_followup_ok_names_counts(app):  # noqa: F811
    press(app)
    set_light(app, LAMP_A, "on", -3600)        # both missed (unambiguous job)
    set_light(app, LAMP_B, "on", -3600)
    run_next(app, "perform_off_check")
    set_light(app, LAMP_A, "off", 6)
    app.full_states[LAMP_B] = {"state": "unavailable", "last_updated": app.now.isoformat()}

    run_next(app, "perform_off_level3")

    assert has_log(app, "[OK] Room off verified after LEVEL 2 "
                        "(1 of 2 target(s) observed, 1 unreachable)")


# --- review round 2: late or duplicate reports do not re-stamp -------------------------

OLD_TS = "2026-11-22T10:00:00+00:00"


def test_duplicate_select_report_after_definite_press_does_not_veto(app):  # noqa: F811
    t0 = app.now
    app.on_scene_state_changed(SCENE, "state", OLD_TS, t0.isoformat(), {})  # HA-initiated
    app.now = t0 + timedelta(seconds=0.3)
    t_press = press(app)                           # definite press 0.3 s after the scene
    app.now = t0 + timedelta(seconds=0.6)
    activate(app)                                  # late bridge report of the same activation
    set_light(app, LAMP_A, "off", 0.3 - 0.6)
    set_light(app, LAMP_B, "on", -3600)
    app.now = t_press

    run_next(app, "perform_off_check")

    assert turn_offs(app) == [LAMP_B]
    assert len([n for n, _d, _kw in app.scheduled if n == "perform_scene_validation"]) == 1


def test_scene_path_stamps_scene_timestamp(app):  # noqa: F811
    t_activation = app.now
    app.now += timedelta(seconds=1.5)              # callback late
    app.on_scene_state_changed(SCENE, "state", OLD_TS, t_activation.isoformat(), {})

    assert app.light_activation_at["a-light-a"] == t_activation


def test_debounced_duplicate_does_not_restamp(app):  # noqa: F811
    activate(app)
    stamped = dict(app.light_activation_at)
    app.now += timedelta(seconds=10)
    app.on_select_state_changed(SELECT, "state", "Other", "Standard", {})  # debounced

    assert app.light_activation_at == stamped
