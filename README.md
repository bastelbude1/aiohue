# Philips Hue Bridge Management Scripts

A comprehensive Python toolkit for managing multiple Philips Hue bridges using the V2 API via the `aiohue` library.

## Features

- **Bridge Discovery**: Automatically find Hue bridges on your network and detect API version support
- **V2 API Registration**: Register applications with bridges using modern V2 credentials (username + client_key)
- **Comprehensive Inventory**: Capture complete bridge inventories including devices, lights, scenes, zones, rooms, and sensors
- **Automation Management**: Extract and analyze bridge automations (smart scenes, behavior instances, scripts, geofence)
- **Powerful Query Tools**: Filter and search inventory and automation data with multiple output formats
- **Multi-Bridge Support**: Manage multiple bridges simultaneously with organized data storage

## Requirements

- Python 3.8+
- Virtual environment with `aiohue` library (4.8.0+)
- Network access to Philips Hue bridges

## Quick Start

### 1. Activate Virtual Environment

```bash
cd /home/baste/HA/aiohue
source /home/baste/HA/venv/bin/activate  # Adjust path to your venv
```

### 2. Discover Bridges

```bash
cd scripts
python3 discover-hue-bridges.py
```

This will scan your network and save bridge information to `bridges/config.json`.

### 3. Register with Bridges

```bash
python3 register-hue-user.py
```

Press the link button on each bridge when prompted. This adds V2 credentials to `bridges/config.json`.

### 4. Capture Inventory

```bash
python3 inventory-hue-bridge.py
```

Saves device inventory to `bridges/inventory/{BridgeName}-{BridgeID}.json`.

### 5. Capture Automations

```bash
python3 automation-hue-bridge.py
```

Saves automation data to `bridges/automations/{BridgeName}-{BridgeID}-automations.json`.

### 6. Query Data

```bash
# Search inventory
python3 query-hue-inventory.py --name "*Kitchen*" --type lights

# Search automations
python3 query-hue-automation.py --state enabled --type behavior_instances
```

## Project Structure

```text
aiohue/
├── README.md                                    # This file
├── docs/
│   ├── SCRIPTS.md                              # Detailed script documentation
│   ├── AUTOMATION_API_QUICK_REFERENCE.md       # V2 API automation reference
│   └── HUE_AUTOMATION_RESOURCES.md             # Detailed automation resource docs
├── scripts/
│   ├── discover-hue-bridges.py                 # Bridge discovery
│   ├── register-hue-user.py                    # V2 API registration
│   ├── inventory-hue-bridge.py                 # Capture device inventory
│   ├── automation-hue-bridge.py                # Capture automation data
│   ├── query-hue-inventory.py                  # Query inventory with filters
│   └── query-hue-automation.py                 # Query automations with filters
└── bridges/                                     # Generated data (not in git)
    ├── config.json                              # Bridge credentials
    ├── inventory/                               # Device inventories
    │   ├── {BridgeName}-{BridgeID}.json
    │   └── ...
    └── automations/                             # Automation data
        ├── {BridgeName}-{BridgeID}-automations.json
        └── ...
```

## Documentation

- **[docs/SCRIPTS.md](docs/SCRIPTS.md)** - Complete script documentation with usage examples
- **[docs/AUTOMATION_API_QUICK_REFERENCE.md](docs/AUTOMATION_API_QUICK_REFERENCE.md)** - V2 API automation endpoints and examples
- **[docs/HUE_AUTOMATION_RESOURCES.md](docs/HUE_AUTOMATION_RESOURCES.md)** - Deep dive into automation resource types

## Key Features

### Bridge Discovery & Registration

Automatically discovers bridges on your network and registers V2 API applications:

```bash
# Discover bridges
python3 discover-hue-bridges.py

# Register V2 credentials (username + client_key)
python3 register-hue-user.py
```

### Comprehensive Inventory Capture

Captures all bridge resources in a structured format:

- **Devices**: All hardware connected to the bridge
- **Lights**: Individual light controls and capabilities
- **Scenes**: Pre-configured lighting scenes
- **Groups**: Zones, rooms, and entertainment areas
- **Sensors**: Motion sensors, switches, buttons, etc.

Output: `bridges/inventory/{BridgeName}-{BridgeID}.json`

### Automation Data Capture

Extracts automation configurations:

- **Smart Scenes**: Time-based scheduled automations
- **Behavior Instances**: Active running automations
- **Behavior Scripts**: Available automation templates
- **Geofence Clients**: Location-based triggers
- **Geolocation**: Sun position and location data

Output: `bridges/automations/{BridgeName}-{BridgeID}-automations.json`

### Powerful Query Tools

Filter and search data with flexible options:

```bash
# Find all lights with "Kitchen" in the name
python3 query-hue-inventory.py --type lights --name "*Kitchen*"

# Show all enabled automations
python3 query-hue-automation.py --state enabled

# Get summary statistics
python3 query-hue-automation.py --summary

# Export to JSON for processing
python3 query-hue-inventory.py --bridge abc123def456 --json > devices.json
```

**Filter Options:**
- `--type` - Filter by resource type
- `--name` - Pattern matching with wildcards
- `--state` - Filter by state (on/off, enabled/disabled, brightness)
- `--bridge` - Query specific bridge
- `--json` - JSON output
- `--detailed` - Full attribute display
- `--summary` - Count statistics

## Security

**Important:** All generated JSON files contain sensitive information and are excluded from git via `.gitignore`:

- `bridges/config.json` - Contains bridge credentials (username, client_key)
- `bridges/inventory/*.json` - Device-specific data
- `bridges/automations/*.json` - Automation-specific data

Only Python scripts and documentation are tracked in version control.

## Use Cases

### Home Automation Integration

Use the inventory data to integrate bridges with Home Assistant, Node-RED, or custom automation platforms:

```bash
# Export all devices to JSON
python3 query-hue-inventory.py --type devices --json > ha_devices.json

# Get all sensors for integration
python3 query-hue-inventory.py --type sensors --detailed
```

### Automation Backup & Analysis

Back up and analyze existing automations:

```bash
# Capture current automations
python3 automation-hue-bridge.py

# Review all enabled automations
python3 query-hue-automation.py --state enabled --detailed

# Find specific automation
python3 query-hue-automation.py --name "*Wake*"
```

### Multi-Bridge Management

Manage multiple bridges with organized data:

```bash
# Query specific bridge
python3 query-hue-inventory.py --bridge abc123def456

# Compare bridges
python3 query-hue-inventory.py --summary
python3 query-hue-automation.py --summary
```

### Troubleshooting

Find issues with devices or automations:

```bash
# Find lights that are on
python3 query-hue-inventory.py --type lights --state on

# Check disabled automations
python3 query-hue-automation.py --state disabled

# Search for specific device
python3 query-hue-inventory.py --name "*sensor*" --detailed
```

## Development

### Virtual Environment Setup

The scripts automatically activate the virtual environment at `/home/baste/HA/venv/` if available. To set up your own:

```bash
python3 -m venv venv
source venv/bin/activate
pip install aiohue
```

### Data Structure

All JSON files follow a consistent structure:

**Inventory Files:**
```json
{
  "bridge_info": {
    "ip": "192.168.1.100",
    "captured_at": "2025-11-12T10:00:00",
    "config": { "bridge_id": "...", "name": "..." }
  },
  "resources": {
    "devices": { "count": 10, "items": [...] },
    "lights": { "count": 8, "items": [...] },
    ...
  }
}
```

**Automation Files:**
```json
{
  "bridge_info": { ... },
  "automations": {
    "smart_scenes": { "count": 2, "items": [...] },
    "behavior_instances": { "count": 5, "items": [...] },
    ...
  }
}
```

## Contributing

This is a personal project for managing Philips Hue bridges. Feel free to fork and adapt for your needs.

## License

See LICENSE file for details.

## Resources

- [aiohue Documentation](https://github.com/home-assistant-libs/aiohue)
- [Philips Hue API V2 Documentation](https://developers.meethue.com/develop/hue-api-v2/)
- [Home Assistant Hue Integration](https://www.home-assistant.io/integrations/hue/)
