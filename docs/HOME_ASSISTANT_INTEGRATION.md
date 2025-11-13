# Home Assistant Integration

Complete guide for integrating Philips Hue bridges with Home Assistant, including scene validation, inventory export, and automation monitoring.

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Components](#components)
- [Scene Validation System](#scene-validation-system)
- [Configuration](#configuration)
- [Use Cases](#use-cases)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Home Assistant integration provides advanced features for managing Hue bridges within your HA ecosystem. This goes beyond the native Hue integration to provide:

### What This Integration Adds

- **Scene Validation** - Verify scenes activate correctly with 3-level escalation
- **HA Inventory Export** - Export HA's perspective of Hue entities
- **Inventory Sync** - Keep Hue bridge inventories available on HA server
- **Entity Mapping** - Map between Hue resource IDs and HA entity_ids
- **Automation Monitoring** - Track scene activations and failures
- **Kill Switch** - Circuit breaker for runaway automations

### Architecture

```text
Local Machine                    Home Assistant Server
─────────────────                ─────────────────────

Hue Bridge                       Entity Registry
Inventory ───────SSH/SCP────────> /homeassistant/
                                   hue_inventories/

HA Entity
Export ──────SSH/API────────────> Scene Validator
                                   (AppDaemon)
                                      ↓
                                   Validates
                                   Scenes
```

---

## Requirements

### Home Assistant

- Home Assistant 2024.1 or higher
- Native Hue integration configured
- AppDaemon add-on installed
- SSH access enabled (Advanced SSH & Web Terminal add-on)

### Local Machine

- Python 3.8 or higher
- SSH key for HA access
- Network access to HA server
- Bash shell (for sync script)

### SSH Configuration

**Required Files:**
- SSH private key (e.g., `homeassistant_ssh_key`)
- Configuration file: `ha_config.json`

**SSH Key Setup:**
```bash
# Generate SSH key (if needed)
ssh-keygen -t ed25519 -f homeassistant_ssh_key -C "ha-integration"

# Set proper permissions
chmod 600 homeassistant_ssh_key
chmod 644 homeassistant_ssh_key.pub

# Copy public key to HA server
# (Use HA SSH add-on web interface or CLI)
```

---

## Quick Start

### 1. Create Configuration File

Create `ha_config.json` in project root:

```json
{
  "ha_host": "192.168.1.100",
  "ha_user": "hassio",
  "ha_ssh_key": "../homeassistant_ssh_key",
  "ha_inventory_dir": "/homeassistant/hue_inventories"
}
```

**Security:** This file is excluded from git. Use `ha_config.example` as template.

### 2. Export HA Inventory

Export Home Assistant's view of Hue entities:

```bash
cd scripts

# Set SSH host (if not in ha_config.json)
export HA_SSH_HOST=192.168.1.100

# Export all bridges
python3 export-ha-hue-inventory.py

# Export specific bridge
python3 export-ha-hue-inventory.py --bridge "Bridge Office"

# Include current entity states
python3 export-ha-hue-inventory.py --include-states
```

**Output:**
```text
Home Assistant Hue Integration Inventory Export
======================================================================

Connecting to 192.168.1.100...
Home Assistant Version: 2024.11.1

Loading HA storage files...

Found 2 Hue bridge(s)

Processing: Bridge Office (abc123def456)...
  Found 52 entities
  Exported to: bridges/ha_inventory/ha_Bridge_Office-abc123def456.json

Processing: Bridge Living (xyz789ghi012)...
  Found 68 entities
  Exported to: bridges/ha_inventory/ha_Bridge_Living-xyz789ghi012.json

======================================================================
Successfully exported 2 bridge(s)

Output directory: bridges/ha_inventory/
```

### 3. Sync Inventories to HA

Sync Hue bridge inventories to Home Assistant server:

```bash
cd scripts
./sync-inventory-to-ha.sh
```

**Process:**
```text
===================================================================
Hue Inventory Sync to Home Assistant
===================================================================

Step 1: Capturing fresh Hue bridge inventories...
✓ Inventories captured

Step 2: Ensuring HA inventory directory exists...
✓ Directory ready

Step 3: Copying inventories to Home Assistant...
✓ Inventories copied

Step 4: Verifying files on Home Assistant...
Found 2 inventory file(s) on HA
-rw-r--r--  1 hassio hassio 52K Nov 13 10:00 Bridge_Office-abc123.json
-rw-r--r--  1 hassio hassio 68K Nov 13 10:00 Bridge_Living-xyz789.json

===================================================================
✓ Sync complete!
===================================================================

Inventory files are now available at:
  /homeassistant/hue_inventories/
```

### 4. Deploy Scene Validator

Copy scene validator to AppDaemon:

```bash
# Via SSH (example)
scp -i homeassistant_ssh_key \
    scene_validator.py \
    hassio@192.168.1.100:/addon_configs/a0d7b954_appdaemon/apps/

# Configure in apps.yaml
ssh -i homeassistant_ssh_key hassio@192.168.1.100
cd /addon_configs/a0d7b954_appdaemon/apps/
nano apps.yaml
```

**apps.yaml Configuration:**
```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  # Inventory paths
  inventory_dir: /homeassistant/hue_inventories

  # Timing
  transition_delay: 5
  validation_delay: 2

  # Rate limiting
  max_validations_per_minute: 20
  max_validations_per_scene_per_minute: 5

  # Circuit breaker
  circuit_breaker:
    failure_threshold: 5
    success_threshold: 2
    timeout: 300

  # Scene filtering
  scene_filter:
    include_labels: ["validate_scenes"]
    exclude_labels: ["no_validation"]
    exclude_uids: []
    name_patterns: []
```

**Restart AppDaemon:**
```bash
# Via HA UI: Settings > Add-ons > AppDaemon > Restart
# Or via CLI:
ha addons restart a0d7b954_appdaemon
```

### 5. Add Label to Scenes

In Home Assistant UI:

1. Go to **Settings** > **Automations & Scenes** > **Scenes**
2. Click on a scene you want to validate
3. Click **⋮** (three dots) > **Settings**
4. Add label: `validate_scenes`
5. Save

**Alternative - YAML:**
```yaml
# In scenes.yaml
- id: kitchen_bright
  name: Kitchen Bright
  labels:
    - validate_scenes
  entities:
    light.kitchen_ceiling:
      state: on
      brightness: 255
```

### 6. Test Scene Validation

Activate a labeled scene and monitor AppDaemon logs:

```bash
# Watch AppDaemon logs
ssh -i homeassistant_ssh_key hassio@192.168.1.100
docker logs -f addon_a0d7b954_appdaemon

# Look for validation messages
# INFO: Scene activated: scene.kitchen_bright
# INFO: Validation started for scene: scene.kitchen_bright
# INFO: All lights match expected state - validation successful
```

---

## Components

### 1. HA Inventory Export

**Script:** `export-ha-hue-inventory.py`

Exports Home Assistant's perspective of Hue entities, including:
- Entity IDs and friendly names
- Area assignments
- User customizations
- Device information
- Current states (optional)

**What It Captures:**

| Data | Description |
|------|-------------|
| Entity ID | HA-assigned entity identifier |
| Unique ID | Stable Hue resource ID (for mapping) |
| Friendly Name | User-customized entity name |
| Area | Room/area assignment in HA |
| Device Info | Manufacturer, model, MAC address |
| States | Current on/off, brightness, color (optional) |

**Usage:**
```bash
# All bridges
python3 export-ha-hue-inventory.py

# Specific bridge
python3 export-ha-hue-inventory.py --bridge "Bridge Office"

# Include states
python3 export-ha-hue-inventory.py --include-states

# JSON output
python3 export-ha-hue-inventory.py --json

# Custom output directory
python3 export-ha-hue-inventory.py --output-dir /path/to/output
```

**Output Structure:**
```json
{
  "metadata": {
    "source": "home_assistant",
    "ha_version": "2024.11.1",
    "exported_at": "2025-11-13T10:00:00",
    "includes_states": false
  },
  "bridge_info": {
    "config_entry_id": "config-entry-id",
    "unique_id": "abc123def456",
    "title": "Bridge Office",
    "host": "192.168.1.100",
    "api_version": 2
  },
  "resources": {
    "light": {
      "count": 52,
      "items": [
        {
          "entity_id": "light.kitchen_ceiling",
          "unique_id": "abc123-def4-5678-90ab-cdef12345678",
          "name": "Kitchen Ceiling",
          "area_id": "kitchen",
          "device_id": "device-id-1",
          "device_info": {
            "manufacturer": "Signify Netherlands B.V.",
            "model": "Hue color spot",
            "model_id": "LCG002",
            "sw_version": "1.104.2",
            "mac": "00:17:88:ab:cd:ef"
          }
        }
      ]
    }
  }
}
```

**Environment Variables:**
- `HA_SSH_HOST` - Home Assistant IP/hostname (required)
- `HA_SSH_USER` - SSH username (default: `hassio`)

**Exit Codes:**
- `0` - Success
- `1` - Connection failed, no bridges found, or error

---

### 2. Inventory Sync

**Script:** `sync-inventory-to-ha.sh`

Syncs Hue bridge inventories to Home Assistant server.

**What It Does:**
1. Captures fresh Hue inventories (runs `inventory-hue-bridge.py`)
2. Creates directory on HA server (`/homeassistant/hue_inventories/`)
3. Copies JSON files via SCP
4. Verifies successful transfer

**Usage:**
```bash
./sync-inventory-to-ha.sh
```

**Configuration:**

Reads from `ha_config.json`:
```json
{
  "ha_host": "192.168.1.100",
  "ha_user": "hassio",
  "ha_ssh_key": "../homeassistant_ssh_key",
  "ha_inventory_dir": "/homeassistant/hue_inventories"
}
```

**Environment Variable Fallback:**
```bash
export HA_SSH_HOST=192.168.1.100
export HA_SSH_USER=hassio
export HA_INVENTORY_DIR=/homeassistant/hue_inventories
./sync-inventory-to-ha.sh
```

**Output:**
```text
Step 1: Capturing fresh Hue bridge inventories...
✓ Inventories captured

Step 2: Ensuring HA inventory directory exists...
✓ Directory ready

Step 3: Copying inventories to Home Assistant...
✓ Inventories copied

Step 4: Verifying files on Home Assistant...
Found 2 inventory file(s) on HA
```

**Exit Codes:**
- `0` - Success
- `1` - Inventory capture failed, SSH failed, or SCP failed

---

### 3. Scene Validator (AppDaemon)

**File:** `scene_validator.py`

AppDaemon app that validates scene activations and provides fallback mechanisms.

**Features:**

1. **Scene Validation**
   - Monitors scene activation events
   - Compares actual light states with expected states
   - Validates on/off, brightness, and color

2. **3-Level Escalation**
   - Level 1: Validate only (no action)
   - Level 2: Re-trigger scene if validation fails
   - Level 3: Control lights individually as fallback

3. **Entity Mapping**
   - Connects Hue resource IDs to HA entity_ids
   - Uses `unique_id` for stable mapping
   - Survives entity renames

4. **Rate Limiting**
   - Per-scene: Max 5 validations/minute
   - Global: Max 20 validations/minute
   - Prevents rapid-fire validations

5. **Circuit Breaker**
   - Opens after threshold failures (default: 5)
   - Cooldown period (default: 5 minutes)
   - Half-open testing before full recovery

6. **Scene Filtering**
   - Include/exclude by labels
   - Pattern matching on scene names
   - UID-based exclusions

**Configuration Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `inventory_dir` | string | `/homeassistant/hue_inventories` | Path to inventory files |
| `transition_delay` | int | 5 | Wait time after scene activation (seconds) |
| `validation_delay` | int | 2 | Wait time between retries (seconds) |
| `max_validations_per_minute` | int | 20 | Global rate limit |
| `max_validations_per_scene_per_minute` | int | 5 | Per-scene rate limit |
| `circuit_breaker.failure_threshold` | int | 5 | Failures before opening circuit |
| `circuit_breaker.success_threshold` | int | 2 | Successes to close circuit |
| `circuit_breaker.timeout` | int | 300 | Cooldown period (seconds) |
| `scene_filter.include_labels` | list | `[]` | Only validate scenes with these labels |
| `scene_filter.exclude_labels` | list | `[]` | Never validate scenes with these labels |
| `scene_filter.exclude_uids` | list | `[]` | Exclude specific scene UIDs |
| `scene_filter.name_patterns` | list | `[]` | Include scenes matching patterns |

**Scene Filtering Examples:**

```yaml
# Only validate scenes with label
scene_filter:
  include_labels:
    - validate_scenes

# Exclude development scenes
scene_filter:
  exclude_labels:
    - dev
    - testing

# Only validate specific patterns
scene_filter:
  name_patterns:
    - ".*Standard$"      # Scenes ending with "Standard"
    - "^Kitchen.*"       # Scenes starting with "Kitchen"

# Exclude specific scenes by UID
scene_filter:
  exclude_uids:
    - "scene-uid-1"
    - "scene-uid-2"
```

**Logging Levels:**

- `INFO` - Normal validation flow
- `WARNING` - Rate limits, filtered scenes
- `ERROR` - Validation failures, circuit breaker activation
- `DEBUG` - Detailed state comparisons (verbose)

**Example Log Output:**
```text
INFO: Scene activated: scene.kitchen_bright
INFO: Validation started for scene: scene.kitchen_bright (uid: abc123)
INFO: Checking 3 lights in scene
INFO: Light light.kitchen_ceiling: ✓ ON, ✓ Brightness 100%, ✓ Color match
INFO: Light light.kitchen_counter: ✓ ON, ✓ Brightness 80%, ✓ Color match
INFO: Light light.kitchen_pendant: ✓ ON, ✓ Brightness 100%, ✓ Color match
INFO: All lights match expected state - validation successful
```

---

## Scene Validation System

### How It Works

```text
1. User activates scene
   ↓
2. AppDaemon receives event
   ↓
3. Check filters (labels, patterns)
   ↓ [PASS]
4. Check rate limits
   ↓ [PASS]
5. Check circuit breaker
   ↓ [CLOSED/HALF_OPEN]
6. Wait transition_delay (5s)
   ↓
7. LEVEL 1: Validate
   ↓
   [SUCCESS] → Done
   ↓
   [FAILURE]
   ↓
8. LEVEL 2: Re-trigger
   ↓
   [SUCCESS] → Done
   ↓
   [FAILURE]
   ↓
9. LEVEL 3: Individual control
   ↓
   [SUCCESS] → Done
   ↓
   [FAILURE] → Open circuit
```

### State Comparison Logic

For each light in scene:

**1. On/Off State:**
```python
expected_on = scene_state['on']
actual_on = light_state['on']
match = (expected_on == actual_on)
```

**2. Brightness:**
```python
expected_brightness = scene_state['brightness']
actual_brightness = light_state['brightness']
tolerance = 5  # ±5% tolerance
match = abs(expected_brightness - actual_brightness) <= tolerance
```

**3. Color (XY):**
```python
expected_xy = scene_state['xy_color']
actual_xy = light_state['xy_color']
tolerance = 0.01  # ±0.01 tolerance
match = (
    abs(expected_xy[0] - actual_xy[0]) <= tolerance and
    abs(expected_xy[1] - actual_xy[1]) <= tolerance
)
```

**4. Color Temperature:**
```python
expected_ct = scene_state['color_temp']
actual_ct = light_state['color_temp']
tolerance = 10  # ±10 mireds
match = abs(expected_ct - actual_ct) <= tolerance
```

### Entity Mapping

Map Hue resource IDs to HA entity_ids:

```python
def get_entity_id_from_hue_id(hue_resource_id):
    """Map Hue resource ID to HA entity_id."""
    entities = self.get_state('light')

    for entity_id in entities.keys():
        unique_id = self.get_state(entity_id, attribute='unique_id')

        if unique_id == hue_resource_id:
            return entity_id

    return None
```

**Why This Works:**
- `unique_id` is stable across HA reinstalls
- Survives entity_id renames
- Directly maps to Hue resource ID

### Fallback Strategy

**Level 1 - Validation Only:**
- Fast check, non-intrusive
- Most scenes should pass here
- No changes made to system

**Level 2 - Re-trigger:**
- Handles transient network issues
- Lost Zigbee messages
- Bridge communication hiccups
- Still uses scene (proper behavior)

**Level 3 - Individual Control:**
- Last resort fallback
- Ensures desired state achieved
- Indicates underlying issue needs investigation
- Logs warning for manual review

### Circuit Breaker States

**CLOSED (Normal):**
- All validations proceed normally
- Track failure count
- Open if threshold exceeded

**OPEN (Kill Switch):**
- All validations skipped
- Log warning for each attempt
- Wait for timeout period

**HALF_OPEN (Testing):**
- After timeout expires
- Allow next validation through
- Close if success, re-open if failure

**Benefits:**
- Prevents runaway automation
- Automatic recovery
- Protects system from cascading failures

---

## Configuration

### ha_config.json

Create in project root:

```json
{
  "ha_host": "192.168.1.100",
  "ha_user": "hassio",
  "ha_ssh_key": "../homeassistant_ssh_key",
  "ha_inventory_dir": "/homeassistant/hue_inventories"
}
```

**Parameters:**

| Field | Required | Description |
|-------|----------|-------------|
| `ha_host` | Yes | Home Assistant IP or hostname |
| `ha_user` | No | SSH username (default: `hassio`) |
| `ha_ssh_key` | No | Path to SSH private key (relative or absolute) |
| `ha_inventory_dir` | No | Directory on HA server for inventories |

**Security:** This file is excluded from git. Use `ha_config.example` as template.

### apps.yaml (AppDaemon)

Configure scene validator:

```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  # Required
  inventory_dir: /homeassistant/hue_inventories

  # Timing (optional)
  transition_delay: 5        # Wait after scene activation
  validation_delay: 2        # Wait between retries

  # Rate limiting (optional)
  max_validations_per_minute: 20
  max_validations_per_scene_per_minute: 5

  # Circuit breaker (optional)
  circuit_breaker:
    failure_threshold: 5     # Failures before opening
    success_threshold: 2     # Successes to close (from half-open)
    timeout: 300             # Cooldown period (seconds)

  # Scene filtering (optional)
  scene_filter:
    include_labels:          # Only these labels
      - validate_scenes
    exclude_labels:          # Never these labels
      - no_validation
      - dev
    exclude_uids:            # Specific scene UIDs to skip
      - "scene-uid-to-exclude"
    name_patterns:           # Regex patterns (if include_labels empty)
      - ".*Standard$"
      - "^Kitchen.*"
```

### Environment Variables

**For Scripts:**

```bash
# Required for export-ha-hue-inventory.py
export HA_SSH_HOST=192.168.1.100

# Optional
export HA_SSH_USER=hassio
```

**For Sync Script:**

```bash
# Optional overrides (if not in ha_config.json)
export HA_SSH_HOST=192.168.1.100
export HA_SSH_USER=hassio
export HA_INVENTORY_DIR=/homeassistant/hue_inventories
```

---

## Use Cases

### Use Case 1: Basic Scene Validation

**Goal:** Validate all important scenes.

```yaml
# apps.yaml
scene_validator:
  module: scene_validator
  class: SceneValidator
  inventory_dir: /homeassistant/hue_inventories
  scene_filter:
    include_labels:
      - validate_scenes
```

**Workflow:**
1. Add `validate_scenes` label to important scenes
2. Activate scene
3. Validator checks all lights
4. Re-triggers if needed
5. Falls back to individual control if scene fails

### Use Case 2: Development Environment

**Goal:** Skip validation for development scenes.

```yaml
# apps.yaml
scene_filter:
  include_labels:
    - validate_scenes
  exclude_labels:
    - dev
    - testing
```

**Label Scenes:**
- Production scenes: `validate_scenes`
- Development scenes: `dev` or `testing`
- Both labels: Development wins (excluded)

### Use Case 3: Pattern-Based Validation

**Goal:** Validate only specific scene naming patterns.

```yaml
# apps.yaml
scene_filter:
  name_patterns:
    - ".*Standard$"          # All "Standard" scenes
    - "^Kitchen.*Bright$"    # Kitchen bright scenes
```

**Scene Names:**
- `Kitchen Morning Standard` - ✓ Validated
- `Living Room Standard` - ✓ Validated
- `Kitchen Evening Bright` - ✓ Validated
- `Bedroom Dim` - ✗ Not validated

### Use Case 4: Monitor Validation Performance

**Goal:** Track validation success rate.

```bash
# SSH to HA
ssh -i homeassistant_ssh_key hassio@192.168.1.100

# Watch AppDaemon logs
docker logs -f addon_a0d7b954_appdaemon | grep "validation"

# Count successes
docker logs addon_a0d7b954_appdaemon | grep "validation successful" | wc -l

# Count failures
docker logs addon_a0d7b954_appdaemon | grep "validation failed" | wc -l
```

### Use Case 5: Regular Inventory Updates

**Goal:** Keep HA inventories up-to-date.

**Cron Job:**
```bash
#!/bin/bash
# update-ha-inventories.sh

cd /path/to/aiohue/scripts

# Sync inventories to HA
./sync-inventory-to-ha.sh

# Export HA perspective
python3 export-ha-hue-inventory.py
```

**Schedule:**
```cron
# Daily at 3 AM
0 3 * * * /path/to/update-ha-inventories.sh
```

### Use Case 6: Emergency Kill Switch

**Goal:** Manually open circuit breaker to stop validations.

**Method 1 - Restart AppDaemon:**
```bash
# Via HA UI
Settings > Add-ons > AppDaemon > Restart

# Via CLI
ssh -i homeassistant_ssh_key hassio@192.168.1.100
ha addons restart a0d7b954_appdaemon
```

**Method 2 - Disable App:**
```yaml
# apps.yaml - comment out entire app
# scene_validator:
#   module: scene_validator
#   ...

# Reload apps (if supported)
# Or restart AppDaemon
```

**Method 3 - Remove Label:**
```bash
# Remove validate_scenes label from all scenes
# Validator will skip all scenes
```

---

## Troubleshooting

### SSH Connection Fails

**Problem:** Cannot connect to HA server via SSH.

**Solutions:**

1. Verify SSH key permissions:
   ```bash
   chmod 600 homeassistant_ssh_key
   ls -la homeassistant_ssh_key
   ```

2. Test SSH connection:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   ```

3. Check HA SSH add-on status:
   - Go to HA UI > Settings > Add-ons
   - Verify "Advanced SSH & Web Terminal" is running
   - Check add-on logs for errors

4. Verify SSH key is authorized:
   ```bash
   # In HA SSH add-on config
   authorized_keys:
     - "ssh-ed25519 AAAA... your-public-key-here"
   ```

### Inventory Export Fails

**Problem:** `export-ha-hue-inventory.py` fails with permission errors.

**Solutions:**

1. Check HA API token:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   ls -la /data/.ha_token
   cat /data/.ha_token  # Verify token exists
   ```

2. Test API access:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   curl -s -H "Authorization: Bearer $(cat /data/.ha_token)" \
     http://localhost:8123/api/states | jq '.[0]'
   ```

3. Verify storage files exist:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   ls -la /homeassistant/.storage/core.config_entries
   ls -la /homeassistant/.storage/core.entity_registry
   ```

### Scene Validator Not Running

**Problem:** Scenes activate but no validation happens.

**Solutions:**

1. Check AppDaemon is running:
   ```bash
   # HA UI: Settings > Add-ons > AppDaemon
   # Status should be "Running"
   ```

2. Check AppDaemon logs:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   docker logs addon_a0d7b954_appdaemon | tail -100
   ```

3. Verify app loaded:
   ```text
   # Look for in logs:
   INFO: Loading app scene_validator
   INFO: Initializing SceneValidator
   ```

4. Check apps.yaml configuration:
   ```bash
   ssh -i homeassistant_ssh_key hassio@192.168.1.100
   cat /addon_configs/a0d7b954_appdaemon/apps/apps.yaml
   ```

5. Verify scene has label:
   ```bash
   # Check scene configuration
   # Must have label: validate_scenes
   ```

### Scenes Not Validated

**Problem:** Validator is running, but scenes are skipped.

**Solutions:**

1. Check scene has correct label:
   ```yaml
   # In HA UI: Scene Settings
   Labels: validate_scenes
   ```

2. Check scene filter configuration:
   ```yaml
   # apps.yaml
   scene_filter:
     include_labels:
       - validate_scenes  # Must match label on scene
   ```

3. Check scene is not excluded:
   ```yaml
   # Apps.yaml - check exclude lists
   scene_filter:
     exclude_labels:
       - no_validation  # Make sure scene doesn't have this
   ```

4. Check AppDaemon logs for filter messages:
   ```text
   WARNING: Scene scene.kitchen_bright skipped (no matching label)
   WARNING: Scene scene.bedroom_dim excluded by label: dev
   ```

### Validation Always Fails

**Problem:** All validations fail even though lights look correct.

**Solutions:**

1. Check transition_delay is long enough:
   ```yaml
   # apps.yaml
   transition_delay: 5  # Increase if lights are slow
   ```

2. Verify inventory files are current:
   ```bash
   # Re-sync inventories
   cd scripts
   ./sync-inventory-to-ha.sh
   ```

3. Check for unique_id mapping issues:
   ```bash
   # AppDaemon logs
   ERROR: Could not map Hue ID abc123 to entity_id
   ```

4. Enable debug logging:
   ```yaml
   # appdaemon.yaml
   logs:
     scene_validator:
       name: SceneValidator
       level: DEBUG
   ```

5. Check state comparison tolerances:
   ```python
   # In scene_validator.py
   BRIGHTNESS_TOLERANCE = 5      # ±5%
   COLOR_TOLERANCE = 0.01        # ±0.01
   COLOR_TEMP_TOLERANCE = 10     # ±10 mireds
   ```

### Circuit Breaker Opens Frequently

**Problem:** Circuit breaker opens too often, stopping validations.

**Solutions:**

1. Increase failure threshold:
   ```yaml
   # apps.yaml
   circuit_breaker:
     failure_threshold: 10  # Increase from 5
   ```

2. Check for systemic issues:
   ```bash
   # Review failure patterns in logs
   docker logs addon_a0d7b954_appdaemon | grep "validation failed"
   ```

3. Investigate specific failing scenes:
   - Are certain lights always failing?
   - Are failures during specific times (network congestion)?
   - Are Zigbee devices losing connectivity?

4. Adjust tolerances if needed:
   - Brightness tolerance too strict?
   - Color tolerance too strict?
   - Transition delay too short?

### Rate Limit Warnings

**Problem:** Too many "Rate limit exceeded" warnings.

**Solutions:**

1. Increase rate limits:
   ```yaml
   # apps.yaml
   max_validations_per_minute: 30             # Increase from 20
   max_validations_per_scene_per_minute: 10  # Increase from 5
   ```

2. Check for automation loops:
   - Is automation re-triggering scenes rapidly?
   - Are multiple automations activating same scene?

3. Add delay between scene activations:
   ```yaml
   # In HA automation
   action:
     - service: scene.turn_on
       target:
         entity_id: scene.kitchen_bright
     - delay: "00:00:10"  # Wait 10 seconds before next action
   ```

---

## Next Steps

- **For Hue bridge management**: See [HUE_BRIDGE_MANAGEMENT.md](HUE_BRIDGE_MANAGEMENT.md)
- **For architecture overview**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **For detailed scene validation**: See [SCENE_VALIDATION_IMPLEMENTATION.md](SCENE_VALIDATION_IMPLEMENTATION.md)
- **For complete script reference**: See [SCRIPTS.md](SCRIPTS.md)
