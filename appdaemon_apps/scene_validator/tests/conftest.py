"""Test setup: stub the AppDaemon API so scene_validator imports without AppDaemon."""

import sys
import types
from datetime import datetime, timezone
from pathlib import Path


class FakeHass:
    """Minimal stand-in for appdaemon.plugins.hass.hassapi.Hass."""

    def __init__(self, states=None, attributes=None):
        self.args = {}
        self.states = states or {}
        self.attributes = attributes or {}
        self.scheduled = []
        self.listeners = []
        self.logs = []
        self.service_calls = []
        self.now = datetime(2026, 11, 22, 18, 0, 0, tzinfo=timezone.utc)

    def get_now(self):
        return self.now

    def log(self, msg, level="INFO", **_kwargs):
        self.logs.append((level, msg))

    def error(self, msg, **_kwargs):
        self.logs.append(("ERROR", msg))

    def run_in(self, callback, delay, **kwargs):
        self.scheduled.append((callback.__name__, delay, kwargs))
        self.callbacks = getattr(self, "callbacks", []) + [(callback, kwargs)]

    def run_scheduled(self):
        """Run all pending scheduled callbacks (including ones they schedule)."""
        while getattr(self, "callbacks", []):
            callback, kwargs = self.callbacks.pop(0)
            callback(kwargs)

    def call_service(self, service, **kwargs):
        self.service_calls.append((service, kwargs))

    def listen_state(self, callback, entity_id, **_kwargs):
        self.listeners.append((callback.__name__, entity_id))

    def get_state(self, entity_id=None, attribute=None, **_kwargs):
        if attribute == "all":
            return getattr(self, "full_states", {}).get(entity_id)
        if attribute is not None:
            return self.attributes.get(entity_id, {}).get(attribute)
        if entity_id in ("scene", "select"):
            return {e: s for e, s in self.states.items() if e.startswith(entity_id + ".")}
        return self.states.get(entity_id)

    def friendly_name(self, entity_id):
        return self.attributes.get(entity_id, {}).get("friendly_name", entity_id)


hassapi = types.ModuleType("appdaemon.plugins.hass.hassapi")
hassapi.Hass = FakeHass
for name in ("appdaemon", "appdaemon.plugins", "appdaemon.plugins.hass"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["appdaemon.plugins.hass.hassapi"] = hassapi
sys.modules["appdaemon.plugins.hass"].hassapi = hassapi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
