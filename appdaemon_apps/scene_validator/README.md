# Scene Validator for Philips Hue

**Version:** 2.2.0-FORMATTED

AppDaemon automation for validating Philips Hue scene activations in Home Assistant with intelligent 3-level escalation.

## Features

- **Universal Scene Detection**: Detects scene activations from any source (HA UI, Hue app, physical switches, Hue automations)
- **3-Level Escalation**: Validate → Re-trigger → Individual Control
- **Adaptive Delays**: Automatically uses 2x/3x delays when only color temperature fails
- **Configurable Tolerances**: Brightness, color (XY), and color temperature validation
- **Debug Logging**: Optional verbose logging for troubleshooting
- **Circuit Breaker**: Automatic kill switch for runaway validations
- **Rate Limiting**: Per-scene and global validation limits

## Requirements

- AppDaemon 4.x
- Home Assistant with Hue integration (V2)
- Hue bridge inventories in `/homeassistant/hue_inventories/`

## Installation

1. Copy `scene_validator.py` to your AppDaemon apps directory
2. Copy `apps.yaml.example` to `apps.yaml` and configure parameters
3. Restart AppDaemon

## Configuration

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
```

## How It Works

### Level 1: Initial Validation
- Wait `transition_delay` seconds after scene activation
- Validate all light states against scene expectations
- If successful → Done ✓
- If failed → Proceed to Level 2

### Level 2: Re-trigger Scene
- Re-activate the scene
- Wait `validation_delay` × `delay_multiplier` seconds (2x if only color temp failed)
- Validate again
- If successful → Done ✓
- If failed → Proceed to Level 3

### Level 3: Individual Light Control
- Control each light individually
- Wait `level3_settle_delay` seconds for lights to settle
- Perform final validation
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

- **2.2.0-FORMATTED**: Consistent logging format + debug flag
- **2.1.1-CLEAN**: Production ready - debug logs removed
- **2.1.0-FINAL**: All tolerances and delays configurable
- **2.0.14**: Added Level 3 final validation
- **2.0.13**: Comprehensive callback logging
- **2.0.12**: Adaptive delays for color temperature
- **2.0.11**: Entity registry-based scene matching

## License

MIT License - Feel free to use and modify.
