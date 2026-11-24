# Scene Validator for Philips Hue

**Version:** 2.5.1

AppDaemon automation for validating Philips Hue scene activations in Home Assistant with intelligent 3-level escalation.

## Features

- **Scene Detection from any source**: HA-initiated activations via `scene.*` state changes; activations from outside HA (Hue app, physical switches, Hue automations) via the Hue active-scene `select.*` entities (requires Home Assistant 2026.10+). Select options are mapped to the exact scene by ID, reproducing HA's numbering of duplicate names within a group. If an inventory scene of the group is missing from the select's live options, or the live options sharing the chosen option's base name (without " (N)") differ from the inventory's (a duplicate name was added or renamed, so the numbering may have shifted), the activation is not validated: `[WARN] <select> options differ from inventory - not validated (regenerate inventory)`. Extra live options with other names (smart scenes, scenes added after the inventory) are allowed. Recalling the scene the select already shows does not change the select, so it does not trigger validation (an HA-initiated recall is still seen via `scene.*`).
- **3-Level Escalation**: Validate → Re-trigger → Individual Control
- **Adaptive Delays**: Automatically uses 2x/3x delays when only color temperature fails
- **Configurable Tolerances**: Brightness, color (XY), and color temperature validation
- **Debug Logging**: Optional verbose logging for troubleshooting
- **Circuit Breaker**: Automatic kill switch for runaway validations
- **Rate Limiting**: Per-scene and global validation limits
- **Room-off Validation** (optional, off by default): after a Hue switch press switches a room off, checks `off_check_delay` seconds (default 5) later that all room lights are off and switches off lights that missed the command. Lights the owner changed after the press are never touched.

## Requirements

- AppDaemon 4.x
- Home Assistant with Hue integration (V2); select-based detection (activations from outside HA) requires Home Assistant 2026.10+
- Hue bridge inventories in `/homeassistant/hue_inventories/`
- For room-off validation: inventories written by `scripts/inventory-hue-bridge.py` (2.4.0 format, with v1 `rules`). Older inventories disable room-off validation with a `[WARN]` line; scene validation is unaffected.

## Installation

1. Copy `scene_validator.py` to your AppDaemon apps directory
2. Copy `apps.yaml.example` to `apps.yaml` and configure parameters
3. Restart AppDaemon

## Configuration

📖 **For detailed information about how AppDaemon configuration works, see [CONFIGURATION.md](CONFIGURATION.md)**

See `apps.yaml.example` for all available parameters:

```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  # Inventory paths
  inventory_dir: /homeassistant/hue_inventories

  # Timing Configuration (seconds)
  transition_delay: 5              # Wait after scene activation before Level 1
  validation_delay: 2              # Wait before Level 2 (multiplied by 2x/3x for color_temp)
  level3_settle_delay: 3           # Wait after Level 3 control before final validation
  validation_debounce: 30          # Prevent duplicate validations

  # Validation Tolerances
  color_temp_tolerance: 50         # Color temperature (mirek units)
  brightness_tolerance: 5          # Brightness (percentage points)
  color_tolerance: 0.01            # XY color coordinates

  # Debug Logging
  debug_logging: true              # Enable verbose OK/success logging

  # Rate Limiting
  max_validations_per_minute: 20
  max_validations_per_scene_per_minute: 5

  # Scene Filtering
  scene_filter:
    name_patterns:
      - ".*Standard$"              # Scenes ending with "Standard"
      - ".*Nachtlicht$"            # Scenes ending with "Nachtlicht"

  # Room-off validation (optional, disabled by default)
  off_validation:
    enabled: false                 # default off
    rooms: []                      # room names or v2 ids; empty = none
    off_check_delay: 5             # seconds after the press
```

### Room-off Validation (2.4.0)

When a Hue switch press switches a room off, the validator checks about
`off_check_delay` seconds later whether every light in that room is off.
Lights that missed the command (still on, and unchanged since the press) are
switched off. Only rooms listed in `off_validation.rooms` are covered.

Limitations:
- Only Hue switches configured as v1 rules on the bridge are covered. Hue app "room off", Hue schedules, and off commands sent from HA are not covered.
- Presses replayed after an HA restart are ignored (press older than `off_check_delay` + 2 s). Since 2.5.1 the first press after a switch's event entity is created is checked.
- Known assumption: it only helps if the bridge reports a lamp that missed the command as still on.
- A lamp the owner changes after the press is never touched.
- Hue-app generated off-rules usually also write a CLIP status sensor, so those buttons are treated as ambiguous and need evidence (a light switched off by the press) before anything is sent (safe direction). Only an unconditional off-rule makes a press a certain room-off (a `lastupdated ddx` condition is a delayed trigger and also counts as conditional). If two rules give the same room-off job, one unconditional off-rule is enough.
- Evidence window (ambiguous buttons, 2.5.1): only light updates within 2 s after the press (and up to 1 s before it) count as evidence, because the bridge executes the rule immediately. Later changes (e.g. the owner in the Hue app) are not evidence, and are never commanded either.
- A scene activated before the press does not block a certain (unconditional) room-off; for ambiguous buttons a scene up to 1 s before the press still marks the press as a scene step.
- Scene validation: if all lights a scene switched on are switched off within the check window (e.g. Hue app room off), this is treated as a deliberate room off and the scene is not re-triggered. (The switch-press room-off check still does not cover the Hue app.)
- If a room is switched off just before a scene is activated and every lamp also misses the scene command, the scene may not be corrected (very unlikely).
- A real HA activation of the same scene within 3 s of the validator's own Level 2 re-trigger is treated as the re-trigger's echo and not validated again (harmless: same scene, same outcome).
- Select-reported activations whose scene was renamed and whose old name was reused by another scene are declined: `[WARN] <select> option '<name>' resolves to scene named '<other>' - not validated (regenerate inventory)` (uses the scene's `name` attribute; skipped if it is missing).
- The bridge's select report of an HA-initiated activation (within 2 s of the scene.* timestamp) is the same activation, not a new one: it does not re-stamp room-off evidence. A real re-activation of the same scene from the Hue app within those 2 s is treated the same way.
- Dynamic scenes are never re-triggered (2.5.0): a re-trigger could undo owner dimming that the on/off check cannot see; lamps that missed the command get Level 3 (on/off only).

Example: `off_validation.rooms: [Room_Office]`. Enable one room first and watch the log for `Room off` lines.

## How It Works

### Level 1: Initial Validation
- Wait `transition_delay` seconds after scene activation
- Validate all light states against scene expectations
- If successful → Done ✓
- If failed → classify the failing lights (2.5.0):
  - **missed**: no update since the activation (`last_updated` more than 1 s before it). Only these are corrected.
  - **changed**: updated after the activation (owner or Hue). Left alone with `[SKIP] <light> changed after activation`; a `[WARN] ... inventory may be outdated` line is added if the light reacted within 2 s of the activation (`REACTION_WINDOW`) but its brightness, colour or colour temperature differs from the inventory.
  - Only changed lights fail → `[OK] nothing to correct (only owner/Hue changes)`, nothing recorded
  - Every failing light missed, and no reachable scene light was touched 2 s or more after the activation → Level 2
  - A scene light (failing or passing) touched 2 s or more after the activation (most likely the owner) → no Level 2; Level 3 for the missed lights only
  - Missed and changed lights → no Level 2 (it would undo the changes); Level 3 for the missed lights only

### Level 2: Re-trigger Scene
- Re-activate the scene (only if every failing light missed the command)
- Wait `validation_delay` × `delay_multiplier` seconds (2x if only color temp failed)
- Validate again
- If successful → Done ✓
- If failed → re-classify against the original activation; lights updated meanwhile are left alone; the missed ones go to Level 3

### Level 3: Individual Light Control
- Control each light that still fails and still missed the command
- Wait `level3_settle_delay` seconds for lights to settle
- Perform final validation (of the controlled lights only)
- Report true success or failure

## Logging Format

All logs follow a consistent `[scene] [light] [check] : info` format:

```text
[scene.room_office_standard] LEVEL 1: Validating scene state
[scene.room_office_standard] [light.lamp_a] [BRIGHTNESS] OK: exp 0.0%, got 0.0%, diff 0.0% < tol 5%
[scene.room_office_standard] [light.lamp_a] [COLOR_TEMP] FAIL: exp 499, got 346, diff 153 > tol 50
[scene.room_office_standard] [ADAPTIVE] Only color_temp failed - using 2x delay for Level 2 (4s)
[scene.room_office_standard] [FAIL] Validation failed (failures: color_temp)
[scene.room_office_standard] LEVEL 2: Re-triggering scene
```

Set `debug_logging: false` to only show failures (cleaner logs for production).

## Version History

- **2.5.1**: PR #20 review fixes. Scene path: first HA activation of a never-activated scene validates; A -> B -> A runs only the newest chain; scene.* activations use the scene timestamp; the validator's own re-trigger echo is ignored; unresolved selects supersede older validations; select options must match the inventory; no whole-scene replay once a light was adjusted after the scene reacted; dynamic scenes with legacy actions are not replayed. Room-off path: first press on a new event entity is checked; scene steps wait for the real (scheduled) off check; an older scene no longer blocks a certain room-off; 2 s evidence window; unconditional rule wins on merge; `ddx` is conditional; follow-ups with unreachable targets record nothing. Inventory script: HTTP status errors are kept.
- **2.5.0**: Only lamps that missed the command are corrected; lamps changed after activation (owner or Hue) are left alone. Restored/re-added entities after an integration reload are ignored. exclude_uids and labels now work. Duplicate inventories are de-duplicated.
- **2.4.2**: Unreachable lights (unavailable/unknown) are skipped in scene validation and never controlled; a scene is no longer failed or re-triggered because of them.
- **2.4.1**: Dynamic scenes (is_dynamic) are validated and corrected on/off only, so animations are not frozen. Validating every scene is now safe (remove name_patterns).
- **2.4.0**: Room-off validation after Hue switch presses (optional, `off_validation`); inventory script writes rooms/zones, buttons and v1 `rules`
- **2.3.2**: HA 2026.x compatibility for color temperature - Level 3 sends `color_temp_kelvin` (HA rejects the removed `color_temp`), validation reads `color_temp_kelvin` (color temperature checks were silently skipped)
- **2.3.1**: Abort validation/escalation when a newer scene was activated on any of the same lights (also unvalidated scenes and overlapping zones); re-activating a scene after another scene took over its lights is no longer swallowed by the debounce
- **2.3.0**: Detect activations from outside HA via Hue select entities; listeners no longer depend on HA states at startup; optional `entity_registry_path`
- **2.2.0-FORMATTED**: Consistent logging format + debug flag
- **2.1.1-CLEAN**: Production ready - debug logs removed
- **2.1.0-FINAL**: All tolerances and delays configurable
- **2.0.14**: Added Level 3 final validation
- **2.0.13**: Comprehensive callback logging
- **2.0.12**: Adaptive delays for color temperature
- **2.0.11**: Entity registry-based scene matching

## License

MIT License - Feel free to use and modify.
