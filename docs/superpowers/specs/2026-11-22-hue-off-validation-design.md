# Design: Verify Hue "room off" jobs (scene_validator off-validation)

Date: 2026-11-22
Status: draft, awaiting approval. Builder check done, and its questions are
answered below and marked "decided" where the author made the call.
Component: `appdaemon_apps/scene_validator/` (AppDaemon app) and `scripts/inventory-hue-bridge.py`

## Intent

Hue switches and Hue automations send their commands straight to the bridge.
Home Assistant (HA) only sees the result. Sometimes a bulb misses a command
(radio problem) and keeps burning after its room was switched off.

The owner's principle: **HA only checks whether Hue did the job it was given.
HA does not make its own decisions.** So HA must know the job, and must not
guess it from light changes alone.

scene_validator 2.3.2 already does this for scene activations: it knows the
target state from the inventory and checks it ~5 s after the activation.
This design adds the same for "room off" jobs.

## Goals

- When a Hue switch press switches a room off, HA checks after a short delay
  that every light of that room is off.
- Lights that **missed** the command are switched off again: still on, and
  unchanged since the press.
- The job (which button switches which room off) comes from the bridge
  configuration, not from guessing.
- Opt-in per room. Start with one test room (the owner's office, called
  `Room_Office` below).

## Non-goals (for this iteration)

- Hue automations / schedules (v2 `behavior_instance`, script "Schedule").
  The inventory will already capture them (see below), but checking them
  needs time-based triggers. That is a later iteration. The test room has
  none today.
- Off commands issued by HA itself (`light.turn_off` via UI or automations).
- Hue app "room off" (no switch press is visible to HA).
- Permanent enforcement. The check runs once per job, shortly after it.

## Anti-goals (a failure even if it "works")

- Turning off a light the owner deliberately switched (back) on. Any light
  whose state changed after the press must be left alone.
- Acting on light changes that no known Hue job explains. For example, a
  single lamp switched off in the Hue app must never cause other lamps to be
  switched off.
- Fighting a newer job. If a scene is activated on the same lights before
  the check runs, the off-check is aborted. Reuse the 2.3.1 supersede logic.
- Writing bridge credentials into the inventory. v1 rules contain an
  `owner` field, which is a bridge username (credential). It must be
  stripped.

## Findings this design builds on (verified 2026-11-22)

1. **HA cannot see the job.** The Hue grouped light state is "joined on
   control & aggregated on state" (`aiohue/v2/models/grouped_light.py:36`).
   It stays "on" while any member burns, so it never reports "off" in the
   failure case. Also, most room grouped-light entities are disabled in HA
   by default; the test room's one is disabled on production.
2. **The bridge knows the job.** The test room's switch is configured as
   **legacy v1 rules**, not as v2 `behavior_instance`. Example (anonymised):
   - Rule "17:": conditions = switch sensor `/sensors/16` `buttonevent ==
     1002` AND a CLIPGenericStatus "cycling" sensor; action =
     `/groups/1/action` `{"on": false}`. This is "room off".
   - Ten more rules on the same button 1002, with "cycling"/"slotState"
     CLIP conditions, recall scenes. This is a scene cycle on one button.
   - Rules on 1001/1003 dim the room.
   So **the same button press can mean "next scene" or "room off"**,
   depending on bridge-internal CLIP state that HA cannot evaluate.
3. **HA sees the press.** HA exposes each Hue button as an event entity,
   e.g. `event.<switch>_button_1`. Its `event_type` is one of
   `initial_press`, `repeat`, `short_release`, `long_press`, `long_release`.
   The entity `unique_id` is the v2 button resource id
   (`homeassistant/components/hue/v2/entity.py:58`).
4. **The ID chain exists.** v1 `buttonevent` codes are `<button><x>`, where
   x is 0 = initial_press, 1 = repeat, 2 = short_release, 3 = long_release
   (1002 = button 1, short_release). The v1 sensor `/sensors/16` is a v2
   device with `id_v1 == "/sensors/16"`. Its v2 `button` services carry
   `metadata.control_id` (button number) and an id that equals the HA event
   entity `unique_id`. The v1 group `/groups/1` is the v2 room with
   `id_v1 == "/groups/1"`.
5. **The inventory has no rooms or zones today (bug).**
   `scripts/inventory-hue-bridge.py:314` filters with `g.type == "zone"`,
   but `g.type` is an `Enum` (`ResourceTypes.ZONE == "zone"` is `False`).
   Room children are devices. The lights of a room are the `light` services
   of those devices.
6. **A cycle step can switch lights off.** The test room's button cycles
   through 4 scenes. One of them ("Nachtlicht") switches 1 of the 2 lamps
   off. So "a room light went off after the press" alone does not prove a
   room-off. See the evidence rule in C.2.
7. **Other readers of the inventories:** `scripts/query-hue-inventory.py`,
   `scripts/export-ha-hue-inventory.py`, `scripts/sync-inventory-to-ha.sh`
   and both scene_validator copies.

## Approaches considered

1. **Job from bridge configuration (chosen).** Read rules and behaviors into
   the inventory, build a job table "button X of switch Y can switch room R
   off", and check room R after such a press. Exact; respects the principle.
   Costs an inventory extension and rule parsing.
2. **Pattern only.** Treat "several lights of a room go off together" as a
   room-off. Cheap, but in a 2-lamp room "one lamp missed the command" looks
   the same as "owner switched one lamp off in the app". That breaks the
   principle. Rejected.
3. **Switch press only, without effect evidence.** Wrong in this setup,
   because the same press often means "next scene" (finding 2). Rejected as
   a standalone rule. It is used as the trigger in approach 1.

## Design

### A. Inventory (`scripts/inventory-hue-bridge.py`)

- Fix the room/zone filter: compare `g.type` against `ResourceTypes.ROOM` /
  `ResourceTypes.ZONE` (or `.value`).
- For rooms and zones, store `id`, `id_v1`, `metadata.name`, `children`
  (device rids) and `services` (incl. the grouped_light rid) as structured
  dicts `{rid, rtype}`, not as `str(ResourceIdentifier)`.
- Add v1 `rules` and `sensors` (GET `/api/<user>/rules` and `/sensors`).
  Drop the `owner` field from every rule before writing.
- Add v2 `behavior_instance` and `behavior_script` (id, name, enabled,
  configuration). These are stored for the later automation iteration.
- For devices, also store `id_v1` and services as structured `{rid, rtype}`.
  For button resources, store `metadata.control_id`. The job table needs
  these.
- **Additive only (decided):** existing keys keep their format, because
  other scripts read them (finding 7). New data goes into new keys:
  - the rooms/zones fix fills the existing empty `groups.rooms` and
    `groups.zones` lists,
  - new fields on device and button entries,
  - v1 data under `resources.v1.rules` and `resources.v1.sensors`. This
    avoids the clash with the existing v2 `resources.sensors`.
- **Rollout order (decided):** the new inventory first. The 2.3.2 validator
  ignores unknown keys. 2.4.0 must also start with an old inventory: off
  validation is then disabled, with a `[WARN]` line.
- Inventories stay git-ignored (`*.json`), as today.

### B. Job table (validator startup)

For every enabled v1 rule with an action `{"on": false}` on
`/groups/<n>/action`:

- Find the room/zone with `id_v1 == "/groups/<n>"`. Its target lights are
  the `light` services of its child devices, mapped to HA entity_ids via
  the entity registry. This is the existing `hue_id_to_entity_id`.
- Find the condition `"/sensors/<s>/state/buttonevent" eq <code>`, then the
  v2 device with `id_v1 == "/sensors/<s>"`, then its `button` service with
  `control_id == code // 1000`, then the HA event entity whose `unique_id`
  is that button id. The HA event_type comes from `code % 1000` (see
  finding 4).
- Record whether the button is **ambiguous**: other enabled rules with the
  same sensor and code have non-off actions (scene recall, dimming).

Result: `off_jobs[event_entity] = [(event_type, room_id, light_entities,
ambiguous)]`. Log a summary line at startup, ASCII only.

### C. Runtime

1. `listen_state` on each event entity in the job table. On a new state with
   a matching `event_type`, record `t_press` and a snapshot of the room
   lights (`state`, `last_updated`).
   - **`t_press` (decided):** the event entity's new state value, which is
     the bridge-reported press time. Not the AppDaemon callback time.
   - **Press window (decided):** `[t_press - 1 s, check time]`. The 1 s
     backwards tolerance covers light updates that reach HA before the
     button event. They share one event stream, and the order is not
     guaranteed.
2. After `off_check_delay` seconds (default 5, configurable):
   - **Evidence rule (ambiguous buttons, decided):** proceed only if
     **all three** hold within the press window:
     a. at least one room light changed to `off`,
     b. **every** room light that changed, changed to `off`. A scene step
        like "Nachtlicht" turns one lamp off and changes the other one's
        brightness, so it fails this condition (finding 6),
     c. no scene activation was observed on any room light. That means
        neither the room's select changing to a scene nor a `scene.*`
        state change. If one was observed, the press was a scene step, and
        the existing scene validation handles it.
   - Unambiguous buttons (only an off-rule) proceed without evidence.
   - **Missed lights (decided: `last_updated`, not `last_changed`):** room
     lights that are `on` now and have **no update at all** since
     `t_press - 1 s`. A lamp that missed the command gets no updates. A lamp
     the owner dimmed, recoloured or switched after the press did get one,
     and is never touched (anti-goal 1).
   - If there are none, log `[OK]`. Otherwise send `light.turn_off` to each
     missed light (Level 2). After `validation_delay`, re-check. Lights still
     on get one more individual `light.turn_off` (Level 3). Then a final
     check: log `[OK]`, or `[FAIL]` and `record_failure()` (shared circuit
     breaker).
3. **Supersede (decided: time window, not pure sequence order):**
   - Any scene activation on the room lights within the press window
     aborts the off-check with `[SKIP]`, in either arrival order. This is
     evidence rule c, re-checked before every Level.
   - For ambiguous buttons, the off job registers with the 2.3.1
     per-light ownership (owner `off:<room>`) **only after** the evidence
     rule has confirmed it. It then supersedes a pending scene validation
     on the same lights, so the validator never re-triggers a scene the
     owner just switched off. Registering at press time could let a
     scene step be superseded by a wrongly assumed off (anti-goal 3).
   - Unambiguous buttons register at press time.
4. **Debounce / rate limits:** one pending off-check per room. A new press
   restarts it. Shared global rate limit and circuit breaker.

### D. Configuration (`apps.yaml`)

```yaml
off_validation:
  enabled: false          # default off
  rooms: []               # room names or v2 ids; empty = none
  off_check_delay: 5      # seconds after the press
```

Production rollout: enable for `Room_Office` only.

## Constraints

- Production: HA 2026.11.2, AppDaemon add-on 0.19.3 (AppDaemon 4.5.16,
  Python 3.12). No HA core changes.
- The existing scene validation behaviour must not change.
- Log output ASCII only. No real names, IPs or bridge ids in code or docs.
- Testing:
  - Unit tests at the agreed seams: job-table builder (rule/inventory
    fixtures) and app callbacks with `FakeHass`.
  - Integration on ha-test. ha-test shares the production bridges, so stop
    the production AppDaemon during the test, and use only `Room_Office`.
  - A missed command cannot be forced on a real bulb. Simulate it on ha-test
    instead: set the button event entity state via the HA REST API (fake
    press), then switch off only one room lamp directly on the bridge. The
    other lamp is now "on and unchanged since the press", which is exactly
    the missed-command picture from HA's view.
  - Required negative test on real hardware: a real press that cycles to
    "Nachtlicht" must not cause any off command.
  - The test setup already exists from the 2.3.x work. AppDaemon 4.5.16 runs
    in Docker on network `ha-test-net` against ha-test (2026.11.2), with a
    read-only mount of the local inventories, `entity_registry_path` pointing
    at ha-test's registry, and `name_patterns` restricted to the test room.
    Config files live outside the repo. Recreate them from this description.

## Left to the builder

- Module layout (job-table builder as a pure function next to
  `resolve_scene_entity_from_select` is suggested).
- How the inventory script fetches v1 endpoints (aiohue raw request vs.
  aiohttp with the bridge's self-signed certificate).
- Exact log wording, keeping the existing `[OK]/[FAIL]/[SKIP]` prefixes.
- Version number (suggest 2.4.0).

## Amendment 2026-11-22: deliberate room-off without a switch press

Found in the ha-test run: a scene was activated, and within the 5 s
transition delay **all** its lights were switched off from the Hue app
(no switch press, so there was no off-job). The existing scene validation
then saw "scene active, lights off" and re-triggered the scene.

Owner decision: treat this as a deliberate room-off.

Rule (scene validation, checked before the Level 2 re-trigger, before Level 2
validation, and before Level 3 control): if **every** light that the scene
expects to be ON is now `off`, **and** each of those lights has
`last_updated >= activation time` (it changed after the activation), then
log `[SKIP] <step> - all scene lights switched off after activation
(deliberate room off)`. Do not re-trigger, do not control lights, and do not
record a failure.

Not covered by this rule (still corrected as before):
- Some expected-on lights are off while others are on (a single lamp switched
  off or missed).
- Expected-on lights that are off but have **not** changed since the
  activation. They missed the scene command, which is what the validator
  exists to fix.
- Expected-on lights that are unavailable or have no state. The rule needs
  every expected-on light to be known and off.

## Amendment 2026-11-23: validate every scene, on/off only for dynamic scenes (2.4.1)

Owner decision: every Hue scene that Hue activates is validated (the production
`name_patterns` filter is removed). Dynamic scenes (HA scene attribute
`is_dynamic == true`, 27 of 201 today) animate colour and brightness, so a
static comparison would always fail. Level 2/3 would then freeze the
animation.

Rule:
- For a scene with `is_dynamic == true`, Level 1 and Level 2 compare only the
  on/off state of each light.
- Level 3 only switches lights on or off. On means `light.turn_on` with
  no brightness or colour; off means `light.turn_off`.
- Static scenes keep the full check.
- The deliberate-room-off rule and the switch room-off check are unchanged.

## Amendment 2026-11-24: unreachable lights are skipped (2.4.2)

Found on the Terrasse test: an unreachable lamp (HA state `unavailable`) was
counted as "off". The scene therefore failed on every activation: Level 2
re-trigger (restarts a dynamic animation), Level 3, and a circuit-breaker
failure. Production has 28 unreachable Hue lights. Once every scene is
validated, this would open the circuit breaker and pause all validation.

Rule (scene validation, static and dynamic):
- A light whose HA state is `unavailable`, `unknown` or missing is skipped.
  It is neither OK nor a failure, it gets no command in Level 3, and it is
  logged once per validation run as
  `[<scene>] [SKIP] <light> unavailable - not validated`.
- The scene passes if every other light passes.
- If every light of the scene is skipped, the run ends with
  `[SKIP] all scene lights unavailable` and records neither success nor
  failure.
- Applies to Level 1, Level 2, Level 3 control and the Level 3 final
  validation.
- The room-off check and the deliberate-room-off rule already treat
  unavailable lights conservatively and are unchanged.
- Addendum (review of 2.4.2): the deliberate-room-off rule ignores unreachable
  lights too. It considers only reachable expected-on lights and needs at least
  one of them. If all reachable expected-on lights are `off` with
  `last_updated >= activation time`, the off is deliberate. Without this, a
  Hue-app room off in any room with an unreachable lamp would re-trigger the
  scene and switch the room back on.
