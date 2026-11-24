# Scripts

## Inventory format (`inventory-hue-bridge.py`)

Changes are additive; existing keys keep their format.

- `resources.groups.rooms.items[]` / `resources.groups.zones.items[]`:
  `{id, id_v1, type, metadata: {name, archetype}, children: [{rid, rtype}], services: [{rid, rtype}]}`
- `resources.devices.items[]` additionally: `id_v1`, `services_structured: [{rid, rtype}]`
- `resources.buttons.items[]`: `{id, owner_rid, control_id}`
- `resources.v1.rules`: dict keyed by v1 rule id, as returned by the bridge minus `owner`
  (a bridge username). `resources.v1.sensors`: `{id: {name, type, uniqueid}}`
- `resources.behaviors.items[]`: `{id, name, script_name, enabled, configuration}`

Each block is collected in its own try/except; a failure yields `{"error": "..."}` for
that key only. Helpers live in `hue_inventory_extras.py`; tests in `scripts/tests`.
