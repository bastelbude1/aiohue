"""
AppDaemon Scene Validator for Philips Hue Integration

Validates Hue scene activations in Home Assistant with 3-level escalation
and intelligent fallback mechanisms. Detects scene activations from ANY
source (HA UI, Hue app, physical switches, Hue automations) via the Hue
active-scene select entities (HA 2026.10+) plus scene.* state changes.

Features:
- Scene detection from HA (scene.*) and from outside HA (Hue select.*)
- 3-level escalation (validate → re-trigger → individual control)
- Intelligent debouncing (prevents duplicate validations)
- Entity mapping (Hue resource ID ↔ HA entity_id)
- Circuit breaker (kill switch for runaway validations)
- Rate limiting (per-scene and global)
- Scene filtering (labels, patterns, exclusions)
- Room-off validation (optional): after a Hue switch press that switches a
  room off, verify the room's lights went off and switch off any that missed

Requirements:
- AppDaemon 4.x
- Home Assistant with Hue integration
- Hue bridge inventories in /homeassistant/hue_inventories/ (room-off
  validation needs inventories with v1 rules from scripts/inventory-hue-bridge.py)

Author: Scene Validator
Version: 2.5.1 (PR #20 review fixes: event ordering, attribution, evidence windows)
"""

__VERSION__ = "2.5.1"

import appdaemon.plugins.hass.hassapi as hass
import json
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Set, Tuple

SCENE_SELECT_SUFFIX = "_scene_select"


def _mired_to_kelvin(mired: float) -> int:
    """Hue scenes store mired; HA 2026.x light.turn_on only accepts color_temp_kelvin."""
    return round(1_000_000 / mired)


def _actual_mired(attrs: Dict[str, Any]) -> Optional[float]:
    """Light's color temperature in mired (HA 2026.x states only have color_temp_kelvin)."""
    if attrs.get('color_temp'):
        return attrs['color_temp']
    kelvin = attrs.get('color_temp_kelvin')
    return 1_000_000 / kelvin if kelvin else None
_GROUP_RID_RE = re.compile(r"rid='([^']+)'")


def _scene_group_rid(scene: Dict[str, Any]) -> Optional[str]:
    """Return the group id of an inventory scene (dict or ResourceIdentifier repr)."""
    group = scene.get('group')
    if isinstance(group, dict):
        return group.get('rid')
    if isinstance(group, str):
        match = _GROUP_RID_RE.search(group)
        return match.group(1) if match else None
    return None


def build_scene_option_map(
    select_unique_id: str,
    inventories: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    {select option name: Hue scene id} for the group of a Hue scene select.

    The select entity only exposes scene names, and Hue allows duplicate names
    within a group. Rebuilds the option names exactly like Home Assistant's
    hue/v2/select.py (_build_scene_option_maps): sort by (name, id), suffix
    repeats with " (2)", " (3)", ... - so each option maps to one scene ID.
    """
    group_id = select_unique_id[:-len(SCENE_SELECT_SUFFIX)]
    # One entry per scene id: a scene listed twice must not take an extra " (n)" slot
    names_by_id: Dict[str, str] = {}
    for inventory in inventories:
        for scene in inventory.get('resources', {}).get('scenes', {}).get('items', []):
            if _scene_group_rid(scene) == group_id and scene.get('id') not in names_by_id:
                names_by_id[scene.get('id')] = scene.get('metadata', {}).get('name', '')
    group_scenes = sorted((name, scene_id) for scene_id, name in names_by_id.items())
    option_to_scene_id: Dict[str, str] = {}
    for name, scene_id in group_scenes:
        candidate = name
        repeat = 1
        while candidate in option_to_scene_id:
            repeat += 1
            candidate = f"{name} ({repeat})"
        option_to_scene_id[candidate] = scene_id
    return option_to_scene_id


def resolve_scene_entity_from_select(
    select_unique_id: str,
    option: str,
    inventories: List[Dict[str, Any]],
    hue_id_to_entity_id: Dict[str, str],
) -> Optional[str]:
    """Map a Hue scene select option to the exact scene.* entity_id via scene ID."""
    scene_id = build_scene_option_map(select_unique_id, inventories).get(option)
    return hue_id_to_entity_id.get(scene_id) if scene_id else None


V1_EVENT_TYPES = {0: "initial_press", 1: "repeat", 2: "short_release", 3: "long_release"}

_V1_BUTTON_COND_RE = re.compile(r"^(/sensors/\d+)/state/buttonevent$")
_V1_GROUP_ACTION_RE = re.compile(r"^(/groups/\d+)/action$")


def _items(inventory: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Items of resources.<key>, or of resources.groups.<key> for rooms/zones."""
    resources = inventory.get('resources', {})
    if key in ('rooms', 'zones'):
        resources = resources.get('groups', {})
        resources = resources if isinstance(resources, dict) else {}
    section = resources.get(key, {})
    items = section.get('items') if isinstance(section, dict) else None
    return items if isinstance(items, list) else []


def _rule_button_codes(rule: Dict[str, Any]) -> List[tuple]:
    """(sensor_v1, code) pairs from the rule's buttonevent 'eq' conditions."""
    pairs = []
    for cond in rule.get('conditions') or []:
        match = _V1_BUTTON_COND_RE.match(str(cond.get('address', '')))
        if match and cond.get('operator') == 'eq':
            try:
                pairs.append((match.group(1), int(cond.get('value'))))
            except (TypeError, ValueError):
                continue
    return pairs


def _group_lights(group: Dict[str, Any], devices_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    """Hue light rids of a room (via child devices) or zone (direct light children)."""
    rids: List[str] = []
    for child in group.get('children') or []:
        if child.get('rtype') == 'light':
            rids.append(child.get('rid'))
        elif child.get('rtype') == 'device':
            device = devices_by_id.get(child.get('rid'), {})
            rids.extend(s.get('rid') for s in device.get('services_structured') or []
                        if s.get('rtype') == 'light')
    return [rid for rid in rids if rid]


def _only_harmless_conditions(rule: Dict[str, Any], sensor_v1: str, code: int,
                              group_v1: str) -> bool:
    """True if every condition of an off-rule only says "this button was pressed".

    Allowed: the rule's own buttonevent eq <code>, its sensor's lastupdated dx,
    and "<own group>/state/any_on eq true". Anything else (time, CLIP status,
    presence, ...) can make the bridge skip the rule on a press. ddx is not
    harmless: the bridge fires later, and a newer event cancels it.
    """
    for cond in rule.get('conditions') or []:
        address = str(cond.get('address', ''))
        operator = cond.get('operator')
        value = str(cond.get('value', '')).lower()
        if address == f"{sensor_v1}/state/buttonevent" and operator == 'eq' and value == str(code):
            continue
        if address == f"{sensor_v1}/state/lastupdated" and operator == 'dx':
            continue
        if address == f"{group_v1}/state/any_on" and operator == 'eq' and value == 'true':
            continue
        return False
    return True


def build_off_jobs(
    inventories: List[Dict[str, Any]],
    hue_id_to_entity_id: Dict[str, str],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build {HA button event entity_id: [room-off jobs]} from enabled v1 rules.

    A rule "buttonevent eq <code> -> PUT /groups/<n>/action {on: false}" becomes
    a job for the room/zone with id_v1 /groups/<n>. v1 ids are per bridge, so
    each inventory is resolved on its own. A rule with any broken link in the
    chain is skipped. A job is ambiguous when another enabled rule on the same
    sensor and code does something other than switching a group off, or when
    the off-rule itself has a condition beyond the button press (only an
    unconditional off-rule makes a press a certain room-off).
    """
    jobs: Dict[str, List[Dict[str, Any]]] = {}
    for inventory in inventories:
        v1 = inventory.get('resources', {}).get('v1')
        rules = v1.get('rules') if isinstance(v1, dict) else None
        if not isinstance(rules, dict):
            continue
        devices_by_id = {d.get('id'): d for d in _items(inventory, 'devices')}
        devices_by_v1 = {d.get('id_v1'): d for d in _items(inventory, 'devices') if d.get('id_v1')}
        groups_by_v1 = {g.get('id_v1'): g for key in ('rooms', 'zones')
                        for g in _items(inventory, key) if g.get('id_v1')}
        buttons = _items(inventory, 'buttons')

        def is_off(action: Dict[str, Any]) -> bool:
            body = action.get('body') or {}
            return (bool(_V1_GROUP_ACTION_RE.match(str(action.get('address', ''))))
                    and body.get('on') is False)

        enabled = [r for r in rules.values()
                   if isinstance(r, dict) and r.get('status') == 'enabled']
        non_off_codes = {pair for r in enabled
                         if any(not is_off(a) for a in r.get('actions') or [])
                         for pair in _rule_button_codes(r)}

        for r in enabled:
            for action in r.get('actions') or []:
                match = _V1_GROUP_ACTION_RE.match(str(action.get('address', '')))
                if not (match and is_off(action)):
                    continue
                group = groups_by_v1.get(match.group(1))
                if group is None:
                    continue
                for sensor_v1, code in _rule_button_codes(r):
                    event_type = V1_EVENT_TYPES.get(code % 1000)
                    device = devices_by_v1.get(sensor_v1)
                    if event_type is None or device is None:
                        continue
                    button = next((b for b in buttons
                                   if b.get('owner_rid') == device.get('id')
                                   and b.get('control_id') == code // 1000), None)
                    entity = hue_id_to_entity_id.get(button.get('id')) if button else None
                    if not entity:
                        continue
                    pairs = [(rid, hue_id_to_entity_id[rid])
                             for rid in _group_lights(group, devices_by_id)
                             if rid in hue_id_to_entity_id]
                    job = {
                        "event_type": event_type,
                        "room_id": group.get('id'),
                        "room_name": (group.get('metadata') or {}).get('name'),
                        "lights": [e for _, e in pairs],
                        "light_rids": [rid for rid, _ in pairs],
                        "ambiguous": ((sensor_v1, code) in non_off_codes
                                      or not _only_harmless_conditions(
                                          r, sensor_v1, code, match.group(1))),
                    }
                    existing = jobs.setdefault(entity, [])
                    same = next((j for j in existing if j['event_type'] == event_type
                                 and j['room_id'] == job['room_id']), None)
                    if same is None:
                        existing.append(job)
                    else:
                        # An unconditional off-rule (and no non-off action on this
                        # sensor/code) makes the merged job a certain room-off
                        same['ambiguous'] = same['ambiguous'] and job['ambiguous']
    return jobs


def classify_off_check(
    lights_now: Dict[str, Dict[str, Any]],
    press_window_start: datetime,
    scene_activated_in_window: bool,
    ambiguous: bool,
    evidence_end: Optional[datetime] = None,
) -> Tuple[str, List[str]]:
    """Decide what a room-off check found.

    Returns ("skip_scene", []), ("skip_no_evidence", []), ("ok", []) or
    ("missed", [sorted entities]). A light is "changed" if it was updated at or
    after press_window_start; changed lights are never reported as missed.
    For ambiguous jobs only changes up to evidence_end (None: no limit) count
    as off-evidence; later changes are still "changed".
    """
    if scene_activated_in_window:
        return ("skip_scene", [])
    changed = {e for e, v in lights_now.items() if v["last_updated"] >= press_window_start}
    if ambiguous:
        evidence = {e for e in changed
                    if evidence_end is None or lights_now[e]["last_updated"] <= evidence_end}
        changed_off = [e for e in evidence if lights_now[e]["state"] == "off"]
        if not changed_off or len(changed_off) != len(evidence):
            return ("skip_no_evidence", [])
    missed = sorted(e for e, v in lights_now.items() if v["state"] == "on" and e not in changed)
    if not missed:
        return ("ok", [])
    return ("missed", missed)


def all_expected_on_lights_switched_off(
    expected_on: List[str],
    lights_now: Dict[str, Dict[str, Any]],
    activated_at: datetime,
) -> bool:
    """True if every light the scene expects ON was switched off after the activation.

    Deliberate room off (e.g. Hue app) without a switch press. Requires a
    non-empty expected_on and at least one reachable light. Unreachable lights
    (absent from lights_now, or state unavailable/unknown) are ignored. Every
    reachable one must be off with last_updated >= activated_at (a light that
    is off but unchanged missed the scene command).
    """
    reachable = [lights_now[e] for e in expected_on
                 if e in lights_now and lights_now[e]["state"] not in ("unavailable", "unknown")]
    if not reachable:
        return False
    for light in reachable:
        if light["state"] != "off" or light["last_updated"] < activated_at:
            return False
    return True


MISSED_TOLERANCE = timedelta(seconds=1)
REACTION_WINDOW = timedelta(seconds=2)  # update this soon after activation = reaction to it
OFF_EVIDENCE_WINDOW = timedelta(seconds=2)  # bridge executes an off-rule this soon after the press
PRESS_LOOKBACK = timedelta(seconds=1)  # light updates may reach HA before the button event
OFF_DEFER_MAX = 3  # times a scene step waits for a pending room-off check
OFF_DEFER_GRACE = timedelta(seconds=10)  # ... and only until this long after the check was due
OWN_RETRIGGER_ECHO = timedelta(seconds=3)  # scene.* change this soon after our own scene/turn_on


def classify_scene_failures(
    failing: List[str],
    lights_now: Dict[str, Dict[str, Any]],
    activated_at: datetime,
) -> Tuple[List[str], List[str]]:
    """Split failing scene lamps into (missed, changed).

    A lamp missed the scene command if it shows no update since the activation
    (last_updated < activated_at - 1 s); only those are corrected. Any later
    update means the owner or Hue changed it (changed: left alone). Lamps
    missing from lights_now count as neither.
    """
    missed: List[str] = []
    changed: List[str] = []
    for entity in failing:
        light = lights_now.get(entity)
        if light is None:
            continue
        if light["last_updated"] < activated_at - MISSED_TOLERANCE:
            missed.append(entity)
        else:
            changed.append(entity)
    return missed, changed


@dataclass
class SceneCheck:
    """Result of one scene validation run.

    usable: False when the scene cannot be validated (no actions, legacy
        string actions, or an error); legacy: True only for legacy string actions.
    failing: lamps that differ from the scene, in scene order.
    kinds: failure kind per failing lamp ('on_off', 'brightness', 'color', 'color_temp').
    checked: lamps actually compared (unreachable and unmapped lamps are skipped).
    """
    passed: bool
    usable: bool = True
    legacy: bool = False
    failing: List[str] = field(default_factory=list)
    kinds: Dict[str, str] = field(default_factory=dict)
    checked: int = 0


class SceneValidator(hass.Hass):
    """
    AppDaemon app that validates Hue scene activations with fallback.

    Monitors scene entity state changes to detect activations from ANY source,
    validates light states, and provides escalating fallback mechanisms.
    """

    def initialize(self):
        """
        Initialize the scene validator.

        Loads configuration, inventories, and sets up scene monitoring.
        """
        self.log(f"=== Initializing Scene Validator {__VERSION__} ===", level="WARNING")
        self.log(f"Version: {__VERSION__}", level="WARNING")

        # Configuration parameters
        self.inventory_dir = self.args.get('inventory_dir', '/homeassistant/hue_inventories')
        self.entity_registry_path = self.args.get(
            'entity_registry_path', '/homeassistant/.storage/core.entity_registry'
        )
        self.transition_delay = self.args.get('transition_delay', 5)
        self.validation_delay = self.args.get('validation_delay', 2)
        self.validation_debounce = self.args.get('validation_debounce', 30)
        self.level3_settle_delay = self.args.get('level3_settle_delay', 2)  # Delay after Level 3 control before final validation

        # Rate limiting
        self.max_validations_per_minute = self.args.get('max_validations_per_minute', 20)
        self.max_validations_per_scene_per_minute = self.args.get(
            'max_validations_per_scene_per_minute', 5
        )

        # Circuit breaker configuration
        cb_config = self.args.get('circuit_breaker', {})
        self.cb_failure_threshold = cb_config.get('failure_threshold', 5)
        self.cb_success_threshold = cb_config.get('success_threshold', 2)
        self.cb_timeout = cb_config.get('timeout', 300)

        # Scene filtering
        filter_config = self.args.get('scene_filter', {})
        self.include_labels = filter_config.get('include_labels', [])
        self.exclude_labels = filter_config.get('exclude_labels', [])
        self.exclude_uids = filter_config.get('exclude_uids', [])
        self.name_patterns = filter_config.get('name_patterns', [])

        # State tracking
        self.inventories = []
        self.hue_id_to_entity_id = {}  # Hue unique_id -> HA entity_id mapping cache
        self.entity_id_to_hue_id = {}  # reverse of hue_id_to_entity_id
        self.entity_labels = {}  # HA entity_id -> entity registry label ids
        self.unmapped_scenes_reported = set()  # Hue scenes missing from the mapping (logged once)
        self.select_entity_to_unique_id = {}  # select.*_szene -> "<group_id>_scene_select"
        self._activation_seq = 0
        self.light_last_activation = {}  # Hue light rid -> (activation seq, scene_entity)
        self.latest_scene_seq = {}  # scene_entity -> seq of its newest (non-duplicate) activation
        self.own_retrigger = {}  # scene_entity -> time of the validator's own Level 2 scene/turn_on
        self.interrupted_scenes = set()  # scenes whose lights another scene took over
        self.circuit_breaker_state = 'CLOSED'
        self.circuit_breaker_failures = 0
        self.circuit_breaker_successes = 0
        self.circuit_breaker_opened_at = None
        self.validation_timestamps = []
        self.scene_validation_timestamps = {}
        self.recent_validations = {}  # {scene_entity: timestamp}

        # Tolerances for state comparison
        self.brightness_tolerance = self.args.get('brightness_tolerance', 5)  # ±5%
        self.color_tolerance = self.args.get('color_tolerance', 0.01)  # ±0.01
        self.color_temp_tolerance = self.args.get('color_temp_tolerance', 50)  # ±50 mireds (lenient for Hue variations)

        # Room-off validation (switch press -> verify all room lights went off)
        off_config = self.args.get('off_validation') or {}
        self.off_validation_enabled = bool(off_config.get('enabled', False))
        self.off_validation_rooms = list(off_config.get('rooms') or [])
        try:
            self.off_check_delay = float(off_config.get('off_check_delay', 5))
        except (TypeError, ValueError):
            self.log("[WARN] off_check_delay invalid, using 5", level="WARNING")
            self.off_check_delay = 5.0
        self.off_jobs = {}  # event entity -> [room-off jobs] (enabled rooms only)
        self.light_activation_at = {}  # Hue light rid -> last scene activation time
        self.latest_press = {}  # room_id -> t_press of the newest press (one pending check per room)
        self.off_check_evaluated = {}  # room_id -> t_press whose off-check has run
        self.off_check_due = {}  # room_id -> scheduled time of its pending off-check

        # Debug logging - when False, only log failures and errors (not OK/success messages)
        self.debug_logging = self.args.get('debug_logging', False)

        # Load inventories
        if not self.load_inventories():
            self.error("Failed to load inventories - validator will not function")
            return

        # Load entity registry mapping (workaround for unique_id not available in state API)
        try:
            self.load_entity_registry_mapping()
        except Exception as e:  # noqa: BLE001
            self.error(f"Critical error loading entity registry: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")

        # Listen for scene activations from ANY source (HA, Hue app, switches)
        # Monitor state changes instead of call_service events
        self.setup_scene_listeners()
        self.setup_off_validation()

        self.log("Validator initialized successfully")
        self.log(f"Inventory directory: {self.inventory_dir}")
        self.log("Detection: scene.* (HA-initiated) + Hue select.* (bridge-reported)")
        if self.off_validation_enabled:
            self.log("Detection: room-off on Hue switch presses (off_validation)")
        self.log(f"Transition delay: {self.transition_delay}s")
        self.log(f"Validation delay: {self.validation_delay}s")
        self.log(f"Level 3 settle delay: {self.level3_settle_delay}s")
        self.log(f"Debounce window: {self.validation_debounce}s")
        self.log(f"Tolerances: brightness +/-{self.brightness_tolerance}%, color +/-{self.color_tolerance}, color_temp +/-{self.color_temp_tolerance} mirek")
        self.log(f"Circuit breaker: {self.cb_failure_threshold} failures / {self.cb_timeout}s timeout")

        if self.include_labels:
            self.log(f"Include labels: {self.include_labels}")
        if self.exclude_labels:
            self.log(f"Exclude labels: {self.exclude_labels}")
        if self.name_patterns:
            self.log(f"Name patterns: {self.name_patterns}")

    def _is_legacy_action_format(self, actions: List[Any]) -> bool:
        """
        Check if actions use legacy string format.

        Args:
            actions: List of action objects or strings

        Returns:
            True if actions are in legacy string format, False otherwise
        """
        return len(actions) > 0 and isinstance(actions[0], str)

    def _has_legacy_inventory_format(self) -> bool:
        """
        Check if any inventory uses legacy string-formatted actions.

        Returns:
            True if any scene has string-formatted actions, False otherwise
        """
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scenes', {}).get('items', [])
            for scene in scenes:
                actions = scene.get('actions', [])
                if self._is_legacy_action_format(actions):
                    return True
        return False

    def load_inventories(self) -> bool:
        """
        Load Hue bridge inventories from filesystem.

        Returns:
            True if at least one inventory loaded, False otherwise
        """
        inventory_path = Path(self.inventory_dir)

        if not inventory_path.exists():
            self.error(f"Inventory directory not found: {self.inventory_dir}")
            return False

        inventory_files = list(inventory_path.glob("*.json"))

        if not inventory_files:
            self.error(f"No inventory files found in: {self.inventory_dir}")
            return False

        loaded = []  # (file, inventory)
        for inventory_file in sorted(inventory_files):
            try:
                with open(inventory_file) as f:
                    loaded.append((inventory_file, json.load(f)))
            except (json.JSONDecodeError, IOError) as e:
                self.error(f"Failed to load {inventory_file.name}: {e}")

        for inventory_file, inventory in self._dedupe_inventories(loaded):
            self.inventories.append(inventory)
            # Handle nested bridge_info structure (bridge_info.config.name)
            bridge_config = inventory.get('bridge_info', {}).get('config', {})
            bridge_name = bridge_config.get('name') or inventory.get('bridge_info', {}).get('name', 'Unknown')
            self.log(f"Loaded inventory: {bridge_name} ({inventory_file.name})")

        if not self.inventories:
            self.error("No inventories loaded successfully")
            return False

        self.log(f"Loaded {len(self.inventories)} inventory file(s)")

        # Check for legacy inventory format (string-formatted actions)
        if self._has_legacy_inventory_format():
            self.log(
                "WARNING: Legacy inventory format detected (string-formatted actions). "
                "Level 1 validation will be limited. Please regenerate inventories with: "
                "python3 inventory-hue-bridge.py",
                level="WARNING"
            )

        return True

    def _dedupe_inventories(self, loaded: List[Tuple[Path, Dict[str, Any]]]
                            ) -> List[Tuple[Path, Dict[str, Any]]]:
        """Keep one inventory per bridge_info.config.bridge_id (newest inventoried_at).

        Inventories without a bridge id are all kept. Older duplicates are logged
        and ignored (e.g. a file left behind after renaming the bridge).
        """
        oldest = datetime.min.replace(tzinfo=timezone.utc)

        def bridge_id(inventory: Dict[str, Any]) -> Optional[str]:
            info = inventory.get('bridge_info')
            config = info.get('config') if isinstance(info, dict) else None
            return config.get('bridge_id') if isinstance(config, dict) else None

        def inventoried_at(inventory: Dict[str, Any]) -> datetime:
            info = inventory.get('bridge_info')
            value = info.get('inventoried_at') if isinstance(info, dict) else None
            return self._parse_ts(value) or oldest

        newest: Dict[str, Tuple[Path, Dict[str, Any]]] = {}
        for item in loaded:
            bid = bridge_id(item[1])
            if bid and (bid not in newest
                        or inventoried_at(item[1]) > inventoried_at(newest[bid][1])):
                newest[bid] = item
        kept = []
        for item in loaded:
            bid = bridge_id(item[1])
            if bid and newest[bid] is not item:
                self.log(f"[WARN] duplicate inventory for bridge {bid} ignored {item[0].name}",
                         level="WARNING")
                continue
            kept.append(item)
        return kept

    def load_entity_registry_mapping(self):
        """
        Load unique_id to entity_id mapping from entity registry.

        This is a workaround for Home Assistant's state API limitation:
        /api/states does NOT expose unique_id for ANY entity type (lights, scenes, sensors, etc.)
        even though unique_ids are present in the entity registry.

        We read the entity registry file during initialization and build a cache
        for O(1) lookup when mapping Hue resource IDs to HA entity_ids.

        Note: This reads internal HA storage which may change between versions,
        but is the only reliable way to map external IDs to entity_ids.

        Compatibility: Tested with Home Assistant 2025.11.x
        The entity registry structure (data.entities[]) has been stable since HA 2021.x,
        but future HA versions may change the internal storage format.
        """
        self.log("Loading entity registry mapping...", level="DEBUG")
        registry_file = Path(self.entity_registry_path)
        self.log(f"Registry file path: {registry_file}, exists: {registry_file.exists()}", level="DEBUG")

        if not registry_file.exists():
            self.error(f"Entity registry not found: {registry_file}")
            self.error("Entity ID mapping will not work - validation will fail")
            return

        try:
            with open(registry_file) as f:
                registry = json.load(f)

            # Validate expected structure exists
            if 'data' not in registry or 'entities' not in registry.get('data', {}):
                self.error("Entity registry structure has changed - expected 'data.entities' not found")
                self.error("This may indicate a Home Assistant update that changed the internal storage format")
                return

            entities = registry.get('data', {}).get('entities', [])

            # Build mapping for Hue platform entities only
            hue_count = 0
            for entry in entities:
                entity_id = entry.get('entity_id')
                unique_id = entry.get('unique_id')
                platform = entry.get('platform')

                # Only map Hue platform entities
                if platform == 'hue' and entity_id and unique_id:
                    self.hue_id_to_entity_id[unique_id] = entity_id
                    self.entity_id_to_hue_id[entity_id] = unique_id
                    self.entity_labels[entity_id] = list(entry.get('labels') or [])
                    if unique_id.endswith(SCENE_SELECT_SUFFIX):
                        self.select_entity_to_unique_id[entity_id] = unique_id
                    hue_count += 1

            self.log(f"Loaded entity registry mapping: {hue_count} Hue entities", level="DEBUG")
            self.log(f"Loaded entity registry mapping: {hue_count} Hue entities")

        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
            self.error(f"Failed to load entity registry: {e}")
            self.error("Entity ID mapping will not work - validation will fail")
        except Exception as e:  # noqa: BLE001
            self.error(f"Unexpected error loading entity registry: {e}")

    def setup_scene_listeners(self):
        """
        Set up state listeners for all scene entities.

        This detects scene activations from ANY source:
        - Home Assistant UI/automations
        - Hue mobile app
        - Hue physical switches/dimmers
        - Hue third-party apps

        Note: Monitors ALL scenes; filtering happens in should_validate_scene()
        based on name_patterns, labels, etc.
        """
        scene_count = 0

        # Registry entries cover Hue scenes even if initialize() runs before
        # AppDaemon has received HA states (startup race seen with 4.5.16).
        all_scenes = set(self.get_state("scene") or {}) | {
            entity_id for entity_id in self.hue_id_to_entity_id.values()
            if entity_id.startswith("scene.")
        }

        if not all_scenes:
            self.error("No scene entities found in Home Assistant or entity registry")

        for entity_id in sorted(all_scenes):
            # Monitor all scene entities - filtering happens later
            # Listen to state changes (scene state IS the activation timestamp)
            self.listen_state(self.on_scene_state_changed, entity_id)
            scene_count += 1
            self.log(f"Monitoring: {entity_id}", level="DEBUG")

        self.log(f"Monitoring {scene_count} scene(s) for activations")

        # Hue active-scene selects report activations from outside HA as well
        for select_entity in self.select_entity_to_unique_id:
            self.listen_state(self.on_select_state_changed, select_entity)
        self.log(f"Monitoring {len(self.select_entity_to_unique_id)} Hue scene select(s) "
                 f"for bridge-reported activations")

    def is_hue_scene(self, entity_id: str) -> bool:
        """
        Check if scene entity belongs to Hue integration.

        Args:
            entity_id: HA entity_id (e.g., scene.wohnzimmer_standard)

        Returns:
            True if scene is from Hue integration, False otherwise
        """
        unique_id = self.get_state(entity_id, attribute="unique_id")

        if unique_id:
            # Try unique_id approach (works for lights, sensors, etc.)
            # Check if unique_id contains any loaded Hue bridge ID
            # Bridge IDs from Hue API typically have format: "XX:XX:XX:XX:XX:XX" (MAC address)
            # HA unique_ids contain the normalized form without colons
            for inventory in self.inventories:
                bridge_id = inventory.get('bridge_info', {}).get('bridge_id', '')
                if not bridge_id:
                    continue

                # Normalize bridge ID by removing colons (handles both formats)
                normalized_bridge_id = bridge_id.replace(':', '').lower()
                if normalized_bridge_id and normalized_bridge_id in unique_id.lower():
                    return True

        # Fallback for scenes: Check for Hue-specific attributes
        # Scene entities don't expose unique_id in state API, but have Hue-specific attributes
        # like group_name and group_type that non-Hue scenes don't have
        group_name = self.get_state(entity_id, attribute="group_name")
        group_type = self.get_state(entity_id, attribute="group_type")

        # If scene has both group_name and group_type, it's a Hue scene
        # (HA-created scenes don't have these attributes)
        if group_name is not None and group_type is not None:
            return True

        return False

    def on_scene_state_changed(self, entity, _attribute, old, new, _kwargs):
        """
        Handle scene state change (detects activations from ANY source).

        This is called when scene state changes (state = activation timestamp).
        Scene activated by:
        - Home Assistant (UI, automation, voice)
        - Hue app (mobile, desktop)
        - Physical Hue switches/dimmers
        - Hue automations/routines

        Args:
            entity: Scene entity_id
            _attribute: Attribute that changed (None for state) - unused but required by callback
            old: Previous state (old timestamp)
            new: New state (new timestamp indicating activation)
            _kwargs: Additional parameters - unused but required by callback
        """
        # Skip if state didn't actually change
        if old == new or new is None or new in ("unavailable", "unknown"):
            self.log(f"Skipping {entity} - no state change", level="DEBUG")
            return
        # Restored or re-added entity (integration reload, HA restart): the state is
        # the last activation time, not a new activation. "unknown" (never activated)
        # -> fresh timestamp is a real first activation; the stale check below
        # rejects a restored old timestamp.
        if old in (None, "unavailable"):
            self.log(f"Skipping {entity} - restored state ({old} -> {new})", level="DEBUG")
            return
        own_call = self.own_retrigger.get(entity)
        if own_call is not None and timedelta(0) <= self.get_now() - own_call <= OWN_RETRIGGER_ECHO:
            # Echo of the validator's own Level 2 re-trigger: not a new activation
            self.log(f"Skipping {entity} - echo of own re-trigger", level="DEBUG")
            return
        activated = self._parse_ts(new)
        if (activated is not None
                and (self.get_now() - activated).total_seconds() > self.transition_delay):
            self.log(f"Skipping {entity} - stale activation time {new}", level="DEBUG")
            return

        self._handle_scene_activation(entity, source="scene entity (HA-initiated)",
                                      activated_at=activated)

    def on_select_state_changed(self, entity, _attribute, old, new, _kwargs):
        """
        Handle a Hue scene select change (active scene of a room/zone).

        Since HA 2026.x the Hue integration exposes the bridge-reported active
        scene per group as select.*. This is the only HA signal for activations
        from outside HA (Hue app, Hue switches, Hue automations) - the scene.*
        state only changes on HA-initiated activations.
        """
        if old == new or new is None or new in ("unavailable", "unknown"):
            self.log(f"Skipping {entity} - no active scene", level="DEBUG")
            return
        if old in (None, "unavailable"):
            # Re-added after an integration reload; unknown -> <scene> is a real activation
            self.log(f"Skipping {entity} - restored state ({old} -> {new})", level="DEBUG")
            return

        select_unique_id = self.select_entity_to_unique_id.get(entity)
        group_rids: List[str] = []
        if select_unique_id:
            # Any active-scene change is a scene step for room-off evidence, even if
            # the option cannot be resolved to a scene entity below
            now = self.get_now()
            group_rids = self._group_light_rids(select_unique_id.removesuffix(SCENE_SELECT_SUFFIX))
            for rid in group_rids:
                self.light_activation_at[rid] = now
        scene_entity = None
        option_map: Dict[str, str] = {}
        if select_unique_id:
            option_map = build_scene_option_map(select_unique_id, self.inventories)
            scene_id = option_map.get(new)
            scene_entity = self.hue_id_to_entity_id.get(scene_id) if scene_id else None
        if not scene_entity:
            self.log(f"[WARN] Could not resolve '{new}' from {entity} to a scene entity "
                     f"(smart scene or inventory outdated?)", level="WARNING")
            self._claim_unresolved(entity, group_rids)
            return
        options = self.get_state(entity, attribute="options")
        if not isinstance(options, list) or set(options) != set(option_map):
            # Names (and the " (n)" numbering of duplicates) shifted since the
            # inventory was written: the option may point to another scene
            self.log(f"[WARN] {entity} options differ from inventory - not validated "
                     f"(regenerate inventory)", level="WARNING")
            self._claim_unresolved(entity, group_rids)
            return

        self._handle_scene_activation(scene_entity, source=f"{entity} (bridge-reported)")

    def _claim_unresolved(self, select_entity: str, group_rids: List[str]):
        """An unattributable scene on the group: older chains on its lights abort."""
        if group_rids:
            self._claim_lights(f"unresolved:{select_entity}", group_rids)

    def _group_light_rids(self, group_id: str) -> List[str]:
        """Hue light rids of the room/zone with this v2 id ([] if unknown)."""
        for inventory in self.inventories:
            for key in ('rooms', 'zones'):
                for group in _items(inventory, key):
                    if group.get('id') == group_id:
                        devices_by_id = {d.get('id'): d for d in _items(inventory, 'devices')}
                        return _group_lights(group, devices_by_id)
        return []

    def _scene_light_rids(self, scene_entity: str) -> List[str]:
        """Return the Hue light rids of a scene (silent lookup, [] if unknown)."""
        hue_scene_id = self.entity_id_to_hue_id.get(scene_entity)
        if not hue_scene_id:
            return []
        for inventory in self.inventories:
            for scene in inventory.get('resources', {}).get('scenes', {}).get('items', []):
                if scene.get('id') == hue_scene_id:
                    actions = scene.get('actions', [])
                    if self._is_legacy_action_format(actions):
                        return []
                    return [a.get('target', {}).get('rid') for a in actions
                            if isinstance(a, dict) and a.get('target', {}).get('rid')]
        return []

    def _claim_lights(self, owner: str, light_rids: List[str]) -> int:
        """Mark the lights as owned by this activation; return its sequence number."""
        self._activation_seq += 1
        for rid in light_rids:
            _seq, previous_owner = self.light_last_activation.get(rid, (0, None))
            if previous_owner and previous_owner != owner:
                # A later re-activation of previous_owner is a real user choice
                self.interrupted_scenes.add(previous_owner)
            self.light_last_activation[rid] = (self._activation_seq, owner)
        return self._activation_seq

    def _record_activation(self, scene_entity: str) -> int:
        """Mark the scene's lights as owned by this activation; return its sequence number."""
        light_rids = self._scene_light_rids(scene_entity)
        now = self.get_now()
        for rid in light_rids:
            self.light_activation_at[rid] = now
        return self._claim_lights(scene_entity, light_rids)

    def _superseded_by(self, scene_entity: str, activation_seq: Optional[int]) -> Optional[str]:
        """Return the newer scene that took over any of this scene's lights, if any."""
        if activation_seq is None:
            return None
        for rid in self._scene_light_rids(scene_entity):
            seq, owner = self.light_last_activation.get(rid, (0, None))
            if seq > activation_seq and owner != scene_entity:
                return owner
        return None

    def _abort_if_superseded(self, scene_entity: str, activation_seq: Optional[int], step: str) -> bool:
        """Log and return True if a newer activation replaced this one before `step`.

        Newer means another scene (or room-off) on any of its lights, or a newer
        activation of the same scene (A -> B -> A: only the newest chain runs).
        """
        if (activation_seq is not None
                and activation_seq < self.latest_scene_seq.get(scene_entity, 0)):
            self.log(f"[{scene_entity}] [SKIP] {step} - superseded by a newer activation "
                     f"of the same scene")
            return True
        newer = self._superseded_by(scene_entity, activation_seq)
        if newer:
            self.log(f"[{scene_entity}] [SKIP] {step} aborted - superseded by newer "
                     f"activation of {newer}")
            return True
        return False

    def _pending_off_wait(self, scene_entity: str) -> Optional[Tuple[str, float, datetime]]:
        """(room, seconds to wait, check due time) if a room-off check on the scene's
        lights is still pending.

        The wait is computed from the off-check's scheduled due time (+1 s), not
        from the press time: a press delivered late is checked later.
        """
        rids = set(self._scene_light_rids(scene_entity))
        pending = None
        for jobs in self.off_jobs.values():
            for job in jobs:
                due = self.off_check_due.get(job['room_id'])
                if due is None or not rids & set(job['light_rids']):
                    continue
                wait = max((due - self.get_now()).total_seconds(), 0.0) + 1
                if pending is None or wait > pending[1]:
                    pending = (job['room_name'] or job['room_id'], wait, due)
        return pending

    def _defer_for_pending_off(self, callback, kwargs, step: str) -> bool:
        """Re-schedule a scene step until a pending room-off check has decided.

        A confirmed room-off then claims the lights and the deferred step aborts
        as superseded; a skipped off-check lets it proceed normally. Deferred at
        most OFF_DEFER_MAX times, and only until OFF_DEFER_GRACE after the
        check was due.
        """
        scene_entity = kwargs.get('scene_entity')
        pending = self._pending_off_wait(scene_entity)
        if pending is None:
            return False
        room, wait, due = pending
        count = int(kwargs.get('off_defer_count', 1 if kwargs.get('off_deferred') else 0))
        if count >= OFF_DEFER_MAX or self.get_now() >= due + OFF_DEFER_GRACE:
            self.log(f"[{scene_entity}] [WARN] {step} - room-off check for {room} overdue, "
                     f"proceeding", level="WARNING")
            return False
        self.log(f"[{scene_entity}] [SKIP] {step} deferred - pending room-off check for {room}")
        self.run_in(callback, wait,
                    scene_entity=scene_entity,
                    scene_data=kwargs.get('scene_data'),
                    delay_multiplier=kwargs.get('delay_multiplier', 1),
                    activation_seq=kwargs.get('activation_seq'),
                    activated_at=kwargs.get('activated_at'),
                    on_off_only=kwargs.get('on_off_only', False),
                    only_entities=kwargs.get('only_entities'),
                    off_deferred=True,
                    off_defer_count=count + 1)
        return True

    def _handle_scene_activation(self, entity: str, source: str,
                                 activated_at: Optional[datetime] = None):
        """Debounce, filter and schedule validation for an activated scene entity.

        activated_at: the scene's own activation timestamp (scene.* path);
        None means get_now() (select path: the select carries no time).
        """
        if entity not in self.entity_id_to_hue_id:
            if self.is_hue_scene(entity):
                # Hue scene created after startup: the mapping is read once at start
                if entity not in self.unmapped_scenes_reported:
                    self.unmapped_scenes_reported.add(entity)
                    self.log(f"[INFO] {entity} not in entity registry mapping - "
                             f"restart AppDaemon to validate it", level="INFO")
            else:
                self.log(f"Skipping {entity} - not a Hue scene (no entity registry mapping)",
                         level="DEBUG")
            return
        # Record before debounce/filtering: unvalidated scenes must still supersede
        activation_seq = self._record_activation(entity)

        # Debouncing: avoid duplicate validations within window
        now = time.time()

        # Clean old validation records (older than debounce window)
        cutoff = now - self.validation_debounce
        self.recent_validations = {
            ent: ts for ent, ts in self.recent_validations.items()
            if ts > cutoff
        }

        if entity in self.interrupted_scenes:
            # Another scene took over since the last validation: not a duplicate report
            self.interrupted_scenes.discard(entity)
            self.recent_validations.pop(entity, None)

        if entity in self.recent_validations:
            last_validation = self.recent_validations[entity]
            if now - last_validation < self.validation_debounce:
                elapsed = int(now - last_validation)
                self.log(f"Skipping {entity} - validated {elapsed}s ago "
                        f"(debounce: {self.validation_debounce}s)", level="DEBUG")
                return

        # A real new activation (not a duplicate report): older chains of this
        # scene abort, even if this one is filtered out below
        self.latest_scene_seq[entity] = activation_seq
        self.log(f"Scene activated: {entity} (source: {source})")

        # Check if scene should be validated (filtering logic)
        # scene_uid is looked up in the entity registry mapping
        if not self.should_validate_scene(entity, None):
            self.log(f"Skipping validation for {entity} (filtered out)")
            return

        # Record this validation attempt (after filtering)
        self.recent_validations[entity] = now

        # Schedule validation after transition delay
        self.run_in(self.perform_scene_validation, self.transition_delay,
                    scene_entity=entity, activation_seq=activation_seq,
                    activated_at=activated_at if activated_at is not None else self.get_now())

    def _unusable_stop(self, scene_entity: str, check: SceneCheck,
                       on_off_only: bool = False) -> bool:
        """True (and logs) if the check is unusable for a reason other than legacy actions.

        Without a usable check the lamps cannot be classified, so nothing is
        escalated (a blind re-trigger could undo the owner). Legacy string actions
        keep the old re-trigger fallback, except in a dynamic scene (never replayed).
        """
        if check.usable or (check.legacy and not on_off_only):
            return False
        self.error(f"[ERROR] {scene_entity} validation unusable - not escalated")
        return True

    def _failing_lamp_states(self, failing: List[str]) -> Dict[str, Dict[str, Any]]:
        """State and last_updated of failing lamps (unreachable ones left out).

        A reachable lamp without a usable last_updated shows no provable update,
        so it counts as missed (same convention as the deliberate-room-off rule).
        """
        lights_now = {}
        for entity in failing:
            state = self.get_state(entity, attribute="all") or {}
            if self._state_unreachable(state.get('state')):
                continue
            last_updated = self._parse_ts(state.get('last_updated'))
            if last_updated is None:
                last_updated = datetime.min.replace(tzinfo=timezone.utc)
            lights_now[entity] = {"state": state['state'], "last_updated": last_updated}
        return lights_now

    def _missed_lamps(self, scene_entity: str, check: SceneCheck,
                      activated_at: Optional[datetime]) -> Optional[List[str]]:
        """Failing lamps that missed the scene command; logs the ones left alone.

        Returns None if the check cannot be classified (unusable result or no
        activation time): the caller then treats every failing lamp as before.
        Returns [] (after logging [OK] nothing to correct) if only lamps changed
        after the activation fail.
        """
        if not check.usable or not isinstance(activated_at, datetime):
            return None
        lights_now = self._failing_lamp_states(check.failing)
        missed, changed = classify_scene_failures(check.failing, lights_now, activated_at)
        window_end = activated_at + REACTION_WINDOW
        for entity in changed:
            self.log(f"[{scene_entity}] [SKIP] {entity} changed after activation")
            if (check.kinds.get(entity) in ('brightness', 'color', 'color_temp')
                    and lights_now[entity]['last_updated'] <= window_end):
                # Reacted to the activation itself, but not as the inventory says
                self.log(f"[WARN] {scene_entity} {entity} differs from inventory after "
                         f"reacting - inventory may be outdated", level="WARNING")
        if not missed:
            self.log(f"[{scene_entity}] [OK] nothing to correct (only owner/Hue changes)")
        return missed

    def _lamps_touched_after_reaction(self, scene_data: Dict[str, Any],
                                      activated_at: datetime) -> List[str]:
        """Reachable scene lamps updated at or after activated_at + REACTION_WINDOW.

        Such a lamp (failing or passing) was changed after the scene reacted,
        most likely by the owner, so replaying the whole scene would undo it.
        """
        actions = scene_data.get('actions', []) if isinstance(scene_data, dict) else []
        if self._is_legacy_action_format(actions):
            return []
        window_end = activated_at + REACTION_WINDOW
        touched: List[str] = []
        for action in actions:
            rid = action.get('target', {}).get('rid') if isinstance(action, dict) else None
            entity = self.get_entity_id_from_hue_id(rid) if rid else None
            if not entity or entity in touched:
                continue
            state = self.get_state(entity, attribute="all") or {}
            if self._state_unreachable(state.get('state')):
                continue
            last_updated = self._parse_ts(state.get('last_updated'))
            if last_updated is not None and last_updated >= window_end:
                touched.append(entity)
        return touched

    def _deliberate_room_off(self, scene_entity: str, scene_data: Dict[str, Any],
                             activated_at: Optional[datetime], step: str) -> bool:
        """True (and logs a skip) if all scene lights were switched off after activation."""
        if not isinstance(activated_at, datetime):
            return False
        actions = scene_data.get('actions', []) if isinstance(scene_data, dict) else []
        if self._is_legacy_action_format(actions):
            return False
        expected_on: List[str] = []
        for action in actions:
            if (action.get('action', {}).get('on') or {}).get('on') is not True:
                continue
            rid = action.get('target', {}).get('rid')
            entity = self.get_entity_id_from_hue_id(rid) if rid else None
            if not entity:
                return False  # cannot map an expected-on light: not provably all off
            if entity not in expected_on:
                expected_on.append(entity)
        lights_now = {}
        for entity in expected_on:
            state = self.get_state(entity, attribute="all") or {}
            last_updated = self._parse_ts(state.get('last_updated'))
            if state.get('state') in (None, "unavailable", "unknown"):
                continue  # unreachable: ignored by the rule
            if last_updated is None:  # reachable but unprovable: blocks the rule
                last_updated = datetime.min.replace(tzinfo=timezone.utc)
            lights_now[entity] = {"state": state['state'], "last_updated": last_updated}
        if not all_expected_on_lights_switched_off(expected_on, lights_now, activated_at):
            return False
        self.log(f"[{scene_entity}] [SKIP] {step} - all scene lights switched off "
                 f"after activation (deliberate room off)")
        return True

    def should_validate_scene(self, entity_id: str, scene_uid: str) -> bool:
        """
        Determine if scene should be validated based on filters.

        Args:
            entity_id: HA entity_id
            scene_uid: Scene unique_id

        Returns:
            True if scene should be validated, False otherwise
        """
        # Check circuit breaker
        if not self._circuit_breaker_allows(entity_id):
            return False

        if not self._passes_scene_filters(entity_id, scene_uid):
            return False

        # Rate limits last: a filtered-out scene must not use up the budget
        return self.check_rate_limits(entity_id)

    def _passes_scene_filters(self, entity_id: str, scene_uid: Optional[str]) -> bool:
        """exclude_uids, exclude/include labels and name patterns (no side effects)."""
        # Check UID exclusions (the scene's Hue id, from the entity registry)
        scene_uid = scene_uid or self.entity_id_to_hue_id.get(entity_id)
        if scene_uid and scene_uid in self.exclude_uids:
            self.log(f"Scene {entity_id} excluded by UID", level="DEBUG")
            return False

        # Scene labels live in the entity registry (not in the state attributes)
        if entity_id in self.entity_labels:
            scene_labels = self.entity_labels[entity_id]
        else:
            scene_labels = self.get_state(entity_id, attribute="labels") or []

        # Check exclude labels (takes priority)
        if self.exclude_labels:
            for label in scene_labels:
                if label in self.exclude_labels:
                    self.log(f"Scene {entity_id} excluded by label: {label}", level="DEBUG")
                    return False

        # Check include labels
        if self.include_labels:
            has_label = any(label in self.include_labels for label in scene_labels)
            if not has_label:
                self.log(f"Scene {entity_id} missing required label", level="DEBUG")
                return False
            return True

        # Check name patterns (if no include_labels specified)
        if self.name_patterns:
            scene_name = self.friendly_name(entity_id)
            for pattern in self.name_patterns:
                if re.match(pattern, scene_name):
                    return True
            self.log(f"Scene {entity_id} doesn't match name patterns", level="DEBUG")
            return False

        # If no filters specified, validate all scenes
        return True

    def _circuit_breaker_allows(self, entity_id: str) -> bool:
        """False while the circuit breaker is OPEN (moves to HALF_OPEN after the timeout)."""
        if self.circuit_breaker_state == 'OPEN':
            # Check if timeout expired - transition to HALF_OPEN
            if (self.circuit_breaker_opened_at and
                time.time() - self.circuit_breaker_opened_at >= self.cb_timeout):
                self.circuit_breaker_state = 'HALF_OPEN'
                self.circuit_breaker_successes = 0
                self.log("Circuit breaker HALF_OPEN (timeout expired, testing)")
            else:
                self.log(f"Circuit breaker OPEN - skipping {entity_id}", level="WARNING")
                return False
        return True

    def check_rate_limits(self, entity_id: str) -> bool:
        """
        Check if validation is within rate limits.

        Args:
            entity_id: Scene entity_id

        Returns:
            True if within limits, False otherwise
        """
        now = time.time()

        # Clean old timestamps (older than 60s)
        self.validation_timestamps = [
            ts for ts in self.validation_timestamps if now - ts < 60
        ]

        if entity_id not in self.scene_validation_timestamps:
            self.scene_validation_timestamps[entity_id] = []

        self.scene_validation_timestamps[entity_id] = [
            ts for ts in self.scene_validation_timestamps[entity_id]
            if now - ts < 60
        ]

        # Check global rate limit
        if len(self.validation_timestamps) >= self.max_validations_per_minute:
            self.log(f"Global rate limit exceeded ({self.max_validations_per_minute}/min)",
                    level="WARNING")
            return False

        # Check per-scene rate limit
        scene_count = len(self.scene_validation_timestamps[entity_id])
        if scene_count >= self.max_validations_per_scene_per_minute:
            self.log(f"Per-scene rate limit exceeded for {entity_id} "
                    f"({self.max_validations_per_scene_per_minute}/min)",
                    level="WARNING")
            return False

        # Record this validation
        self.validation_timestamps.append(now)
        self.scene_validation_timestamps[entity_id].append(now)

        return True

    def perform_scene_validation(self, kwargs):
        """
        Perform complete scene validation with 3-level escalation.

        This is called after debouncing and transition delay,
        regardless of how the scene was activated (HA, Hue app, switch).

        Level 1: Validate only (no action)
        Level 2: Re-trigger scene if validation fails
        Level 3: Control lights individually as last resort

        Args:
            kwargs: Contains scene_entity and scene_uid
        """
        try:
            scene_entity = kwargs.get('scene_entity')
            activation_seq = kwargs.get('activation_seq')
            activated_at = kwargs.get('activated_at')

            if not scene_entity:
                self.error("perform_scene_validation called without required parameters")
                return

            if self._abort_if_superseded(scene_entity, activation_seq, "Validation"):
                return
            # Covers Level 1 and the Level 2 re-trigger (same callback, no wait between)
            if self._defer_for_pending_off(self.perform_scene_validation, kwargs, "Validation"):
                return

            self.log(f"Starting validation: {scene_entity}")

            # Find scene in inventory by entity_id/name
            scene_data = self.find_scene_in_inventory(scene_entity)

            if not scene_data:
                self.error(f"Scene {scene_entity} not found in inventories")
                return

            # Dynamic scenes animate colour/brightness: check on/off only
            on_off_only = self._is_dynamic_scene(scene_entity)
            if on_off_only:
                self.log(f"[{scene_entity}] [INFO] Dynamic scene - checking on/off only")

            # LEVEL 1: Validate
            self.log(f"[{scene_entity}] LEVEL 1: Validating scene state")
            check = self.validate_scene_state(scene_entity, scene_data, on_off_only=on_off_only)

            if check.passed:
                if self._all_lights_skipped(scene_entity, check):
                    return
                self.log(f"[{scene_entity}] [OK] Validation successful")
                self.record_success()
                return

            if self._unusable_stop(scene_entity, check, on_off_only=on_off_only):
                return

            # Deliberate room off (all expected-on lights switched off after activation)
            if self._deliberate_room_off(scene_entity, scene_data, activated_at,
                                         "Level 2 re-trigger"):
                return

            # Correct only lamps that missed the command (no update since the activation)
            missed = self._missed_lamps(scene_entity, check, activated_at)
            if missed is not None and not missed:
                return
            adjusted = (self._lamps_touched_after_reaction(scene_data, activated_at)
                        if missed is not None else [])
            if missed is not None and (on_off_only or set(missed) != set(check.failing)
                                       or adjusted):
                # A scene re-trigger would undo lamps changed after the activation
                # (owner or Hue), failing or passing; in a dynamic scene the on/off
                # check cannot even see owner dimming/recolouring. Only the missed
                # lamps get Level 3.
                if on_off_only:
                    reason = "dynamic scene"
                elif set(missed) != set(check.failing):
                    reason = "lamps changed after activation"
                else:
                    reason = f"{', '.join(adjusted)} adjusted after the scene reacted"
                self.log(f"[{scene_entity}] [FAIL] Validation failed - missed by "
                         f"{', '.join(missed)}; LEVEL 2 re-trigger skipped "
                         f"({reason})", level="WARNING")
                self.log(f"[{scene_entity}] LEVEL 3: Controlling missed lights individually")
                self.run_in(
                    self.perform_level3_control,
                    0,
                    scene_entity=scene_entity,
                    scene_data=scene_data,
                    activation_seq=activation_seq,
                    activated_at=activated_at,
                    on_off_only=on_off_only,
                    only_entities=missed,
                )
                return

            # Analyze what failed to determine adaptive delay
            failure_kinds = list(check.kinds.values())
            only_color_temp_failed = (
                len(failure_kinds) > 0 and
                all(failure == 'color_temp' for failure in failure_kinds)
            )

            if only_color_temp_failed:
                delay_multiplier = 2
                self.log(f"[{scene_entity}] [ADAPTIVE] Only color_temp failed - using 2x delay for Level 2 ({self.validation_delay * delay_multiplier}s)", level="INFO")
            else:
                delay_multiplier = 1

            self.log(f"[{scene_entity}] [FAIL] Validation failed (failures: {set(failure_kinds)})", level="WARNING")

            # LEVEL 2: Re-trigger scene (async scheduling to avoid blocking)
            if self._abort_if_superseded(scene_entity, activation_seq, "Level 2 re-trigger"):
                return
            self.log(f"[{scene_entity}] LEVEL 2: Re-triggering scene")
            # Its scene.* echo must not count as a new activation
            self.own_retrigger[scene_entity] = self.get_now()
            self.call_service("scene/turn_on", entity_id=scene_entity)

            # Schedule level 2 validation after adaptive delay (non-blocking)
            level2_delay = self.validation_delay * delay_multiplier

            try:
                self.run_in(
                    self.perform_level2_validation,
                    level2_delay,
                    scene_entity=scene_entity,
                    scene_data=scene_data,
                    delay_multiplier=delay_multiplier,  # Pass to Level 3
                    on_off_only=on_off_only,
                    activation_seq=activation_seq,
                    activated_at=activated_at,
                )
                self.log(f"[{scene_entity}] [SCHEDULER] Level 2 validation scheduled in {level2_delay}s", level="INFO")
            except Exception as e:  # noqa: BLE001 - Broad catch to prevent scheduler failures from crashing app
                self.error(f"[SCHEDULER ERROR] Failed to schedule Level 2 validation: {e}")
                import traceback
                self.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during validation: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def perform_level2_validation(self, kwargs):
        """
        Perform level 2 and 3 validation after re-trigger delay.

        This is called asynchronously after the re-trigger delay to avoid
        blocking the AppDaemon worker thread.

        Args:
            kwargs: Contains scene_entity, scene_data, and delay_multiplier
        """
        # FIRST LINE: Log that callback was executed (to detect silent failures)
        self.log("[CALLBACK] perform_level2_validation called", level="INFO")

        try:
            scene_entity = kwargs.get('scene_entity')
            scene_data = kwargs.get('scene_data')
            level1_delay_multiplier = kwargs.get('delay_multiplier', 1)
            activation_seq = kwargs.get('activation_seq')
            activated_at = kwargs.get('activated_at')
            on_off_only = bool(kwargs.get('on_off_only', False))

            self.log(f"[{scene_entity}] [LEVEL 2] Validating (delay_multiplier={level1_delay_multiplier})", level="INFO")

            if not scene_entity or not scene_data:
                self.error("perform_level2_validation called without required parameters")
                return

            if self._abort_if_superseded(scene_entity, activation_seq, "Level 2 validation"):
                return
            if self._defer_for_pending_off(self.perform_level2_validation, kwargs,
                                           "Level 2 validation"):
                return
            if self._deliberate_room_off(scene_entity, scene_data, activated_at,
                                         "Level 2 validation"):
                return

            # Check if validation is possible (inventory format)
            actions = scene_data.get('actions', [])
            actions_are_strings = self._is_legacy_action_format(actions)

            if actions_are_strings:
                # Validation impossible due to inventory format
                # But re-trigger was performed, so consider it successful
                self.log(f"[{scene_entity}] [OK] Re-trigger completed (validation unavailable due to inventory format)")
                self.record_success()
                return

            # Level 2: Validate after re-trigger
            check = self.validate_scene_state(scene_entity, scene_data, on_off_only=on_off_only)

            if check.passed:
                if self._all_lights_skipped(scene_entity, check):
                    return
                self.log(f"[{scene_entity}] [OK] Re-trigger successful")
                self.record_success()
                return

            if self._unusable_stop(scene_entity, check):
                return

            # Re-classify against the original activation: a lamp that shows an
            # update now was changed (owner or Hue) and is not commanded
            missed = self._missed_lamps(scene_entity, check, activated_at)
            if missed is not None and not missed:
                return

            # Analyze what failed in Level 2 to determine Level 3 delay
            failure_kinds = [check.kinds[e] for e in (missed or check.failing) if e in check.kinds]
            only_color_temp_failed = (
                len(failure_kinds) > 0 and
                all(failure == 'color_temp' for failure in failure_kinds)
            )

            # If Level 1 already used 2x delay (color temp only) and Level 2 still failed with color temp,
            # use 3x delay for Level 3. Otherwise use original delay.
            if only_color_temp_failed and level1_delay_multiplier == 2:
                level3_delay_multiplier = 3
                level3_delay = self.validation_delay * level3_delay_multiplier
                self.log(f"[{scene_entity}] [ADAPTIVE] Only color_temp failed again - using 3x delay for Level 3 ({level3_delay}s)", level="INFO")
            else:
                level3_delay = self.validation_delay
                level3_delay_multiplier = 1

            self.log(f"[{scene_entity}] [FAIL] Re-trigger failed (failures: {set(failure_kinds)})", level="WARNING")

            # LEVEL 3: Individual light control (with adaptive delay)
            self.log(f"[{scene_entity}] LEVEL 3: Controlling lights individually in {level3_delay}s")

            # Schedule Level 3 execution with adaptive delay
            try:
                self.run_in(
                    self.perform_level3_control,
                    level3_delay,
                    scene_entity=scene_entity,
                    scene_data=scene_data,
                    activation_seq=activation_seq,
                    activated_at=activated_at,
                    on_off_only=on_off_only,
                    only_entities=missed,
                )
                self.log(f"[{scene_entity}] [SCHEDULER] Level 3 control scheduled in {level3_delay}s", level="INFO")
            except Exception as e:  # noqa: BLE001 - Broad catch to prevent scheduler failures from crashing app
                self.error(f"[SCHEDULER ERROR] Failed to schedule Level 3 control: {e}")
                import traceback
                self.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during level 2/3 validation: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def perform_level3_control(self, kwargs):
        """
        Perform Level 3 individual light control after adaptive delay.

        This is called after the Level 3 delay to give color temperature
        transitions more time to complete if that was the only failure.

        Args:
            kwargs: Contains scene_entity and scene_data
        """
        # FIRST LINE: Log that callback was executed (to detect silent failures)
        self.log("[CALLBACK] perform_level3_control called", level="INFO")

        try:
            scene_entity = kwargs.get('scene_entity')
            scene_data = kwargs.get('scene_data')
            activation_seq = kwargs.get('activation_seq')
            activated_at = kwargs.get('activated_at')
            on_off_only = bool(kwargs.get('on_off_only', False))

            self.log(f"[{scene_entity}] [LEVEL 3] Controlling lights individually", level="INFO")

            if not scene_entity or not scene_data:
                self.error("perform_level3_control called without required parameters")
                return

            if self._abort_if_superseded(scene_entity, activation_seq, "Level 3 control"):
                return
            if self._defer_for_pending_off(self.perform_level3_control, kwargs, "Level 3 control"):
                return
            if self._deliberate_room_off(scene_entity, scene_data, activated_at,
                                         "Level 3 control"):
                return

            # Only lamps that still fail and still qualify as missed are commanded
            only_entities = kwargs.get('only_entities')
            targets: Optional[Set[str]] = None
            if only_entities is not None:
                targets = set(only_entities)
                check = self.validate_scene_state(scene_entity, scene_data,
                                                  on_off_only=on_off_only, only_entities=targets)
                if check.passed:
                    if self._all_lights_skipped(scene_entity, check):
                        return
                    self.log(f"[{scene_entity}] [OK] Level 3 not needed - missed lights "
                             f"match now")
                    self.record_success()
                    return
                if self._unusable_stop(scene_entity, check):
                    return
                missed = self._missed_lamps(scene_entity, check, activated_at)
                if missed is not None:
                    if not missed:
                        return
                    targets = set(missed)
                elif check.usable:
                    targets = set(check.failing)

            # Control lights individually
            if not self.control_lights_individually(scene_data, on_off_only=on_off_only,
                                              scene_entity=scene_entity,
                                              only_entities=targets):
                self.error(f"[{scene_entity}] [FAIL] Level 3 control commands failed")
                self.record_failure()
                return

            # Schedule final validation after settle delay instead of blocking the worker thread
            def _final_level3_validation(_kwargs):
                self.log(
                    f"[{scene_entity}] [LEVEL 3] Final validation after {self.level3_settle_delay}s settle delay",
                    level="INFO",
                )
                if self._abort_if_superseded(scene_entity, activation_seq, "Level 3 final validation"):
                    return
                final = self.validate_scene_state(scene_entity, scene_data,
                                                  on_off_only=on_off_only, only_entities=targets)
                if self._unusable_stop(scene_entity, final):
                    return
                if final.passed:
                    if self._all_lights_skipped(scene_entity, final):
                        return
                    self.log(f"[{scene_entity}] [OK] Level 3 successful - final validation PASSED")
                    self.record_success()
                else:
                    self.error(f"[{scene_entity}] [FAIL] Level 3 control executed, but final validation FAILED")
                    self.error(f"[{scene_entity}] [FAIL] Still failing: "
                               f"{', '.join(f'{e} ({k})' for e, k in final.kinds.items())}")
                    self.record_failure()

            self.run_in(_final_level3_validation, self.level3_settle_delay)

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during level 3 control: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    # ------------------------------------------------------------------
    # Room-off validation (Hue switch press switches a room off)
    # ------------------------------------------------------------------

    def setup_off_validation(self):
        """Build the room-off job table for the configured rooms and listen to their buttons."""
        if not self.off_validation_enabled:
            self.log("Off validation disabled", level="DEBUG")
            return

        def has_v1_rules(inventory: Dict[str, Any]) -> bool:
            v1 = inventory.get('resources', {}).get('v1')
            return isinstance(v1, dict) and isinstance(v1.get('rules'), dict)

        if not any(has_v1_rules(inv) for inv in self.inventories):
            self.log("[WARN] off validation disabled: inventory has no v1 rules "
                     "(regenerate inventory)", level="WARNING")
            return

        all_jobs = build_off_jobs(self.inventories, self.hue_id_to_entity_id)
        rooms = set(self.off_validation_rooms)

        for room in self.off_validation_rooms:
            if not any(room in (job['room_name'], job['room_id'])
                       for jobs in all_jobs.values() for job in jobs):
                self.log(f"[WARN] off validation: room '{room}' has no switch off-rule "
                         f"(check name or use room id)", level="WARNING")

        warned_empty = set()
        self.off_jobs = {}
        for entity, jobs in all_jobs.items():
            for job in jobs:
                if job['room_name'] not in rooms and job['room_id'] not in rooms:
                    continue
                if not job['lights']:
                    if job['room_id'] not in warned_empty:
                        warned_empty.add(job['room_id'])
                        self.log(f"[WARN] off validation: room '{job['room_name']}' has no lights "
                                 f"in the entity registry - not monitored", level="WARNING")
                    continue
                self.off_jobs.setdefault(entity, []).append(job)

        for entity in self.off_jobs:
            # Full state: event_type must come from the triggering change, not a later read
            self.listen_state(self.on_switch_event, entity, attribute="all")
        room_names = sorted({job['room_name'] or job['room_id']
                             for jobs in self.off_jobs.values() for job in jobs})
        self.log(f"Monitoring {len(self.off_jobs)} switch button(s) for room-off jobs "
                 f"({', '.join(room_names)})")

    @staticmethod
    def _parse_ts(value: Any) -> Optional[datetime]:
        """Parse an ISO timestamp (as AppDaemon returns it) to an aware datetime."""
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def on_switch_event(self, entity, _attribute, old_full, new_full, _kwargs):
        """Handle a Hue button event entity change (full state; state = press time)."""
        old = old_full.get('state') if isinstance(old_full, dict) else None
        new = new_full.get('state') if isinstance(new_full, dict) else None
        # Only None/unavailable is a restore; "unknown" (entity just created) ->
        # press is real. A restored old press is rejected by the age check below.
        if old == new or old in (None, "unavailable") or new in (None, "unknown", "unavailable"):
            self.log(f"Skipping {entity} - not a new press ({old} -> {new})", level="DEBUG")
            return

        event_type = (new_full.get('attributes') or {}).get('event_type')
        jobs = [job for job in self.off_jobs.get(entity, []) if job['event_type'] == event_type]
        if not jobs:
            return

        t_press = self._parse_ts(new)
        if t_press is None:
            self.log(f"[WARN] {entity}: cannot parse press time '{new}'", level="WARNING")
            return
        age = (self.get_now() - t_press).total_seconds()
        if age > self.off_check_delay + 2:
            # HA restores the last event state after a restart or reconnect
            self.log(f"[SKIP] {entity}: press is {age:.0f}s old (restored state?)")
            return

        for job in jobs:
            room = job['room_name']
            self.latest_press[job['room_id']] = t_press
            if not job['ambiguous']:
                # Only an off-rule on this button: the press is the room-off
                self._claim_lights(f"off:{room}", job['light_rids'])
            self.log(f"[{room}] Room off press: {entity} ({event_type}), "
                     f"check in {self.off_check_delay}s")
            self.off_check_due[job['room_id']] = (self.get_now()
                                                  + timedelta(seconds=self.off_check_delay))
            try:
                self.run_in(self.perform_off_check, self.off_check_delay,
                            job=job, t_press=t_press)
            except Exception as e:  # noqa: BLE001 - scheduler failure must not crash the app
                # No check will run: scene steps must not wait for it
                self.off_check_due.pop(job['room_id'], None)
                self.error(f"[{room}] [SCHEDULER ERROR] Failed to schedule room off check: {e}")

    def _read_room_lights(self, entities: List[str], room: str) -> Dict[str, Dict[str, Any]]:
        """Current state and last_updated of the given lights (missing/unavailable left out)."""
        lights_now = {}
        missing = []
        for entity in entities:
            state = self.get_state(entity, attribute="all") or {}
            last_updated = self._parse_ts(state.get('last_updated'))
            if state.get('state') in (None, "unavailable", "unknown") or last_updated is None:
                missing.append(entity)
                continue
            lights_now[entity] = {"state": state['state'], "last_updated": last_updated}
        if missing:
            self.log(f"[{room}] [WARN] Room off: no usable state for {', '.join(missing)} "
                     f"- left out", level="WARNING")
        return lights_now

    def _scene_activated_since(self, light_rids: List[str], since: datetime) -> bool:
        """True if a scene activation touched any of the lights at or after `since`."""
        return any(self.light_activation_at.get(rid) and self.light_activation_at[rid] >= since
                   for rid in light_rids)

    def _scene_vetoes_press(self, job: Dict[str, Any], t_press: datetime) -> bool:
        """True if a scene activation on the room lights makes the press a scene step.

        Unambiguous job: only a scene strictly after the press (the press is the
        room-off and overrides an older scene). Ambiguous job: also a scene up to
        PRESS_LOOKBACK before the press (event order in HA is not guaranteed).
        """
        if job['ambiguous']:
            return self._scene_activated_since(job['light_rids'], t_press - PRESS_LOOKBACK)
        return any(self.light_activation_at.get(rid) and self.light_activation_at[rid] > t_press
                   for rid in job['light_rids'])

    def _off_send_allowed(self, room: str) -> bool:
        """Shared circuit breaker and rate limits before sending any off command."""
        label = f"off:{room}"
        if not self._circuit_breaker_allows(label):
            self.log(f"[{room}] [SKIP] Room off: circuit breaker open - no commands sent")
            return False
        if not self.check_rate_limits(label):
            self.log(f"[{room}] [SKIP] Room off: rate limit - no commands sent")
            return False
        return True

    def _turn_off_lights(self, entities: List[str]):
        for entity in entities:
            self.call_service("light/turn_off", entity_id=entity)

    def perform_off_check(self, kwargs):
        """Check the room lights after a room-off press; switch off lights that missed it."""
        try:
            job = kwargs['job']
            t_press = kwargs['t_press']
            room = job['room_name']
            if self.latest_press.get(job['room_id']) != t_press:
                self.log(f"[{room}] Room off check replaced by a newer press", level="DEBUG")
                return
            self.off_check_evaluated[job['room_id']] = t_press
            self.off_check_due.pop(job['room_id'], None)

            window_start = t_press - PRESS_LOOKBACK
            lights_now = self._read_room_lights(job['lights'], room)
            if not lights_now:
                self.log(f"[{room}] [SKIP] Room off: no light state available")
                return

            result, missed = classify_off_check(
                lights_now, window_start,
                self._scene_vetoes_press(job, t_press),
                job['ambiguous'],
                evidence_end=t_press + OFF_EVIDENCE_WINDOW,
            )
            if result == "skip_scene":
                self.log(f"[{room}] [SKIP] Room off: scene activated on room lights (scene step)")
                return
            if result == "skip_no_evidence":
                self.log(f"[{room}] [SKIP] Room off: no off evidence (press was not a room-off)")
                return

            if job['ambiguous']:
                # Confirmed now: pending scene validations on these lights must not fight it
                self._claim_lights(f"off:{room}", job['light_rids'])

            if result == "ok":
                self.log(f"[{room}] [OK] Room off verified ({len(lights_now)} light(s))")
                self.record_success()
                return

            if not self._off_send_allowed(room):
                return
            self.log(f"[{room}] [WARN] Room off missed by {', '.join(missed)} - "
                     f"LEVEL 2: switching off", level="WARNING")
            self._turn_off_lights(missed)
            self.run_in(self.perform_off_level3, self.validation_delay,
                        job=job, t_press=t_press, missed=missed)

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during room off check: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def _off_recheck(self, kwargs, step: str) -> Optional[Tuple[List[str], bool]]:
        """(lights of `missed` still on and untouched since the press, owner switched one on).

        None if the check must stop.
        """
        job = kwargs['job']
        t_press = kwargs['t_press']
        room = job['room_name']
        if self.latest_press.get(job['room_id']) != t_press:
            self.log(f"[{room}] [SKIP] Room off {step} aborted - newer press")
            return None
        window_start = t_press - PRESS_LOOKBACK
        lights_now = self._read_room_lights(kwargs['missed'], room)
        if not lights_now:
            # No observation of any target: neither verified nor failed
            self.log(f"[{room}] [SKIP] Room off check inconclusive - target lamp(s) unreachable")
            return None
        # Unambiguous rule on the subset: "on and no update since the press".
        # A lamp the owner switched or dimmed meanwhile was updated and is left alone.
        result, still_on = classify_off_check(
            lights_now, window_start, self._scene_vetoes_press(job, t_press), False,
        )
        if result == "skip_scene":
            self.log(f"[{room}] [SKIP] Room off {step} aborted - scene activated on room lights")
            return None
        # A light that is on but not in still_on was changed after the press
        owner_changed = any(v['state'] == "on" and e not in still_on
                            for e, v in lights_now.items())
        return still_on, owner_changed

    def _off_ended_by_owner(self, room: str, owner_changed: bool) -> bool:
        """Log and return True if the check ends only because the owner changed a light."""
        if owner_changed:
            self.log(f"[{room}] [SKIP] Room off check ended - light(s) changed by owner")
        return owner_changed

    def perform_off_level3(self, kwargs):
        """Re-check lights switched off at Level 2; switch remaining ones off individually."""
        try:
            room = kwargs['job']['room_name']
            recheck = self._off_recheck(kwargs, "Level 3")
            if recheck is None:
                return
            still_on, owner_changed = recheck
            if not still_on:
                if self._off_ended_by_owner(room, owner_changed):
                    return
                self.log(f"[{room}] [OK] Room off verified after LEVEL 2")
                self.record_success()
                return

            if not self._off_send_allowed(room):
                return
            self.log(f"[{room}] [WARN] Room off still missed by {', '.join(still_on)} - "
                     f"LEVEL 3: switching off individually", level="WARNING")
            self._turn_off_lights(still_on)
            self.run_in(self.perform_off_final_check, self.level3_settle_delay,
                        job=kwargs['job'], t_press=kwargs['t_press'], missed=still_on)

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during room off level 3: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def perform_off_final_check(self, kwargs):
        """Final check after Level 3: [OK] or [FAIL] + record_failure()."""
        try:
            room = kwargs['job']['room_name']
            recheck = self._off_recheck(kwargs, "final check")
            if recheck is None:
                return
            still_on, owner_changed = recheck
            if not still_on and self._off_ended_by_owner(room, owner_changed):
                return
            if still_on:
                self.error(f"[{room}] [FAIL] Room off: still on after LEVEL 3: {', '.join(still_on)}")
                self.record_failure()
                return
            self.log(f"[{room}] [OK] Room off verified after LEVEL 3")
            self.record_success()

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during room off final check: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def find_scene_in_inventory(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Find scene data in loaded inventories using entity registry unique_id.

        Uses the entity registry to get the Hue scene ID (unique_id) for the given
        HA entity_id, then searches inventories for that exact scene ID.

        This provides 100% reliable scene matching with no ambiguity, unlike the
        previous name-based matching which failed when multiple scenes had the same
        name (e.g., 28 scenes named "Nachtlicht" across different rooms).

        Args:
            entity_id: Scene entity_id (e.g., scene.buro_markus_nachtlicht)

        Returns:
            Scene data dict or None if not found
        """
        # Get Hue scene ID from entity registry (unique_id = Hue scene ID)
        # The entity registry provides the direct 1:1 mapping:
        # scene.buro_markus_nachtlicht → f0309f80-9480-4b12-a0c3-a026790d87bf
        hue_scene_id = None
        for unique_id, mapped_entity_id in self.hue_id_to_entity_id.items():
            if mapped_entity_id == entity_id:
                hue_scene_id = unique_id
                break

        if not hue_scene_id:
            self.log(f"Could not find Hue scene ID for {entity_id} in entity registry", level="WARNING")
            return None

        # Search inventories for scene with this exact ID
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scenes', {}).get('items', [])
            for scene in scenes:
                if scene.get('id') == hue_scene_id:
                    # Found exact scene match by ID - 100% reliable!
                    return scene

        # Scene not found in any inventory
        self.log(f"Scene {entity_id} (Hue ID: {hue_scene_id}) not found in inventories", level="WARNING")
        return None

    def _is_dynamic_scene(self, scene_entity: str) -> bool:
        """True if HA reports the scene as dynamic (None or missing means static)."""
        return bool(self.get_state(scene_entity, attribute="is_dynamic"))

    @staticmethod
    def _state_unreachable(state: Any) -> bool:
        """True if an HA light state means the light is unreachable (or missing)."""
        return state in (None, "unavailable", "unknown")

    def _log_skip_unreachable(self, scene_entity: str, entity_id: str):
        self.log(f"[{scene_entity}] [SKIP] {entity_id} unavailable - not validated")

    def _all_lights_skipped(self, scene_entity: str, check: SceneCheck) -> bool:
        """After a validation that passed: True if no light was actually checked."""
        if check.checked == 0:
            self.log(f"[{scene_entity}] [SKIP] all scene lights unavailable - "
                     "not escalated, not recorded")
            return True
        return False

    def validate_scene_state(self, scene_entity: str, scene_data: Dict[str, Any],
                             on_off_only: bool = False,
                             only_entities: Optional[Set[str]] = None) -> SceneCheck:
        """
        Validate that all lights match expected scene state.

        Args:
            scene_entity: Scene entity_id
            scene_data: Scene data from inventory
            on_off_only: Dynamic scene - compare only on/off, skip brightness/colour
            only_entities: If set, judge only these lamps (Level 3 final validation)

        Returns:
            SceneCheck: passed, the failing lamps and their failure kinds, and how
            many lamps were compared. Unreachable lamps are skipped (checked == 0
            with passed means all lamps were skipped). usable is False when the
            scene cannot be validated (no or legacy actions).
        """
        actions = scene_data.get('actions', [])

        if not actions:
            self.log(f"Scene {scene_entity} has no actions", level="WARNING")
            return SceneCheck(passed=False, usable=False)

        # Check if actions are string representations (inventory format issue)
        if self._is_legacy_action_format(actions):
            self.log("Actions stored as strings - skipping validation, will re-trigger", level="WARNING")
            return SceneCheck(passed=False, usable=False, legacy=True)

        try:
            all_match = True
            checked = 0
            failing: List[str] = []
            kinds: Dict[str, str] = {}

            for action in actions:
                target = action.get('target', {})
                rid = target.get('rid')

                if not rid:
                    continue

                # Map Hue resource ID to HA entity_id
                entity_id = self.get_entity_id_from_hue_id(rid)

                if not entity_id:
                    # No HA entity for this lamp: skipped like an unreachable lamp
                    self.log(f"[{scene_entity}] [SKIP] {rid} not mapped")
                    continue

                if only_entities is not None and entity_id not in only_entities:
                    continue

                # Get expected state from action
                expected = action.get('action', {})

                # Get actual state from HA
                actual_state = self.get_state(entity_id, attribute="all")

                if (not actual_state
                        or self._state_unreachable(actual_state.get('state'))):
                    self._log_skip_unreachable(scene_entity, entity_id)
                    continue

                # Compare states (a malformed action leaves only this lamp unchecked)
                try:
                    kind = self.compare_light_states(entity_id, expected, actual_state,
                                                     scene_entity, on_off_only=on_off_only)
                except Exception as e:  # noqa: BLE001
                    self.log(f"[WARN] {scene_entity} {entity_id} not checked - {e}",
                             level="WARNING")
                    continue
                checked += 1
                if kind is not None:
                    all_match = False
                    if entity_id not in kinds:
                        failing.append(entity_id)
                        kinds[entity_id] = kind

            return SceneCheck(passed=all_match, failing=failing, kinds=kinds, checked=checked)

        except AttributeError as e:
            self.log(f"Inventory format issue (actions are strings): {e}", level="WARNING")
            return SceneCheck(passed=False, usable=False)
        except Exception as e:  # noqa: BLE001
            self.error(f"Error validating scene state: {e}")
            return SceneCheck(passed=False, usable=False)

    def compare_light_states(self, entity_id: str, expected: Dict[str, Any],
                            actual_state: Dict[str, Any], scene_entity: str = "unknown",
                            on_off_only: bool = False) -> Optional[str]:
        """
        Compare expected and actual light states.

        Args:
            entity_id: Light entity_id
            expected: Expected state from scene
            actual_state: Actual state from HA
            scene_entity: Scene entity_id for logging
            on_off_only: Dynamic scene - only the on/off state is compared

        Returns:
            None if the states match within tolerances, otherwise the failure kind:
            'on_off', 'brightness', 'color' or 'color_temp'.
        """
        actual_attrs = actual_state.get('attributes', {})
        actual_on = actual_state.get('state') == 'on'

        # Check on/off state
        expected_on = expected.get('on', {}).get('on', False)
        if expected_on != actual_on:
            self.log(f"[{scene_entity}] [{entity_id}] [ON_OFF] FAIL: exp {'ON' if expected_on else 'OFF'}, got {'ON' if actual_on else 'OFF'}", level="WARNING")
            return 'on_off'

        # If light should be off, no need to check other attributes
        if not expected_on or on_off_only:
            return None

        # Check brightness
        expected_dimming = expected.get('dimming', {})
        if expected_dimming and 'brightness' in expected_dimming:
            expected_brightness = expected_dimming['brightness']

            # CRITICAL HUE RULE: When on:true, brightness 0.0 in scene means light will be at 0% in HA state
            # We DON'T convert 0.0 to 1.0 for validation - we accept 0% as the correct actual state
            # The conversion to 1% only happens when CONTROLLING the light (Level 3)

            actual_brightness = actual_attrs.get('brightness', 0)
            # Convert HA brightness (0-255) to percentage
            actual_brightness_pct = (actual_brightness / 255) * 100
            diff = abs(expected_brightness - actual_brightness_pct)

            if diff > self.brightness_tolerance:
                self.log(f"[{scene_entity}] [{entity_id}] [BRIGHTNESS] FAIL: exp {expected_brightness:.1f}%, got {actual_brightness_pct:.1f}%, diff {diff:.1f}% > tol {self.brightness_tolerance}%", level="WARNING")
                return 'brightness'
            elif self.debug_logging:
                self.log(f"[{scene_entity}] [{entity_id}] [BRIGHTNESS] OK: exp {expected_brightness:.1f}%, got {actual_brightness_pct:.1f}%, diff {diff:.1f}% < tol {self.brightness_tolerance}%", level="INFO")

        # Check color (XY)
        expected_color = expected.get('color', {})
        if expected_color and 'xy' in expected_color:
            expected_xy = expected_color['xy']
            actual_xy = actual_attrs.get('xy_color')

            # Only validate if light has xy_color in state (skip if in CT mode)
            if actual_xy:
                x_diff = abs(expected_xy['x'] - actual_xy[0])
                y_diff = abs(expected_xy['y'] - actual_xy[1])
                if x_diff > self.color_tolerance or y_diff > self.color_tolerance:
                    self.log(f"[{scene_entity}] [{entity_id}] [COLOR_XY] FAIL: exp ({expected_xy['x']:.3f}, {expected_xy['y']:.3f}), got ({actual_xy[0]:.3f}, {actual_xy[1]:.3f}), diff (x:{x_diff:.3f}, y:{y_diff:.3f}) > tol {self.color_tolerance}", level="WARNING")
                    return 'color'
                elif self.debug_logging:
                    self.log(f"[{scene_entity}] [{entity_id}] [COLOR_XY] OK: exp ({expected_xy['x']:.3f}, {expected_xy['y']:.3f}), got ({actual_xy[0]:.3f}, {actual_xy[1]:.3f}), diff (x:{x_diff:.3f}, y:{y_diff:.3f}) < tol {self.color_tolerance}", level="INFO")

        # Check color temperature
        if 'color_temperature' in expected:
            if expected['color_temperature']:
                expected_ct = expected['color_temperature'].get('mirek')
                actual_ct = _actual_mired(actual_attrs)

                # Only validate if light reports a color temperature (skip if in XY mode)
                if expected_ct and actual_ct:
                    actual_ct = round(actual_ct)
                    diff = abs(expected_ct - actual_ct)
                    if diff > self.color_temp_tolerance:
                        self.log(f"[{scene_entity}] [{entity_id}] [COLOR_TEMP] FAIL: exp {expected_ct}, got {actual_ct}, diff {diff} > tol {self.color_temp_tolerance}", level="WARNING")
                        return 'color_temp'
                    elif self.debug_logging:
                        self.log(f"[{scene_entity}] [{entity_id}] [COLOR_TEMP] OK: exp {expected_ct}, got {actual_ct}, diff {diff} < tol {self.color_temp_tolerance}", level="INFO")

        return None

    def control_lights_individually(self, scene_data: Dict[str, Any],
                                    on_off_only: bool = False,
                                    scene_entity: str = "control",
                                    only_entities: Optional[Set[str]] = None) -> bool:
        """
        Control each light individually to achieve desired state.

        Args:
            scene_data: Scene data from inventory
            on_off_only: Dynamic scene - only switch on/off, no brightness or colour
            only_entities: If set, command only these lamps (the ones that missed
                the scene command); all other lamps are left alone

        Returns:
            True if all lights controlled successfully, False otherwise
        """
        actions = scene_data.get('actions', [])

        if not actions:
            return False

        # Check if actions are string representations (inventory format issue)
        if self._is_legacy_action_format(actions):
            self.log("Cannot control lights - actions stored as strings (inventory format issue)", level="WARNING")
            return False

        all_success = True

        for action in actions:
            target = action.get('target', {})
            rid = target.get('rid')

            if not rid:
                continue

            entity_id = self.get_entity_id_from_hue_id(rid)

            if not entity_id:
                self.log(f"[{scene_entity}] [SKIP] {rid} not mapped")
                continue

            if only_entities is not None and entity_id not in only_entities:
                continue

            if self._state_unreachable(self.get_state(entity_id)):
                self._log_skip_unreachable(scene_entity, entity_id)
                continue

            # Build service call parameters
            expected = action.get('action', {})
            service_data = {"entity_id": entity_id}

            # On/off
            expected_on = expected.get('on', {}).get('on', False)
            if on_off_only:
                # Dynamic scene: only fix lights whose on/off state differs, never send
                # brightness/colour. on:true means ON (brightness 0.0 is not off).
                is_on = self.get_state(entity_id) == "on"
                if expected_on != is_on:
                    self.call_service("light/turn_on" if expected_on else "light/turn_off",
                                      **service_data)
                continue

            if not expected_on:
                self.call_service("light/turn_off", **service_data)
                continue

            # Brightness
            dimming = expected.get('dimming', {})
            if dimming and 'brightness' in dimming:
                brightness_pct = dimming['brightness']

                # CRITICAL HUE RULE: When on:true, brightness 0.0 means "minimum brightness" (~1%), NOT off
                # This is Hue-specific behavior - see CLAUDE.md for details
                if brightness_pct == 0.0:
                    brightness_pct = 1.0  # Minimum brightness for ON lights

                # Convert percentage to 0-255
                brightness = int((brightness_pct / 100) * 255)
                service_data['brightness'] = max(1, min(brightness, 255))  # Clamp to valid range 1-255

            # Color (XY)
            color = expected.get('color', {})
            if color and 'xy' in color:
                xy = color['xy']
                service_data['xy_color'] = [xy['x'], xy['y']]

            # Color temperature
            if 'color_temperature' in expected:
                if expected['color_temperature']:
                    ct = expected['color_temperature'].get('mirek')
                    if ct:
                        service_data['color_temp_kelvin'] = _mired_to_kelvin(ct)

            # Turn on light with parameters
            self.call_service("light/turn_on", **service_data)

        return all_success

    def get_entity_id_from_hue_id(self, hue_resource_id: str) -> Optional[str]:
        """
        Map Hue resource ID to HA entity_id using cached entity registry mapping.

        This uses the entity registry cache loaded during initialization instead
        of querying the state API, because the state API does NOT expose unique_id
        for any entity type (see HOME_ASSISTANT_API_LIMITATIONS.md).

        Args:
            hue_resource_id: Hue resource ID (UUID)

        Returns:
            HA entity_id or None if not found
        """
        # Try exact match first (resource ID is the unique_id)
        if hue_resource_id in self.hue_id_to_entity_id:
            return self.hue_id_to_entity_id[hue_resource_id]

        # Try partial match (unique_id contains resource ID with delimiters)
        for unique_id, entity_id in self.hue_id_to_entity_id.items():
            if (unique_id.endswith(hue_resource_id) or
                f"_{hue_resource_id}" in unique_id or
                f"-{hue_resource_id}" in unique_id):
                return entity_id

        return None

    def record_success(self):
        """Record successful validation for circuit breaker."""
        if self.circuit_breaker_state == 'HALF_OPEN':
            self.circuit_breaker_successes += 1
            self.log(f"Circuit breaker HALF_OPEN: {self.circuit_breaker_successes}/"
                    f"{self.cb_success_threshold} successes")

            if self.circuit_breaker_successes >= self.cb_success_threshold:
                self.circuit_breaker_state = 'CLOSED'
                self.circuit_breaker_failures = 0
                self.circuit_breaker_successes = 0
                self.log("Circuit breaker CLOSED (recovered)")

        elif self.circuit_breaker_state == 'CLOSED':
            # Reset failure count on success
            if self.circuit_breaker_failures > 0:
                self.circuit_breaker_failures = 0

    def record_failure(self):
        """Record validation failure for circuit breaker."""
        if self.circuit_breaker_state == 'HALF_OPEN':
            # Failure during half-open state - re-open circuit
            self.circuit_breaker_state = 'OPEN'
            self.circuit_breaker_opened_at = time.time()
            self.circuit_breaker_successes = 0
            self.error("Circuit breaker re-OPENED (half-open test failed)")

        elif self.circuit_breaker_state == 'CLOSED':
            self.circuit_breaker_failures += 1
            self.log(f"Circuit breaker failures: {self.circuit_breaker_failures}/"
                    f"{self.cb_failure_threshold}")

            if self.circuit_breaker_failures >= self.cb_failure_threshold:
                self.circuit_breaker_state = 'OPEN'
                self.circuit_breaker_opened_at = time.time()
                self.error("Circuit breaker OPENED (threshold reached)")
