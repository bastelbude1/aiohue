# Scene Validator for Philips Hue

**Version:** 2.5.0

AppDaemon automation for validating Philips Hue scene activations in Home Assistant with intelligent 3-level escalation.

## Features

- **Scene Detection from any source**: HA-initiated activations via `scene.*` state changes; activations from outside HA (Hue app, physical switches, Hue automations) via the Hue active-scene `select.*` entities (Home Assistant 2026.x+). Select options are mapped to the exact scene by ID, reproducing HA's numbering of duplicate names within a group.
- **3-Level Escalation**: Validate → Re-trigger → Individual Control
- **Adaptive Delays**: Automatically uses 2x/3x delays when only color temperature fails
- **Configurable Tolerances**: Brightness, color (XY), and color temperature validation
- **Debug Logging**: Optional verbose logging for troubleshooting
- **Circuit Breaker**: Automatic kill switch for runaway validations
- **Rate Limiting**: Per-scene and global validation limits
- **Room-off Validation** (optional, off by default): after a Hue switch press switches a room off, checks `off_check_delay` seconds (default 5) later that all room lights are off and switches off lights that missed the command. Lights the owner changed after the press are never touched.

## Requirements

- AppDaemon 4.x
- Home Assistant with Hue integration (V2)
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
- The first press after a switch's event entity is first created in HA is ignored, and presses replayed after an HA restart are ignored.
- Known assumption: it only helps if the bridge reports a lamp that missed the command as still on.
- A lamp the owner changes after the press is never touched.
- Hue-app generated off-rules usually also write a CLIP status sensor, so those buttons are treated as ambiguous and need evidence (a light switched off by the press) before anything is sent (safe direction). Only an unconditional off-rule makes a press a certain room-off.
- Scene validation: if all lights a scene switched on are switched off within the check window (e.g. Hue app room off), this is treated as a deliberate room off and the scene is not re-triggered. (The switch-press room-off check still does not cover the Hue app.)
- If a room is switched off just before a scene is activated and every lamp also misses the scene command, the scene may not be corrected (very unlikely).

Example: `off_validation.rooms: [Room_Office]`. Enable one room first and watch the log for `Room off` lines.

## How It Works

### Level 1: Initial Validation
- Wait `transition_delay` seconds after scene activation
- Validate all light states against scene expectations
- If successful → Done ✓
- If failed → classify the failing lights (2.5.0):
  - **missed**: no update since the activation (`last_updated` more than 1 s before it). Only these are corrected.
  - **changed**: updated after the activation (owner or Hue). Left alone with `[SKIP] <light> changed after activation`; a `[WARN] ... inventory may be outdated` line is added if the light reacted within `transition_delay` but differs from the inventory.
  - Only changed lights fail → `[OK] nothing to correct (only owner/Hue changes)`, nothing recorded
  - Every failing light missed → Level 2
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
[scene.buro_markus_nachtlicht] LEVEL 1: Validating scene state
[scene.buro_markus_nachtlicht] [light.ecklampe_markus_buro] [BRIGHTNESS] OK: exp 0.0%, got 0.0%, diff 0.0% < tol 5%
[scene.buro_markus_nachtlicht] [light.ecklampe_markus_buro] [COLOR_TEMP] FAIL: exp 499, got 346, diff 153 > tol 50
[scene.buro_markus_nachtlicht] [ADAPTIVE] Only color_temp failed - using 2x delay for Level 2 (4s)
[scene.buro_markus_nachtlicht] [FAIL] Validation failed (failures: color_temp)
[scene.buro_markus_nachtlicht] LEVEL 2: Re-triggering scene
```

Set `debug_logging: false` to only show failures (cleaner logs for production).

## Version History

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
