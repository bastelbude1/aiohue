# Architecture Overview

This document describes the system architecture, data flow, and design decisions for the Philips Hue Bridge Management and Home Assistant Integration toolkit.

## Table of Contents

- [System Overview](#system-overview)
- [Architecture Principles](#architecture-principles)
- [Component Architecture](#component-architecture)
- [Data Flow](#data-flow)
- [File Structure](#file-structure)
- [Security Model](#security-model)
- [Integration Patterns](#integration-patterns)

---

## System Overview

This toolkit provides a comprehensive solution for managing Philips Hue bridges and integrating them with Home Assistant. It consists of two main subsystems:

### 1. Hue Bridge Management (Direct API)
- **Purpose**: Interact directly with Hue bridges using aiohue library
- **API**: Philips Hue API v2
- **Environment**: Local development machine (BastelBude)
- **Use Cases**: Bridge discovery, registration, inventory capture, automation analysis

### 2. Home Assistant Integration
- **Purpose**: Integrate Hue bridges with Home Assistant ecosystem
- **Components**: Scene validation, inventory export, automation monitoring
- **Environment**: Home Assistant server (192.168.188.42)
- **Use Cases**: Scene validation, entity mapping, automation reliability

### System Diagram

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Local Development Machine                     │
│                         (BastelBude)                             │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           Hue Bridge Management Scripts                 │    │
│  │                                                          │    │
│  │  • discover-hue-bridges.py                              │    │
│  │  • register-hue-user.py                                 │    │
│  │  • inventory-hue-bridge.py                              │    │
│  │  • automation-hue-bridge.py                             │    │
│  │  • query-hue-inventory.py                               │    │
│  │  • query-hue-automation.py                              │    │
│  │                                                          │    │
│  │  → aiohue library → Direct Hue API v2 calls            │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↓                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                 Generated Data Files                    │    │
│  │                                                          │    │
│  │  bridges/config.json         (credentials)              │    │
│  │  bridges/inventory/*.json    (device data)              │    │
│  │  bridges/automations/*.json  (automation data)          │    │
│  │                                                          │    │
│  │  → Excluded from git (sensitive data)                  │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↓                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │          Home Assistant Integration Scripts             │    │
│  │                                                          │    │
│  │  • export-ha-hue-inventory.py  (SSH → HA perspective)  │    │
│  │  • sync-inventory-to-ha.sh     (Copy to HA server)     │    │
│  │                                                          │    │
│  │  → SSH + HA API → Query HA entity registry            │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↓ SSH                                │
└─────────────────────────────┼────────────────────────────────────┘
                              ↓
┌─────────────────────────────┼────────────────────────────────────┐
│                             ↓                                     │
│                 Home Assistant Server                            │
│                    (192.168.188.42)                              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Inventory Data Storage                     │    │
│  │                                                          │    │
│  │  /homeassistant/hue_inventories/                       │    │
│  │    Bridge_Name-abc123.json  (Hue perspective)          │    │
│  │    ha_Bridge_Name-abc123.json  (HA perspective)        │    │
│  │                                                          │    │
│  │  → Used by AppDaemon for validation                    │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↓                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         AppDaemon Scene Validation System               │    │
│  │                                                          │    │
│  │  /addon_configs/a0d7b954_appdaemon/apps/               │    │
│  │    scene_validator.py                                   │    │
│  │    apps.yaml                                            │    │
│  │                                                          │    │
│  │  Features:                                               │    │
│  │  • Scene validation with 3-level escalation             │    │
│  │  • Entity registry mapping (Hue ID → HA entity_id)     │    │
│  │  • Rate limiting (per-scene + global)                   │    │
│  │  • Circuit breaker kill switch                          │    │
│  │  • Pattern-based scene filtering                        │    │
│  │                                                          │    │
│  │  → Listens to scene activation events                  │    │
│  │  → Validates scenes against Hue inventories            │    │
│  │  → Falls back to individual light control              │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↑                                     │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              Home Assistant Core                        │    │
│  │                                                          │    │
│  │  • Hue Integration (native)                             │    │
│  │  • Entity Registry                                      │    │
│  │  • Event Bus (scene activation)                         │    │
│  │  • State Machine                                        │    │
│  │                                                          │    │
│  └────────────────────────────────────────────────────────┘    │
│                            ↑                                     │
└─────────────────────────────┼────────────────────────────────────┘
                              ↑
                              │
                    Network (Local LAN)
                              │
                              ↑
┌─────────────────────────────┼────────────────────────────────────┐
│                  Philips Hue Bridges (2x)                        │
│                                                                  │
│  • Bridge EG    (00:17:88:b3:e3:55)                             │
│  • Bridge OG    (c4:29:96:67:24:91)                             │
│                                                                  │
│  API v2: Devices, Lights, Scenes, Zones, Sensors, Automations  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Architecture Principles

### 1. Separation of Concerns

**Hue Management ≠ HA Integration**

- **Hue scripts** operate independently, directly querying bridges
- **HA scripts** operate via SSH/API, querying HA perspective
- Both perspectives are complementary and provide different views

### 2. Data Locality

**Where Data Lives:**

- **Bridge credentials** (`bridges/config.json`): Local development machine only
- **Hue inventories** (`bridges/inventory/*.json`): Local + synced to HA server
- **HA inventories** (`bridges/ha_inventory/*.json`): Generated on HA server
- **Scene validator** (`scene_validator.py`): Runs on HA server in AppDaemon

### 3. Security by Design

**Sensitive Data Protection:**

- All JSON files excluded from git via `.gitignore`
- SSH keys with proper permissions (600)
- Environment variable validation (command injection prevention)
- Configuration files (local only) vs example files (committed)

### 4. Fail-Safe Operation

**Graceful Degradation:**

- Scene validation has 3-level escalation (validate → retry → fallback)
- Circuit breaker prevents runaway automation
- Rate limiting protects against rapid-fire changes
- Unavailable lights are skipped (not failed)

### 5. Observability

**Debugging and Monitoring:**

- Structured logging with severity levels
- JSON output mode for all scripts (machine-readable)
- Detailed error messages with actionable guidance
- State tracking and metrics

---

## Component Architecture

### Hue Bridge Management Layer

**Components:**
1. **Bridge Discovery** (`discover-hue-bridges.py`)
   - mDNS/SSDP discovery
   - API version detection
   - Saves to `bridges/config.json`

2. **Registration** (`register-hue-user.py`)
   - V2 API application registration
   - Generates username + client_key
   - Updates `bridges/config.json`

3. **Inventory Capture** (`inventory-hue-bridge.py`)
   - Queries all V2 API resources
   - Structured JSON output
   - Saves to `bridges/inventory/{Name}-{ID}.json`

4. **Automation Capture** (`automation-hue-bridge.py`)
   - Extracts smart scenes, behavior instances, scripts
   - Geofence and geolocation data
   - Saves to `bridges/automations/{Name}-{ID}-automations.json`

5. **Query Tools** (`query-hue-inventory.py`, `query-hue-automation.py`)
   - Filtering, searching, pattern matching
   - Multiple output formats (human, JSON, detailed)
   - Summary statistics

**Technology Stack:**
- Language: Python 3.8+
- Library: aiohue 4.8.0+
- API: Philips Hue API v2 (REST + SSE)

### Home Assistant Integration Layer

**Components:**

1. **HA Inventory Export** (`export-ha-hue-inventory.py`)
   - SSH to HA server
   - Query entity registry, device registry, config entries
   - Export HA perspective of Hue entities
   - Saves to `bridges/ha_inventory/ha_{Name}-{ID}.json`

2. **Inventory Sync** (`sync-inventory-to-ha.sh`)
   - Captures fresh Hue inventories
   - Copies to HA server via SCP
   - Verifies successful transfer
   - Destination: `/homeassistant/hue_inventories/`

3. **Scene Validator** (`scene_validator.py` - AppDaemon)
   - Listens to scene activation events
   - Maps HA entities to Hue resources via unique_id
   - Validates scenes against inventories
   - 3-level escalation with fallback
   - Circuit breaker and rate limiting

**Technology Stack:**
- Language: Python 3.12
- Framework: AppDaemon 4.x (synchronous)
- APIs: Home Assistant REST API, AppDaemon API
- Transport: SSH (secure remote access)

---

## Data Flow

### Flow 1: Initial Setup

```text
1. Discover Bridges
   discover-hue-bridges.py
   ↓
   bridges/config.json (created)

2. Register Applications
   register-hue-user.py
   ↓
   bridges/config.json (credentials added)

3. Capture Inventories
   inventory-hue-bridge.py
   ↓
   bridges/inventory/*.json (created)

4. Sync to HA
   sync-inventory-to-ha.sh
   ↓
   HA server: /homeassistant/hue_inventories/*.json

5. Deploy Scene Validator
   (Manual: Copy scene_validator.py to AppDaemon)
   ↓
   AppDaemon: scene_validator.py running
```

### Flow 2: Scene Validation Runtime

```text
1. User activates scene in Home Assistant
   ↓
2. HA fires event: call_service (scene.turn_on)
   ↓
3. AppDaemon scene_validator receives event
   ↓
4. Check scene filtering rules
   • Labels (include/exclude)
   • Name patterns (regex)
   • UID exclusions
   ↓
   [SKIP if filtered out]
   ↓
5. Check rate limits
   • Per-scene: 5 validations/minute
   • Global: 20 validations/minute
   ↓
   [SKIP if rate limited]
   ↓
6. Check circuit breaker state
   • CLOSED: Normal operation
   • HALF_OPEN: Testing after failures
   • OPEN: Kill switch activated
   ↓
   [SKIP if circuit open]
   ↓
7. Wait for transition delay (default: 5s)
   ↓
8. LEVEL 1: Validate Scene
   • Query HA scene state
   • Extract expected light states from scene
   • For each light:
     - Map HA entity_id → Hue resource ID (via unique_id)
     - Compare current state vs expected state
     - Check: on/off, brightness, color
   ↓
   [SUCCESS: All lights match] → DONE
   ↓
   [FAILURE: Some lights don't match]
   ↓
9. LEVEL 2: Re-trigger Scene
   • Call scene.turn_on again
   • Wait transition_delay
   • Re-validate
   ↓
   [SUCCESS: All lights match] → DONE
   ↓
   [FAILURE: Still don't match]
   ↓
10. LEVEL 3: Individual Light Fallback
    • For each failed light:
      - Set state individually via light.turn_on
      - Apply expected brightness/color
    • Final validation
    ↓
    [SUCCESS] → Close circuit (if half-open)
    ↓
    [FAILURE] → Open circuit (kill switch)
```

### Flow 3: Inventory Update Cycle

```text
1. Hue bridge configuration changes
   (new device added, scene modified, etc.)
   ↓
2. Capture fresh inventory
   cd scripts && python3 inventory-hue-bridge.py
   ↓
3. Sync to HA
   ./sync-inventory-to-ha.sh
   ↓
4. Scene validator automatically picks up changes
   (reads inventories on each validation)
```

### Flow 4: HA Inventory Export (HA Perspective)

```text
1. SSH to HA server
   ↓
2. Query HA storage files
   • /homeassistant/.storage/core.config_entries
   • /homeassistant/.storage/core.entity_registry
   • /homeassistant/.storage/core.device_registry
   ↓
3. Query HA API for current states (optional)
   • GET /api/states
   ↓
4. Filter Hue entities
   • Match platform=hue
   • Match config_entry_id to bridge
   ↓
5. Enrich with device info
   • Manufacturer, model, MAC address
   • Software version
   ↓
6. Group by entity type
   • light.*, sensor.*, switch.*, etc.
   ↓
7. Export to JSON
   bridges/ha_inventory/ha_{Name}-{ID}.json
```

---

## File Structure

```text
aiohue/
│
├── README.md                              # Short intro, links to detailed docs
├── LICENSE
├── .gitignore                             # Excludes all *.json files
│
├── docs/
│   ├── ARCHITECTURE.md                    # This file
│   ├── HUE_BRIDGE_MANAGEMENT.md           # Hue-specific functionality
│   ├── HOME_ASSISTANT_INTEGRATION.md      # HA integration features
│   ├── SCRIPTS.md                         # Legacy script documentation
│   ├── SCENE_VALIDATION_IMPLEMENTATION.md # Scene validator implementation guide
│   ├── SCENE_VALIDATION_ANALYSIS.md       # Scene filtering approach analysis
│   ├── AUTOMATION_API_QUICK_REFERENCE.md  # Hue API v2 automation reference
│   └── HUE_AUTOMATION_RESOURCES.md        # Hue automation resource details
│
├── scripts/
│   │
│   ├── # Hue Bridge Management (Direct API)
│   ├── discover-hue-bridges.py           # Find bridges on network
│   ├── register-hue-user.py              # Register V2 API credentials
│   ├── inventory-hue-bridge.py           # Capture device inventories
│   ├── automation-hue-bridge.py          # Capture automation data
│   ├── query-hue-inventory.py            # Query/filter inventory data
│   ├── query-hue-automation.py           # Query/filter automation data
│   │
│   ├── # Home Assistant Integration
│   ├── export-ha-hue-inventory.py        # Export HA entity registry data
│   └── sync-inventory-to-ha.sh           # Sync inventories to HA server
│
├── bridges/                               # Generated data (excluded from git)
│   ├── config.json                        # Bridge credentials
│   ├── inventory/                         # Hue perspective inventories
│   │   ├── {BridgeName}-{BridgeID}.json
│   │   └── ...
│   ├── automations/                       # Hue automation data
│   │   ├── {BridgeName}-{BridgeID}-automations.json
│   │   └── ...
│   └── ha_inventory/                      # HA perspective inventories
│       ├── ha_{BridgeName}-{BridgeID}.json
│       └── ...
│
├── ha_config.json                         # Local HA SSH config (excluded from git)
└── ha_config.example                      # Example config (committed)
```

### Data File Naming Conventions

**Hue Inventories:**
```
bridges/inventory/{BridgeName}-{BridgeID}.json
Example: Bridge_EG-001788b3e355.json
```

**Hue Automations:**
```
bridges/automations/{BridgeName}-{BridgeID}-automations.json
Example: Bridge_EG-001788b3e355-automations.json
```

**HA Inventories:**
```
bridges/ha_inventory/ha_{BridgeName}-{BridgeID}.json
Example: ha_Bridge_EG-001788b3e355.json
```

**Filename Sanitization:**
- Colons removed/replaced with underscores
- Spaces replaced with underscores
- Cross-platform compatibility (Windows, Linux, macOS)

---

## Security Model

### Threat Model

**Assets to Protect:**
1. Hue bridge credentials (username, client_key)
2. Home Assistant API tokens
3. SSH private keys
4. Network topology information (IPs, MACs)
5. Personal information (device names, locations)

**Attack Vectors:**
1. Git repository exposure (accidental commit of secrets)
2. Command injection via environment variables
3. Unauthorized access to HA server
4. Man-in-the-middle on local network

### Security Controls

#### 1. Git Protection

**.gitignore Rules:**
```gitignore
# Sensitive data and credentials
*.json                    # All bridge data

# SSH keys
*.pem
*_ssh_key
*_ssh_key.pub

# Configuration files
ha_config.json            # Local HA config
bridges/config.json       # Bridge credentials

# Generated data
bridges/inventory/
bridges/automations/
bridges/ha_inventory/
```

**Safe to Commit:**
- Python scripts (after sanitization)
- Documentation files
- Example configuration files (no real data)
- .gitignore itself

#### 2. Input Validation

**SSH Host Validation** (`export-ha-hue-inventory.py`):
```python
def _validate_ssh_host(host: str) -> str:
    """Prevent command injection via hostname."""
    if not re.match(r'^[\w\.\-\[\]:]+$', host):
        print(f"Error: Invalid hostname format", file=sys.stderr)
        sys.exit(1)
    return host
```

**Allowed Characters:**
- Alphanumeric: `a-z A-Z 0-9 _`
- DNS/IP: `. - :`
- IPv6: `[ ]`

**Blocked Characters:**
- Shell metacharacters: `; | & $ ( ) < > \`
- Quotes: `' "`
- Wildcards: `* ?`

#### 3. SSH Security

**Key Management:**
- Private keys: 600 permissions (owner read/write only)
- Stored outside repository (or .gitignored)
- Relative path resolution (supports absolute paths)

**SSH Configuration:**
```bash
# Secure SSH invocation
ssh -i "${HA_SSH_KEY}" "${HA_SSH_USER}@${HA_SSH_HOST}" "command"

# SCP with same key
scp -i "${HA_SSH_KEY}" source "${HA_SSH_USER}@${HA_SSH_HOST}:dest"
```

#### 4. Configuration Management

**Separation:**
- **Local config** (`ha_config.json`): Real values, .gitignored
- **Example config** (`ha_config.example`): Placeholders, committed

**Example:**
```json
{
  "ha_host": "192.168.1.100",           // Generic example
  "ha_user": "hassio",
  "ha_ssh_key": "../homeassistant_ssh_key",
  "ha_inventory_dir": "/homeassistant/hue_inventories"
}
```

#### 5. API Security

**Home Assistant API:**
- Token stored on HA server only (`/data/.ha_token`)
- Never transmitted to local machine
- Used via SSH tunnel for commands

**Hue API:**
- Credentials stored in local `bridges/config.json`
- HTTPS communication (TLS 1.2+)
- Client key for encryption

### Security Best Practices

**Before Committing:**
```bash
# Check for sensitive data
git diff --cached | grep -iE "192\.168\.|00:17:88|c4:29:96|password|token|key"

# Verify no JSON files staged
git ls-files --cached | grep '\.json$'

# Review all changes
git diff --cached
```

**Data Sanitization:**
- Replace real IPs with `192.168.1.100`
- Replace real bridge IDs with `abc123def456`
- Replace personal names with `Bridge_Office`, `Bridge_Living`
- Use relative paths, not absolute user-specific paths

---

## Integration Patterns

### Pattern 1: Two-Perspective Inventory

**Problem:** Hue API and HA have different views of the same devices.

**Solution:** Maintain both perspectives:

**Hue Perspective** (`inventory-hue-bridge.py`):
```json
{
  "resources": {
    "lights": {
      "items": [
        {
          "id": "abc123-def4-5678-90ab-cdef12345678",
          "type": "light",
          "metadata": { "name": "Kitchen Light" },
          "on": { "on": true },
          "dimming": { "brightness": 80.0 }
        }
      ]
    }
  }
}
```

**HA Perspective** (`export-ha-hue-inventory.py`):
```json
{
  "resources": {
    "light": {
      "items": [
        {
          "entity_id": "light.kitchen_light",
          "unique_id": "abc123-def4-5678-90ab-cdef12345678",
          "name": "Kitchen Light",
          "area_id": "kitchen",
          "device_info": { ... }
        }
      ]
    }
  }
}
```

**Mapping:** `unique_id` links both perspectives (Hue resource ID)

### Pattern 2: Entity Registry Mapping

**Problem:** HA entity_ids are user-customizable and don't match Hue resource IDs.

**Solution:** Use `unique_id` as stable identifier:

```python
def get_entity_id_from_hue_id(self, hue_resource_id):
    """Map Hue resource ID to HA entity_id via unique_id."""
    entities = self.get_state('light')
    for entity_id in entities.keys():
        unique_id = self.get_state(entity_id, attribute='unique_id')
        if unique_id == hue_resource_id:
            return entity_id
    return None
```

**Benefits:**
- Survives entity_id renames
- Works across HA reinstalls
- Stable even if device names change

### Pattern 3: 3-Level Escalation

**Problem:** Scene validation might fail due to transient issues.

**Solution:** Progressive escalation with fallback:

```text
LEVEL 1: Validate only
  → Check if lights match expected state
  → Fast, non-intrusive
  → SUCCESS: Done
  → FAILURE: Continue to Level 2

LEVEL 2: Re-trigger scene
  → Maybe Zigbee message was lost
  → Give scene another chance
  → SUCCESS: Done
  → FAILURE: Continue to Level 3

LEVEL 3: Individual light control
  → Bypass scene, control lights directly
  → Ensures desired state is achieved
  → SUCCESS: Done (but investigate why scene failed)
  → FAILURE: Open circuit breaker (critical issue)
```

**Benefits:**
- Resilient to network glitches
- Minimizes false positives
- Provides fallback for reliability

### Pattern 4: Circuit Breaker Kill Switch

**Problem:** Runaway automation could cause infinite loops or rapid-fire changes.

**Solution:** Circuit breaker with three states:

```text
CLOSED (Normal Operation)
  ↓
  Validation failures ≥ threshold
  ↓
OPEN (Kill Switch Activated)
  ↓
  After cooldown period
  ↓
HALF_OPEN (Testing)
  ↓
  Next validation succeeds
  ↓
CLOSED (Normal Operation)

  OR

  Next validation fails
  ↓
OPEN (Back to kill switch)
```

**Configuration:**
```yaml
circuit_breaker:
  failure_threshold: 5        # Open after 5 failures
  success_threshold: 2        # Close after 2 successes in half-open
  timeout: 300                # 5 minutes cooldown
```

**Benefits:**
- Prevents runaway automation
- Automatic recovery after cooldown
- Logs incidents for debugging

### Pattern 5: Rate Limiting

**Problem:** Rapid scene changes could overwhelm system or hit API rate limits.

**Solution:** Two-tier rate limiting:

**Per-Scene Rate Limiting:**
```python
scene_rate_limits = {
    "scene.kitchen_bright": deque(maxlen=5),  # Track last 5 validations
    # Max 5 validations per minute per scene
}
```

**Global Rate Limiting:**
```python
global_validations = deque(maxlen=20)  # Track last 20 validations
# Max 20 validations per minute total
```

**Benefits:**
- Prevents hammering single scene
- Protects overall system performance
- Fair resource allocation across scenes

---

## Summary

This architecture provides:

1. **Separation of Concerns**: Hue management vs HA integration
2. **Data Locality**: Right data in the right place
3. **Security by Design**: Multiple layers of protection
4. **Fail-Safe Operation**: Graceful degradation and recovery
5. **Observability**: Logging, metrics, debugging tools
6. **Integration Patterns**: Proven solutions for common problems

The system is designed to be:
- **Reliable**: Multiple fallback mechanisms
- **Secure**: No secrets in git, input validation, secure transport
- **Maintainable**: Clear separation, good documentation
- **Observable**: Comprehensive logging and error reporting
- **Extensible**: Easy to add new scripts or features

---

## Next Steps

- **For Hue bridge management**: See [HUE_BRIDGE_MANAGEMENT.md](HUE_BRIDGE_MANAGEMENT.md)
- **For Home Assistant integration**: See [HOME_ASSISTANT_INTEGRATION.md](HOME_ASSISTANT_INTEGRATION.md)
- **For scene validation details**: See [SCENE_VALIDATION_IMPLEMENTATION.md](SCENE_VALIDATION_IMPLEMENTATION.md)
- **For script reference**: See [SCRIPTS.md](SCRIPTS.md)
