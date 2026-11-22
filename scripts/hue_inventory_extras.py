"""Pure helpers for the Hue bridge inventory (rooms/zones, buttons, v1 rules, behaviors).

Everything here duck-types on aiohue objects (``.type.value`` etc.) so it can be
tested without aiohue installed. Only ``fetch_v1`` does I/O (aiohttp, imported lazily).
"""


def _val(x):
    """Return enum .value if present, else the object itself."""
    return getattr(x, "value", x)


def _refs(items):
    return [{"rid": r.rid, "rtype": _val(r.rtype)} for r in (items or [])]


def split_groups(groups):
    """Split groups into (rooms, zones) by type value."""
    rooms = [g for g in groups if _val(g.type) == "room"]
    zones = [g for g in groups if _val(g.type) == "zone"]
    return rooms, zones


def serialize_group(group):
    meta = getattr(group, "metadata", None)
    return {
        "id": group.id,
        "id_v1": getattr(group, "id_v1", None),
        "type": _val(group.type),
        "metadata": {
            "name": getattr(meta, "name", None),
            "archetype": _val(getattr(meta, "archetype", None)),
        } if meta is not None else {},
        "children": _refs(getattr(group, "children", None)),
        "services": _refs(getattr(group, "services", None)),
    }


def device_extras(device):
    return {
        "id_v1": getattr(device, "id_v1", None),
        "services_structured": _refs(getattr(device, "services", None)),
    }


def serialize_buttons(buttons):
    out = []
    for b in buttons:
        owner = getattr(b, "owner", None)
        meta = getattr(b, "metadata", None)
        out.append({
            "id": b.id,
            "owner_rid": getattr(owner, "rid", owner),
            "control_id": getattr(meta, "control_id", None),
        })
    return out


def sanitize_v1_rules(rules):
    """Copy v1 rules without their ``owner`` field (a bridge username)."""
    return {rid: {k: v for k, v in rule.items() if k != "owner"}
            for rid, rule in rules.items()}


def serialize_v1_sensors(sensors):
    return {sid: {"name": s.get("name"), "type": s.get("type"),
                  "uniqueid": s.get("uniqueid")}
            for sid, s in sensors.items()}


def serialize_behaviors(instances, scripts):
    names = {s.id: getattr(getattr(s, "metadata", None), "name", None) for s in scripts}
    return [{
        "id": i.id,
        "name": getattr(getattr(i, "metadata", None), "name", None),
        "script_name": names.get(i.script_id),
        "enabled": i.enabled,
        "configuration": i.configuration,
    } for i in instances]


async def fetch_v1(bridge_ip, username):
    """Fetch v1 rules and sensors (read-only). Bridge cert is self-signed."""
    import aiohttp

    base = f"https://{bridge_ip}/api/{username}"
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base}/rules", ssl=False) as r:
            rules = await r.json()
        async with session.get(f"{base}/sensors", ssl=False) as r:
            sensors = await r.json()
    return {"rules": sanitize_v1_rules(rules), "sensors": serialize_v1_sensors(sensors)}
