"""Build the table button event entity -> room-off jobs from v1 rules."""

from scene_validator import build_off_jobs

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
        "rooms": {"items": [{
            "id": f"{prefix}-room", "id_v1": group_v1, "type": "room",
            "metadata": {"name": room_name},
            "children": [{"rid": lamp_dev_a, "rtype": "device"},
                         {"rid": lamp_dev_b, "rtype": "device"}],
        }]},
        "zones": {"items": []},
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
    inv["resources"]["zones"]["items"] = [{
        "id": "a-zone", "id_v1": "/groups/5", "type": "zone",
        "metadata": {"name": "Zone_X"},
        "children": [{"rid": "a-light-b", "rtype": "light"}],
    }]
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
