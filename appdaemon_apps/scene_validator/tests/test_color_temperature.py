"""Color temperature on HA 2026.x: only kelvin exists (color_temp/mired was removed)."""

import json

import pytest

from scene_validator import SceneValidator

GROUP = "11111111-1111-1111-1111-111111111111"
SELECT = "select.buro_buro_szene"
SCENE = "scene.buro_standard"
LIGHT = "light.buro_ecklampe"


@pytest.fixture
def make_app(tmp_path):
    def _make(light_state):
        inventory_dir = tmp_path / "inventories"
        inventory_dir.mkdir(exist_ok=True)
        (inventory_dir / "bridge.json").write_text(json.dumps({
            "bridge_info": {"config": {"name": "Bridge_Test"}},
            "resources": {"scenes": {"items": [{
                "id": "aaaa",
                "type": "scene",
                "metadata": {"name": "Standard"},
                "group": f"ResourceIdentifier(rid='{GROUP}', rtype=<ResourceTypes.ROOM: 'room'>)",
                "actions": [{
                    "target": {"rid": "light-1", "rtype": "light"},
                    "action": {
                        "on": {"on": True},
                        "dimming": {"brightness": 100.0},
                        "color_temperature": {"mirek": 250},
                    },
                }],
            }]}},
        }))
        registry = tmp_path / "core.entity_registry"
        registry.write_text(json.dumps({"data": {"entities": [
            {"entity_id": SCENE, "unique_id": "aaaa", "platform": "hue"},
            {"entity_id": LIGHT, "unique_id": "light-1", "platform": "hue"},
            {"entity_id": SELECT, "unique_id": f"{GROUP}_scene_select", "platform": "hue"},
        ]}}))
        app = SceneValidator(states={SCENE: "unknown", SELECT: "unknown"})
        app.full_states = {LIGHT: light_state}
        app.args = {"inventory_dir": str(inventory_dir), "entity_registry_path": str(registry)}
        app.initialize()
        return app
    return _make


def light_turn_on_calls(app):
    return [kw for service, kw in app.service_calls if service == "light/turn_on"]


def test_level3_sends_color_temp_kelvin_not_mired(make_app):
    app = make_app({"state": "off", "attributes": {}})

    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    app.run_scheduled()

    calls = light_turn_on_calls(app)
    assert calls, "Level 3 should control the light individually"
    assert calls[0]["color_temp_kelvin"] == 4000
    assert "color_temp" not in calls[0]


def test_wrong_color_temperature_is_detected_from_kelvin_attribute(make_app):
    # HA 2026.x state has color_temp_kelvin only; 2000 K = 500 mired, expected 250.
    app = make_app({
        "state": "on",
        "attributes": {"brightness": 255, "color_mode": "color_temp", "color_temp_kelvin": 2000},
    })

    app.on_select_state_changed(SELECT, "state", "unknown", "Standard", {})
    first_callback, kwargs = app.callbacks.pop(0)
    first_callback(kwargs)

    assert ("scene/turn_on", {"entity_id": SCENE}) in app.service_calls
