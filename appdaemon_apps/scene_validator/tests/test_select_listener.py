"""Scene activations reported via Hue select entities trigger validation."""

import json

import pytest

from scene_validator import SceneValidator

GROUP = "11111111-1111-1111-1111-111111111111"
SELECT = "select.keller_keller_szene"
SCENE = "scene.keller_standard"


def make_app(tmp_path, states):
    inventory_dir = tmp_path / "inventories"
    inventory_dir.mkdir()
    (inventory_dir / "bridge.json").write_text(json.dumps({
        "bridge_info": {"config": {"name": "Bridge_Test"}},
        "resources": {"scenes": {"items": [{
            "id": "aaaa",
            "type": "scene",
            "metadata": {"name": "Standard"},
            "group": f"ResourceIdentifier(rid='{GROUP}', rtype=<ResourceTypes.ROOM: 'room'>)",
            "actions": [],
        }]}},
    }))
    registry = tmp_path / "core.entity_registry"
    registry.write_text(json.dumps({"data": {"entities": [
        {"entity_id": SCENE, "unique_id": "aaaa", "platform": "hue"},
        {"entity_id": SELECT, "unique_id": f"{GROUP}_scene_select", "platform": "hue"},
    ]}}))

    validator = SceneValidator(states=states)
    validator.args = {
        "inventory_dir": str(inventory_dir),
        "entity_registry_path": str(registry),
    }
    validator.initialize()
    return validator


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path, {SCENE: "2026-11-01T10:00:00", SELECT: "unknown"})


def test_listeners_do_not_depend_on_ha_states_at_startup(tmp_path):
    # AppDaemon may call initialize() before HA states are loaded (startup race).
    app = make_app(tmp_path, states={})

    assert ("on_select_state_changed", SELECT) in app.listeners
    assert ("on_scene_state_changed", SCENE) in app.listeners


def validations(app):
    return [kw["scene_entity"] for name, _delay, kw in app.scheduled if name == "perform_scene_validation"]


def test_initialize_listens_to_hue_scene_select_entities(app):
    assert ("on_select_state_changed", SELECT) in app.listeners


def test_select_change_schedules_validation_of_resolved_scene(app):
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})

    assert validations(app) == [SCENE]


def test_ha_activation_reported_by_scene_and_select_validates_once(app):
    # HA-initiated: scene.* timestamp changes, then the bridge reports it via select.
    app.on_scene_state_changed(SCENE, "state", "2026-11-01T10:00:00", "2026-11-22T17:00:00", {})
    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})

    assert validations(app) == [SCENE]
