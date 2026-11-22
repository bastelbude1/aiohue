"""Resolve a Hue scene select entity's option to the exact scene.* entity."""

import pytest

from scene_validator import resolve_scene_entity_from_select

GROUP = "11111111-1111-1111-1111-111111111111"
OTHER_GROUP = "22222222-2222-2222-2222-222222222222"


def scene(scene_id, name, group_rid):
    # Inventories store the group as the aiohue ResourceIdentifier repr string.
    return {
        "id": scene_id,
        "type": "scene",
        "metadata": {"name": name},
        "group": f"ResourceIdentifier(rid='{group_rid}', rtype=<ResourceTypes.ROOM: 'room'>)",
        "actions": [],
    }


def inventory(*scenes):
    return [{"resources": {"scenes": {"items": list(scenes)}}}]


def test_resolves_option_to_scene_entity_of_same_group():
    inventories = inventory(
        scene("aaaa", "Standard", GROUP),
        scene("bbbb", "Standard", OTHER_GROUP),
    )
    registry = {"aaaa": "scene.keller_standard", "bbbb": "scene.buro_standard"}

    result = resolve_scene_entity_from_select(
        f"{GROUP}_scene_select", "Standard", inventories, registry
    )

    assert result == "scene.keller_standard"


@pytest.mark.parametrize(
    ("select_uid", "option"),
    [
        pytest.param(f"{GROUP}_scene_select", "Smart Szene", id="option_not_in_inventory"),
        pytest.param(f"{OTHER_GROUP}_scene_select", "Standard", id="scene_only_in_other_group"),
    ],
)
def test_unresolvable_option_returns_none(select_uid, option):
    inventories = inventory(scene("aaaa", "Standard", GROUP))
    registry = {"aaaa": "scene.keller_standard"}

    assert resolve_scene_entity_from_select(select_uid, option, inventories, registry) is None


def test_duplicate_names_in_group_are_numbered_like_home_assistant():
    # HA sorts by (name, scene_id) and suffixes repeats with " (2)", " (3)", ...
    inventories = inventory(
        scene("zzzz", "Nachtlicht", GROUP),
        scene("cccc", "Nachtlicht", GROUP),
    )
    registry = {"cccc": "scene.keller_nachtlicht", "zzzz": "scene.keller_nachtlicht_2"}
    select_uid = f"{GROUP}_scene_select"

    assert (
        resolve_scene_entity_from_select(select_uid, "Nachtlicht", inventories, registry)
        == "scene.keller_nachtlicht"
    )
    assert (
        resolve_scene_entity_from_select(select_uid, "Nachtlicht (2)", inventories, registry)
        == "scene.keller_nachtlicht_2"
    )
