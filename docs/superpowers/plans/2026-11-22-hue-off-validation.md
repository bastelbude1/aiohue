# Hue Room-Off Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a Hue switch press switches a room off, scene_validator verifies that every light of the room is off, and switches off lights that missed the command.

**Architecture:** The inventory script additionally captures rooms/zones (bug fix), structured device/button data, v1 rules (owner stripped) and v2 behaviors. At startup the validator builds an "off job" table from v1 rules (button event entity -> room lights). On a matching press it checks the room after a delay, using a pure classifier for evidence and missed lights, and escalates individual `light.turn_off` like the existing Level 2/3.

**Tech Stack:** Python 3.12 (AppDaemon 4.5.16), aiohue 4.8 (inventory script), pytest with the existing `FakeHass` stub.

**Spec:** `docs/superpowers/specs/2026-11-22-hue-off-validation-design.md`

## Global Constraints

- Production: HA 2026.11.2, AppDaemon 4.5.16, Python 3.12. No HA core changes.
- Existing scene validation behaviour must not change. All 14 existing tests stay green.
- Log output ASCII only, keeping the `[OK]` / `[FAIL]` / `[SKIP]` / `[WARN]` prefixes.
- No real names, IPs or bridge ids in code, tests or docs. Use `Room_Office`, `abc123def456`, `192.168.1.100`.
- Inventory changes are additive. Existing keys keep their format.
- v1 rules must be written without their `owner` field (it is a bridge username).
- Off validation defaults to disabled. It is enabled per room via `off_validation.rooms`.
- `scene_validator.py` stays a single file, because it is deployed as one file to AppDaemon.
- Test command (from `appdaemon_apps/scene_validator`): `<testvenv>/bin/python -m pytest tests -q`. For `scripts/`: `<testvenv>/bin/python -m pytest scripts/tests -q`. Here `<testvenv>` is any venv with pytest. aiohue is not needed for tests.

## Review Focus

1. A scene-cycle step that switches some room lights off ("Nachtlicht": one lamp off, the other dimmed) must not cause any off command. Pinned in Task 3 (`test_scene_step_that_turns_one_lamp_off_is_not_an_off_job`).
2. A lamp the owner dims or switches on after the press must never be switched off. Pinned in Task 3 (`test_lamp_changed_after_press_is_left_alone`).
3. A light update that reaches HA up to 1 s **before** the button event still counts as evidence. Pinned in Task 3 (`test_off_update_up_to_1s_before_press_counts`).
4. An old inventory without `v1` data must not crash startup. Off validation is disabled with `[WARN]`. Pinned in Task 4 (`test_old_inventory_disables_off_validation_with_warning`).
5. The same v1 ids (`/groups/1`, `/sensors/16`) on two bridges must not cross-match. Pinned in Task 2 (`test_v1_ids_resolve_per_bridge_only`).

---

### Task 1: Inventory captures rooms/zones, structured devices/buttons, v1 rules, behaviors

**Files:**
- Create: `scripts/hue_inventory_extras.py` (pure helpers plus one async v1 fetch)
- Modify: `scripts/inventory-hue-bridge.py:240-370` (use the helpers; fix the room/zone filter at :314-315)
- Create: `scripts/tests/test_hue_inventory_extras.py`
- Modify: `scripts/README.md` (inventory format section: new keys)

**Interfaces:**
- Produces (inventory JSON, consumed by Tasks 2 and 4):
  - `resources.groups.rooms.items[]` and `resources.groups.zones.items[]`. Each item is `{id, id_v1, name, children: [{rid, rtype}], services: [{rid, rtype}]}`.
  - On each `resources.devices.items[]`, additionally `id_v1` and `services_structured: [{rid, rtype}]`.
  - `resources.buttons.items[]`: `{id, owner_rid, control_id}`.
  - `resources.v1.rules`: dict keyed by rule id, values as returned by the bridge **minus `owner`**. `resources.v1.sensors`: `{id: {name, type, uniqueid}}`.
  - `resources.behaviors.items[]`: `{id, name, script_name, enabled, configuration}`.
- Functions in `hue_inventory_extras.py`:
  - `split_groups(groups) -> tuple[list, list]` returns (rooms, zones), comparing against `ResourceTypes.ROOM` / `ResourceTypes.ZONE`. Duck-type on `.type.value` so tests need no aiohue.
  - `serialize_group(group) -> dict`
  - `device_extras(device) -> dict` returns `{"id_v1": ..., "services_structured": [...]}`
  - `serialize_buttons(buttons) -> list[dict]`
  - `sanitize_v1_rules(rules: dict) -> dict`
  - `serialize_v1_sensors(sensors: dict) -> dict`
  - `serialize_behaviors(instances, scripts) -> list[dict]`
  - `async fetch_v1(bridge_ip: str, username: str) -> dict` returns `{"rules": ..., "sensors": ...}` via aiohttp, `ssl=False` (the bridge has a self-signed certificate).

- [ ] **Step 1: Write failing tests** in `scripts/tests/test_hue_inventory_extras.py`, using `types.SimpleNamespace` fakes:
  - `test_split_groups_uses_enum_value`: groups with `.type.value` `"room"` / `"zone"` / `"bridge_home"` split into 1 room and 1 zone. This is the regression for the always-false `== "zone"`.
  - `test_serialize_group_structures_children_and_services`: children `[{"rid": "dev-1", "rtype": "device"}]`, services contain `{"rid": "gl-1", "rtype": "grouped_light"}`, `id_v1 == "/groups/1"`, `name == "Room_Office"`.
  - `test_sanitize_v1_rules_drops_owner`: input rule with `owner: "abc123def456"`. Output has no `owner` key; `conditions` and `actions` are unchanged.
  - `test_serialize_buttons_keeps_control_id_and_owner`.
- [ ] **Step 2: Run, verify FAIL** (`ModuleNotFoundError: hue_inventory_extras`).
- [ ] **Step 3: Implement the helpers** listed under Interfaces.
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Wire into `inventory_bridge()`:**
  - Groups go through `split_groups` / `serialize_group` into the existing `groups.rooms` / `groups.zones` keys.
  - Devices get `**device_extras(device)`.
  - Add `buttons` from `bridge.sensors.button`, `behaviors` from `bridge.config.behavior_instance` / `behavior_script`, and `v1` from `await fetch_v1(...)`.
  - Each new block goes in its own `try/except`, matching the file's existing pattern, so one failure never drops the rest.
- [ ] **Step 6: Verify against a real bridge (read-only):** run the script into a scratch output dir. Check with `jq` that `groups.rooms.count > 0`, `v1.rules` exists, and no rule has an `owner` key: `jq '[.resources.v1.rules[] | has("owner")] | any'` prints `false`.
- [ ] **Step 7: Commit** `feat(inventory): rooms/zones fix, buttons, v1 rules (owner stripped), behaviors`.

---

### Task 2: Off job table from v1 rules (pure function)

**Files:**
- Modify: `appdaemon_apps/scene_validator/scene_validator.py` (module-level functions next to `resolve_scene_entity_from_select`)
- Create: `appdaemon_apps/scene_validator/tests/test_off_jobs.py`

**Interfaces:**
- Consumes: inventory keys from Task 1, and `hue_id_to_entity_id: Dict[str, str]` (registry unique_id -> entity_id, already built in `load_entity_registry_mapping`).
- Produces:
  - `V1_EVENT_TYPES = {0: "initial_press", 1: "repeat", 2: "short_release", 3: "long_release"}`
  - `build_off_jobs(inventories: List[dict], hue_id_to_entity_id: Dict[str, str]) -> Dict[str, List[dict]]`. The key is the HA event entity_id. Each value item is `{"event_type": str, "room_id": str, "room_name": str, "lights": List[str], "ambiguous": bool}`.
  - Resolution happens **within one inventory** (v1 ids are per bridge). Chain: rule action address `/groups/<n>/action` with body `{"on": false}` -> room/zone `id_v1`. Then condition `/sensors/<s>/state/buttonevent` `eq <code>` -> device `id_v1 == "/sensors/<s>"` -> button with `owner_rid == device.id` and `control_id == code // 1000` -> event entity via `hue_id_to_entity_id[button.id]`. The event type is `V1_EVENT_TYPES[code % 1000]`.
  - Room lights: the `light` services of child devices (rooms). Zones may list `light` children directly. Map via `hue_id_to_entity_id`.
  - `ambiguous = True` if another enabled rule with the same sensor and code has a non-off action.
  - Rules with `status != "enabled"` are ignored. Any broken link in the chain skips that rule, with no exception.

- [ ] **Step 1: Write failing tests**, using a fixture inventory built in the test (Room_Office with 2 lamps, a switch `/sensors/16`, button 1 owned by that device):
  - `test_off_rule_maps_button_event_to_room_lights`: rule `{"on": false}` on `/groups/1` with code 1002. Result: `{"event.room_office_switch_button_1": [{"event_type": "short_release", "lights": ["light.lamp_a", "light.lamp_b"], "ambiguous": False, ...}]}`.
  - `test_scene_rules_on_same_button_make_it_ambiguous`: add a rule on 1002 with `{"scene": "xyz"}`. Then `ambiguous is True`.
  - `test_disabled_rules_are_ignored`.
  - `test_broken_chain_skips_rule`: no device with that `id_v1` gives `{}`.
  - `test_v1_ids_resolve_per_bridge_only`: two inventories that both use `/groups/1` and `/sensors/16` for different rooms. Each button maps only to its own bridge's room.
- [ ] **Step 2: Run, verify FAIL** (`ImportError: build_off_jobs`).
- [ ] **Step 3: Implement `build_off_jobs`.**
- [ ] **Step 4: Run, verify PASS** (all tests, incl. the existing 14).
- [ ] **Step 5: Commit** `feat(scene_validator): build off-job table from v1 switch rules`.

---

### Task 3: Off-check classifier (pure function)

**Files:**
- Modify: `appdaemon_apps/scene_validator/scene_validator.py` (module level)
- Create: `appdaemon_apps/scene_validator/tests/test_off_classifier.py`

**Interfaces:**
- Produces: `classify_off_check(lights_now: Dict[str, dict], press_window_start: datetime, scene_activated_in_window: bool, ambiguous: bool) -> Tuple[str, List[str]]`.
  - `lights_now[entity] = {"state": "on"|"off", "last_updated": datetime}`.
  - `press_window_start = t_press - 1 s` (the caller computes it).
  - Returns one of `("skip_scene", [])`, `("skip_no_evidence", [])`, `("ok", [])`, `("missed", [entities])`.
  - Rules from spec C.2, in this order:
    1. `scene_activated_in_window` -> `skip_scene`.
    2. "changed" means `last_updated >= press_window_start`. If ambiguous: require at least one changed light that is `off`, and every changed light `off`. Otherwise `skip_no_evidence`.
    3. Missed = `state == "on"` and not changed. If none -> `ok`, else `missed` with the sorted entity list.

- [ ] **Step 1: Write failing tests** (t = 2026-11-22T18:00:00+00:00, window start = t - 1 s):
  - `test_room_off_with_one_missed_lamp`: A off (updated t+0.3 s), B on (updated t-60 s). Expect `("missed", ["light.lamp_b"])`.
  - `test_all_off_is_ok`.
  - `test_scene_step_that_turns_one_lamp_off_is_not_an_off_job`: A off (t+0.3), B on and updated t+0.3 (dimmed), ambiguous. Expect `("skip_no_evidence", [])`.
  - `test_lamp_changed_after_press_is_left_alone`: A off (t+0.3), B on and updated t+2 s (owner switched it back on). Ambiguous, so `skip_no_evidence`. With `ambiguous=False` the result is `("ok", [])`, because B changed and is therefore not "missed".
  - `test_off_update_up_to_1s_before_press_counts`: A off updated t-0.8 s, B on unchanged. Expect `missed` [B].
  - `test_scene_activation_in_window_skips`: `scene_activated_in_window=True`. Expect `skip_scene`.
  - `test_unambiguous_button_needs_no_evidence`: both on, unchanged, `ambiguous=False`. Expect `missed` [A, B].
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement `classify_off_check`.**
- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** `feat(scene_validator): classify room-off checks (evidence, missed lights)`.

---

### Task 4: App wiring: config, listeners, press handling, escalation, supersede

**Files:**
- Modify: `appdaemon_apps/scene_validator/scene_validator.py` (`initialize`, `_handle_scene_activation`, new methods)
- Modify: `appdaemon_apps/scene_validator/tests/conftest.py`. `FakeHass` gets `get_now()` returning a settable `self.now` (aware datetime). `full_states` values may carry `last_updated` as ISO strings, as AppDaemon returns them.
- Create: `appdaemon_apps/scene_validator/tests/test_off_validation_app.py`

**Interfaces:**
- Consumes: `build_off_jobs` (Task 2) and `classify_off_check` (Task 3).
- Produces (methods on `SceneValidator`):
  - Config: `self.off_validation_enabled: bool`, `self.off_validation_rooms: List[str]` (matched against `room_name` or `room_id`), `self.off_check_delay: float` (default 5). They come from `args["off_validation"]` with keys `enabled`, `rooms`, `off_check_delay`.
  - `self.off_jobs`: the `build_off_jobs` result, filtered to enabled rooms.
  - `self.light_activation_at: Dict[str, datetime]` (Hue light rid -> last scene activation time). It is set in `_record_activation` via `self.get_now()`, next to the existing sequence.
  - `on_switch_event(self, entity, attribute, old, new, kwargs)`: reads `event_type` via `get_state(entity, attribute="event_type")` and matches the job's `event_type`. `t_press = datetime.fromisoformat(new)`. Schedules `perform_off_check` after `off_check_delay` with `job` and `t_press`. Keeps one pending check per room: a newer press for the same room replaces the pending one.
  - `perform_off_check(self, kwargs)`:
    - reads `lights_now` via `get_state(e, attribute="all")`,
    - computes `scene_activated_in_window` from `light_activation_at` of the room lights,
    - calls `classify_off_check`, then logs `[SKIP]` / `[OK]`, or sends `light/turn_off` to the missed lights (Level 2),
    - after a confirmed off on an ambiguous button, records ownership `off:<room_name>` via the existing per-light sequence. That makes pending scene validations on those lights abort with the existing `[SKIP] ... superseded`. Unambiguous buttons record ownership already in `on_switch_event` (at press time),
    - before sending anything, passes `check_rate_limits(f"off:{room_name}")` and the circuit breaker state, so off checks share the existing global limits,
    - schedules `perform_off_level3` after `validation_delay`.
  - `perform_off_level3`: re-checks the lights that were missed. If any are still on: individual `light/turn_off`, then a final check after `level3_settle_delay`. Logs `[OK]`, or `[FAIL]` plus `record_failure()`. Before each step it re-checks `scene_activated_in_window`, and aborts with `[SKIP]` if a scene was activated meanwhile.
  - Startup: if `off_validation.enabled` but no inventory has `resources.v1`, log `[WARN] off validation disabled: inventory has no v1 rules (regenerate inventory)` and register no listeners.
  - Startup log line: `Monitoring <n> switch button(s) for room-off jobs (<rooms>)`.

- [ ] **Step 1: Write failing tests** (fixture: the Task 2 inventory plus `v1`, registry incl. the event entity, `off_validation: {enabled: true, rooms: ["Room_Office"]}`):
  - `test_listens_to_switch_buttons_of_enabled_rooms_only`.
  - `test_missed_lamp_is_switched_off_after_press`: press, then A off (updated t+0.3) and B on (unchanged). `run_scheduled()` gives `("light/turn_off", {"entity_id": "light.lamp_b"})` in `service_calls`.
  - `test_scene_step_press_sends_nothing`: press plus a select change to a scene on the room (via `on_select_state_changed`) gives no `light/turn_off`.
  - `test_room_off_supersedes_pending_scene_validation`: scene activation pending, then a confirmed room-off. The scene validation aborts (no `scene/turn_on`).
  - `test_old_inventory_disables_off_validation_with_warning`: no `v1` key gives no switch listeners and a `[WARN]` log line, and the existing scene listeners are still registered.
  - `test_off_validation_disabled_by_default`: no `off_validation` arg gives no switch listeners.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** the config, listeners and methods above.
- [ ] **Step 4: Run, verify PASS** (all tests).
- [ ] **Step 5: Commit** `feat(scene_validator): verify Hue room-off jobs from switch presses`.

---

### Task 5: Version, docs, example config

**Files:**
- Modify: `scene_validator.py` header plus `__VERSION__ = "2.4.0"`. The startup `Detection:` line also mentions room-off when it is enabled.
- Modify: `appdaemon_apps/scene_validator/README.md` (feature, changelog 2.4.0, requirement: inventory from Task 1).
- Modify: `appdaemon_apps/scene_validator/apps.yaml.example` (`off_validation` block from spec D, commented, disabled).

- [ ] **Step 1: Apply the edits.** Run the tests: all pass.
- [ ] **Step 2: Sensitive-data scan:** `git diff master... | grep -iE "<the CLAUDE.md pattern list>"` prints nothing.
- [ ] **Step 3: Commit** `docs(scene_validator): 2.4.0 room-off validation`.

---

### Task 6: Integration test on ha-test (Room_Office only)

No code. Each step is an action with a checkable result. Record the results in the final commit message or the PR text.

- [ ] **Step 1:** Regenerate the local inventories with the Task 1 script (read-only on the bridges). Check that the job table contains Room_Office's switch: a quick Python call of `build_off_jobs` with the ha-test registry prints exactly one event entity for Room_Office, `ambiguous=True`.
- [ ] **Step 2:** Start ha-test (2026.11.2) and AppDaemon 4.5.16 (Docker, network `ha-test-net`, inventories mounted read-only, `entity_registry_path` = ha-test registry). Config: `off_validation: {enabled: true, rooms: [Room_Office]}`, scene `name_patterns` restricted to Room_Office. The startup log shows `Monitoring 1 switch button(s) for room-off jobs`.
- [ ] **Step 3:** Ask the owner for permission, then stop the production AppDaemon (`ha apps stop a0d7b954_appdaemon`).
- [ ] **Step 4 (simulated missed command):** Snapshot the Room_Office lights. Turn both on. Fake a press by POSTing `/api/states/<event entity>` with the current ISO time and `event_type: short_release`. Within 1 s, switch **one** lamp off directly on the bridge (aiohue). Expected log: `missed` -> `light/turn_off` for the other lamp. Both lamps end up off.
- [ ] **Step 5 (owner presses the real switch):** The owner cycles through the scenes, including "Nachtlicht". Expected: no off command at any step (`[SKIP]` lines only). The owner then switches the room off with the real switch. Expected: `[OK]`.
- [ ] **Step 6:** Restore the light snapshot, start the production AppDaemon, stop AppDaemon/ha-test. Verify the production state is `started`.

---

### Task 7: Production rollout (only after the owner approves)

- [ ] **Step 1:** Copy the new inventories to production with `scripts/sync-inventory-to-ha.sh`. Check that the 2.3.2 validator still starts cleanly (`ha apps restart`, logs).
- [ ] **Step 2:** Back up the production `scene_validator.py` (`.backup_2.3.2_<ts>`), deploy 2.4.0, compare md5, delete `*.pyc`.
- [ ] **Step 3:** Add `off_validation: {enabled: true, rooms: [<office room name>], off_check_delay: 5}` to the production `apps.yaml`, after backing it up. Restart and check the startup lines.
- [ ] **Step 4:** Watch the logs passively while the owner uses the switch. Do not trigger anything on production.
