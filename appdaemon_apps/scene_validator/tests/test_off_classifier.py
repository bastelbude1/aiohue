"""Classify a room-off check: skip, ok, or which lights missed the off."""

from datetime import datetime, timedelta, timezone

from scene_validator import classify_off_check

T = datetime(2026, 11, 22, 18, 0, 0, tzinfo=timezone.utc)
WINDOW = T - timedelta(seconds=1)


def lt(state, offset):
    return {"state": state, "last_updated": T + timedelta(seconds=offset)}


def test_room_off_with_one_missed_lamp():
    lights = {"light.lamp_a": lt("off", 0.3), "light.lamp_b": lt("on", -60)}
    assert classify_off_check(lights, WINDOW, False, True) == ("missed", ["light.lamp_b"])


def test_all_off_is_ok():
    lights = {"light.lamp_a": lt("off", 0.3), "light.lamp_b": lt("off", 0.4)}
    assert classify_off_check(lights, WINDOW, False, True) == ("ok", [])


def test_scene_step_that_turns_one_lamp_off_is_not_an_off_job():
    lights = {"light.lamp_a": lt("off", 0.3), "light.lamp_b": lt("on", 0.3)}
    assert classify_off_check(lights, WINDOW, False, True) == ("skip_no_evidence", [])


def test_lamp_changed_after_press_is_left_alone():
    lights = {"light.lamp_a": lt("off", 0.3), "light.lamp_b": lt("on", 2)}
    assert classify_off_check(lights, WINDOW, False, True) == ("skip_no_evidence", [])
    assert classify_off_check(lights, WINDOW, False, False) == ("ok", [])


def test_off_update_up_to_1s_before_press_counts():
    lights = {"light.lamp_a": lt("off", -0.8), "light.lamp_b": lt("on", -60)}
    assert classify_off_check(lights, WINDOW, False, True) == ("missed", ["light.lamp_b"])


def test_scene_activation_in_window_skips():
    lights = {"light.lamp_a": lt("on", -60)}
    assert classify_off_check(lights, WINDOW, True, False) == ("skip_scene", [])


def test_unambiguous_button_needs_no_evidence():
    lights = {"light.lamp_b": lt("on", -60), "light.lamp_a": lt("on", -60)}
    assert classify_off_check(lights, WINDOW, False, False) == (
        "missed", ["light.lamp_a", "light.lamp_b"])
