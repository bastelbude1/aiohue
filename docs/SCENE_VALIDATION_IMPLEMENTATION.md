# Scene Validation Implementation Guide

## Enhanced Hybrid Approach: Scene → Individual Lights Fallback

**Final Recommendation**: 3-level escalation with inventory-based validation

**Status**: Ready for implementation
**Date**: 2025-11-13
**Related**: [SCENE_VALIDATION_ANALYSIS.md](SCENE_VALIDATION_ANALYSIS.md)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Inventory Sync Workflow](#inventory-sync-workflow)
5. [AppDaemon Implementation](#appdaemon-implementation)
6. [Scene Filtering Configuration](#scene-filtering-configuration)
7. [Deployment Steps](#deployment-steps)
8. [Testing Strategy](#testing-strategy)
9. [Monitoring & Maintenance](#monitoring--maintenance)
10. [Troubleshooting](#troubleshooting)

---

## Overview

### Problem

When Hue scenes are activated, lights may not reach their target states due to:
- Network issues between HA and bridge
- Hue bridge being overloaded
- Individual bulb communication failures
- Scene corruption or misconfiguration

Neither the Hue bridge nor Home Assistant detects these failures automatically.

### Solution: 3-Level Escalation

```text
Level 1: Initial Scene Activation
  User triggers scene.wohnzimmer_standard
  → Hue bridge activates scene
  → Wait 5 seconds
  → Validate actual states against inventory
  ✓ Success → Done
  ✗ Failure → Level 2

Level 2: Re-trigger Scene
  → Re-trigger scene.wohnzimmer_standard
  → Wait 5 seconds
  → Validate again
  ✓ Success → Done
  ✗ Failure → Level 3

Level 3: Individual Light Control (Fallback)
  → Parse scene from Hue inventory
  → Set each light individually via HA
  → Bypass Hue scene mechanism completely
  → Wait 5 seconds
  → Final validation
  ✓ Success → Done
  ✗ Failure → Alert user (critical failure)
```

### Key Features

- ✅ **Inventory-based validation**: Ground truth from Hue bridge scene definitions
- ✅ **Automatic correction**: Re-triggers scenes or sets lights individually
- ✅ **Fallback mechanism**: Works even if Hue bridge scenes fail
- ✅ **Snapshot capture**: Records actual states for drift detection
- ✅ **Selective validation**: Filter scenes by labels or patterns (avoid validating all 214 scenes)
- ✅ **Minimal overhead**: Validation only on scene activation, not continuous monitoring
- ✅ **User notifications**: Alerts on critical failures

---

## Architecture

### Component Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│ LocalMachine (Local Machine)                                      │
│                                                                  │
│  ┌────────────────────────┐         ┌─────────────────────┐    │
│  │ inventory-hue-bridge.py│────────▶│ bridges/inventory/  │    │
│  │  - Captures inventories│         │  - EG.json          │    │
│  │  - Uses aiohue 4.8.0   │         │  - OG.json          │    │
│  └────────────────────────┘         └─────────────────────┘    │
│                                               │                 │
│  ┌────────────────────────┐                  │                 │
│  │ sync-inventory-to-ha.sh│                  │                 │
│  │  - Runs inventory script                  │                 │
│  │  - SCPs JSON to HA      │◀─────────────────┘                 │
│  └────────────────────────┘                                    │
│                │                                                │
└────────────────┼────────────────────────────────────────────────┘
                 │ SCP over SSH
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Home Assistant (<HA_IP>)                                 │
│                                                                  │
│  ┌──────────────────────────┐                                   │
│  │ /config/hue_inventories/ │                                   │
│  │  - Bridge_Downstairs.json        │◀──────────┐                       │
│  │  - Bridge_Upstairs.json        │           │                       │
│  └──────────────────────────┘           │                       │
│                                          │                       │
│  ┌──────────────────────────────────────┴──────────────────┐   │
│  │ AppDaemon: scene_validator.py                           │   │
│  │                                                          │   │
│  │  1. Listens for scene activations (event: call_service) │   │
│  │  2. Waits for light transitions (5s)                    │   │
│  │  3. Creates snapshot (scene.create)                     │   │
│  │  4. Validates against inventory:                        │   │
│  │     - On/off states                                     │   │
│  │     - Brightness (±5% tolerance)                        │   │
│  │  5. Escalation on failure:                              │   │
│  │     - Level 2: Re-trigger scene                         │   │
│  │     - Level 3: Set lights individually                  │   │
│  │  6. Sends notifications on critical failures            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ Monitoring Sensors                                      │   │
│  │  - sensor.scene_validation_status                       │   │
│  │  - sensor.scene_validation_stats                        │   │
│  │  - sensor.last_validated_scene                          │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```text
1. User activates scene (UI, automation, switch, voice)
   ↓
2. HA calls scene.turn_on → Hue bridge activates scene
   ↓
3. AppDaemon intercepts call_service event
   ↓
4. Wait for transition (5s)
   ↓
5. Create snapshot (capture actual states)
   ↓
6. Load scene definition from inventory JSON
   ↓
7. Validate each light:
   - Map Hue resource ID → HA entity_id (via unique_id)
   - Compare actual vs target (on/off, brightness)
   ↓
8. If failures detected:
   - Level 2: Re-trigger scene
   - Level 3: Set lights individually from inventory
   ↓
9. Update monitoring sensors
   ↓
10. Send notification if critical failure
```

---

## Prerequisites

### On LocalMachine (Local Machine)

```bash
# Already installed:
- Python 3.8+
- aiohue 4.8.0 in venv
- SSH key: /path/to/workspace/homeassistant_ssh_key
- Hue bridge credentials in bridges/config.json

# Scripts available:
- scripts/inventory-hue-bridge.py
- scripts/sync-inventory-to-ha.sh
```

### On Home Assistant

```bash
# 1. Install AppDaemon add-on
# Home Assistant → Settings → Add-ons → Add-on Store
# Search: "AppDaemon 4" → Install

# 2. Configure AppDaemon
# Add-on Configuration:
system_packages: []
python_packages: []  # No extra packages needed
init_commands: []

# 3. Start AppDaemon add-on

# 4. Create directories
ssh -i /path/to/workspace/homeassistant_ssh_key hassio@<HA_IP>
mkdir -p /homeassistant/hue_inventories
mkdir -p /homeassistant/appdaemon/apps
```

### Hue Inventories

```bash
# Initial sync (run on LocalMachine):
cd /path/to/workspace/aiohue/scripts
./sync-inventory-to-ha.sh

# Verifies these files exist on HA:
/homeassistant/hue_inventories/Bridge_Downstairs-abc123def456.json
/homeassistant/hue_inventories/Bridge_Upstairs-xyz789ghi012.json
```

---

## Inventory Sync Workflow

### When to Update Inventories

Re-run inventory sync when:
- ✅ Created new scenes in Hue app
- ✅ Modified scene brightness/color targets
- ✅ Deleted scenes
- ✅ Added/removed lights from scenes

**NOT needed for**:
- ❌ Normal scene usage
- ❌ Manual light adjustments
- ❌ Adding HA automations

**Frequency**: Estimated monthly or less

### Sync Process

```bash
# On LocalMachine:
cd /path/to/workspace/aiohue/scripts

# Run sync script (captures fresh inventories + copies to HA)
./sync-inventory-to-ha.sh

# Output:
# ===================================================================
# Hue Inventory Sync to Home Assistant
# ===================================================================
#
# Step 1: Capturing fresh Hue bridge inventories...
# Found 2 bridge(s):
#   - Bridge_Downstairs (abc123def456)
#   - Bridge_Upstairs (xyz789ghi012)
# ✓ Inventories captured
#
# Step 2: Ensuring HA inventory directory exists...
# ✓ Directory ready
#
# Step 3: Copying inventories to Home Assistant...
# ✓ Inventories copied
#
# Step 4: Verifying files on Home Assistant...
# Found 2 inventory file(s) on HA
# -rw-r--r-- 1 root root 1.2M Nov 13 10:00 Bridge_Downstairs-abc123def456.json
# -rw-r--r-- 1 root root 856K Nov 13 10:00 Bridge_Upstairs-xyz789ghi012.json
#
# ===================================================================
# ✓ Sync complete!
# ===================================================================
```

### Automatic Reload in AppDaemon

AppDaemon will automatically reload inventories:
- When app restarts
- When `reload_inventories` service is called
- Optionally: File watcher (if implemented)

---

## AppDaemon Implementation

### File Structure

```text
/homeassistant/appdaemon/
├── apps/
│   ├── apps.yaml                    # App configuration
│   └── scene_validator.py           # Main implementation
└── appdaemon.yaml                   # AppDaemon configuration
```

### Configuration: apps.yaml

```yaml
# /homeassistant/appdaemon/apps/apps.yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  # Configuration
  brightness_tolerance: 5              # ±5% brightness tolerance
  transition_delay: 5                  # Seconds to wait for light transitions
  retry_delay: 5                       # Seconds between retry attempts
  individual_light_delay: 0.2          # Seconds between individual light calls

  # Inventory paths
  inventory_eg: /homeassistant/hue_inventories/Bridge_Downstairs-abc123def456.json
  inventory_og: /homeassistant/hue_inventories/Bridge_Upstairs-xyz789ghi012.json

  # Notification settings
  notify_on_retry: false               # Notify on Level 2 (re-trigger)
  notify_on_fallback: true             # Notify on Level 3 (individual lights)
  notify_on_failure: true              # Notify on critical failure
  notification_target: notify.mobile_app_iphone  # Or persistent_notification

  # Monitoring
  enable_stats: true                   # Track validation statistics
  stats_sensor: sensor.scene_validation_stats

  # Scene Filtering (Hybrid Approach)
  use_labels: true                     # Check HA entity labels for validation
  label_name: validate_scene           # Label to identify scenes for validation

  validated_patterns: []               # Regex patterns for scene names to validate
    # Examples:
    # - ".*Standard$"                  # All scenes ending with "Standard"
    # - ".*Nachtlicht$"                # All scenes ending with "Nachtlicht"
    # - "^Feuer.*"                     # All scenes starting with "Feuer"

  excluded_patterns: []                # Regex patterns for scenes to EXCLUDE
    # Examples:
    # - ".*Test.*"                     # Exclude any scene with "Test"
    # - ".*Temp.*"                     # Exclude temporary scenes
    # - ".*DEBUG.*"                    # Exclude debug scenes

  validate_all_by_default: false       # If no label/pattern matches, validate anyway?
```

---

## Scene Filtering Configuration

### Overview: Hybrid Approach (Labels + Patterns)

By default, validating all 214 scenes creates unnecessary overhead. The **Hybrid Filtering Approach** allows you to specify which scenes require strict validation using:

1. **HA Entity Labels** (explicit opt-in)
2. **Name Patterns** (systematic matching)
3. **Exclusion Patterns** (explicit opt-out)

### Filter Priority Order

When a scene is activated, the validator checks in this order:

```text
┌─────────────────────────────────────────────────────────────┐
│ Priority 1: HA Entity Label                                 │
│ If scene has label "validate_scene" → VALIDATE ✓           │
└─────────────────────────────────────────────────────────────┘
                           ↓ (no label)
┌─────────────────────────────────────────────────────────────┐
│ Priority 2: Exclusion Patterns                              │
│ If scene name matches excluded_patterns → SKIP ✗           │
└─────────────────────────────────────────────────────────────┘
                           ↓ (not excluded)
┌─────────────────────────────────────────────────────────────┐
│ Priority 3: Inclusion Patterns                              │
│ If validated_patterns defined:                              │
│   - Matches pattern → VALIDATE ✓                           │
│   - No match → SKIP ✗                                      │
└─────────────────────────────────────────────────────────────┘
                           ↓ (no patterns defined)
┌─────────────────────────────────────────────────────────────┐
│ Priority 4: Default Behavior                                │
│ Use validate_all_by_default setting                         │
└─────────────────────────────────────────────────────────────┘
```

### Configuration Options

#### 1. Label-Based Filtering (Recommended for Explicit Scenes)

**Best for**: Critical scenes that must always be validated (security, sleep, wake routines)

```yaml
scene_validator:
  use_labels: true
  label_name: validate_scene
```

**How to use**:
```bash
# In Home Assistant UI:
# Settings → Entities → scene.wohnzimmer_standard
# → Labels section → Click "+" → Select or create "validate_scene"

# Via service call:
service: label.add
data:
  label_id: validate_scene
  entity_id:
    - scene.wohnzimmer_standard
    - scene.schlafzimmer_nachtlicht
    - scene.security_lights_on
```

**Pros**:
- ✅ Visible in HA UI (badge shows label)
- ✅ Point-and-click management
- ✅ No config file edits needed
- ✅ Survives HA updates

#### 2. Pattern-Based Filtering (Recommended for Systematic Scenes)

**Best for**: Scene naming conventions (all "Standard", all "Nachtlicht", all room-specific)

```yaml
scene_validator:
  validated_patterns:
    - ".*Standard$"      # All scenes ending with "Standard"
    - ".*Nachtlicht$"    # All scenes ending with "Nachtlicht"
    - "^Wohnzimmer.*"    # All scenes starting with "Wohnzimmer"
    - "Schlafzimmer.*"   # All Schlafzimmer scenes
```

**Pattern Examples**:

| Pattern | Matches | Use Case |
|---------|---------|----------|
| `".*Standard$"` | Any scene ending with "Standard" | Validate all default scenes |
| `".*Nachtlicht$"` | Any scene ending with "Nachtlicht" | Validate all night scenes |
| `"^Feuer.*"` | Scenes starting with "Feuer" | Validate all fire-effect scenes |
| `"Wohnzimmer\|Schlafzimmer"` | Scenes containing either word | Validate specific rooms |
| `".*_(on\|off)$"` | Scenes ending with `_on` or `_off` | Validate binary scenes |

**Regex Reference**:
- `^` = Start of string
- `$` = End of string
- `.*` = Any characters (0 or more)
- `.+` = Any characters (1 or more)
- `\|` = OR operator
- `[abc]` = Any of a, b, or c
- `[^abc]` = Not a, b, or c

#### 3. Exclusion Patterns (Prevent False Validations)

**Best for**: Test scenes, temporary scenes, debug scenes

```yaml
scene_validator:
  excluded_patterns:
    - ".*Test.*"       # Exclude any scene with "Test"
    - ".*Temp.*"       # Exclude temporary scenes
    - ".*DEBUG.*"      # Exclude debug scenes
    - "^_.*"           # Exclude scenes starting with underscore
```

**Why use exclusions**:
- Prevent validation of experimental scenes
- Skip decorative/party scenes that change frequently
- Avoid false failures for scenes under development

#### 4. Default Behavior

```yaml
scene_validator:
  validate_all_by_default: false   # Recommended: opt-in only
  # OR
  validate_all_by_default: true    # Validate everything unless excluded
```

**Recommendation**: Set to `false` (opt-in only) to avoid unnecessary overhead.

### Configuration Examples

#### Example 1: Label-Only (Simple)

**Use case**: You want explicit control, manually label critical scenes

```yaml
scene_validator:
  use_labels: true
  label_name: validate_scene
  validate_all_by_default: false
```

**Result**: Only scenes with "validate_scene" label are validated

#### Example 2: Pattern-Only (Systematic)

**Use case**: You have consistent naming (all "Standard" and "Nachtlicht" scenes are critical)

```yaml
scene_validator:
  use_labels: false
  validated_patterns:
    - ".*Standard$"
    - ".*Nachtlicht$"
  validate_all_by_default: false
```

**Result**: Only scenes matching patterns are validated

#### Example 3: Hybrid (Recommended)

**Use case**: Most scenes follow patterns, but some exceptions need explicit labeling

```yaml
scene_validator:
  # Use labels for explicit opt-in
  use_labels: true
  label_name: validate_scene

  # Use patterns for systematic scenes
  validated_patterns:
    - ".*Standard$"
    - ".*Nachtlicht$"

  # Exclude test scenes
  excluded_patterns:
    - ".*Test.*"
    - ".*Temp.*"

  # Default: don't validate unless matched
  validate_all_by_default: false
```

**Result**:
- Scenes with "validate_scene" label → Always validated
- Scenes matching "Test" or "Temp" → Never validated
- Scenes matching "Standard" or "Nachtlicht" → Validated
- All other scenes → Not validated

#### Example 4: Room-Based (Area Filtering)

**Use case**: Only validate scenes in specific rooms

```yaml
scene_validator:
  validated_patterns:
    - "^wohnzimmer_.*"     # Match entity_id prefix
    - "^schlafzimmer_.*"
    - "^kuche_.*"
```

**Note**: This matches HA entity_id (e.g., `scene.wohnzimmer_standard`), not Hue scene name

### Usage Scenarios

#### Scenario 1: Label a Critical Custom Scene

```bash
# Scene: scene.wohnzimmer_goldener_stern
# This scene is critical for evening routine

# Add label via HA UI:
Settings → Entities → scene.wohnzimmer_goldener_stern
→ Labels → Add "validate_scene"

# Result: ✓ Scene will be validated
```

#### Scenario 2: Validate All "Standard" Scenes

```yaml
# All "Standard" scenes across all rooms are important defaults
validated_patterns:
  - ".*Standard$"

# Matches:
# - scene.wohnzimmer_standard
# - scene.kuche_standard
# - scene.schlafzimmer_standard
# Result: ✓ All validated automatically
```

#### Scenario 3: Exclude Test Scene

```yaml
# You're experimenting with "Wohnzimmer Test New Colors"
excluded_patterns:
  - ".*Test.*"

# Matches:
# - scene.wohnzimmer_test_new_colors
# Result: ✗ Not validated (even if matches other patterns)
```

#### Scenario 4: One-Off Decorative Scene

```yaml
# Scene: scene.party_lights
# No label, no pattern match, default=false

# Result: ✗ Not validated (party lights don't need strict validation)
```

### Labeling Helper: Bulk Operations

For initial setup, label multiple scenes at once:

```bash
# In HA Developer Tools → Services:
service: label.add
data:
  label_id: validate_scene
  entity_id:
    - scene.wohnzimmer_standard
    - scene.wohnzimmer_nachtlicht
    - scene.schlafzimmer_standard
    - scene.schlafzimmer_nachtlicht
    - scene.kuche_hell
    - scene.kuche_gedimmt
    # ... add all critical scenes
```

### Recommended Initial Configuration

**For first deployment**, start simple:

```yaml
scene_validator:
  # Start with patterns only (easier than labeling 50 scenes)
  use_labels: false
  validated_patterns:
    - ".*Standard$"
    - ".*Nachtlicht$"

  # Exclude test scenes
  excluded_patterns:
    - ".*Test.*"

  validate_all_by_default: false
```

**After 1-2 weeks of monitoring**:
- Review stats: Which scenes fail most often?
- Add labels to specific high-priority scenes
- Enable `use_labels: true`
- Fine-tune patterns based on actual usage

### Troubleshooting Filtering

#### Issue: Scene should validate but doesn't

**Debug steps**:
```python
# Check if scene has label:
# HA → Developer Tools → States → scene.xxx
# Look at "labels" attribute

# Check if scene name matches pattern:
# HA → Developer Tools → States → scene.xxx
# Compare "original_name" against validated_patterns
```

**Solution**:
1. Verify label is correct: `validate_scene` (exact match)
2. Test regex pattern: Use online regex tester with scene name
3. Check exclusion patterns (they override inclusion)
4. Enable debug logging (see Troubleshooting section)

#### Issue: Scene validates but shouldn't

**Debug steps**:
- Check if scene has unexpected label
- Check if scene name matches a pattern unintentionally

**Solution**:
1. Remove label or add to `excluded_patterns`
2. Make patterns more specific (use `^` and `$`)

---

### Implementation: scene_validator.py

```python
# /homeassistant/appdaemon/apps/scene_validator.py
"""
Hue Scene Validator - Enhanced Hybrid Approach
3-Level Escalation: Scene → Re-trigger → Individual Lights

Validates Hue scenes against inventory definitions and automatically corrects deviations.
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import re
from datetime import datetime


class SceneValidator(hass.Hass):
    """Validates and corrects Hue scene activations"""

    def initialize(self):
        """Initialize the scene validator"""
        # Load configuration
        self.brightness_tolerance = self.args.get('brightness_tolerance', 5)
        self.transition_delay = self.args.get('transition_delay', 5)
        self.retry_delay = self.args.get('retry_delay', 5)
        self.individual_light_delay = self.args.get('individual_light_delay', 0.2)

        self.notify_on_retry = self.args.get('notify_on_retry', False)
        self.notify_on_fallback = self.args.get('notify_on_fallback', True)
        self.notify_on_failure = self.args.get('notify_on_failure', True)
        self.notification_target = self.args.get('notification_target', 'persistent_notification')

        self.enable_stats = self.args.get('enable_stats', True)
        self.stats_sensor = self.args.get('stats_sensor', 'sensor.scene_validation_stats')

        # Scene filtering configuration
        self.use_labels = self.args.get('use_labels', True)
        self.label_name = self.args.get('label_name', 'validate_scene')
        self.validated_patterns = self.args.get('validated_patterns', [])
        self.excluded_patterns = self.args.get('excluded_patterns', [])
        self.validate_all_by_default = self.args.get('validate_all_by_default', False)

        # Load inventories
        self.inventories = []
        self.load_inventories()

        # Initialize statistics
        self.stats = {
            'total_validations': 0,
            'successful': 0,
            'failed_level_1': 0,
            'recovered_level_2': 0,
            'recovered_level_3': 0,
            'critical_failures': 0,
            'last_failure': None
        }

        # Listen for scene activations
        self.listen_event(self.on_scene_activated, "call_service",
                         domain="scene", service="turn_on")

        # Register reload service
        self.register_service("scene_validator/reload_inventories", self.reload_inventories)

        self.log("Scene Validator initialized")
        self.log(f"Loaded {len(self.inventories)} inventory file(s)")
        self.log(f"Brightness tolerance: ±{self.brightness_tolerance}%")

    def load_inventories(self):
        """Load Hue inventory JSON files"""
        inventory_paths = [
            self.args.get('inventory_eg'),
            self.args.get('inventory_og')
        ]

        self.inventories = []
        for path in inventory_paths:
            if not path:
                continue

            try:
                with open(path, 'r') as f:
                    inventory = json.load(f)
                    self.inventories.append(inventory)
                    bridge_name = inventory.get('bridge_info', {}).get('config', {}).get('name', 'Unknown')
                    self.log(f"Loaded inventory: {bridge_name}")
            except FileNotFoundError:
                self.error(f"Inventory file not found: {path}")
            except json.JSONDecodeError as e:
                self.error(f"Failed to parse inventory {path}: {e}")

        if not self.inventories:
            self.error("No inventories loaded! Scene validation will not work.")

    def reload_inventories(self, namespace, domain, service, kwargs):
        """Service call to reload inventories"""
        self.log("Reloading inventories...")
        self.load_inventories()
        return {"status": "ok", "inventories_loaded": len(self.inventories)}

    async def should_validate_scene(self, scene_entity, scene_uid):
        """
        Determine if scene should be validated based on filtering configuration.

        Priority order:
        1. Check HA entity label (explicit opt-in)
        2. Check exclusion patterns (explicit opt-out)
        3. Check inclusion patterns (systematic matching)
        4. Fall back to default behavior

        Args:
            scene_entity: HA entity_id (e.g., scene.wohnzimmer_standard)
            scene_uid: Hue scene unique_id

        Returns:
            bool: True if scene should be validated, False otherwise
        """

        # Priority 1: Check label (explicit opt-in)
        if self.use_labels:
            entity_labels = await self.get_state(scene_entity, attribute='labels')
            if entity_labels and self.label_name in entity_labels:
                self.log(f"Scene {scene_entity} has label '{self.label_name}' → VALIDATE", level="DEBUG")
                return True

        # Get scene from inventory for name-based pattern matching
        scene = self.find_scene(scene_uid)
        if not scene:
            self.log(f"Scene {scene_uid} not found in inventory → SKIP", level="DEBUG")
            return False

        scene_name = scene.get('metadata', {}).get('name', '')

        # Priority 2: Check exclusion patterns (explicit opt-out)
        if self.excluded_patterns:
            for pattern in self.excluded_patterns:
                if re.match(pattern, scene_name):
                    self.log(f"Scene '{scene_name}' matches exclusion pattern '{pattern}' → SKIP", level="DEBUG")
                    return False

        # Priority 3: Check inclusion patterns (systematic matching)
        if self.validated_patterns:
            for pattern in self.validated_patterns:
                if re.match(pattern, scene_name):
                    self.log(f"Scene '{scene_name}' matches pattern '{pattern}' → VALIDATE", level="DEBUG")
                    return True
            # Patterns defined but no match
            self.log(f"Scene '{scene_name}' doesn't match any validated_patterns → SKIP", level="DEBUG")
            return False

        # Priority 4: Default behavior
        if self.validate_all_by_default:
            self.log(f"Scene '{scene_name}' using default (validate all) → VALIDATE", level="DEBUG")
        else:
            self.log(f"Scene '{scene_name}' using default (opt-in only) → SKIP", level="DEBUG")

        return self.validate_all_by_default

    async def on_scene_activated(self, event, data, kwargs):
        """Handle scene activation event"""
        try:
            # Extract scene entity_id
            service_data = data.get('service_data', {})
            scene_entity = service_data.get('entity_id')

            if not scene_entity:
                return

            # Get scene unique_id
            scene_uid = await self.get_state(scene_entity, attribute='unique_id')
            if not scene_uid:
                self.log(f"Scene {scene_entity} has no unique_id, skipping validation")
                return

            # Check if scene should be validated (filtering)
            if not await self.should_validate_scene(scene_entity, scene_uid):
                self.log(f"Scene {scene_entity} filtered out, skipping validation")
                return

            self.log(f"Scene activated: {scene_entity} (uid: {scene_uid})")

            # Update status sensor
            self.set_state('sensor.scene_validation_status', state='validating',
                          attributes={'scene': scene_entity, 'level': 1})

            # Wait for lights to transition
            await self.sleep(self.transition_delay)

            # Create snapshot
            await self.create_snapshot(scene_entity, scene_uid)

            # Level 1: Validate initial activation
            self.log(f"Level 1: Validating initial activation")
            failures = await self.validate_scene(scene_uid)

            self.stats['total_validations'] += 1

            if not failures:
                self.log(f"✓ Scene {scene_entity} validated successfully")
                self.stats['successful'] += 1
                self.set_state('sensor.scene_validation_status', state='success',
                              attributes={'scene': scene_entity, 'level': 1})
                self.update_stats_sensor()
                return

            # Level 2: Re-trigger scene
            self.log(f"⚠ Level 1 validation failed ({len(failures)} issue(s)), re-triggering scene")
            self.log(f"Failures: {failures}")
            self.stats['failed_level_1'] += 1

            if self.notify_on_retry:
                await self.notify(f"Scene {scene_entity} validation failed, re-triggering", "warning")

            self.set_state('sensor.scene_validation_status', state='retrying',
                          attributes={'scene': scene_entity, 'level': 2, 'failures': failures})

            await self.call_service('scene/turn_on', entity_id=scene_entity)
            await self.sleep(self.retry_delay)

            # Validate again
            failures = await self.validate_scene(scene_uid)

            if not failures:
                self.log(f"✓ Scene {scene_entity} validated after re-trigger")
                self.stats['recovered_level_2'] += 1
                self.set_state('sensor.scene_validation_status', state='success',
                              attributes={'scene': scene_entity, 'level': 2})
                self.update_stats_sensor()
                return

            # Level 3: Set lights individually (fallback)
            self.log(f"❌ Level 2 validation failed, setting lights individually")
            self.log(f"Remaining failures: {failures}")

            if self.notify_on_fallback:
                await self.notify(f"Scene {scene_entity} re-trigger failed, using fallback", "warning")

            self.set_state('sensor.scene_validation_status', state='fallback',
                          attributes={'scene': scene_entity, 'level': 3, 'failures': failures})

            await self.apply_scene_via_individual_lights(scene_uid)
            await self.sleep(self.retry_delay)

            # Final validation
            failures = await self.validate_scene(scene_uid)

            if not failures:
                self.log(f"✓ Scene {scene_entity} applied via individual lights")
                self.stats['recovered_level_3'] += 1
                self.set_state('sensor.scene_validation_status', state='success',
                              attributes={'scene': scene_entity, 'level': 3})
                self.update_stats_sensor()
                return

            # Critical failure
            self.log(f"🚨 CRITICAL: Scene {scene_entity} validation failed after all attempts")
            self.log(f"Final failures: {failures}")

            self.stats['critical_failures'] += 1
            self.stats['last_failure'] = {
                'scene': scene_entity,
                'time': datetime.now().isoformat(),
                'failures': failures
            }

            self.set_state('sensor.scene_validation_status', state='failed',
                          attributes={'scene': scene_entity, 'level': 3, 'failures': failures})

            if self.notify_on_failure:
                await self.notify(
                    f"CRITICAL: Scene {scene_entity} failed validation after 3 attempts. Failures: {failures}",
                    "error"
                )

            self.update_stats_sensor()

        except Exception as e:
            self.error(f"Error in scene validation: {e}", level="ERROR")
            import traceback
            self.error(traceback.format_exc())

    async def create_snapshot(self, scene_entity, scene_uid):
        """Create snapshot of scene for complex attributes (color, effects)"""
        try:
            # Find scene definition to get light list
            scene = self.find_scene(scene_uid)
            if not scene:
                return

            # Extract light entity_ids from scene actions
            light_entities = []
            for action_str in scene['actions']:
                action = self.parse_action(action_str)
                light_entity = await self.get_entity_id_from_hue_id(action['target_id'])
                if light_entity:
                    light_entities.append(light_entity)

            if not light_entities:
                return

            # Create snapshot
            snapshot_id = f"snapshot_{scene_entity.replace('scene.', '')}"
            await self.call_service('scene/create',
                                   scene_id=snapshot_id,
                                   snapshot_entities=light_entities)

            self.log(f"Created snapshot: {snapshot_id} ({len(light_entities)} lights)")

        except Exception as e:
            self.error(f"Failed to create snapshot: {e}")

    async def validate_scene(self, scene_uid):
        """Validate scene against inventory, return list of failures"""
        scene = self.find_scene(scene_uid)
        if not scene:
            return [f"Scene {scene_uid} not found in inventory"]

        failures = []

        for action_str in scene['actions']:
            action = self.parse_action(action_str)

            # Get HA entity_id from Hue resource ID
            light_entity = await self.get_entity_id_from_hue_id(action['target_id'])
            if not light_entity:
                # Light not found in HA (might be disabled or removed)
                continue

            # Get current state
            current_state = await self.get_state(light_entity)
            if current_state == 'unavailable':
                failures.append(f"{light_entity}: unavailable")
                continue

            # Validate on/off
            target_on = action.get('on', True)
            current_on = (current_state == 'on')

            if target_on != current_on:
                failures.append(f"{light_entity}: state {current_state} != {'on' if target_on else 'off'}")
                continue  # Skip brightness check if light is off

            # Validate brightness (only if light is on and brightness specified)
            if current_on and 'brightness' in action:
                target_brightness_pct = action['brightness']
                current_brightness = await self.get_state(light_entity, attribute='brightness')

                if current_brightness is None:
                    continue  # Light doesn't support brightness

                current_brightness_pct = (current_brightness / 255 * 100)
                deviation = abs(target_brightness_pct - current_brightness_pct)

                if deviation > self.brightness_tolerance:
                    failures.append(
                        f"{light_entity}: brightness {current_brightness_pct:.1f}% "
                        f"!= {target_brightness_pct:.1f}% (Δ{deviation:.1f}%)"
                    )

        return failures

    async def apply_scene_via_individual_lights(self, scene_uid):
        """Apply scene by setting each light individually (fallback)"""
        scene = self.find_scene(scene_uid)
        if not scene:
            self.log(f"Cannot apply scene {scene_uid}: not found in inventory")
            return

        scene_name = scene.get('metadata', {}).get('name', 'Unknown')
        self.log(f"Applying scene '{scene_name}' via individual lights ({len(scene['actions'])} lights)")

        for action_str in scene['actions']:
            action = self.parse_action(action_str)

            # Get HA entity_id
            light_entity = await self.get_entity_id_from_hue_id(action['target_id'])
            if not light_entity:
                continue

            # Build service data
            service_data = {'entity_id': light_entity}

            # On/off
            if not action.get('on', True):
                await self.call_service('light/turn_off', **service_data)
                await self.sleep(self.individual_light_delay)
                continue

            # Brightness (convert 0-100 to brightness_pct)
            if 'brightness' in action:
                service_data['brightness_pct'] = action['brightness']

            # Color (xy coordinates)
            if 'color_xy' in action:
                service_data['xy_color'] = action['color_xy']

            # Color temperature (mirek to kelvin)
            if 'color_temperature' in action:
                kelvin = 1000000 / action['color_temperature']
                service_data['color_temp_kelvin'] = kelvin

            # Effect
            if 'effect' in action:
                service_data['effect'] = action['effect']

            # Call light.turn_on
            self.log(f"  Setting {light_entity}: {service_data}", level="DEBUG")
            await self.call_service('light/turn_on', **service_data)

            # Small delay between lights to avoid overwhelming bridge
            await self.sleep(self.individual_light_delay)

    def find_scene(self, scene_uid):
        """Find scene by unique_id in inventories"""
        for inv in self.inventories:
            for scene in inv['resources']['scenes']['items']:
                if scene['id'] == scene_uid:
                    return scene
        return None

    def parse_action(self, action_str):
        """Parse action from inventory string representation"""
        # Example: "Action(target=ResourceIdentifier(rid='ebb31eab...', rtype='light'),
        #           action=ActionAction(on=OnFeature(on=True), dimming=DimmingFeatureBase(brightness=12.25)))"

        action = {}

        # Extract target rid
        target_match = re.search(r"target=ResourceIdentifier\(rid='([^']+)'", action_str)
        if target_match:
            action['target_id'] = target_match.group(1)

        # Extract on state
        on_match = re.search(r"on=OnFeature\(on=(True|False)\)", action_str)
        if on_match:
            action['on'] = (on_match.group(1) == 'True')

        # Extract brightness
        brightness_match = re.search(r"brightness=([\d.]+)", action_str)
        if brightness_match:
            action['brightness'] = float(brightness_match.group(1))

        # Extract color xy
        xy_match = re.search(r"xy=ColorPoint\(x=([\d.]+), y=([\d.]+)\)", action_str)
        if xy_match:
            action['color_xy'] = [float(xy_match.group(1)), float(xy_match.group(2))]

        # Extract color temperature (mirek)
        mirek_match = re.search(r"mirek=([\d.]+)", action_str)
        if mirek_match:
            action['color_temperature'] = float(mirek_match.group(1))

        # Extract effect
        effect_match = re.search(r"effect=<EffectStatus\.(\w+)", action_str)
        if effect_match:
            action['effect'] = effect_match.group(1).lower()

        return action

    async def get_entity_id_from_hue_id(self, hue_resource_id):
        """Map Hue resource ID to HA entity_id via unique_id"""
        # Get all light entities
        entities = await self.get_state('light', attribute='all')

        for entity_id in entities.keys():
            if not entity_id.startswith('light.'):
                continue

            # Query unique_id directly from entity registry via get_state
            # unique_id is not in state attributes, must query separately
            unique_id = await self.get_state(entity_id, attribute='unique_id')

            # Check if this entity matches the Hue resource ID
            if unique_id == hue_resource_id:
                return entity_id

        return None

    async def notify(self, message, level="info"):
        """Send notification"""
        if self.notification_target == 'persistent_notification':
            await self.call_service('persistent_notification/create',
                                   title="Scene Validation",
                                   message=message,
                                   notification_id=f"scene_validation_{level}")
        else:
            await self.call_service(self.notification_target,
                                   title="Scene Validation",
                                   message=message)

    def update_stats_sensor(self):
        """Update statistics sensor"""
        if not self.enable_stats:
            return

        success_rate = 0
        if self.stats['total_validations'] > 0:
            success_rate = ((self.stats['successful'] +
                           self.stats['recovered_level_2'] +
                           self.stats['recovered_level_3']) /
                          self.stats['total_validations'] * 100)

        self.set_state(self.stats_sensor,
                      state=round(success_rate, 1),
                      attributes={
                          'unit_of_measurement': '%',
                          'friendly_name': 'Scene Validation Success Rate',
                          'total_validations': self.stats['total_validations'],
                          'successful': self.stats['successful'],
                          'failed_level_1': self.stats['failed_level_1'],
                          'recovered_level_2': self.stats['recovered_level_2'],
                          'recovered_level_3': self.stats['recovered_level_3'],
                          'critical_failures': self.stats['critical_failures'],
                          'last_failure': self.stats['last_failure']
                      })
```

---

## Deployment Steps

### Phase 1: Preparation (Day 1)

```bash
# 1. Sync inventories to HA
cd /path/to/workspace/aiohue/scripts
./sync-inventory-to-ha.sh

# 2. Verify inventories on HA
ssh -i /path/to/workspace/homeassistant_ssh_key hassio@<HA_IP> \
  "ls -lh /homeassistant/hue_inventories/"

# Expected output:
# -rw-r--r-- 1 root root 1.2M Nov 13 10:00 Bridge_Downstairs-abc123def456.json
# -rw-r--r-- 1 root root 856K Nov 13 10:00 Bridge_Upstairs-xyz789ghi012.json

# 3. Install AppDaemon add-on (if not already installed)
# Home Assistant → Settings → Add-ons → Add-on Store → AppDaemon 4
```

### Phase 2: AppDaemon Configuration (Day 1)

```bash
# 1. Create AppDaemon app directory
ssh -i /path/to/workspace/homeassistant_ssh_key hassio@<HA_IP>
mkdir -p /homeassistant/appdaemon/apps

# 2. Copy scene_validator.py
# (Use SCP or edit directly via SSH)
```

Create `/homeassistant/appdaemon/apps/apps.yaml`:
```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator
  brightness_tolerance: 5
  transition_delay: 5
  retry_delay: 5
  inventory_eg: /homeassistant/hue_inventories/Bridge_Downstairs-abc123def456.json
  inventory_og: /homeassistant/hue_inventories/Bridge_Upstairs-xyz789ghi012.json
  notify_on_fallback: true
  notify_on_failure: true

  # Scene Filtering (Recommended: Start with patterns)
  use_labels: false                # Enable later after testing
  validated_patterns:
    - ".*Standard$"                # All "Standard" scenes
    - ".*Nachtlicht$"              # All "Nachtlicht" scenes
  excluded_patterns:
    - ".*Test.*"                   # Exclude test scenes
  validate_all_by_default: false   # Only validate matched scenes
```

```bash
# 3. Restart AppDaemon add-on
# Home Assistant → Settings → Add-ons → AppDaemon 4 → Restart

# 4. Check AppDaemon logs
# Home Assistant → Settings → Add-ons → AppDaemon 4 → Log

# Expected:
# INFO scene_validator: Scene Validator initialized
# INFO scene_validator: Loaded 2 inventory file(s)
# INFO scene_validator: Loaded inventory: Bridge_Downstairs
# INFO scene_validator: Loaded inventory: Bridge_Upstairs
```

### Phase 3: Testing (Day 2-3)

```bash
# Test with a single scene first

# 1. Identify test scene
# Use a room with 2-3 lights, simple scene (no effects)
# Example: scene.wohnzimmer_standard

# 2. Test Level 1 (should pass normally)
# Activate scene via HA UI
# Check AppDaemon logs:
# - "Scene activated: scene.wohnzimmer_standard"
# - "Level 1: Validating initial activation"
# - "✓ Scene scene.wohnzimmer_standard validated successfully"

# 3. Test Level 2 (simulate failure)
# Manually change one light after scene activation
# (Turn off or change brightness)
# Wait >5 seconds
# Check logs:
# - "⚠ Level 1 validation failed"
# - "Re-triggering scene"
# - "✓ Scene validated after re-trigger"

# 4. Test Level 3 (simulate bridge issue)
# This is harder to test without actually breaking something
# Could temporarily remove bridge from network
```

### Phase 4: Monitoring Setup (Day 3)

Create monitoring dashboard in Home Assistant:

```yaml
# configuration.yaml or dashboard
type: entities
title: Scene Validation Monitor
entities:
  - entity: sensor.scene_validation_status
    name: Current Status
  - entity: sensor.scene_validation_stats
    name: Success Rate
  - entity: sensor.scene_validation_stats
    type: attribute
    attribute: total_validations
    name: Total Validations
  - entity: sensor.scene_validation_stats
    type: attribute
    attribute: failed_level_1
    name: Initial Failures
  - entity: sensor.scene_validation_stats
    type: attribute
    attribute: recovered_level_2
    name: Recovered (Re-trigger)
  - entity: sensor.scene_validation_stats
    type: attribute
    attribute: recovered_level_3
    name: Recovered (Fallback)
  - entity: sensor.scene_validation_stats
    type: attribute
    attribute: critical_failures
    name: Critical Failures
```

### Phase 5: Production Rollout (Day 4+)

```bash
# 1. Monitor for 2-3 days
# - Check logs daily
# - Review statistics
# - Look for false positives

# 2. Tune parameters if needed
# Edit apps.yaml:
# - brightness_tolerance (if too many false positives, increase)
# - transition_delay (if slow lights, increase)

# 3. (Optional) Enable label-based filtering
# After confirming pattern-based filtering works:
# - Edit apps.yaml: use_labels: true
# - Add labels to specific high-priority scenes
# - Patterns + labels work together (hybrid approach)

# 4. Label critical scenes (if using labels)
# HA → Developer Tools → Services:
```

```yaml
service: label.add
data:
  label_id: validate_scene
  entity_id:
    - scene.wohnzimmer_goldener_stern
    - scene.security_lights_on
    - scene.bedtime_routine
    # Add other critical scenes
```

```bash
# 5. Set up alerting (optional)
# Create automation to notify on critical failures:
```

```yaml
# automations.yaml
- alias: "Alert on Scene Validation Critical Failure"
  trigger:
    - platform: state
      entity_id: sensor.scene_validation_stats
      attribute: critical_failures
  condition:
    - condition: template
      value_template: >
        {{ trigger.to_state.attributes.critical_failures >
           trigger.from_state.attributes.critical_failures }}
  action:
    - service: notify.mobile_app_iphone
      data:
        title: "Scene Validation Failed"
        message: >
          Scene {{ state_attr('sensor.scene_validation_stats', 'last_failure').scene }}
          failed validation after all attempts.
```

---

## Testing Strategy

### Test Scenarios

#### Test 1: Normal Operation (Level 1 Success)
```text
1. Activate scene.wohnzimmer_standard
2. Expected: Validation passes, no retry needed
3. Verify: Check logs show "✓ Scene validated successfully"
```

#### Test 2: Single Light Deviation (Level 2 Recovery)
```text
1. Activate scene.wohnzimmer_standard
2. Immediately after activation (within 5s):
   - Manually turn off one light via HA
3. Expected:
   - Level 1 fails (light is off but should be on)
   - Level 2 re-triggers scene
   - Light turns back on
   - Validation passes
4. Verify: Check logs show "✓ Scene validated after re-trigger"
```

#### Test 3: Multiple Light Deviation (Level 2 Recovery)
```
1. Activate scene.wohnzimmer_standard
2. Immediately change 2-3 lights (brightness or on/off)
3. Expected: Level 2 recovers
4. Verify: All lights return to scene targets
```

#### Test 4: Scene Re-trigger Failure (Level 3 Fallback)
```
This is difficult to test without breaking something.
Options:
A. Disconnect Hue bridge from network briefly
B. Modify inventory to have wrong scene ID (forces failure)
C. Temporarily disable a light in HA
```

#### Test 5: Color Scene Validation
```
1. Activate scene with color (e.g., "Ruhephase" with xy colors)
2. Verify: Validation passes even with color attributes
3. Check: Snapshot captured colors correctly
```

#### Test 6: Effect Scene Validation
```
1. Activate scene with effects (e.g., "Glowing grins" with fire effect)
2. Verify: Validation passes (skips effect validation)
3. Check: Snapshot captured effect state
```

#### Test 7: Scene Filtering - Labeled Scene
```
1. Add label "validate_scene" to scene.wohnzimmer_standard via HA UI
2. Activate scene.wohnzimmer_standard
3. Expected: Scene is validated
4. Verify: Check logs show "Scene ... has label 'validate_scene' → VALIDATE"
5. Verify: Validation proceeds normally
```

#### Test 8: Scene Filtering - Pattern Match
```
1. Configure validated_patterns: [".*Standard$"]
2. Activate scene.kuche_standard
3. Expected: Scene is validated (matches pattern)
4. Verify: Check logs show "Scene 'Standard' matches pattern '.*Standard$' → VALIDATE"
5. Verify: Validation proceeds normally
```

#### Test 9: Scene Filtering - Excluded Scene
```
1. Configure excluded_patterns: [".*Test.*"]
2. Activate scene.wohnzimmer_test_new_colors
3. Expected: Scene is NOT validated
4. Verify: Check logs show "Scene 'Test New Colors' matches exclusion pattern '.*Test.*' → SKIP"
5. Verify: Log shows "Scene ... filtered out, skipping validation"
```

#### Test 10: Scene Filtering - Unmatched Scene
```
1. Configure validated_patterns: [".*Standard$"]
2. Configure validate_all_by_default: false
3. Activate scene.party_lights (not matching pattern, no label)
4. Expected: Scene is NOT validated
5. Verify: Check logs show "Scene ... doesn't match any validated_patterns → SKIP"
6. Verify: Log shows "Scene ... filtered out, skipping validation"
```

#### Test 11: Scene Filtering - Priority Order
```
1. Configure:
   - use_labels: true
   - validated_patterns: [".*Standard$"]
   - excluded_patterns: [".*Test.*"]
2. Add label "validate_scene" to scene.wohnzimmer_test_standard
3. Activate scene.wohnzimmer_test_standard
4. Expected: Scene is validated (label has priority over exclusion)
5. Verify: Check logs show "Scene ... has label 'validate_scene' → VALIDATE"
```

### Success Criteria

- ✅ 95%+ scenes validate successfully on Level 1
- ✅ 100% of Level 2 failures recover (re-trigger works)
- ✅ No false positives (valid scenes marked as failed)
- ✅ Fallback works when scene mechanism fails
- ✅ Performance acceptable (<10s total validation time)
- ✅ Filtering works correctly (labeled scenes validated, excluded scenes skipped)
- ✅ Pattern matching works as expected
- ✅ Priority order respected (labels > exclusions > patterns > default)

---

## Monitoring & Maintenance

### Key Metrics

Monitor these sensors:

1. **sensor.scene_validation_status**
   - Current validation state
   - Last validated scene
   - Failure details if applicable

2. **sensor.scene_validation_stats**
   - Success rate percentage
   - Total validations count
   - Breakdown by level (1/2/3)
   - Critical failure count
   - Last failure details

### Log Analysis

```bash
# View AppDaemon logs
ssh -i /path/to/workspace/homeassistant_ssh_key hassio@<HA_IP>

# Real-time logs
docker logs -f addon_xxxxx_appdaemon

# Search for failures
docker logs addon_xxxxx_appdaemon | grep "validation failed"

# Search for fallbacks
docker logs addon_xxxxx_appdaemon | grep "Level 3"

# Count validations
docker logs addon_xxxxx_appdaemon | grep "Scene activated" | wc -l
```

### Maintenance Tasks

#### Monthly: Update Inventories (When Scenes Modified)

```bash
# On LocalMachine
cd /path/to/workspace/aiohue/scripts
./sync-inventory-to-ha.sh

# On HA (reload inventories in AppDaemon)
# Developer Tools → Services
# Service: scene_validator.reload_inventories
# Call Service
```

#### Quarterly: Review Statistics

```bash
# Check stats sensor
# Home Assistant → Developer Tools → States
# Find: sensor.scene_validation_stats
# Review attributes:
# - success_rate (should be >95%)
# - critical_failures (should be 0 or very low)
# - last_failure (investigate if recent)
```

#### As Needed: Tune Parameters

Edit `/homeassistant/appdaemon/apps/apps.yaml`:

```yaml
# If too many false positives (brightness mismatches):
brightness_tolerance: 10  # Increase from 5 to 10

# If lights are slow to transition:
transition_delay: 8  # Increase from 5 to 8

# If individual light control is too fast for bridge:
individual_light_delay: 0.5  # Increase from 0.2 to 0.5
```

Then restart AppDaemon add-on.

---

## Troubleshooting

### Issue: Validation Always Fails for Specific Scene

**Symptoms**: Scene X always shows Level 1 failures, even though lights look correct

**Possible Causes**:
1. Brightness tolerance too strict
2. Light doesn't support brightness (on/off only)
3. Scene inventory data is outdated
4. Light unique_id changed (re-paired in HA)

**Solutions**:
```bash
# 1. Check actual vs target values in logs
docker logs addon_xxxxx_appdaemon | grep "scene_name"

# 2. Update inventory
cd /path/to/workspace/aiohue/scripts
./sync-inventory-to-ha.sh

# 3. Check entity unique_id matches Hue resource ID
# HA → Developer Tools → States → light.xxx → attributes → unique_id
```

### Issue: AppDaemon Not Intercepting Scene Activations

**Symptoms**: Scenes activate but no validation logs appear

**Possible Causes**:
1. AppDaemon not running
2. App not loaded (error in code)
3. Event listener not registered

**Solutions**:
```bash
# 1. Check AppDaemon is running
# HA → Settings → Add-ons → AppDaemon 4 → Should show "Running"

# 2. Check AppDaemon logs for errors
docker logs addon_xxxxx_appdaemon | grep -i error

# 3. Verify app loaded
docker logs addon_xxxxx_appdaemon | grep "Scene Validator initialized"

# 4. Check event is firing
# HA → Developer Tools → Events
# Listen to: call_service
# Activate a scene
# Verify event appears with domain: scene, service: turn_on
```

### Issue: Scene Not Being Validated (Filtered Out)

**Symptoms**: Scene activates but no validation occurs, log shows "filtered out, skipping validation"

**Possible Causes**:
1. Scene doesn't have required label
2. Scene name doesn't match validated_patterns
3. Scene matches excluded_patterns
4. validate_all_by_default is false and no patterns configured

**Solutions**:
```bash
# 1. Check if scene has label
# HA → Developer Tools → States → scene.xxx
# Look at "labels" attribute → Should contain "validate_scene"

# 2. Check scene name in inventory
cd /path/to/workspace/aiohue/bridges/inventory
cat Bridge_Downstairs-*.json | jq '.resources.scenes.items[] | select(.id == "YOUR_SCENE_UID") | .metadata.name'

# 3. Test pattern matching (use online regex tester)
# Scene name: "Standard"
# Pattern: ".*Standard$" → Should match

# 4. Check AppDaemon configuration
cat /homeassistant/appdaemon/apps/apps.yaml | grep -A5 "validated_patterns"

# 5. Enable debug logging
# Look for "→ SKIP" or "→ VALIDATE" messages in logs
docker logs addon_xxxxx_appdaemon | grep "SKIP\|VALIDATE"
```

**Solutions**:
- **Add label**: HA → Settings → Entities → scene.xxx → Labels → Add "validate_scene"
- **Update patterns**: Edit apps.yaml, add pattern that matches scene name
- **Remove from exclusions**: Check excluded_patterns, remove scene if listed
- **Change default**: Set validate_all_by_default: true (not recommended)

### Issue: Wrong Scenes Being Validated

**Symptoms**: Scene is being validated but shouldn't be (e.g., party lights, test scenes)

**Possible Causes**:
1. Scene has label by mistake
2. Scene name matches pattern unintentionally
3. validate_all_by_default is true

**Solutions**:
```bash
# 1. Check scene label
# HA → Settings → Entities → scene.xxx → Labels
# Remove "validate_scene" label if present

# 2. Add to exclusions
# Edit apps.yaml:
excluded_patterns:
  - ".*Party.*"
  - ".*Test.*"

# 3. Make patterns more specific
# Change: ".*Standard.*" (matches "Standard Test")
# To: ".*Standard$" (only matches names ending with "Standard")
```

### Issue: Level 3 Fallback Not Working

**Symptoms**: Validation reaches Level 3 but lights still wrong

**Possible Causes**:
1. Light entity_ids not found (mapping failed)
2. Lights are unavailable
3. Color/effect attributes not supported by light

**Solutions**:
```bash
# 1. Check light mapping in logs
docker logs addon_xxxxx_appdaemon | grep "Setting light"

# 2. Verify lights are available
# HA → Developer Tools → States → light.xxx → Should not be "unavailable"

# 3. Test manual light control
# Developer Tools → Services
# Service: light.turn_on
# Target: light.xxx
# Data: {brightness_pct: 50, xy_color: [0.5, 0.4]}
# Call Service → Verify light responds
```

### Issue: Inventories Not Found

**Symptoms**: AppDaemon logs show "Inventory file not found"

**Solutions**:
```bash
# 1. Verify files exist on HA
ssh -i /path/to/workspace/homeassistant_ssh_key hassio@<HA_IP> \
  "ls -lh /homeassistant/hue_inventories/"

# 2. Check file paths in apps.yaml
cat /homeassistant/appdaemon/apps/apps.yaml

# 3. Re-sync inventories
cd /path/to/workspace/aiohue/scripts
./sync-inventory-to-ha.sh

# 4. Reload AppDaemon app
# Service: scene_validator.reload_inventories
```

### Issue: Performance Problems (Slow Validation)

**Symptoms**: Validation takes >10 seconds

**Possible Causes**:
1. Too many lights in scene
2. Network latency to Hue bridge
3. HA system overloaded

**Solutions**:
```yaml
# Reduce delays in apps.yaml:
transition_delay: 3  # Reduce from 5
individual_light_delay: 0.1  # Reduce from 0.2

# Or increase for reliability:
transition_delay: 8  # Increase from 5 (for slow lights)
```

---

## Future Enhancements

### Possible Improvements

1. **Color Validation**
   - Implement xy to hs_color conversion
   - Validate color attributes (currently skipped)
   - Tolerance for color deviation

2. **Effect Validation**
   - Map Hue effects to HA effects
   - Validate effect is active (currently skipped)

3. **Smart Timing**
   - Dynamic transition delays based on scene complexity
   - Learn optimal delays per scene

4. **Predictive Failure Detection**
   - Track which lights frequently fail
   - Pre-emptively use Level 3 for known-bad lights

5. **Dashboard Integration**
   - Custom Lovelace card showing validation history
   - Chart of success rate over time

6. **Scene Health Monitoring**
   - Daily automated validation of critical scenes
   - Alert if scene definition changes unexpectedly

7. **Inventory Auto-Update**
   - Webhook from Hue bridge on scene changes
   - Automatic inventory re-sync trigger

---

## Summary

**Implementation Ready**: This guide provides complete code and deployment steps for the Enhanced Hybrid Approach.

**Key Benefits**:
- ✅ 3-level escalation ensures scene reliability
- ✅ Inventory-based validation provides ground truth
- ✅ Fallback mechanism bypasses Hue bridge issues
- ✅ Selective validation via labels and patterns (filter 214 scenes to critical ones)
- ✅ Minimal maintenance (monthly inventory updates)
- ✅ Comprehensive monitoring and statistics

**Deployment Timeline**: 4 days (preparation → configuration → testing → rollout)

**Next Step**: Begin Phase 1 (Preparation) when ready to implement.

---

*Implementation Guide v1.0 - 2025-11-13*
