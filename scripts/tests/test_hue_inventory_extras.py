"""Tests for hue_inventory_extras (no aiohue required)."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from hue_inventory_extras import (  # noqa: E402
    device_extras,
    sanitize_v1_rules,
    serialize_behaviors,
    serialize_buttons,
    serialize_group,
    serialize_v1_sensors,
    split_groups,
)


def _group(kind, name="Room_Office"):
    return NS(
        id=f"id-{kind}",
        id_v1="/groups/1",
        type=NS(value=kind),
        metadata=NS(name=name, archetype="office"),
        children=[NS(rid="dev-1", rtype=NS(value="device"))],
        services=[NS(rid="gl-1", rtype=NS(value="grouped_light"))],
    )


def test_split_groups_uses_enum_value():
    rooms, zones = split_groups([_group("room"), _group("zone"), _group("bridge_home")])
    assert len(rooms) == 1 and len(zones) == 1


def test_serialize_group_structures_children_and_services():
    out = serialize_group(_group("room"))
    assert out["children"] == [{"rid": "dev-1", "rtype": "device"}]
    assert {"rid": "gl-1", "rtype": "grouped_light"} in out["services"]
    assert out["id_v1"] == "/groups/1"
    assert out["metadata"]["name"] == "Room_Office"
    assert out["type"] == "room"


def test_serialized_rooms_work_with_query_name_filter():
    spec = importlib.util.spec_from_file_location(
        "query_hue_inventory", SCRIPTS / "query-hue-inventory.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.filter_by_name([serialize_group(_group("room"))], "room_*")) == 1


def test_sanitize_v1_rules_drops_owner():
    rules = {"1": {"name": "r", "owner": "abc123def456",
                   "conditions": [{"a": 1}], "actions": [{"b": 2}]}}
    out = sanitize_v1_rules(rules)
    assert "owner" not in out["1"]
    assert out["1"]["conditions"] == [{"a": 1}]
    assert out["1"]["actions"] == [{"b": 2}]
    assert "owner" in rules["1"]  # input not mutated


def test_serialize_buttons_keeps_control_id_and_owner():
    b = NS(id="b1", owner=NS(rid="dev-1", rtype=NS(value="device")),
           metadata=NS(control_id=2))
    assert serialize_buttons([b]) == [{"id": "b1", "owner_rid": "dev-1", "control_id": 2}]


def test_device_extras():
    d = NS(id_v1="/lights/3", services=[NS(rid="x", rtype=NS(value="light"))])
    assert device_extras(d) == {"id_v1": "/lights/3",
                                "services_structured": [{"rid": "x", "rtype": "light"}]}


def test_serialize_v1_sensors():
    out = serialize_v1_sensors({"5": {"name": "n", "type": "ZLLSwitch",
                                      "uniqueid": "u", "config": {"x": 1}}})
    assert out == {"5": {"name": "n", "type": "ZLLSwitch", "uniqueid": "u"}}


def test_serialize_behaviors():
    inst = NS(id="i1", metadata=NS(name="Auto"), script_id="s1", enabled=True,
              configuration={"k": "v"})
    scripts = [NS(id="s1", metadata=NS(name="Motion"))]
    assert serialize_behaviors([inst], scripts) == [
        {"id": "i1", "name": "Auto", "script_name": "Motion",
         "enabled": True, "configuration": {"k": "v"}}]


# ---- fetch_v1 (fake bridge, no network) ----
import asyncio  # noqa: E402
import types  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

import pytest  # noqa: E402

import hue_inventory_extras as extras  # noqa: E402

USER = "secretuser123"


@pytest.fixture(autouse=True)
def fake_aiohttp(monkeypatch):
    mod = types.ModuleType("aiohttp")
    mod.ClientTimeout = lambda total: ("timeout", total)
    monkeypatch.setitem(sys.modules, "aiohttp", mod)


class FakeBridge:
    def __init__(self, responses=None, exc=None):
        self.responses, self.exc, self.calls = responses or {}, exc, []

    @asynccontextmanager
    async def create_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if self.exc:
            raise self.exc
        data = self.responses[path.rsplit("/", 1)[1]]

        async def _json():
            return data
        yield NS(status=200, json=_json)


def test_fetch_v1_returns_sanitized_rules_and_sensors():
    b = FakeBridge({
        "rules": {"1": {"name": "r", "owner": USER, "conditions": [], "actions": []}},
        "sensors": {"2": {"name": "s", "type": "ZLLSwitch", "uniqueid": "u", "x": 1}},
    })
    out = asyncio.run(extras.fetch_v1(b, USER))
    assert "owner" not in out["rules"]["1"]
    assert out["sensors"] == {"2": {"name": "s", "type": "ZLLSwitch", "uniqueid": "u"}}
    assert all(c[2]["timeout"] == ("timeout", 10) for c in b.calls)


def test_fetch_v1_list_error_raises_without_username():
    b = FakeBridge({"rules": [{"error": {"type": 1, "description": "unauthorized user"}}]})
    with pytest.raises(ValueError) as ei:
        asyncio.run(extras.fetch_v1(b, USER))
    assert USER not in str(ei.value)
    assert "unauthorized user" in str(ei.value)


def test_fetch_v1_exception_text_has_no_username():
    b = FakeBridge(exc=OSError(f"Cannot connect https://192.168.1.100/api/{USER}/rules"))
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(extras.fetch_v1(b, USER))
    assert USER not in str(ei.value) and "192.168" not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


class StatusBridge:
    def __init__(self, status):
        self.status = status

    @asynccontextmanager
    async def create_request(self, method, path, **kwargs):
        async def _json():
            return {}
        yield NS(status=self.status, json=_json)


def test_fetch_v1_http_error_keeps_status():
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(extras.fetch_v1(StatusBridge(403), USER))
    assert str(ei.value) == "HTTP 403"
    assert USER not in str(ei.value)
