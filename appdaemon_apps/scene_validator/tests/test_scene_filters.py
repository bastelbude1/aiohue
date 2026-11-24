"""I2: scene_filter exclude_uids and include/exclude labels from the entity registry."""

import json

import pytest

from scene_validator import SceneValidator

GROUP = "11111111-1111-1111-1111-111111111111"
LABELLED = "scene.room_a_relax"
PLAIN = "scene.room_a_read"
OLD_TS = "2026-11-01T10:00:00+00:00"


def scene(scene_id, name):
    return {"id": scene_id, "type": "scene", "metadata": {"name": name},
            "group": {"rid": GROUP, "rtype": "room"}, "actions": []}


@pytest.fixture
def make_app(tmp_path):
    def _make(scene_filter):
        inventory_dir = tmp_path / "inventories"
        inventory_dir.mkdir(exist_ok=True)
        (inventory_dir / "bridge.json").write_text(json.dumps({
            "bridge_info": {"config": {"name": "Bridge_Test"}},
            "resources": {"scenes": {"items": [scene("aaaa", "Relax"), scene("bbbb", "Read")]}},
        }))
        registry = tmp_path / "core.entity_registry"
        registry.write_text(json.dumps({"data": {"entities": [
            {"entity_id": LABELLED, "unique_id": "aaaa", "platform": "hue",
             "labels": ["no_check", "evening"]},
            {"entity_id": PLAIN, "unique_id": "bbbb", "platform": "hue", "labels": []},
        ]}}))
        app = SceneValidator(states={LABELLED: OLD_TS, PLAIN: OLD_TS})
        app.args = {"inventory_dir": str(inventory_dir), "entity_registry_path": str(registry),
                    "scene_filter": scene_filter}
        app.initialize()
        return app
    return _make


def activate(app, entity):
    app.on_scene_state_changed(entity, "state", OLD_TS, app.get_now().isoformat(), {})


def validations(app):
    return [kw["scene_entity"] for name, _d, kw in app.scheduled
            if name == "perform_scene_validation"]


def test_exclude_uids_excludes_scene(make_app):
    app = make_app({"exclude_uids": ["aaaa"]})

    activate(app, LABELLED)
    activate(app, PLAIN)

    assert validations(app) == [PLAIN]


def test_exclude_labels_from_registry(make_app):
    app = make_app({"exclude_labels": ["no_check"]})

    activate(app, LABELLED)
    activate(app, PLAIN)

    assert validations(app) == [PLAIN]


def test_include_labels_from_registry(make_app):
    app = make_app({"include_labels": ["evening"]})

    activate(app, LABELLED)
    activate(app, PLAIN)

    assert validations(app) == [LABELLED]
