"""2.5.0 review fix round 1: unusable checks, dynamic scenes, Hue scenes missing from the registry."""

from test_off_validation_app import LAMP_A, LAMP_B, SCENE, SELECT, app  # noqa: F401
from test_missed_only import activate, calls, light_targets, set_lamp
from test_scene_filters import activate as activate_scene, make_app  # noqa: F401


def has_log(app, text, level=None):
    return any(text in m and (level is None or lvl == level) for lvl, m in app.logs)


def spy_records(app):
    rec = []
    app.record_success = lambda: rec.append("success")
    app.record_failure = lambda: rec.append("failure")
    return rec


def test_unusable_check_does_not_command_owner_changed_lamp(app, monkeypatch):
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)      # missed
    set_lamp(app, LAMP_B, "off", 2)          # owner switched it off
    orig = app.compare_light_states

    def boom(entity_id, *a, **k):
        if entity_id == LAMP_A:
            raise TypeError("malformed")
        return orig(entity_id, *a, **k)
    monkeypatch.setattr(app, "compare_light_states", boom)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert LAMP_B not in light_targets(app)
    assert has_log(app, f"[WARN] {SCENE} {LAMP_A} not checked", "WARNING")


def test_whole_check_unusable_is_not_escalated(app, monkeypatch):
    rec = spy_records(app)
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)
    set_lamp(app, LAMP_B, "off", 2)
    monkeypatch.setattr(app, "get_entity_id_from_hue_id",
                        lambda rid: (_ for _ in ()).throw(RuntimeError("registry broken")))

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, f"[ERROR] {SCENE} validation unusable - not escalated")
    assert rec == []


def test_scene_without_actions_is_not_escalated(app):
    app.find_scene_in_inventory(SCENE)["actions"] = []
    activate(app)

    app.run_scheduled()

    assert app.service_calls == []
    assert has_log(app, f"[ERROR] {SCENE} validation unusable - not escalated")


def test_legacy_string_actions_still_retrigger(app):
    app.find_scene_in_inventory(SCENE)["actions"] = ["ResourceIdentifier(...)"]
    activate(app)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == [{"entity_id": SCENE}]


def test_dynamic_scene_missed_lamp_skips_retrigger_goes_level3(app):
    app.attributes[SCENE] = {"is_dynamic": True}
    activate(app)
    set_lamp(app, LAMP_A, "off", -3600)      # missed
    set_lamp(app, LAMP_B, "on", 2, 40)       # owner dimmed (invisible to on/off-only)

    app.run_scheduled()

    assert calls(app, "scene/turn_on") == []
    assert calls(app, "light/turn_on") == [{"entity_id": LAMP_A}]
    assert light_targets(app) == [LAMP_A]


def test_hue_scene_missing_from_registry_logs_info_once(make_app):  # noqa: F811
    app = make_app({})
    new_scene = "scene.room_a_created_later"
    app.attributes[new_scene] = {"group_name": "Room A", "group_type": "room"}
    app.logs.clear()

    activate_scene(app, new_scene)
    app.now = app.now.replace(minute=1)
    activate_scene(app, new_scene)

    infos = [m for lvl, m in app.logs if lvl == "INFO" and new_scene in m]
    assert infos == [f"[INFO] {new_scene} not in entity registry mapping - "
                     "restart AppDaemon to validate it"]
    assert app.scheduled == []
