# Bridges Configuration Directory

This directory stores sensitive configuration and generated data for Philips Hue bridges.

## ⚠️ SECURITY WARNING

**ALL files in this directory (except this README) are excluded from git via `.gitignore`.**

**NEVER commit the actual configuration or data files to git!**

## Directory Structure

```
bridges/
├── README.md                    # This file (tracked in git)
├── config.json                  # Bridge credentials (NEVER commit!)
├── inventory/                   # aiohue device inventories (NEVER commit!)
│   ├── BridgeName-BridgeID.json
│   └── ...
├── ha_inventory/                # Home Assistant Hue inventories (NEVER commit!)
│   ├── ha_BridgeName-BridgeID.json
│   └── ...
└── automations/                 # Automation data (NEVER commit!)
    ├── BridgeName-BridgeID-automations.json
    └── ...
```

## Configuration Files

### `config.json` - Bridge Credentials

**Status:** 🔴 SENSITIVE - NEVER COMMIT

Contains bridge registration data including usernames and client keys.

**Created by:** `discover-hue-bridges.py` and `register-hue-user.py`

**Format:**
```json
{
  "discovered": "YYYY-MM-DD",
  "timestamp": "YYYY-MM-DDTHH:MM:SS",
  "count": 2,
  "bridges": [
    {
      "id": "bridge_id",
      "ip": "192.168.1.100",
      "api_version": "v2",
      "registered": true,
      "username": "api_username",
      "client_key": "client_key_value"
    }
  ]
}
```

**Security:** Contains API credentials for bridge access. Protected by `.gitignore`.

### `inventory/` - Device Inventories

**Status:** 🔴 SENSITIVE - NEVER COMMIT

Contains complete device inventories from each bridge including:
- All connected devices
- Light configurations
- Scenes
- Groups (zones, rooms)
- Sensors

**Created by:** `inventory-hue-bridge.py`

**Queried by:** `query-hue-inventory.py`

**Why excluded:** Contains personal device names, room layouts, and network topology.

### `automations/` - Automation Data

**Status:** 🔴 SENSITIVE - NEVER COMMIT

Contains automation configurations from each bridge including:
- Smart scenes with schedules
- Behavior instances (active automations)
- Behavior scripts (templates)
- Geofence clients
- Geolocation data

**Created by:** `automation-hue-bridge.py`

**Queried by:** `query-hue-automation.py`

**Why excluded:** Contains personal automation schedules, routines, and home patterns.

### `ha_inventory/` - Home Assistant Hue Integration Inventories

**Status:** 🔴 SENSITIVE - NEVER COMMIT

Contains Hue device inventories from the Home Assistant integration perspective, including:
- Entity IDs (HA namespace)
- Device configurations and capabilities
- Area assignments (HA rooms)
- User customizations (friendly names, etc.)
- Entity registry data
- Optionally: current entity states

**Created by:** `export-ha-hue-inventory.py`

**Purpose:** Provides a complementary view to aiohue inventories:
- **aiohue inventories:** Direct Hue API v2 resources (technical, low-level, bridge perspective)
- **HA inventories:** Home Assistant integration perspective (entity IDs, areas, user customization)

**Format:**
```json
{
  "metadata": {
    "source": "home_assistant",
    "ha_version": "2025.11.1",
    "exported_at": "timestamp"
  },
  "bridge_info": {
    "title": "Bridge_Name",
    "unique_id": "abc123def456",
    "host": "192.168.1.100"
  },
  "resources": {
    "light": {"count": X, "items": [...]},
    "sensor": {"count": X, "items": [...]},
    "scene": {"count": X, "items": [...]}
  }
}
```

**Why excluded:** Contains personal device names, room layouts, entity customizations, and integration data.

**Comparison with aiohue inventories:**
- **Use aiohue inventories** for: Technical specs, Hue-native resource IDs, direct API development
- **Use HA inventories** for: Home Assistant automation development, entity ID mapping, area assignments

## Setup Instructions

### First Time Setup

1. **Discover bridges:**
   ```bash
   cd scripts
   python3 discover-hue-bridges.py
   ```
   This creates `bridges/config.json` with discovered bridge information.

2. **Register with bridges:**
   ```bash
   python3 register-hue-user.py
   ```
   Press the link button on each bridge when prompted. This adds credentials to `config.json`.

3. **Capture inventory (optional):**
   ```bash
   python3 inventory-hue-bridge.py
   ```
   Creates `bridges/inventory/` with device data.

4. **Capture automations (optional):**
   ```bash
   python3 automation-hue-bridge.py
   ```
   Creates `bridges/automations/` with automation data.

5. **Export Home Assistant Hue inventory (optional):**
   ```bash
   # Set your HA host
   export HA_SSH_HOST="your-ha-host"
   python3 export-ha-hue-inventory.py
   ```
   Creates `bridges/ha_inventory/` with HA integration perspective.
   Requires SSH access to Home Assistant server (configure HA_SSH_HOST).

### Backup Recommendation

Since these files are excluded from git, create regular backups:

```bash
# Backup bridges directory (locally only!)
tar -czf aiohue-bridges-backup-$(date +%Y%m%d).tar.gz bridges/

# Store in secure location
mv aiohue-bridges-backup-*.tar.gz ~/secure-backups/
```

**⚠️ NEVER commit backups to git or upload to public cloud storage!**

## Security Best Practices

1. **Never share:** Don't share files from this directory with others
2. **No screenshots:** Don't post screenshots containing data from these files
3. **Local only:** Keep backups on encrypted local storage
4. **Regular rotation:** Re-register bridges periodically to rotate credentials
5. **Check .gitignore:** Verify `.gitignore` excludes all sensitive files before committing

## Verification

Check that no sensitive files are tracked:

```bash
# Should return nothing
git ls-files bridges/ | grep -v README.md

# Verify .gitignore works
git status bridges/
# Should show "nothing to commit" even with files present
```

## Recovery

If you accidentally commit sensitive files:

1. **DO NOT** just delete and recommit (data remains in history)
2. Stop using those credentials immediately
3. Re-register all bridges to get new credentials
4. Clean git history with `git filter-branch` or BFG Repo-Cleaner
5. Force push cleaned history
6. Verify old credentials no longer work

## Support

For issues or questions, see the main repository documentation.

**Remember: This directory contains your bridge credentials and personal device data. Treat it like a password file!**
