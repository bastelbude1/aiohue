# Hue Bridge Management

Complete guide for managing Philips Hue bridges using direct API v2 access via the `aiohue` library.

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Scripts Reference](#scripts-reference)
- [Data Structures](#data-structures)
- [Use Cases](#use-cases)
- [Troubleshooting](#troubleshooting)

---

## Overview

The Hue Bridge Management toolkit provides direct access to Philips Hue bridges via the V2 API. This is independent of Home Assistant and provides the "technical, low-level" perspective of your Hue ecosystem.

### What This Toolkit Does

- **Discover bridges** on your local network
- **Register applications** with V2 API credentials
- **Capture complete inventories** of devices, lights, scenes, zones, sensors
- **Export automation configurations** (smart scenes, behavior instances, scripts)
- **Query and filter** data with powerful search tools

### When to Use This

- Setting up new bridges
- Backing up bridge configurations
- Analyzing automation setups
- Troubleshooting device issues
- Preparing data for Home Assistant integration
- Multi-bridge management

---

## Requirements

### Software

- Python 3.8 or higher
- Virtual environment with `aiohue` library (4.8.0+)
- Network access to Hue bridges

### Environment Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install aiohue
pip install aiohue
```

**Note:** Scripts will auto-activate the virtual environment if found at standard location.

### Network Requirements

- Bridges must be on same local network
- UDP port 1900 (SSDP discovery)
- HTTP/HTTPS access to bridge IPs
- Physical access to bridges (for registration button press)

---

## Quick Start

### 1. Discover Bridges

Find all Hue bridges on your network:

```bash
cd scripts
python3 discover-hue-bridges.py
```

**Example Output:**
```text
Discovering Philips Hue Bridges...

Bridge: Bridge Office
  IP: 192.168.1.100
  ID: abc123def456
  API Version: 2
  Model: BSB002

Bridge: Bridge Living
  IP: 192.168.1.101
  ID: xyz789ghi012
  API Version: 2
  Model: BSB002

Discovered 2 bridge(s)
Saved to: bridges/config.json
```

**Machine-Readable Output:**
```bash
python3 discover-hue-bridges.py --json
```

```json
{
  "bridges": [
    {
      "name": "Bridge Office",
      "ip": "192.168.1.100",
      "bridge_id": "abc123def456",
      "api_version": 2,
      "model": "BSB002"
    }
  ],
  "count": 2
}
```

### 2. Register with Bridges

Register your application to get V2 API credentials:

```bash
python3 register-hue-user.py
```

**Interactive Process:**
```text
Registering with Bridge Office (192.168.1.100)...
Press the link button on the bridge and hit Enter...
[User presses button and Enter]
✓ Registered successfully
  Username: generated-username-here
  Client Key: generated-client-key-here

Registering with Bridge Living (192.168.1.101)...
Press the link button on the bridge and hit Enter...
[User presses button and Enter]
✓ Registered successfully

Updated bridges/config.json with credentials
```

**What Gets Stored:**
```json
{
  "bridges": [
    {
      "name": "Bridge Office",
      "ip": "192.168.1.100",
      "bridge_id": "abc123def456",
      "username": "generated-username",
      "client_key": "generated-client-key",
      "registered": true
    }
  ]
}
```

**Security Note:** `bridges/config.json` is excluded from git and contains sensitive credentials.

### 3. Capture Inventory

Capture complete device inventory from all bridges:

```bash
python3 inventory-hue-bridge.py
```

**Example Output:**
```text
Capturing Hue Bridge Inventories...

Processing: Bridge Office (abc123def456)
  Devices: 15
  Lights: 12
  Scenes: 8
  Zones: 4
  Rooms: 3
  Sensors: 10
  Saved to: bridges/inventory/Bridge_Office-abc123def456.json

Processing: Bridge Living (xyz789ghi012)
  Devices: 20
  Lights: 18
  Scenes: 12
  Zones: 5
  Rooms: 4
  Sensors: 8
  Saved to: bridges/inventory/Bridge_Living-xyz789ghi012.json

Total bridges processed: 2
```

**Single Bridge:**
```bash
python3 inventory-hue-bridge.py --bridge abc123def456
```

**JSON Output:**
```bash
python3 inventory-hue-bridge.py --json
```

### 4. Capture Automations

Export automation configurations:

```bash
python3 automation-hue-bridge.py
```

**Example Output:**
```text
Capturing Hue Bridge Automation Data...

Processing: Bridge Office (abc123def456)
  Smart Scenes: 3
  Behavior Instances: 5
  Behavior Scripts: 12
  Geofence Clients: 1
  Geolocation: Present
  Saved to: bridges/automations/Bridge_Office-abc123def456-automations.json

Processing: Bridge Living (xyz789ghi012)
  Smart Scenes: 2
  Behavior Instances: 7
  Behavior Scripts: 10
  Geofence Clients: 0
  Geolocation: Present
  Saved to: bridges/automations/Bridge_Living-xyz789ghi012-automations.json

Total bridges processed: 2
```

### 5. Query Data

Search and filter inventory data:

```bash
# Find all lights with "Kitchen" in the name
python3 query-hue-inventory.py --type lights --name "*Kitchen*"

# Show all scenes
python3 query-hue-inventory.py --type scenes

# Get detailed info for specific bridge
python3 query-hue-inventory.py --bridge abc123def456 --detailed

# Export to JSON for processing
python3 query-hue-inventory.py --json > export.json
```

Search automation data:

```bash
# Show all enabled automations
python3 query-hue-automation.py --state enabled

# Find specific automation by name
python3 query-hue-automation.py --name "*Wake*"

# Get summary statistics
python3 query-hue-automation.py --summary
```

---

## Scripts Reference

### discover-hue-bridges.py

Discover Philips Hue bridges on your local network.

**Usage:**
```bash
python3 discover-hue-bridges.py [--json] [--timeout SECONDS]
```

**Options:**
- `--json` - Output in JSON format (machine-readable)
- `--timeout SECONDS` - Discovery timeout (default: 5)

**Output:**
- Console: Human-readable bridge list
- File: `bridges/config.json` (created/updated)

**Example:**
```bash
# Interactive discovery
python3 discover-hue-bridges.py

# JSON output for scripting
python3 discover-hue-bridges.py --json

# Longer timeout for large networks
python3 discover-hue-bridges.py --timeout 10
```

**What It Does:**
1. Scans network via mDNS/SSDP
2. Queries each bridge for details
3. Detects API version support
4. Saves to `bridges/config.json`

**Exit Codes:**
- `0` - Success
- `1` - No bridges found or error

---

### register-hue-user.py

Register V2 API application with bridges.

**Usage:**
```bash
python3 register-hue-user.py [--json] [--bridge BRIDGE_ID]
```

**Options:**
- `--json` - Output in JSON format
- `--bridge BRIDGE_ID` - Register specific bridge only

**Requirements:**
- `bridges/config.json` must exist (run discover first)
- Physical access to bridge link button

**Process:**
1. Reads `bridges/config.json`
2. For each unregistered bridge:
   - Prompts to press link button
   - Waits for button press
   - Registers application
   - Saves credentials
3. Updates `bridges/config.json`

**Example:**
```bash
# Register all bridges
python3 register-hue-user.py

# Register specific bridge
python3 register-hue-user.py --bridge abc123def456

# JSON output
python3 register-hue-user.py --json
```

**Security:**
- Credentials stored in `bridges/config.json` (excluded from git)
- Username and client_key are sensitive - protect this file

**Exit Codes:**
- `0` - Success
- `1` - No bridges found, registration failed, or config missing

---

### inventory-hue-bridge.py

Capture complete bridge inventory (devices, lights, scenes, etc.).

**Usage:**
```bash
python3 inventory-hue-bridge.py [--json] [--bridge BRIDGE_ID] [--output-dir DIR]
```

**Options:**
- `--json` - Output in JSON format
- `--bridge BRIDGE_ID` - Inventory for specific bridge only
- `--output-dir DIR` - Custom output directory (default: `bridges/inventory/`)

**Captured Resources:**
- Devices (physical hardware)
- Lights (individual light controls)
- Scenes (pre-configured states)
- Zones (groups of lights)
- Rooms (physical room groupings)
- Sensors (motion, switches, buttons, temperature, light level)
- Grouped lights
- Bridge home configuration

**Output Files:**
```text
bridges/inventory/{BridgeName}-{BridgeID}.json
```

**Example:**
```bash
# Inventory all bridges
python3 inventory-hue-bridge.py

# Specific bridge
python3 inventory-hue-bridge.py --bridge abc123def456

# JSON progress output
python3 inventory-hue-bridge.py --json

# Custom output directory
python3 inventory-hue-bridge.py --output-dir /path/to/backups
```

**File Structure:**
```json
{
  "bridge_info": {
    "ip": "192.168.1.100",
    "bridge_id": "abc123def456",
    "name": "Bridge Office",
    "captured_at": "2025-11-13T10:00:00"
  },
  "resources": {
    "devices": {
      "count": 15,
      "items": [
        {
          "id": "device-id-1",
          "type": "device",
          "metadata": { "name": "Kitchen Light Strip" },
          "product_data": { "model_id": "LCX001", "product_name": "Hue Light Strip Plus" },
          "services": [...]
        }
      ]
    },
    "lights": { "count": 12, "items": [...] },
    "scenes": { "count": 8, "items": [...] },
    "zones": { "count": 4, "items": [...] },
    "rooms": { "count": 3, "items": [...] },
    "sensors": { "count": 10, "items": [...] }
  }
}
```

**Exit Codes:**
- `0` - Success
- `1` - No bridges found, connection failed, or error

---

### automation-hue-bridge.py

Capture automation configurations (smart scenes, behavior instances, scripts).

**Usage:**
```bash
python3 automation-hue-bridge.py [--json] [--bridge BRIDGE_ID] [--output-dir DIR]
```

**Options:**
- `--json` - Output in JSON format
- `--bridge BRIDGE_ID` - Capture specific bridge only
- `--output-dir DIR` - Custom output directory (default: `bridges/automations/`)

**Captured Automation Types:**
- **Smart Scenes** - Time-based scheduled scenes
- **Behavior Instances** - Active running automations
- **Behavior Scripts** - Available automation templates
- **Geofence Clients** - Location-based triggers
- **Geolocation** - Sun position and location data

**Output Files:**
```text
bridges/automations/{BridgeName}-{BridgeID}-automations.json
```

**Example:**
```bash
# Capture all bridges
python3 automation-hue-bridge.py

# Specific bridge
python3 automation-hue-bridge.py --bridge abc123def456

# JSON output
python3 automation-hue-bridge.py --json

# Custom output directory
python3 automation-hue-bridge.py --output-dir /path/to/backups
```

**File Structure:**
```json
{
  "bridge_info": {
    "ip": "192.168.1.100",
    "bridge_id": "abc123def456",
    "name": "Bridge Office",
    "captured_at": "2025-11-13T10:00:00"
  },
  "automations": {
    "smart_scenes": {
      "count": 3,
      "items": [
        {
          "id": "smart-scene-id",
          "type": "smart_scene",
          "metadata": { "name": "Wake Up" },
          "state": "enabled",
          "week_timeslots": [...]
        }
      ]
    },
    "behavior_instances": { "count": 5, "items": [...] },
    "behavior_scripts": { "count": 12, "items": [...] },
    "geofence_clients": { "count": 1, "items": [...] },
    "geolocation": { "count": 1, "items": [...] }
  }
}
```

**Exit Codes:**
- `0` - Success
- `1` - No bridges found, connection failed, or error

---

### query-hue-inventory.py

Query and filter inventory data with powerful search options.

**Usage:**
```bash
python3 query-hue-inventory.py [OPTIONS]
```

**Options:**
- `--bridge BRIDGE_ID` - Query specific bridge
- `--type TYPE` - Filter by resource type
- `--name PATTERN` - Filter by name (supports wildcards)
- `--state STATE` - Filter by state (on/off/brightness)
- `--json` - JSON output
- `--detailed` - Show all attributes
- `--summary` - Show count statistics only

**Resource Types:**
- `devices` - Physical hardware
- `lights` - Individual lights
- `scenes` - Pre-configured scenes
- `zones` - Light zones
- `rooms` - Room groupings
- `sensors` - All sensors
- `grouped_lights` - Light groups

**Examples:**

```bash
# Find all lights
python3 query-hue-inventory.py --type lights

# Find lights with "Kitchen" in name
python3 query-hue-inventory.py --type lights --name "*Kitchen*"

# Find lights that are currently on
python3 query-hue-inventory.py --type lights --state on

# Find bright lights (>50%)
python3 query-hue-inventory.py --type lights --state 50

# Query specific bridge
python3 query-hue-inventory.py --bridge abc123def456 --type scenes

# Get detailed view
python3 query-hue-inventory.py --type devices --name "*Strip*" --detailed

# Get summary statistics
python3 query-hue-inventory.py --summary

# Export to JSON
python3 query-hue-inventory.py --type lights --json > lights.json
```

**Output Formats:**

**Human-Readable:**
```text
Bridge: Bridge Office (abc123def456)

Lights (12):
  • Kitchen Ceiling (light.kitchen_ceiling)
    State: ON, Brightness: 80%, Color: (0.4, 0.5)
  • Living Room Lamp (light.living_room_lamp)
    State: OFF
```

**JSON:**
```json
{
  "bridges": {
    "abc123def456": {
      "name": "Bridge Office",
      "lights": [
        {
          "id": "light-id-1",
          "name": "Kitchen Ceiling",
          "on": true,
          "brightness": 80.0,
          "color": { "xy": { "x": 0.4, "y": 0.5 } }
        }
      ]
    }
  }
}
```

**Wildcards:**
- `*` - Match any characters
- `?` - Match single character
- Examples: `*Kitchen*`, `Lamp_?`, `*_Sensor`

**Exit Codes:**
- `0` - Success
- `1` - No data found or error

---

### query-hue-automation.py

Query and filter automation data.

**Usage:**
```bash
python3 query-hue-automation.py [OPTIONS]
```

**Options:**
- `--bridge BRIDGE_ID` - Query specific bridge
- `--type TYPE` - Filter by automation type
- `--name PATTERN` - Filter by name (supports wildcards)
- `--state STATE` - Filter by state (enabled/disabled)
- `--json` - JSON output
- `--detailed` - Show all attributes
- `--summary` - Show count statistics only

**Automation Types:**
- `smart_scenes` - Time-based scheduled scenes
- `behavior_instances` - Active running automations
- `behavior_scripts` - Available automation templates
- `geofence_clients` - Location-based triggers
- `geolocation` - Sun position data

**Examples:**

```bash
# Show all automations
python3 query-hue-automation.py

# Show only enabled automations
python3 query-hue-automation.py --state enabled

# Find automations by name
python3 query-hue-automation.py --name "*Wake*"

# Show smart scenes only
python3 query-hue-automation.py --type smart_scenes

# Query specific bridge
python3 query-hue-automation.py --bridge abc123def456

# Get detailed view
python3 query-hue-automation.py --type behavior_instances --detailed

# Get summary statistics
python3 query-hue-automation.py --summary

# Export to JSON
python3 query-hue-automation.py --type smart_scenes --json > smart_scenes.json
```

**Output Example:**
```text
Bridge: Bridge Office (abc123def456)

Smart Scenes (3):
  • Wake Up
    State: ENABLED
    Schedule: Weekdays at 07:00
    Target: bedroom

  • Good Night
    State: ENABLED
    Schedule: Daily at 22:00
    Target: house

Behavior Instances (5):
  • Motion Sensor - Kitchen
    State: ENABLED
    Type: automation
```

**Exit Codes:**
- `0` - Success
- `1` - No data found or error

---

## Data Structures

### bridges/config.json

Bridge credentials and configuration.

**Structure:**
```json
{
  "bridges": [
    {
      "name": "Bridge Office",
      "ip": "192.168.1.100",
      "bridge_id": "abc123def456",
      "model": "BSB002",
      "api_version": 2,
      "username": "generated-username-here",
      "client_key": "generated-client-key-here",
      "registered": true,
      "discovered_at": "2025-11-13T10:00:00",
      "registered_at": "2025-11-13T10:05:00"
    }
  ]
}
```

**Security:** This file is excluded from git and contains sensitive credentials.

### Inventory Files

**Location:** `bridges/inventory/{BridgeName}-{BridgeID}.json`

**Structure:**
```json
{
  "bridge_info": {
    "ip": "192.168.1.100",
    "bridge_id": "abc123def456",
    "name": "Bridge Office",
    "captured_at": "2025-11-13T10:00:00.123456",
    "api_version": 2,
    "config": {
      "name": "Philips hue",
      "bridge_id": "abc123def456",
      "mac_address": "00:17:88:ab:cd:ef"
    }
  },
  "resources": {
    "devices": {
      "count": 15,
      "items": [...]
    },
    "lights": {
      "count": 12,
      "items": [...]
    },
    "scenes": {
      "count": 8,
      "items": [...]
    }
  }
}
```

### Automation Files

**Location:** `bridges/automations/{BridgeName}-{BridgeID}-automations.json`

**Structure:**
```json
{
  "bridge_info": {
    "ip": "192.168.1.100",
    "bridge_id": "abc123def456",
    "name": "Bridge Office",
    "captured_at": "2025-11-13T10:00:00.123456"
  },
  "automations": {
    "smart_scenes": {
      "count": 3,
      "items": [...]
    },
    "behavior_instances": {
      "count": 5,
      "items": [...]
    }
  }
}
```

---

## Use Cases

### Use Case 1: Initial Bridge Setup

**Scenario:** You have new Hue bridges and want to set them up for management.

```bash
# 1. Discover bridges on network
python3 discover-hue-bridges.py

# 2. Register with bridges (press button when prompted)
python3 register-hue-user.py

# 3. Capture initial inventory
python3 inventory-hue-bridge.py

# 4. Capture initial automations
python3 automation-hue-bridge.py

# Done! All data saved to bridges/ directory
```

### Use Case 2: Regular Backups

**Scenario:** Schedule regular backups of bridge configurations.

```bash
#!/bin/bash
# backup-hue-bridges.sh

cd /path/to/aiohue/scripts

# Capture current inventory
python3 inventory-hue-bridge.py --json

# Capture current automations
python3 automation-hue-bridge.py --json

# Copy to backup location with timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp -r ../bridges/inventory ../backups/inventory_${TIMESTAMP}/
cp -r ../bridges/automations ../backups/automations_${TIMESTAMP}/

echo "Backup complete: ${TIMESTAMP}"
```

**Cron Schedule:**
```cron
# Daily backup at 2 AM
0 2 * * * /path/to/backup-hue-bridges.sh
```

### Use Case 3: Multi-Bridge Comparison

**Scenario:** You have multiple bridges and want to compare their setups.

```bash
# Get summary for all bridges
python3 query-hue-inventory.py --summary

# Output:
# Bridge Office (abc123def456):
#   Devices: 15, Lights: 12, Scenes: 8
#
# Bridge Living (xyz789ghi012):
#   Devices: 20, Lights: 18, Scenes: 12

# Compare specific resource
python3 query-hue-inventory.py --type scenes --json > all_scenes.json

# Process with jq or Python
jq '.bridges[] | {name: .name, scene_count: (.scenes | length)}' all_scenes.json
```

### Use Case 4: Find Devices by Name

**Scenario:** You need to find all devices with "Kitchen" in the name.

```bash
# Search across all bridges
python3 query-hue-inventory.py --name "*Kitchen*"

# Search specific resource type
python3 query-hue-inventory.py --type lights --name "*Kitchen*"

# Get detailed info
python3 query-hue-inventory.py --type sensors --name "*Kitchen*" --detailed
```

### Use Case 5: Troubleshoot Lights

**Scenario:** Some lights aren't working - find which ones are off.

```bash
# Find all lights that are off
python3 query-hue-inventory.py --type lights --state off

# Find dim lights (below 20%)
python3 query-hue-inventory.py --type lights --state 20

# Get detailed state for specific light
python3 query-hue-inventory.py --type lights --name "*Problem_Light*" --detailed
```

### Use Case 6: Review Automations

**Scenario:** Review all enabled automations before making changes.

```bash
# List all enabled automations
python3 query-hue-automation.py --state enabled

# Show smart scenes specifically
python3 query-hue-automation.py --type smart_scenes --state enabled --detailed

# Export to file for review
python3 query-hue-automation.py --json > automations_review.json
```

### Use Case 7: Pre-Migration Inventory

**Scenario:** You're migrating to a new system and need complete documentation.

```bash
# Capture everything
python3 inventory-hue-bridge.py --json > inventory.json
python3 automation-hue-bridge.py --json > automations.json

# Get detailed exports
python3 query-hue-inventory.py --detailed --json > inventory_detailed.json
python3 query-hue-automation.py --detailed --json > automations_detailed.json

# Archive everything
tar -czf hue_migration_backup_$(date +%Y%m%d).tar.gz bridges/
```

---

## Troubleshooting

### Bridge Not Discovered

**Problem:** `discover-hue-bridges.py` doesn't find bridges.

**Solutions:**
1. Check network connectivity:
   ```bash
   ping 192.168.1.100  # Use your bridge IP
   ```

2. Verify bridge is powered on and connected to network

3. Try longer timeout:
   ```bash
   python3 discover-hue-bridges.py --timeout 10
   ```

4. Check firewall allows UDP port 1900 (SSDP)

5. Try manual configuration:
   ```json
   {
     "bridges": [
       {
         "name": "My Bridge",
         "ip": "192.168.1.100",
         "bridge_id": "abc123def456"
       }
     ]
   }
   ```
   Save to `bridges/config.json`

### Registration Fails

**Problem:** `register-hue-user.py` fails with "Link button not pressed".

**Solutions:**
1. Make sure to press link button BEFORE hitting Enter
2. Button press has 30-second timeout - be quick
3. Verify bridge is not in pairing mode with another app
4. Try again - sometimes first attempt fails

### API Connection Errors

**Problem:** Scripts fail with connection errors.

**Solutions:**
1. Verify credentials in `bridges/config.json`:
   ```bash
   cat bridges/config.json | grep -E "(username|client_key)"
   ```

2. Test direct API access:
   ```bash
   curl -k https://192.168.1.100/api/abc123/lights
   ```

3. Re-register if credentials are corrupted:
   ```bash
   # Delete old credentials
   rm bridges/config.json

   # Rediscover and register
   python3 discover-hue-bridges.py
   python3 register-hue-user.py
   ```

### Empty or Missing Data

**Problem:** Query scripts return no results.

**Solutions:**
1. Verify inventory files exist:
   ```bash
   ls -la bridges/inventory/
   ```

2. Re-capture inventory:
   ```bash
   python3 inventory-hue-bridge.py
   ```

3. Check file is not empty:
   ```bash
   cat bridges/inventory/*.json | jq '.resources | keys'
   ```

4. Verify bridge ID matches:
   ```bash
   python3 query-hue-inventory.py --bridge abc123def456
   ```

### Virtual Environment Issues

**Problem:** Scripts can't import `aiohue`.

**Solutions:**
1. Manually activate venv:
   ```bash
   source /path/to/venv/bin/activate
   python3 -c "import aiohue; print(aiohue.__version__)"
   ```

2. Install aiohue if missing:
   ```bash
   pip install aiohue
   ```

3. Verify Python version:
   ```bash
   python3 --version  # Should be 3.8+
   ```

4. Reinstall aiohue:
   ```bash
   pip uninstall aiohue
   pip install aiohue
   ```

### JSON Parse Errors

**Problem:** "Failed to parse JSON" errors.

**Solutions:**
1. Check file is valid JSON:
   ```bash
   jq . bridges/config.json
   ```

2. Look for corruption:
   ```bash
   cat bridges/config.json  # Check for truncation
   ```

3. Restore from backup or re-capture:
   ```bash
   python3 discover-hue-bridges.py
   python3 inventory-hue-bridge.py
   ```

### Permission Errors

**Problem:** "Permission denied" errors.

**Solutions:**
1. Check directory permissions:
   ```bash
   ls -la bridges/
   chmod 755 bridges/
   ```

2. Check file permissions:
   ```bash
   ls -la bridges/config.json
   chmod 644 bridges/config.json
   ```

3. Verify ownership:
   ```bash
   chown -R $USER:$USER bridges/
   ```

---

## Next Steps

- **For Home Assistant integration**: See [HOME_ASSISTANT_INTEGRATION.md](HOME_ASSISTANT_INTEGRATION.md)
- **For architecture overview**: See [ARCHITECTURE.md](ARCHITECTURE.md)
- **For scene validation**: See [SCENE_VALIDATION_IMPLEMENTATION.md](SCENE_VALIDATION_IMPLEMENTATION.md)
- **For complete script reference**: See [SCRIPTS.md](SCRIPTS.md)
