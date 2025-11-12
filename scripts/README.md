# aiohue Scripts Collection

A collection of utility scripts for managing and controlling Philips Hue bridges using the aiohue Python library.

## Prerequisites

- Python 3.12+ (installed on BastelBude)
- Virtual environment at `/home/baste/HA/venv/` with aiohue installed
- Network connectivity to Philips Hue bridges

## Setup

The scripts automatically activate the virtual environment, so no manual activation is required.

If you need to set up the environment from scratch:

```bash
cd /home/baste/HA
python3 -m venv venv
source venv/bin/activate
pip install aiohue
```

## Available Scripts

### discover-hue-bridges.py

Scans the local network for Philips Hue bridges using Philips' N-UPnP discovery service.

**Location:** `/home/baste/HA/aiohue/scripts/discover-hue-bridges.py`

**Usage:**

```bash
# Interactive mode (human-readable output)
python3 discover-hue-bridges.py

# JSON mode (machine-readable for scripting)
python3 discover-hue-bridges.py --json

# Save discovered bridges to file
python3 discover-hue-bridges.py --save /home/baste/HA/aiohue/bridges/config.json

# Save and display JSON
python3 discover-hue-bridges.py --save ../bridges/config.json --json

# Pretty JSON with jq
python3 discover-hue-bridges.py --json | jq .

# Show help
python3 discover-hue-bridges.py --help
```

**Output (Interactive Mode):**

```
Philips Hue Bridge Discovery
======================================================================

Found 2 bridge(s):

Bridge #1:
  ID:              ecb5faa015bb
  IP Address:      192.168.188.134
  API Support:     v2 (modern)
----------------------------------------------------------------------
Bridge #2:
  ID:              001788b3e355
  IP Address:      192.168.188.38
  API Support:     v2 (modern)
----------------------------------------------------------------------
```

**Output (JSON Mode):**

```json
{
  "count": 2,
  "bridges": [
    {
      "id": "ecb5faa015bb",
      "ip": "192.168.188.134",
      "supports_v2": true
    },
    {
      "id": "001788b3e355",
      "ip": "192.168.188.38",
      "supports_v2": true
    }
  ]
}
```

**Exit Codes:**
- `0` - Success (bridges found)
- `1` - Error or no bridges found

**Use Cases:**
- Initial bridge discovery for setup
- Verify bridge network connectivity
- Automated bridge monitoring scripts
- Network diagnostics

---

### register-hue-user.py

Registers with Philips Hue bridges to create API users (application keys) for authentication. This script prompts you to press the physical button on each bridge and saves the authentication credentials.

**Location:** `/home/baste/HA/aiohue/scripts/register-hue-user.py`

**Usage:**

```bash
# Register with all unregistered bridges (using default bridges file)
python3 register-hue-user.py

# Use custom bridges file location
python3 register-hue-user.py --bridges /path/to/bridges

# Register with specific bridge by ID
python3 register-hue-user.py --bridge-id ecb5faa015bb

# Force re-registration (even if already registered)
python3 register-hue-user.py --force

# Custom application name
python3 register-hue-user.py --app-name "My Home Automation"

# Show help
python3 register-hue-user.py --help
```

**Interactive Process:**

```
Loading bridges from: /home/baste/HA/aiohue/bridges/config.json
Found 1 bridge(s) to register.

======================================================================
Bridge:   ecb5faa015bb
IP:       192.168.188.134
DNS Name: Detsch-OG.fritz.box
======================================================================

⚠️  ACTION REQUIRED:
   1. Physically press the button on your Hue bridge
   2. You have 30 seconds after pressing to confirm below

Press ENTER after pressing the bridge button (or 'skip' to skip, 'quit' to exit):

🔄 Attempting to register with bridge...
   Requesting V2 credentials (username + clientkey)...
✅ Successfully registered with bridge ecb5faa015bb
   API Version: V2
   Username:    abc123xyz789...
   Client Key:  def456uvw123...
   Note: Client key enables Entertainment API features

💾 Saving credentials to: /home/baste/HA/aiohue/bridges/config.json
✅ Bridges file updated successfully!

You can now use these credentials to control your Hue lights.
```

**Exit Codes:**
- `0` - Success (all registrations successful)
- `1` - Error (registration failed or file error)
- `2` - User cancelled (Ctrl+C or 'quit')

**Use Cases:**
- Initial setup to gain API access to bridges
- Re-registration when credentials expire or are lost
- Register additional bridges discovered later
- Set up multiple API users with different names

**About Client Keys and API Versions:**

The registration behavior depends on the bridge API version:

- **V1 Bridges (older):** Only username is returned. `client_key` will be `null`.
- **V2 Bridges (modern):** Both username and `client_key` are returned.

**What each credential does:**
- **username:** Required for all API operations (lights, scenes, groups, automations). Both V1 and V2 bridges use this.
- **client_key:** Only needed for Entertainment API (synchronized light shows, gaming integrations, direct UDP control). Only available on V2 bridges.

For normal smart home automation, only the username is required. The script automatically detects the bridge version and requests the appropriate credentials.

---

### inventory-hue-bridge.py

Connects to registered Philips Hue bridges and retrieves comprehensive inventory of all resources including devices, lights, scenes, zones, rooms, sensors, and configuration.

**Location:** `/home/baste/HA/aiohue/scripts/inventory-hue-bridge.py`

**Usage:**

```bash
# Inventory all registered bridges
python3 inventory-hue-bridge.py

# Inventory specific bridge by ID
python3 inventory-hue-bridge.py --bridge-id ecb5faa015bb

# Use custom config file location
python3 inventory-hue-bridge.py --config /path/to/config.json

# Save to custom inventory directory
python3 inventory-hue-bridge.py --output /path/to/inventory

# JSON output to stdout
python3 inventory-hue-bridge.py --json

# Show help
python3 inventory-hue-bridge.py --help
```

**Output Files:**

Inventory files are saved with the format: `{BridgeName}-{BridgeID}.json`

Examples:
- `Detsch_OG-ecb5faa015bb.json`
- `Hue_Bridge-c42996c4e528.json`
- `Detsch_EG-001788b3e355.json`

**Inventory Data Structure:**

```json
{
  "bridge_info": {
    "ip": "192.168.188.134",
    "inventoried_at": "2025-11-12T11:07:47.767740",
    "config": {
      "bridge_id": "ecb5fafffea015bb",
      "name": "Detsch_OG",
      "model_id": "BSB002",
      "sw_version": "1.71.2071026000"
    }
  },
  "resources": {
    "devices": { "count": 34, "items": [...] },
    "lights": { "count": 28, "items": [...] },
    "scenes": { "count": 90, "items": [...] },
    "groups": {
      "zones": { "count": 0, "items": [] },
      "rooms": { "count": 0, "items": [] }
    },
    "sensors": { "count": 49, "items": [...] }
  }
}
```

**Exit Codes:**
- `0` - Success (inventory completed)
- `1` - Error (connection failed or no registered bridges)

**Use Cases:**
- Create complete snapshot of bridge resources
- Track changes over time
- Analyze device configuration
- Backup resource metadata
- Query and filter resources with query-hue-inventory.py

---

### query-hue-inventory.py

Query and filter inventory data collected from Philips Hue bridges with flexible search options and multiple output formats.

**Location:** `/home/baste/HA/aiohue/scripts/query-hue-inventory.py`

**Usage:**

```bash
# Find all lights with "Küche" in name
python3 query-hue-inventory.py --type lights --name "*Küche*"

# All devices on specific bridge
python3 query-hue-inventory.py --bridge ecb5faa015bb --type devices

# Lights that are currently on
python3 query-hue-inventory.py --type lights --state on

# Lights with brightness > 50%
python3 query-hue-inventory.py --type lights --state "brightness>50"

# Summary across all bridges
python3 query-hue-inventory.py --summary

# Detailed scene information
python3 query-hue-inventory.py --type scenes --name "Evening" --detailed

# JSON output for scripting
python3 query-hue-inventory.py --type lights --json

# Show help
python3 query-hue-inventory.py --help
```

**Filter Options:**

| Option | Description | Examples |
|--------|-------------|----------|
| `--name PATTERN` | Filter by name (supports wildcards) | `*Küche*`, `Lamp*`, `*Bedroom?` |
| `--type TYPE` | Filter by resource type | `lights`, `devices`, `scenes`, `sensors`, `zones`, `rooms` |
| `--state STATE` | Filter by state | `on`, `off`, `brightness>50`, `brightness<30` |
| `--bridge ID` | Query specific bridge | `ecb5faa015bb` |

**Output Formats:**

| Option | Description |
|--------|-------------|
| Default | Interactive table with key information |
| `--json` | Machine-readable JSON for scripting |
| `--detailed` | Full attribute display for each item |
| `--summary` | Count statistics only |

**Output (Interactive Table):**

```
================================================================================
Query Results
================================================================================

Bridge: Detsch_OG (ecb5faa015bb)
--------------------------------------------------------------------------------

LIGHTS (5):
  • Küche Decke [ON, 87%] - a1b2c3d4...
  • Küche Arbeitslicht [ON, 100%] - e5f6g7h8...
  • Wohnzimmer Ecklampe [OFF] - i9j0k1l2...
  • Schlafzimmer Nachttisch [ON, 45%] - m3n4o5p6...
  • Badezimmer Spiegel [ON, 60%] - q7r8s9t0...
```

**Output (Summary):**

```
======================================================================
Query Summary
======================================================================

Bridge: Detsch_OG (ecb5faa015bb)
  Lights: 28
  Devices: 34
  Scenes: 90
  Sensors: 49

Bridge: Detsch_EG (001788b3e355)
  Lights: 56
  Devices: 65
  Scenes: 124
  Sensors: 100

----------------------------------------------------------------------
Total Across All Bridges:
  Lights: 84
  Devices: 99
  Scenes: 214
  Sensors: 149
```

**Exit Codes:**
- `0` - Success (results found)
- `1` - Error or no results found

**Use Cases:**
- Find specific lights, devices, or scenes
- Check which lights are currently on/off
- Filter by brightness or other states
- Generate reports for documentation
- Automate queries in scripts

---

### automation-hue-bridge.py

Connects to registered Philips Hue bridges and retrieves comprehensive automation data including smart scenes, behavior instances, behavior scripts, geofence clients, and geolocation settings.

**Location:** `/home/baste/HA/aiohue/scripts/automation-hue-bridge.py`

**Usage:**

```bash
# Capture automations from all registered bridges
python3 automation-hue-bridge.py

# Capture from specific bridge by ID
python3 automation-hue-bridge.py --bridge-id ecb5faa015bb

# Use custom config file location
python3 automation-hue-bridge.py --config /path/to/config.json

# Save to custom output directory
python3 automation-hue-bridge.py --output /path/to/automations

# JSON output to stdout
python3 automation-hue-bridge.py --json

# Show help
python3 automation-hue-bridge.py --help
```

**Output Files:**

Automation files are saved with the format: `{BridgeName}-{BridgeID}-automations.json`

Examples:
- `Detsch_OG-ecb5faa015bb-automations.json`
- `Hue_Bridge-c42996c4e528-automations.json`
- `Detsch_EG-001788b3e355-automations.json`

**Automation Resources Captured:**

1. **Smart Scenes** - Time-based scheduled automations
   - Wake up/go to sleep routines
   - Sunrise/sunset triggers
   - Daily recurring schedules
   - Active time slots and transitions

2. **Behavior Instances** - Active running automations
   - Automation status (RUNNING, DISABLED, ERRORED)
   - Configuration and state
   - Enable/disable status
   - Last error information
   - Linked dependencies

3. **Behavior Scripts** - Available automation templates
   - Automation categories (automation, entertainment, accessory)
   - Configuration schemas
   - Trigger definitions
   - Version information
   - Maximum instance limits

4. **Geofence Clients** - Location-based triggers
   - Home/away detection devices
   - Geofence zones

5. **Geolocation** - Sun position data
   - Sunrise/sunset times
   - Location configuration
   - Day type (normal, summer, winter)

**Automation Data Structure:**

```json
{
  "bridge_info": {
    "ip": "192.168.188.134",
    "captured_at": "2025-11-12T13:04:35.123456",
    "config": {
      "bridge_id": "ecb5fafffea015bb",
      "name": "Detsch_OG",
      "model_id": "BSB002",
      "sw_version": "1.71.2071026000"
    }
  },
  "automations": {
    "smart_scenes": { "count": 6, "items": [...] },
    "behavior_instances": { "count": 8, "items": [...] },
    "behavior_scripts": { "count": 13, "items": [...] },
    "geofence_clients": { "count": 0, "items": [] },
    "geolocation": null
  }
}
```

**Output Summary Example:**

```
======================================================================
📊 Automation Capture Summary
======================================================================

Captured data from 3 bridge(s):

Bridge: Detsch_OG (ecb5faa015bb)
   📅 Smart Scenes: 6
   🤖 Behavior Instances: 8 (8 enabled)
   📜 Behavior Scripts: 13
   📍 Geofence Clients: 0

Bridge: Detsch_EG (001788b3e355)
   📅 Smart Scenes: 2
   🤖 Behavior Instances: 18 (14 enabled)
   📜 Behavior Scripts: 13
   📍 Geofence Clients: 0
```

**Exit Codes:**
- `0` - Success (automation data captured)
- `1` - Error (connection failed or no registered bridges)

**Querying Automation Data:**

Since automation files are saved as well-structured JSON, you can query them directly:

```bash
# View smart scene names
cat bridges/automations/Detsch_OG-ecb5faa015bb-automations.json | \
  jq '.automations.smart_scenes.items[] | .metadata.name'

# Find enabled behavior instances
cat bridges/automations/Detsch_OG-ecb5faa015bb-automations.json | \
  jq '.automations.behavior_instances.items[] | select(.enabled == true) | .metadata.name'

# Count all automations across bridges
cat bridges/automations/*.json | \
  jq '.automations.behavior_instances.count' | \
  awk '{sum+=$1} END {print "Total behavior instances:", sum}'

# Find automations by name
cat bridges/automations/*.json | \
  jq '.automations.smart_scenes.items[] | select(.metadata.name | contains("Wake")) | {name: .metadata.name, id: .id}'

# List behavior scripts available
cat bridges/automations/Detsch_OG-ecb5faa015bb-automations.json | \
  jq '.automations.behavior_scripts.items[] | .metadata.name'
```

**Use Cases:**
- Inventory all automation rules and schedules
- Track which automations are active/disabled
- Backup automation configurations
- Analyze automation patterns
- Compare automation setups across bridges
- Monitor automation status over time

---

### query-hue-automation.py

Query and filter automation data collected from Philips Hue bridges with flexible search options and multiple output formats - the automation equivalent of `query-hue-inventory.py`.

**Location:** `/home/baste/HA/aiohue/scripts/query-hue-automation.py`

**Usage:**

```bash
# Find all smart scenes
python3 query-hue-automation.py --type smart_scenes

# Find enabled behavior instances
python3 query-hue-automation.py --type behavior_instances --state enabled

# Find disabled automations
python3 query-hue-automation.py --type behavior_instances --state disabled

# Find running automations
python3 query-hue-automation.py --type behavior_instances --state running

# Find automations by name
python3 query-hue-automation.py --name "*Nacht*"

# Find wake-up automations
python3 query-hue-automation.py --name "*Wake*"

# Query specific bridge
python3 query-hue-automation.py --bridge ecb5faa015bb

# Summary across all bridges
python3 query-hue-automation.py --summary

# Detailed automation information
python3 query-hue-automation.py --type behavior_instances --name "*Markus*" --detailed

# JSON output for scripting
python3 query-hue-automation.py --type smart_scenes --json

# Show help
python3 query-hue-automation.py --help
```

**Filter Options:**

| Option | Description | Examples |
|--------|-------------|----------|
| `--type TYPE` | Filter by automation type | `smart_scenes`, `behavior_instances`, `behavior_scripts`, `geofence_clients`, `geolocation` |
| `--name PATTERN` | Filter by name (supports wildcards) | `*Nacht*`, `*Wake*`, `*Licht*` |
| `--state STATE` | Filter by state (behavior_instances only) | `enabled`, `disabled`, `running`, `errored` |
| `--bridge ID` | Query specific bridge | `ecb5faa015bb` |

**Automation Types:**

| Type | Description |
|------|-------------|
| `smart_scenes` | Time-based scheduled automations with sunrise/sunset triggers |
| `behavior_instances` | Active running automations (can be enabled/disabled) |
| `behavior_scripts` | Available automation templates |
| `geofence_clients` | Location-based triggers (home/away) |
| `geolocation` | Sun position data for location-based automations |

**Output Formats:**

| Option | Description |
|--------|-------------|
| Default | Interactive table with key information |
| `--json` | Machine-readable JSON for scripting |
| `--detailed` | Full attribute display for each automation |
| `--summary` | Count statistics only |

**Output (Interactive Table):**

```
================================================================================
Query Results
================================================================================

Bridge: Detsch_EG (001788b3e355)
--------------------------------------------------------------------------------

BEHAVIOR INSTANCES (14):
  ✓ Garten [running] - 45021769...
  ✓ Sonnenuntergang Licht An [running] - 6c4ee1da...
  ✓ ALARM Carport [running] - 964f50b4...
  ✓ Markus Aufstehen [running] - ef92843d...
  ✓ Dunja Aufstehen [running] - fab4e499...
  ...

Bridge: Detsch_OG (ecb5faa015bb)
--------------------------------------------------------------------------------

BEHAVIOR INSTANCES (3):
  ✓ Nachtlicht Gäste Gedimmt [running] - 239c59a0...
  ✓ Decke OG Nachtlicht [running] - 76bfd8c7...
  ✓ Nachtlicht Gäste [running] - f003110b...
```

**Output (Summary):**

```
======================================================================
Query Summary
======================================================================

Bridge: Detsch_EG (001788b3e355)
  Smart Scenes: 2
  Behavior Instances: 18 (14 enabled)
  Behavior Scripts: 13

Bridge: Detsch_OG (ecb5faa015bb)
  Smart Scenes: 6
  Behavior Instances: 8 (8 enabled)
  Behavior Scripts: 13

----------------------------------------------------------------------
Total Across All Bridges:
  Smart Scenes: 8
  Behavior Instances: 26
  Behavior Scripts: 39
```

**Output (Detailed):**

```
================================================================================
Detailed Query Results
================================================================================

Bridge: Detsch_OG (ecb5faa015bb)
--------------------------------------------------------------------------------

BEHAVIOR INSTANCES:

  [1] Natürlich Aufwachen Markus
      ID: a5b36562-95c9-418e-b705-9a0c9946d630
      Type: ResourceTypes.BEHAVIOR_INSTANCE
      Enabled: True
      Status: running
      Script ID: ff8957e3-2eb9-4699-a0c8-ad2cb3ede704
      Configuration: {...}
```

**Exit Codes:**
- `0` - Success (results found)
- `1` - Error or no results found

**Use Cases:**
- Find specific automations by name or pattern
- Check which automations are enabled/disabled
- Monitor automation status (running/errored)
- Compare automation setups across bridges
- Export automation data for analysis
- Generate automation reports

---

## Common Workflows

### 1. Initial Setup (Discovery + Registration)

```bash
# Step 1: Discover bridges on your network
cd /home/baste/HA/aiohue/scripts
python3 discover-hue-bridges.py --save ../bridges/config.json

# Step 2: Register with discovered bridges
python3 register-hue-user.py
# (Follow prompts to press button on each bridge)

# Step 3: Verify registration
cat /home/baste/HA/aiohue/bridges/config.json
# Should show "registered": true for each bridge
```

### 2. Automated Bridge Monitoring

```bash
# Create a simple monitoring script
python3 discover-hue-bridges.py --json > bridges.json

# Check if a specific bridge is online
BRIDGE_IP="192.168.188.134"
python3 discover-hue-bridges.py --json | jq -e ".bridges[] | select(.ip == \"$BRIDGE_IP\")" && echo "Bridge online" || echo "Bridge offline"
```

### 3. Inventory and Resource Querying

```bash
# Create inventory snapshot of all bridges
cd /home/baste/HA/aiohue/scripts
python3 inventory-hue-bridge.py

# View inventory files
ls -lh ../bridges/inventory/

# Query all lights
python3 query-hue-inventory.py --type lights

# Find specific devices
python3 query-hue-inventory.py --type lights --name "*Küche*"

# Check which lights are on
python3 query-hue-inventory.py --type lights --state on

# Get summary of all resources
python3 query-hue-inventory.py --summary

# Detailed info for scenes
python3 query-hue-inventory.py --type scenes --detailed

# Export to JSON for automation
python3 query-hue-inventory.py --type lights --json > lights.json
```

### 4. Automation Discovery and Analysis

```bash
# Capture automation data from all bridges
cd /home/baste/HA/aiohue/scripts
python3 automation-hue-bridge.py

# View automation files
ls -lh ../bridges/automations/

# Query all automations - summary
python3 query-hue-automation.py --summary

# Find all smart scenes
python3 query-hue-automation.py --type smart_scenes

# Find enabled behavior instances
python3 query-hue-automation.py --type behavior_instances --state enabled

# Find disabled automations
python3 query-hue-automation.py --type behavior_instances --state disabled

# Find automations by name pattern
python3 query-hue-automation.py --name "*Wake*"
python3 query-hue-automation.py --name "*Nacht*"

# Find running automations
python3 query-hue-automation.py --type behavior_instances --state running

# Detailed automation information
python3 query-hue-automation.py --name "*Markus*" --detailed

# List all available automation templates
python3 query-hue-automation.py --type behavior_scripts

# Export automation data
python3 query-hue-automation.py --json > automation-snapshot.json
python3 automation-hue-bridge.py --json > complete-automation-data.json
```

### 5. Integration with Home Assistant

```bash
# SSH into Home Assistant and run discovery from there
ssh -i /home/baste/HA/homeassistant_ssh_key hassio@192.168.188.42 \
  "curl -s 'http://BastelBude/aiohue/scripts/discover-hue-bridges.py' | python3"
```

---

## Troubleshooting

### No Bridges Found

**Problem:** Script returns "No Philips Hue bridges found on the network"

**Solutions:**
1. Ensure your Hue bridge is powered on
2. Verify the bridge is connected to your network (check router DHCP leases)
3. Confirm your computer is on the same network as the bridge
4. Check firewall settings (allow outbound HTTPS to Philips discovery service)
5. Try accessing the bridge web interface: `http://<bridge-ip>/`

### aiohue Import Error

**Problem:** `ImportError: No module named 'aiohue'`

**Solutions:**
1. Verify the virtual environment exists: `ls /home/baste/HA/venv/`
2. Reinstall aiohue:
   ```bash
   cd /home/baste/HA
   source venv/bin/activate
   pip install --upgrade aiohue
   ```
3. Check Python version compatibility (requires Python 3.12+)

### Network Timeout

**Problem:** Script hangs or times out during discovery

**Solutions:**
1. Check internet connectivity (N-UPnP requires internet access)
2. Verify DNS resolution: `nslookg discovery.meethue.com`
3. Try accessing Philips discovery directly:
   ```bash
   curl -s https://discovery.meethue.com/
   ```
4. Check for proxy or VPN interference

---

## Script Development Guidelines

When creating new scripts for this collection, follow these standards:

### Required Elements

1. **Shebang:** `#!/usr/bin/env python3`
2. **Docstring:** Comprehensive module-level docstring with usage examples
3. **Auto-venv activation:** Scripts must auto-activate `/home/baste/HA/venv/`
4. **argparse:** Use argparse for command-line arguments
5. **--help flag:** Detailed help text with examples
6. **--json flag:** Support both interactive and JSON output modes
7. **Exit codes:** Use appropriate exit codes (0=success, 1=error)
8. **Error handling:** Graceful error handling with helpful messages

### Naming Convention

- Use **kebab-case.py** for script names
- Examples: `discover-hue-bridges.py`, `register-hue-user.py`, `list-hue-lights.py`

### When to Save a Script

✅ **Save if:**
- Reusable utility for common operations
- Will be used multiple times
- Provides value for automation
- Part of a larger workflow

❌ **Don't save if:**
- One-time experiment or test
- Temporary debugging code
- Highly specific to a single use case
- Would require constant modification

### Documentation Requirements

For each new script:
1. Add entry to this README.md with:
   - Description
   - Usage examples
   - Input/output formats
   - Exit codes
   - Common use cases
2. Include comprehensive docstring in script
3. Provide troubleshooting guidance if applicable

---

## Future Scripts (Planned)

- `list-hue-lights.py` - List all lights on a bridge
- `control-hue-light.py` - Turn lights on/off, set brightness/color
- `get-hue-scenes.py` - List available scenes
- `backup-hue-config.py` - Backup bridge configuration
- `monitor-hue-events.py` - Monitor real-time bridge events
- `sync-hue-groups.py` - Manage light groups

---

## Related Documentation

- **CLAUDE.md** - AI assistant guidelines for this repository
- **HomeAssistant_SSH_Documentation.md** - Home Assistant system documentation
- [aiohue GitHub](https://github.com/home-assistant-libs/aiohue) - Official aiohue library
- [Philips Hue API](https://developers.meethue.com/) - Official Hue Developer Documentation

---

## Version History

- **1.1.0** (2025-11-12)
  - Added `register-hue-user.py` - Bridge registration script
  - Enhanced `discover-hue-bridges.py` with `--save` option
  - Updated documentation with complete setup workflow

- **1.0.0** (2025-11-12)
  - Initial release
  - Added `discover-hue-bridges.py`
  - Established script standards and documentation

---

*Last Updated: 2025-11-12*
