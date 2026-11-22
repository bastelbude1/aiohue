"""A validation must not fight a newer scene the user activated on the same lights."""

import json

import pytest

from scene_validator import SceneValidator

GROUP = "11111111-1111-1111-1111-111111111111"
SELECT = "select.buro_buro_szene"
STANDARD = "scene.buro_arbeiten_standard"
ABENDS = "scene.buro_arbeiten_abends"
LIGHT = "light.buro_ecklampe"


def scene(scene_id, name, brightness):
    return {
        "id": scene_id,
        "type": "scene",
        "metadata": {"name": name},
        "group": f"ResourceIdentifier(rid='{GROUP}', rtype=<ResourceTypes.ROOM: 'room'>)",
        "actions": [{
            "target": {"rid": "light-1", "rtype": "light"},
            "action": {"on": {"on": True}, "dimming": {"brightness": brightness}},
        }],
    }


@pytest.fixture
def app(tmp_path):
    inventory_dir = tmp_path / "inventories"
    inventory_dir.mkdir()
    (inventory_dir / "bridge.json").write_text(json.dumps({
        "bridge_info": {"config": {"name": "Bridge_Test"}},
        "resources": {"scenes": {"items": [
            scene("aaaa", "Arbeiten Standard", 100.0),
            scene("bbbb", "Arbeiten Abends", 40.0),
        ]}},
    }))
    registry = tmp_path / "core.entity_registry"
    registry.write_text(json.dumps({"data": {"entities": [
        {"entity_id": STANDARD, "unique_id": "aaaa", "platform": "hue"},
        {"entity_id": ABENDS, "unique_id": "bbbb", "platform": "hue"},
        {"entity_id": LIGHT, "unique_id": "light-1", "platform": "hue"},
        {"entity_id": SELECT, "unique_id": f"{GROUP}_scene_select", "platform": "hue"},
    ]}}))

    validator = SceneValidator(states={STANDARD: "unknown", ABENDS: "unknown", SELECT: "unknown"})
    validator.args = {
        "inventory_dir": str(inventory_dir),
        "entity_registry_path": str(registry),
        "scene_filter": {"name_patterns": [".*Standard$"]},
    }
    validator.attributes = {STANDARD: {"friendly_name": "Buero Arbeiten Standard"},
                            ABENDS: {"friendly_name": "Buero Arbeiten Abends"}}
    validator.initialize()
    return validator


def retriggered_scenes(app):
    return [kw.get("entity_id") for service, kw in app.service_calls if service == "scene/turn_on"]


def test_newer_scene_on_same_lights_cancels_pending_validation(app):
    # Observed on prod: Standard, then 1s later Abends (not validated itself);
    # the pending Standard validation re-triggered Standard over the user's choice.
    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Standard", {})
    app.on_select_state_changed(SELECT, "state", "Arbeiten Standard", "Arbeiten Abends", {})

    app.run_scheduled()

    assert retriggered_scenes(app) == []
    assert app.service_calls == []


def test_newer_scene_during_escalation_stops_level3(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Standard", {})
    first_callback, kwargs = app.callbacks.pop(0)
    first_callback(kwargs)  # Level 1 fails -> Level 2 re-trigger scheduled
    assert retriggered_scenes(app) == [STANDARD]

    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Abends", {})
    app.run_scheduled()

    assert retriggered_scenes(app) == [STANDARD]
    assert [s for s, _ in app.service_calls if s.startswith("light/")] == []


def test_reactivation_after_superseded_validation_is_not_debounced(app):
    # Observed on ha-test: Standard, Abends, (Standard validation skipped),
    # Standard again - the second Standard was swallowed by the debounce.
    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Standard", {})
    app.on_select_state_changed(SELECT, "state", "Arbeiten Standard", "Arbeiten Abends", {})
    app.run_scheduled()
    assert retriggered_scenes(app) == []

    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Standard", {})
    app.run_scheduled()

    assert STANDARD in retriggered_scenes(app)


def test_same_scene_reported_twice_still_validates(app):
    # HA-initiated: scene.* then select report the same scene - must not cancel.
    app.on_scene_state_changed(STANDARD, "state", "unknown", "2026-11-22T17:00:00", {})
    app.on_select_state_changed(SELECT, "state", "unknown", "Arbeiten Standard", {})

    app.run_scheduled()

    # Light state is unknown in the fake, so validation fails and escalates.
    assert STANDARD in retriggered_scenes(app)
