"""I1: duplicate inventories of one bridge (renamed bridge, old file left behind)."""

import json

from scene_validator import SceneValidator

BRIDGE = "abc123def456"
GROUP = "11111111-1111-1111-1111-111111111111"


def inventory(bridge_id, inventoried_at, scene_name):
    return {
        "bridge_info": {"inventoried_at": inventoried_at,
                        "config": {"bridge_id": bridge_id, "name": "Bridge_Test"}},
        "resources": {"scenes": {"items": [{
            "id": "aaaa", "type": "scene", "metadata": {"name": scene_name},
            "group": {"rid": GROUP, "rtype": "room"}, "actions": [],
        }]}},
    }


def load(tmp_path, files):
    inventory_dir = tmp_path / "inventories"
    inventory_dir.mkdir()
    for name, data in files.items():
        (inventory_dir / name).write_text(json.dumps(data))
    app = SceneValidator()
    app.inventory_dir = str(inventory_dir)
    app.inventories = []
    assert app.load_inventories() is True
    return app


def scene_names(app):
    return [s["metadata"]["name"] for inv in app.inventories
            for s in inv["resources"].get("scenes", {}).get("items", [])]


def test_duplicate_inventory_files_keep_newest(tmp_path):
    app = load(tmp_path, {
        "Bridge_Old-abc123def456.json": inventory(BRIDGE, "2026-10-01T10:00:00", "Old"),
        "Bridge_New-abc123def456.json": inventory(BRIDGE, "2026-11-20T10:00:00", "New"),
    })

    assert scene_names(app) == ["New"]
    assert any(level == "WARNING" and f"[WARN] duplicate inventory for bridge {BRIDGE} ignored"
               in m and "Bridge_Old-abc123def456.json" in m for level, m in app.logs)


def test_newest_wins_regardless_of_file_order(tmp_path):
    app = load(tmp_path, {
        "a.json": inventory(BRIDGE, "2026-11-20T10:00:00", "New"),
        "b.json": inventory(BRIDGE, "2026-10-01T10:00:00", "Old"),
    })

    assert scene_names(app) == ["New"]


def test_different_bridges_are_all_kept(tmp_path):
    app = load(tmp_path, {
        "one.json": inventory(BRIDGE, "2026-11-20T10:00:00", "One"),
        "two.json": inventory("xyz789ghi012", "2026-11-20T10:00:00", "Two"),
        "noid.json": {"bridge_info": {}, "resources": {}},
    })

    assert sorted(scene_names(app)) == ["One", "Two"]
    assert len(app.inventories) == 3
