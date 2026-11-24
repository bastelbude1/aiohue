"""Build the table button event entity -> room-off jobs from v1 rules."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

# Appended, not inserted: scripts/ has another scene_validator.py, and the app
# module (put first on sys.path by conftest.py) must win
sys.path.append(str(Path(__file__).resolve().parents[3] / "scripts"))
from hue_inventory_extras import serialize_group  # noqa: E402

from scene_validator import build_off_jobs


def group(gid, id_v1, gtype, name, children):
    return serialize_group(NS(
        id=gid, id_v1=id_v1, type=NS(value=gtype),
        metadata=NS(name=name, archetype=NS(value="office")),
        children=[NS(rid=r, rtype=NS(value=rt)) for r, rt in children],
        services=[],
    ))

BTN_ENTITY = "event.room_office_switch_button_1"


def make_inventory(rules, room_name="Room_Office", group_v1="/groups/1",
                   sensor_v1="/sensors/16", prefix="a"):
    lamp_dev_a, lamp_dev_b = f"{prefix}-dev-a", f"{prefix}-dev-b"
    switch_dev, button = f"{prefix}-switch", f"{prefix}-button"
    return {"resources": {
        "devices": {"items": [
            {"id": lamp_dev_a, "id_v1": "/lights/1",
             "services_structured": [{"rid": f"{prefix}-light-a", "rtype": "light"}]},
            {"id": lamp_dev_b, "id_v1": "/lights/2",
             "services_structured": [{"rid": f"{prefix}-light-b", "rtype": "light"}]},
            {"id": switch_dev, "id_v1": sensor_v1,
             "services_structured": [{"rid": button, "rtype": "button"}]},
        ]},
        "groups": {"total_count": 1,
                   "rooms": {"count": 1, "items": [group(
                       f"{prefix}-room", group_v1, "room", room_name,
                       [(lamp_dev_a, "device"), (lamp_dev_b, "device")])]},
                   "zones": {"count": 0, "items": []}},
        "buttons": {"items": [
            {"id": button, "owner_rid": switch_dev, "control_id": 1},
        ]},
        "v1": {"rules": rules, "sensors": {}},
    }}


def rule(code, body, address="/groups/1/action", status="enabled", sensor="/sensors/16"):
    return {
        "status": status,
        "conditions": [
            {"address": f"{sensor}/state/buttonevent", "operator": "eq", "value": str(code)},
            {"address": f"{sensor}/state/lastupdated", "operator": "dx"},
        ],
        "actions": [{"address": address, "method": "PUT", "body": body}],
    }


def registry(prefix="a", button_entity=BTN_ENTITY):
    return {
        f"{prefix}-button": button_entity,
        f"{prefix}-light-a": "light.lamp_a",
        f"{prefix}-light-b": "light.lamp_b",
    }


def test_off_rule_maps_button_event_to_room_lights():
    inv = make_inventory({"1": rule(1002, {"on": False})})
    jobs = build_off_jobs([inv], registry())
    assert jobs == {BTN_ENTITY: [{
        "event_type": "short_release",
        "room_id": "a-room",
        "room_name": "Room_Office",
        "lights": ["light.lamp_a", "light.lamp_b"],
        "light_rids": ["a-light-a", "a-light-b"],
        "ambiguous": False,
    }]}


def test_scene_rules_on_same_button_make_it_ambiguous():
    inv = make_inventory({"1": rule(1002, {"on": False}),
                          "2": rule(1002, {"scene": "xyz"})})
    jobs = build_off_jobs([inv], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_other_code_scene_rule_does_not_make_ambiguous():
    inv = make_inventory({"1": rule(1002, {"on": False}),
                          "2": rule(1000, {"scene": "xyz"})})
    jobs = build_off_jobs([inv], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is False


def test_disabled_rules_are_ignored():
    inv = make_inventory({"1": rule(1002, {"on": False}, status="disabled")})
    assert build_off_jobs([inv], registry()) == {}


def test_disabled_scene_rule_does_not_make_ambiguous():
    inv = make_inventory({"1": rule(1002, {"on": False}),
                          "2": rule(1002, {"scene": "xyz"}, status="disabled")})
    assert build_off_jobs([inv], registry())[BTN_ENTITY][0]["ambiguous"] is False


def test_broken_chain_skips_rule():
    inv = make_inventory({"1": rule(1002, {"on": False}, sensor="/sensors/99")})
    assert build_off_jobs([inv], registry()) == {}


def test_unmapped_button_skips_rule():
    inv = make_inventory({"1": rule(1002, {"on": False})})
    assert build_off_jobs([inv], {"a-light-a": "light.lamp_a"}) == {}


def test_v1_ids_resolve_per_bridge_only():
    inv_a = make_inventory({"1": rule(1002, {"on": False})}, prefix="a")
    inv_b = make_inventory({}, room_name="Room_Other", prefix="b")
    reg = {**registry("a", "event.a_button"), **registry("b", "event.b_button")}
    jobs = build_off_jobs([inv_a, inv_b], reg)
    assert list(jobs) == ["event.a_button"]
    assert jobs["event.a_button"][0]["room_name"] == "Room_Office"

    inv_b = make_inventory({"1": rule(1002, {"on": False})}, room_name="Room_Other", prefix="b")
    jobs = build_off_jobs([inv_a, inv_b], reg)
    assert jobs["event.a_button"][0]["lights"] == ["light.lamp_a", "light.lamp_b"]
    assert jobs["event.a_button"][0]["room_id"] == "a-room"
    assert jobs["event.b_button"][0]["room_id"] == "b-room"
    assert jobs["event.b_button"][0]["room_name"] == "Room_Other"


def test_zone_with_direct_light_children():
    inv = make_inventory({"1": rule(1002, {"on": False}, address="/groups/5/action")})
    inv["resources"]["groups"]["zones"]["items"] = [
        group("a-zone", "/groups/5", "zone", "Zone_X", [("a-light-b", "light")])]
    job = build_off_jobs([inv], registry())[BTN_ENTITY][0]
    assert job["room_id"] == "a-zone"
    assert job["lights"] == ["light.lamp_b"]


def test_event_type_codes():
    inv = make_inventory({"1": rule(1003, {"on": False})})
    assert build_off_jobs([inv], registry())[BTN_ENTITY][0]["event_type"] == "long_release"


def test_inventory_without_v1_is_skipped():
    inv = make_inventory({})
    inv["resources"]["v1"] = {"error": "boom"}
    assert build_off_jobs([inv], registry()) == {}


def test_real_rule_with_extra_conditions_still_matches():
    """Hue-app style rule with a CLIP status condition: matched, but conditional."""
    r = rule(1002, {"on": False})
    r["conditions"] = [
        {"address": "/sensors/16/state/buttonevent", "operator": "eq", "value": "1002"},
        {"address": "/sensors/16/state/lastupdated", "operator": "dx"},
        {"address": "/sensors/59/state/status", "operator": "eq", "value": "1"},
        {"address": "/groups/1/state/any_on", "operator": "eq", "value": "true"},
    ]
    jobs = build_off_jobs([make_inventory({"1": r})], registry())
    assert jobs[BTN_ENTITY][0]["lights"] == ["light.lamp_a", "light.lamp_b"]
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_unconditional_off_rule_with_only_harmless_conditions_is_unambiguous():
    r = rule(1002, {"on": False})
    r["conditions"].append(
        {"address": "/groups/1/state/any_on", "operator": "eq", "value": "true"})
    jobs = build_off_jobs([make_inventory({"1": r})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is False


def test_conditional_sole_off_rule_is_ambiguous():
    r = rule(1002, {"on": False})
    r["conditions"].append(
        {"address": "/config/localtime", "operator": "in", "value": "T22:00:00/T06:00:00"})
    jobs = build_off_jobs([make_inventory({"1": r})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_any_on_of_another_group_makes_ambiguous():
    r = rule(1002, {"on": False})
    r["conditions"].append(
        {"address": "/groups/7/state/any_on", "operator": "eq", "value": "true"})
    jobs = build_off_jobs([make_inventory({"1": r})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_two_off_rules_same_button_different_groups():
    r1 = rule(1002, {"on": False})
    r1["conditions"].append(
        {"address": "/groups/1/state/any_on", "operator": "eq", "value": "true"})
    r2 = rule(1002, {"on": False}, address="/groups/5/action")
    r2["conditions"].append(
        {"address": "/groups/5/state/any_on", "operator": "eq", "value": "true"})
    inv = make_inventory({"1": r1, "2": r2})
    inv["resources"]["groups"]["zones"]["items"] = [
        group("a-zone", "/groups/5", "zone", "Zone_X", [("a-light-b", "light")])]
    jobs = build_off_jobs([inv], registry())[BTN_ENTITY]
    by_room = {j["room_id"]: j for j in jobs}
    assert set(by_room) == {"a-room", "a-zone"}
    assert by_room["a-room"]["lights"] == ["light.lamp_a", "light.lamp_b"]
    assert by_room["a-zone"]["lights"] == ["light.lamp_b"]
    assert by_room["a-room"]["ambiguous"] is False
    assert by_room["a-zone"]["ambiguous"] is False


def test_conditional_then_unconditional_same_job_is_unambiguous():
    # 2.5.1 (CR13): an unconditional off-rule wins when two rules give the same job
    conditional = rule(1002, {"on": False})
    conditional["conditions"].append(
        {"address": "/config/localtime", "operator": "in", "value": "T22:00:00/T06:00:00"})
    jobs = build_off_jobs([make_inventory({"1": conditional,
                                           "2": rule(1002, {"on": False})})], registry())
    assert len(jobs[BTN_ENTITY]) == 1
    assert jobs[BTN_ENTITY][0]["ambiguous"] is False

    jobs = build_off_jobs([make_inventory({"1": rule(1002, {"on": False}),
                                           "2": conditional})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is False


def test_merged_jobs_stay_ambiguous_with_non_off_action():
    conditional = rule(1002, {"on": False})
    conditional["conditions"].append(
        {"address": "/config/localtime", "operator": "in", "value": "T22:00:00/T06:00:00"})
    jobs = build_off_jobs([make_inventory({"1": conditional, "2": rule(1002, {"on": False}),
                                           "3": rule(1002, {"scene": "xyz"})})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_ddx_rule_is_ambiguous():
    # 2.5.1 (CR15): ddx is a delayed trigger, cancelled by a newer event
    r = rule(1002, {"on": False})
    r["conditions"][1] = {"address": "/sensors/16/state/lastupdated", "operator": "ddx",
                          "value": "PT00:00:02"}
    jobs = build_off_jobs([make_inventory({"1": r})], registry())
    assert jobs[BTN_ENTITY][0]["ambiguous"] is True


def test_app_module_is_not_shadowed_by_scripts():
    # 2.5.1 (CR16): scripts/ has another scene_validator.py; the app must win
    import scene_validator
    assert Path(scene_validator.__file__).as_posix().endswith(
        "appdaemon_apps/scene_validator/scene_validator.py")
