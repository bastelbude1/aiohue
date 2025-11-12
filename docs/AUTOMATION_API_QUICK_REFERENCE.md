# Philips Hue V2 Automation API - Quick Reference

## Available Automation Resources

### 1. Smart Scenes (Time-based automations)
```python
# Access
bridge.scenes.smart_scene.items              # List all
bridge.scenes.smart_scene[id]                # Get one
await bridge.scenes.smart_scene.recall(id)   # Activate/deactivate

# Example
for scene in bridge.scenes.smart_scene.items:
    print(f"{scene.metadata.name}: {scene.state}")
```

**Properties**: id, metadata, group, week_timeslots, state, active_timeslot, transition_duration

**Example Count**: 6 on test bridge

---

### 2. Behavior Scripts (Automation templates)
```python
# Access
bridge.config.behavior_script.items          # List all
bridge.config.behavior_script[id]            # Get one

# Example
for script in bridge.config.behavior_script.items:
    if script.metadata.category.value == "automation":
        print(f"{script.metadata.name}: {script.description}")
```

**Properties**: id, metadata, description, configuration_schema, trigger_schema, state_schema, version

**Categories**: automation, entertainment, accessory, other

**Example Count**: 13 on test bridge

---

### 3. Behavior Instances (Active automations)
```python
# Access
bridge.config.behavior_instance.items        # List all
bridge.config.behavior_instance[id]          # Get one
await bridge.config.behavior_instance.set_enabled(id, True/False)  # Toggle
await bridge.config.behavior_instance.update(id, obj)  # Modify

# Example
for instance in bridge.config.behavior_instance.items:
    print(f"{'✓' if instance.enabled else '✗'} {instance.metadata.name}")
    print(f"   Status: {instance.status.value}")
    print(f"   Dependencies: {len(instance.dependees)}")
```

**Properties**: id, metadata, script_id, enabled, configuration, status, last_error, state, dependees

**Statuses**: INITIALIZING, RUNNING, DISABLED, ERRORED

**Example Count**: 8 on test bridge

---

### 4. Geofence Clients (Location-based)
```python
# Access (Raw API - not in controller)
geofence_clients = await bridge.request("get", "clip/v2/resource/geofence_client")

# Example
for client in geofence_clients:
    print(f"{client['name']} (ID: {client['id']})")
```

**Properties**: id, name, type

**Example Count**: 2 on test bridge

---

### 5. Geolocation (Sun position)
```python
# Access (Raw API - not in controller)
geolocation = await bridge.request("get", "clip/v2/resource/geolocation")

# Example
if geolocation and geolocation[0]['is_configured']:
    geo = geolocation[0]
    print(f"Sunset: {geo['sun_today']['sunset_time']}")
```

**Properties**: id, is_configured, sun_today (with sunset_time, day_type)

**Example Count**: 1 on test bridge

---

## Resource Availability Summary

| Type | Controller | Items | Status |
|------|-----------|-------|--------|
| Smart Scenes | `bridge.scenes.smart_scene` | 6 | Fully exposed |
| Behavior Scripts | `bridge.config.behavior_script` | 13 | Fully exposed |
| Behavior Instances | `bridge.config.behavior_instance` | 8 | Fully exposed |
| Geofence Clients | Raw API | 2 | No controller |
| Geolocation | Raw API | 1 | No controller |

**Total Automation Resources**: 30 items on test bridge

---

## Common Tasks

### Get all active automations (enabled or not)
```python
automations = bridge.config.behavior_instance.items
```

### Find automations that depend on a specific room
```python
room_id = "some-room-uuid"
for instance in bridge.config.behavior_instance.items:
    for dep in instance.dependees:
        if dep['target']['rid'] == room_id:
            print(f"Uses room: {instance.metadata.name}")
```

### Get available automation templates (scripts)
```python
automation_templates = [
    s for s in bridge.config.behavior_script.items 
    if s.metadata.category.value == "automation"
]
```

### List all schedules with their scenes
```python
for scene in bridge.scenes.smart_scene.items:
    print(f"\nSchedule: {scene.metadata.name}")
    for day in scene.week_timeslots[0].timeslots:
        time_info = day['start_time']['kind']
        if time_info == 'time':
            hour = day['start_time']['time']['hour']
            minute = day['start_time']['time']['minute']
            print(f"  {hour:02d}:{minute:02d} -> {day['target']['rid']}")
        else:
            print(f"  {time_info.upper()} -> {day['target']['rid']}")
```

### Check automation status
```python
for instance in bridge.config.behavior_instance.items:
    status = "RUNNING" if instance.status.value == "running" else instance.status.value
    enabled = "ENABLED" if instance.enabled else "DISABLED"
    print(f"{instance.metadata.name}: {status} ({enabled})")
    if instance.last_error:
        print(f"  ERROR: {instance.last_error}")
```

---

## File Locations

- **Full Documentation**: `docs/HUE_AUTOMATION_RESOURCES.md`
- **Model Classes**: `venv/lib/python3.x/site-packages/aiohue/v2/models/`
- **Controllers**: `venv/lib/python3.x/site-packages/aiohue/v2/controllers/`

---

## Integration Points in inventory-hue-bridge.py

The inventory script currently does NOT capture automation resources. Proposed additions:

1. Add Smart Scenes retrieval section
2. Add Behavior Scripts retrieval section  
3. Add Behavior Instances retrieval section
4. Consider adding Geofence Clients (raw API)
5. Consider adding Geolocation (raw API)

See full report for proposed code additions.

---

## API Endpoints

```python
# Via aiohue typed controllers
bridge.scenes.smart_scene
bridge.config.behavior_script
bridge.config.behavior_instance

# Via raw API requests
await bridge.request("get", "clip/v2/resource/geofence_client")
await bridge.request("get", "clip/v2/resource/geolocation")
await bridge.request("get", "clip/v2/resource/smart_scene")
await bridge.request("get", "clip/v2/resource/behavior_script")
await bridge.request("get", "clip/v2/resource/behavior_instance")
```

---

## Notes

- No "rules" or "triggers" resource types exist in V2 API (those were in V1)
- No separate "timer" resource type (timers are part of behavior configurations)
- No "routine" resource type (use Smart Scenes or Behavior Instances instead)
- Behavior Instances have flexible JSON configurations (varies by script type)
- All automations use ResourceIdentifier links to other resources (rooms, scenes, lights)
- Geofence requires user location tracking enabled on bridge
- Geolocation requires geographic coordinates configured on bridge

