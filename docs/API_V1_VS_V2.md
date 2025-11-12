# Philips Hue API: V1 vs V2 Comparison

## Why We Need Both APIs

This document explains why some scripts use V2 API while credential management requires V1 API.

---

## API Architecture Overview

### V2 API (Modern - 2020+)
**Used by:** inventory-hue-bridge.py, automation-hue-bridge.py

**Available endpoints:**
- ✅ `/clip/v2/resource/light` - Light control
- ✅ `/clip/v2/resource/device` - Device information
- ✅ `/clip/v2/resource/scene` - Scene management
- ✅ `/clip/v2/resource/room` - Rooms and zones
- ✅ `/clip/v2/resource/grouped_light` - Group control
- ✅ `/clip/v2/resource/behavior_instance` - Automations
- ✅ `/clip/v2/resource/smart_scene` - Smart scenes
- ❌ **NO user/whitelist management**

**Characteristics:**
- Event streaming (SSE)
- Resource-based architecture
- Better performance
- Typed responses
- Focus on **functionality**, not administration

---

### V1 API (Legacy - 2012+)
**Used by:** All credential deletion scripts

**Available endpoints:**
- ✅ `/api/{username}/lights` - Basic light control (on/off, brightness, color)
- ✅ `/api/{username}/groups` - Group/room control
- ✅ `/api/{username}/scenes` - Basic scenes (static only)
- ✅ `/api/{username}/sensors` - Sensor data
- ✅ `/api/{username}/schedules` - Time-based schedules
- ✅ `/api/{username}/rules` - Basic automation rules
- ✅ `/api/{username}/config` - **Bridge configuration**
- ✅ `/api/{username}/config/whitelist` - **User management**
- ✅ User creation, deletion, listing

**V2-exclusive features NOT in V1:**
- ❌ `behavior_instance` - Advanced automations
- ❌ `smart_scene` - Dynamic/adaptive scenes
- ❌ Entertainment API v2 - Gradient zone controls
- ❌ Event streaming (SSE) - Real-time updates
- ❌ Resource-based architecture - Richer metadata

**Characteristics:**
- Polling-based (no event streaming)
- Flat JSON structure
- Includes **administrative functions** (V2 doesn't)
- Still fully supported but missing modern features

---

## Key Difference: User Management

### Whitelist Access (User Management)

**V1 API:**
```bash
# List all registered users
GET https://{bridge_ip}/api/{username}/config

Response includes:
{
  "whitelist": {
    "username1": {
      "name": "MyApp#Device",
      "create date": "2025-11-12T10:00:00",
      "last use date": "2025-11-12T15:00:00"
    },
    ...
  }
}

# Delete a user
DELETE https://{bridge_ip}/api/{username}/config/whitelist/{target_user}
```

**V2 API:**
```bash
# NO EQUIVALENT ENDPOINT
# User management is NOT exposed in V2 API
```

---

## Why This Design?

**Philips' Security Decision:**

1. **V2 API = Application Functionality**
   - Apps should control lights, scenes, automations
   - Apps should NOT manage other apps' access
   - Separation of concerns

2. **V1 API = Administrative Tasks**
   - User management is administrative
   - Kept in V1 for backward compatibility
   - Requires explicit bridge button press for new users

3. **Security Benefit:**
   - An app cannot delete other apps' credentials via V2
   - Compromised V2 credentials can't revoke all access
   - Administrative functions isolated in V1

---

## Script Requirements

| Script | API | Why |
|--------|-----|-----|
| `inventory-hue-bridge.py` | V2 | Needs lights, devices, scenes |
| `automation-hue-bridge.py` | V2 | Needs automations, smart scenes |
| `query-hue-inventory.py` | N/A | Reads JSON files |
| `query-hue-automation.py` | N/A | Reads JSON files |
| `delete-bridge-credentials.sh` | V1 | **Needs whitelist access** |
| `delete-specific-credentials.sh` | V1 | **Needs whitelist access** |
| `register-hue-user.py` | V1 | Creates new users |

---

## Technical Implementation

### Getting Light Data (V2 Works Fine)
```python
from aiohue.v2 import HueBridgeV2

bridge = HueBridgeV2(bridge_ip, username)
await bridge.initialize()

# V2 API provides typed access
lights = bridge.lights.items  # ✅ Works
devices = bridge.devices.items  # ✅ Works
scenes = bridge.scenes.scene.items  # ✅ Works
```

### Getting User List (Must Use V1)
```python
# V2 doesn't have this
# bridge.users.items  # ❌ Does not exist

# Must use V1 API directly
import aiohttp

async with aiohttp.ClientSession() as session:
    async with session.get(
        f"https://{bridge_ip}/api/{username}/config",
        ssl=False
    ) as response:
        config = await response.json()
        whitelist = config["whitelist"]  # ✅ Only in V1
```

---

## When to Use Which API

### Use V2 API When:
- ✅ Controlling lights (better metadata, typed responses)
- ✅ Managing scenes (includes smart scenes, not in V1)
- ✅ Reading device information (richer resource data)
- ✅ Working with automations (behavior_instance - V2 only)
- ✅ Getting sensor data (both APIs have this)
- ✅ Managing rooms/zones (both APIs have this)
- ✅ Need event streaming (SSE - V2 only)
- ✅ Entertainment mode with gradients (V2 only)

### Use V1 API When:
- ✅ Managing user credentials (whitelist - V1 only)
- ✅ Listing registered applications (V1 only)
- ✅ Deleting user access (V1 only)
- ✅ Checking who has access to bridge (V1 only)
- ✅ Administrative bridge configuration (V1 only)
- ✅ Simple light control is sufficient (basic features work in both)

---

## Comparison Example

### Same Task, Different APIs:

**Get Light State:**

```python
# V2 API (Modern)
bridge = HueBridgeV2(ip, username)
await bridge.initialize()
light = bridge.lights[light_id]
print(light.on.on)  # Typed, clean

# V1 API (Legacy)
response = await session.get(f"https://{ip}/api/{username}/lights/{light_id}")
data = await response.json()
print(data["state"]["on"])  # JSON, manual parsing
```

**Get User List:**

```python
# V2 API
# ❌ Not possible - endpoint doesn't exist

# V1 API (Only Option)
response = await session.get(f"https://{ip}/api/{username}/config")
config = await response.json()
users = config["whitelist"]  # ✅ Works
```

**Access Smart Scenes (Dynamic/Adaptive):**

```python
# V2 API (Only Option)
bridge = HueBridgeV2(ip, username)
await bridge.initialize()
smart_scenes = bridge.scenes.smart_scene.items  # ✅ Works
for scene in smart_scenes:
    print(scene.metadata.name, scene.state)  # Dynamic scene state

# V1 API
# ❌ Not possible - smart scenes don't exist in V1
# V1 only has static scenes via /api/{username}/scenes
```

---

## Future Migration?

**Will user management move to V2?**

Unlikely, because:
1. V2 has been out since 2020 - no signs of adding it
2. Philips' security model separates app functionality from admin
3. V1 API is still fully supported and maintained
4. Backward compatibility requirement

**Recommendation:**
- Use V2 for application features (lights, scenes, etc.)
- Use V1 for administrative tasks (user management)
- Both APIs will coexist indefinitely

---

## Summary

**Why credential scripts use V1:**
- User management (whitelist) is **only available in V1 API**
- This is by design, not a limitation of our scripts
- V2 API intentionally does not expose administrative functions
- All apps must use V1 for credential management

**Why other scripts use V2:**
- V2 has exclusive features: smart scenes, behavior_instance, event streaming, gradient controls
- Modern architecture with better performance and richer metadata
- Cleaner, typed data structures with resource-based design
- Better for application functionality (vs administration)

**API Overlap:**
- Basic light control: Both APIs support this (V2 has better metadata)
- Static scenes: Both APIs support this (V2 adds smart scenes)
- Groups/rooms: Both APIs support this
- Sensors: Both APIs support this

**Both APIs are needed** for complete bridge management:
- V1 for administrative tasks (credentials, config)
- V2 for modern features (smart scenes, automations, streaming)

---

*Last updated: 2025-11-12*
*Based on Philips Hue API v1 and v2 documentation*
