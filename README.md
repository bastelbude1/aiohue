# Philips Hue Bridge Management & Home Assistant Integration

A comprehensive toolkit for managing Philips Hue bridges and integrating them with Home Assistant, featuring advanced scene validation, inventory management, and automation monitoring.

## Overview

This project provides two complementary subsystems:

### 1. Hue Bridge Management (Direct API)
Interact directly with Hue bridges using the aiohue library and Philips Hue API v2:
- **Discover bridges** on your network automatically
- **Register V2 API credentials** (username + client_key)
- **Capture complete inventories** (devices, lights, scenes, zones, sensors)
- **Export automation data** (smart scenes, behavior instances, scripts)
- **Query and filter** data with powerful search tools

### 2. Home Assistant Integration
Advanced integration features for reliability and monitoring:
- **Scene validation system** with 3-level escalation and fallback
- **HA inventory export** - Export Home Assistant's perspective of Hue entities
- **Inventory sync** - Keep bridge inventories available on HA server
- **Entity mapping** - Map between Hue resource IDs and HA entity_ids
- **Circuit breaker** - Automatic kill switch for runaway automations
- **Rate limiting** - Protect against rapid-fire validations

## Quick Start

### Hue Bridge Management

```bash
# 1. Discover bridges on your network
cd scripts
python3 discover-hue-bridges.py

# 2. Register with bridges (press button when prompted)
python3 register-hue-user.py

# 3. Capture bridge inventory
python3 inventory-hue-bridge.py

# 4. Query data
python3 query-hue-inventory.py --type lights --name "*Kitchen*"
```

### Home Assistant Integration

```bash
# 1. Create configuration file
cat > ha_config.json <<EOF
{
  "ha_host": "192.168.1.100",
  "ha_user": "hassio",
  "ha_ssh_key": "../homeassistant_ssh_key",
  "ha_inventory_dir": "/homeassistant/hue_inventories"
}
EOF

# 2. Sync inventories to HA server
./sync-inventory-to-ha.sh

# 3. Export HA perspective
export HA_SSH_HOST=192.168.1.100
python3 export-ha-hue-inventory.py

# 4. Deploy scene validator to AppDaemon (see docs)
```

## Features

### Hue Bridge Management
- ✅ Automatic bridge discovery (mDNS/SSDP)
- ✅ V2 API registration with credential management
- ✅ Complete inventory capture (devices, lights, scenes, zones, sensors)
- ✅ Automation export (smart scenes, behavior instances, scripts)
- ✅ Powerful query tools with filtering and pattern matching
- ✅ Multi-bridge support with organized data storage
- ✅ JSON and human-readable output formats

### Home Assistant Integration
- ✅ Scene validation with 3-level escalation
- ✅ Entity registry mapping (Hue resource ID ↔ HA entity_id)
- ✅ HA inventory export (SSH + API)
- ✅ Inventory sync to HA server
- ✅ Circuit breaker kill switch
- ✅ Per-scene and global rate limiting
- ✅ Flexible scene filtering (labels, patterns, UIDs)
- ✅ AppDaemon 4 integration

## Documentation

### Core Documentation
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System architecture, data flow, and design decisions
- **[HUE_BRIDGE_MANAGEMENT.md](docs/HUE_BRIDGE_MANAGEMENT.md)** - Complete guide for Hue bridge management
- **[HOME_ASSISTANT_INTEGRATION.md](docs/HOME_ASSISTANT_INTEGRATION.md)** - HA integration features and setup

### Additional Documentation
- **[SCRIPTS.md](docs/SCRIPTS.md)** - Detailed script reference
- **[SCENE_VALIDATION_IMPLEMENTATION.md](docs/SCENE_VALIDATION_IMPLEMENTATION.md)** - Scene validation system guide
- **[SCENE_VALIDATION_ANALYSIS.md](docs/SCENE_VALIDATION_ANALYSIS.md)** - Analysis of scene filtering approaches
- **[AUTOMATION_API_QUICK_REFERENCE.md](docs/AUTOMATION_API_QUICK_REFERENCE.md)** - Hue API v2 automation reference
- **[HUE_AUTOMATION_RESOURCES.md](docs/HUE_AUTOMATION_RESOURCES.md)** - Deep dive into automation resources

## Project Structure

```text
aiohue/
├── README.md                          # This file - Quick overview
├── LICENSE
├── .gitignore                         # Excludes all sensitive JSON files
│
├── docs/                              # Documentation
│   ├── ARCHITECTURE.md                # System architecture and design
│   ├── HUE_BRIDGE_MANAGEMENT.md       # Hue bridge management guide
│   ├── HOME_ASSISTANT_INTEGRATION.md  # HA integration guide
│   ├── SCRIPTS.md                     # Script reference
│   └── ...                            # Additional documentation
│
├── scripts/                           # Python scripts
│   ├── # Hue Bridge Management
│   ├── discover-hue-bridges.py        # Discover bridges on network
│   ├── register-hue-user.py           # Register V2 API credentials
│   ├── inventory-hue-bridge.py        # Capture device inventories
│   ├── automation-hue-bridge.py       # Capture automation data
│   ├── query-hue-inventory.py         # Query inventory data
│   ├── query-hue-automation.py        # Query automation data
│   │
│   ├── # Home Assistant Integration
│   ├── export-ha-hue-inventory.py     # Export HA entity registry
│   └── sync-inventory-to-ha.sh        # Sync inventories to HA
│
├── bridges/                           # Generated data (excluded from git)
│   ├── config.json                    # Bridge credentials
│   ├── inventory/                     # Hue perspective inventories
│   ├── automations/                   # Hue automation data
│   └── ha_inventory/                  # HA perspective inventories
│
├── ha_config.json                     # Local HA SSH config (excluded)
└── ha_config.example                  # Example config (template)
```

## Requirements

### Software
- Python 3.8 or higher
- aiohue library 4.8.0+
- Home Assistant 2024.1+ (for HA integration)
- AppDaemon 4.x (for scene validation)
- Bash shell (for sync script)

### Network
- Local network access to Hue bridges
- SSH access to Home Assistant server (for HA integration)

### Optional
- Virtual environment (recommended)
- SSH key for HA access

## Security

**All sensitive data is excluded from git:**

```gitignore
# Credentials and sensitive data
*.json                    # All bridge and inventory data
bridges/config.json       # Bridge credentials
ha_config.json           # Local HA SSH configuration

# SSH keys
*_ssh_key
*_ssh_key.pub
*.pem

# Generated data directories
bridges/inventory/
bridges/automations/
bridges/ha_inventory/
```

**Safe to commit:**
- Python scripts (after sanitization)
- Documentation files
- Example configuration files (no real data)
- .gitignore itself

See [ARCHITECTURE.md](docs/ARCHITECTURE.md#security-model) for detailed security model.

## Common Use Cases

### Managing Multiple Hue Bridges
```bash
# Discover all bridges
python3 discover-hue-bridges.py

# Capture inventories from all bridges
python3 inventory-hue-bridge.py

# Query specific bridge
python3 query-hue-inventory.py --bridge abc123def456 --summary
```

### Regular Backups
```bash
# Capture current state
python3 inventory-hue-bridge.py --json
python3 automation-hue-bridge.py --json

# Archive with timestamp
tar -czf hue_backup_$(date +%Y%m%d).tar.gz bridges/
```

### Scene Validation in Home Assistant
```bash
# 1. Sync inventories to HA
./sync-inventory-to-ha.sh

# 2. Deploy scene validator (see HOME_ASSISTANT_INTEGRATION.md)
# 3. Add label 'validate_scenes' to important scenes
# 4. Scenes are automatically validated on activation
```

### Troubleshooting Lights
```bash
# Find lights that are off
python3 query-hue-inventory.py --type lights --state off

# Find dim lights
python3 query-hue-inventory.py --type lights --state 20

# Detailed info for specific light
python3 query-hue-inventory.py --name "*Problem*" --detailed
```

## Getting Started

### New Users
1. Read [ARCHITECTURE.md](docs/ARCHITECTURE.md) for system overview
2. Follow [HUE_BRIDGE_MANAGEMENT.md](docs/HUE_BRIDGE_MANAGEMENT.md) for bridge setup
3. (Optional) Follow [HOME_ASSISTANT_INTEGRATION.md](docs/HOME_ASSISTANT_INTEGRATION.md) for HA integration

### Quick Reference
- **Discover bridges**: `python3 discover-hue-bridges.py`
- **Register credentials**: `python3 register-hue-user.py`
- **Capture inventory**: `python3 inventory-hue-bridge.py`
- **Query data**: `python3 query-hue-inventory.py --help`
- **Sync to HA**: `./sync-inventory-to-ha.sh`
- **Export HA data**: `python3 export-ha-hue-inventory.py`

## Contributing

This is a personal project for managing Philips Hue bridges and integrating with Home Assistant. You're welcome to adapt this toolkit for your own smart home setup or contribute improvements.

## Resources

- [aiohue Documentation](https://github.com/home-assistant-libs/aiohue)
- [Philips Hue API V2 Documentation](https://developers.meethue.com/develop/hue-api-v2/)
- [Home Assistant Hue Integration](https://www.home-assistant.io/integrations/hue/)
- [AppDaemon Documentation](https://appdaemon.readthedocs.io/)

## License

See LICENSE file for details.
