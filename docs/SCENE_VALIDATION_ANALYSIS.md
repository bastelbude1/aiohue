# Hue Scene State Validation Analysis

## Problem Statement

**Goal**: Automatically validate that lights match their scene's target states after scene activation, and correct any deviations.

**Current Situation**:
- Hue bridges store complete scene definitions (brightness, color, effects per light)
- Home Assistant can trigger scenes but doesn't know target states
- When a light fails to reach target state (network issue, manual change), neither system detects the deviation
- Example: "Wohnzimmer Standard" scene has 6 lights with specific brightness targets (2.37%, 12.25%, 0%, etc.)

**Available Data**:
- **Hue Inventories**: 214 scenes total (124 EG, 90 OG) with full action definitions
- **HA Inventories**: 214 matching scene entities (same unique_id for cross-reference)
- **Mapping**: Hue scene `id` = HA scene `unique_id` (confirmed)
- **Mapping**: Hue light `id` = HA light `unique_id` (requires verification)

**Data Structures**:

Hue Scene Action (from aiohue inventory):
```python
Action(
  target=ResourceIdentifier(rid='ebb31eab-f7ce-405a-9339-098d04574373', rtype='light'),
  action=ActionAction(
    on=OnFeature(on=True),
    dimming=DimmingFeatureBase(brightness=12.25),  # 0-100%
    color=ColorFeatureBase(xy=ColorPoint(x=0.561, y=0.4042)),  # CIE xy
    color_temperature=None,
    effects=SceneEffectsFeature(effect='fire'),
    dynamics=None
  )
)
```

HA Scene Entity (from HA inventory):
```json
{
  "entity_id": "scene.wohnzimmer_standard",
  "unique_id": "4e1212fd-6c61-49ba-a96a-b85339d5c495",
  "original_name": "Standard",
  "device_id": "abc123...",
  "platform": "hue"
}
```

---

## Approach Evaluation

### Approach 1: Inventory-Based Validation

**Description**: Parse Hue inventory JSON files, create HA helper sensors/automations that reference the inventory data, validate on trigger.

**Implementation**:
```yaml
# automation:
- alias: "Validate Scene: Wohnzimmer Standard"
  trigger:
    - platform: event
      event_type: call_service
      event_data:
        domain: scene
        service: turn_on
        service_data:
          entity_id: scene.wohnzimmer_standard
  action:
    - delay: 5  # Wait for lights to transition
    - service: python_script.validate_scene
      data:
        scene_id: "4e1212fd-6c61-49ba-a96a-b85339d5c495"
        inventory_file: "/config/custom_components/hue_scene_validator/inventory.json"
```

Python script logic:
```python
# Load inventory
with open(inventory_file) as f:
    inventory = json.load(f)

# Find scene
scene = next(s for s in inventory['resources']['scenes']['items'] if s['id'] == scene_id)

# Validate each light
for action in scene['actions']:
    light_id = action['target']['rid']

    # Map Hue light ID to HA entity_id (via unique_id lookup)
    ha_entity = entity_registry.get_by_unique_id(light_id)

    # Get current state
    current = hass.states.get(ha_entity.entity_id)

    # Compare
    target_brightness = action['action']['dimming']['brightness']
    current_brightness = current.attributes.get('brightness_pct')

    if abs(target_brightness - current_brightness) > 5:  # 5% tolerance
        # Correct deviation
        hass.services.call('light', 'turn_on', {
            'entity_id': ha_entity.entity_id,
            'brightness_pct': target_brightness
        })
```

**Pros**:
- ✅ Single source of truth (Hue inventory)
- ✅ No duplication of scene definitions
- ✅ Automatically stays in sync with Hue bridge changes
- ✅ Works with all scene types (color, effects, temperature)
- ✅ Can validate complex scenes with many lights
- ✅ Minimal maintenance after initial setup

**Cons**:
- ❌ Requires custom Python script or AppDaemon
- ❌ Inventory file must be kept up-to-date (re-export after scene changes)
- ❌ Color space conversion needed (Hue xy → HA hs_color/rgb_color)
- ❌ Complex ID mapping (Hue resource ID → HA entity_id via unique_id)
- ❌ Not visible in HA UI (debugging harder)
- ❌ Performance overhead parsing large JSON on every validation

**Technical Challenges**:
1. **Color Conversion**: Hue uses CIE xy + brightness, HA uses hs_color/rgb_color/kelvin
   - Need conversion library (e.g., python-colormath, colour-science)
   - Rounding errors may cause false positives
   - Tolerance thresholds needed (±5% brightness, ±0.01 xy)

2. **ID Mapping**: Hue light resource ID → HA entity_id
   - Requires entity registry access
   - Must handle missing/disabled entities
   - Device ID mapping for grouped scenes

3. **Timing**: Light transitions take 2-10 seconds
   - Delay must be scene-dependent (simple vs. color scenes)
   - Need to detect if light is still transitioning
   - Handle failed transitions vs. slow transitions

4. **Effects**: Hue effects (fire, sparkle) don't map to HA states
   - Can only validate effect is active, not specific parameters
   - HA reports effect as string, Hue has structured data

**Complexity**: ⚠️ **HIGH** (custom code, JSON parsing, color math, ID mapping)

**Maintenance**: ⚠️ **MEDIUM** (re-export inventory after scene changes)

**Reliability**: ✅ **HIGH** (direct data from bridge, no guessing)

---

### Approach 2: 1:1 Scene Replication to HA

**Description**: Create native HA scenes that replicate Hue scene definitions, use HA scenes exclusively instead of Hue scenes.

**Implementation**:
```yaml
# scenes.yaml (generated from Hue inventory)
- id: wohnzimmer_standard_ha
  name: "Wohnzimmer Standard (HA)"
  entities:
    light.wohnzimmer_decke_1:
      state: on
      brightness_pct: 2.37
    light.wohnzimmer_decke_2:
      state: on
      brightness_pct: 12.25
    light.wohnzimmer_stehlampe:
      state: on
      brightness_pct: 0
    # ... 3 more lights
```

Validation automation:
```yaml
- alias: "Validate HA Scene After Activation"
  trigger:
    - platform: event
      event_type: call_service
      event_data:
        domain: scene
        service: turn_on
  action:
    - delay: 5
    - service: scene.turn_on
      data:
        entity_id: "{{ trigger.event.data.service_data.entity_id }}"
```

**Pros**:
- ✅ Native HA feature, no custom code
- ✅ Visible in HA UI, easy to debug
- ✅ Built-in validation via scene.turn_on (idempotent)
- ✅ Works with HA automations, scripts, dashboards
- ✅ Fast performance (no JSON parsing)
- ✅ Can leverage HA scene editor for modifications
- ✅ Snapshot functionality available

**Cons**:
- ❌ **CRITICAL**: Duplicates all scene definitions (214 scenes × ~6 lights = ~1200 entity states)
- ❌ **CRITICAL**: Manual sync required when Hue scenes change
- ❌ **CRITICAL**: Loses Hue-specific features (effects like fire/sparkle)
- ❌ Abandons Hue scene management (Hue app becomes useless for scenes)
- ❌ Migration effort (generate 214 HA scenes from inventory)
- ❌ Color conversion still needed (one-time during generation)
- ❌ Scenes become HA-only (can't trigger from Hue app, switches, sensors)

**Technical Challenges**:
1. **Scene Generation**: Need script to convert Hue inventory → HA scenes.yaml
   - Color space conversion (xy → hs_color/rgb_color)
   - Effect mapping (Hue effects → HA effects or drop)
   - Entity ID mapping (Hue light ID → HA entity_id)

2. **Sync Process**:
   - Detect changes in Hue scenes (compare inventory snapshots)
   - Regenerate affected HA scenes
   - Manual review before applying (avoid accidental overwrites)
   - Version control for scenes.yaml

3. **Feature Parity**:
   - Hue effects (fire, sparkle) not available in HA
   - Hue gradients not supported in HA scenes
   - Dynamic scenes (sunrise, sunset) require custom logic
   - Smart scenes (time-based) must be recreated in HA automations

4. **User Experience**:
   - Hue app scene triggers won't work (scenes are HA-only)
   - Hue switches configured for scenes need reconfiguration
   - Hue motion sensors triggering scenes need HA automations
   - Family members using Hue app will be confused

**Complexity**: ⚠️ **MEDIUM** (one-time generation, ongoing sync)

**Maintenance**: ❌ **HIGH** (manual sync on every Hue scene change)

**Reliability**: ⚠️ **MEDIUM** (drift risk if sync forgotten)

**User Impact**: ❌ **HIGH** (breaks Hue app scene usage)

---

### Approach 3: Hybrid Snapshot Validation

**Description**: Capture actual light states immediately after scene activation, use as reference for validation triggers.

**Implementation**:
```yaml
# automation:
- alias: "Snapshot Scene State"
  trigger:
    - platform: event
      event_type: call_service
      event_data:
        domain: scene
        service: turn_on
  action:
    - delay: 5  # Wait for transition
    - service: scene.create
      data:
        scene_id: "snapshot_{{ trigger.event.data.service_data.entity_id | replace('scene.', '') }}"
        snapshot_entities:
          - light.wohnzimmer_decke_1
          - light.wohnzimmer_decke_2
          # ... all lights in room

- alias: "Validate Against Snapshot"
  trigger:
    - platform: state
      entity_id: light.wohnzimmer_decke_1
      for: "00:00:30"  # Ignore brief changes
  condition:
    - condition: template
      value_template: >
        {% set snapshot = state_attr('scene.snapshot_wohnzimmer_standard', 'entity_id') %}
        {{ snapshot is not none }}
  action:
    - service: scene.turn_on
      data:
        entity_id: scene.snapshot_wohnzimmer_standard
```

**Pros**:
- ✅ No inventory parsing needed
- ✅ Automatically adapts to actual scene results
- ✅ Handles Hue-specific effects (captures actual state)
- ✅ No color space conversion needed
- ✅ Native HA scenes (easy to inspect)
- ✅ Works with any scene changes (auto-updates snapshot)

**Cons**:
- ❌ **CRITICAL**: Validates against "what happened" not "what should happen"
- ❌ **CRITICAL**: If initial activation fails, snapshot captures wrong state
- ❌ No way to know if snapshot is correct
- ❌ Can't detect systematic issues (e.g., bulb always 10% dimmer)
- ❌ Snapshot timing critical (too early = transitioning, too late = manual change)
- ❌ Storage overhead (214 scenes × 2 = 428 scene entities)
- ❌ Loses definition if snapshot deleted/corrupted

**Technical Challenges**:
1. **Snapshot Timing**: When to capture?
   - Too early: Lights still transitioning, captures intermediate state
   - Too late: User may have adjusted lights, captures wrong state
   - Solution: Dynamic delay based on scene complexity (1 light = 2s, 10 lights = 8s)

2. **Failure Detection**: How to know if snapshot is valid?
   - Can't compare against target (don't have target)
   - Could compare against previous snapshots (detect drift)
   - Could validate all lights responded (check state changes)

3. **Scene Identification**: Which lights belong to scene?
   - Hue scenes target specific lights (defined in action.target)
   - HA scenes don't have explicit membership
   - Must extract from scene.create snapshot or hardcode

4. **State Change Detection**: When to trigger re-validation?
   - Continuous monitoring = high overhead
   - Debounce needed (ignore <30s changes)
   - Should ignore intentional changes (user dimming)

**Complexity**: ⚠️ **MEDIUM** (snapshot logic, timing)

**Maintenance**: ✅ **LOW** (auto-updates snapshots)

**Reliability**: ❌ **LOW** (validates wrong state if initial activation failed)

---

### Approach 4: Template-Based Expected State Sensors

**Description**: Create template sensors for each scene that expose expected states, compare in automations.

**Implementation**:
```yaml
# template.yaml
- sensor:
    - name: "Wohnzimmer Standard Expected States"
      unique_id: wohnzimmer_standard_expected
      state: >
        {
          "light.wohnzimmer_decke_1": {"brightness_pct": 2.37, "state": "on"},
          "light.wohnzimmer_decke_2": {"brightness_pct": 12.25, "state": "on"},
          "light.wohnzimmer_decke_3": {"brightness_pct": 0, "state": "on"}
        }

- binary_sensor:
    - name: "Wohnzimmer Standard State Valid"
      unique_id: wohnzimmer_standard_valid
      state: >
        {% set expected = states('sensor.wohnzimmer_standard_expected') | from_json %}
        {% set valid = true %}
        {% for entity_id, target in expected.items() %}
          {% set current = states(entity_id) %}
          {% set current_brightness = state_attr(entity_id, 'brightness_pct') | float(0) %}
          {% if current != target.state or (current_brightness - target.brightness_pct) | abs > 5 %}
            {% set valid = false %}
          {% endif %}
        {% endfor %}
        {{ valid }}

# automation:
- alias: "Fix Scene State If Invalid"
  trigger:
    - platform: state
      entity_id: binary_sensor.wohnzimmer_standard_valid
      to: 'off'
      for: "00:00:05"
  action:
    - service: scene.turn_on
      data:
        entity_id: scene.wohnzimmer_standard
```

**Pros**:
- ✅ Expected states visible in HA UI
- ✅ Easy to debug (sensor shows exact deviation)
- ✅ No custom Python code needed
- ✅ Can create HA dashboards showing scene validity
- ✅ Reusable templates (create sensor generator)

**Cons**:
- ❌ **CRITICAL**: 214 scenes × 2 sensors = 428 entities (massive overhead)
- ❌ Hardcoded state definitions (must sync manually with Hue)
- ❌ Template complexity for color conversion
- ❌ Performance impact (428 sensors evaluating constantly)
- ❌ Maintenance nightmare (update sensors when scenes change)
- ❌ Still need inventory → template conversion script

**Technical Challenges**:
1. **Sensor Count**: 428 sensors is excessive
   - Entity registry bloat
   - Performance degradation
   - UI clutter

2. **Template Evaluation**: Sensors recalculate on every light state change
   - 522 Hue entities × 428 sensors = massive overhead
   - Need careful trigger limiting
   - May cause HA slowdowns

3. **Data Encoding**: JSON in sensor state is hacky
   - Limited to 255 chars (state limit)
   - Must use attributes for larger scenes
   - Parsing JSON in templates is slow

4. **Color Handling**: Template math for color conversion is painful
   - xy → hs_color requires complex calculations
   - Jinja2 doesn't have color math functions
   - Need custom Jinja2 filters or accept inaccuracy

**Complexity**: ❌ **HIGH** (428 sensors, template logic, color math)

**Maintenance**: ❌ **HIGH** (update sensors on scene changes)

**Reliability**: ⚠️ **MEDIUM** (depends on sync accuracy)

**Performance**: ❌ **POOR** (428 sensors, constant evaluation)

---

### Approach 5: ML-Based Anomaly Detection

**Description**: Learn scene patterns over time, detect deviations using statistical anomaly detection.

**Implementation**:
```python
# AppDaemon app or custom component
import numpy as np
from sklearn.ensemble import IsolationForest

class SceneAnomalyDetector:
    def __init__(self):
        self.models = {}  # scene_id -> IsolationForest model
        self.training_data = {}  # scene_id -> list of light states

    def on_scene_activated(self, scene_id, lights):
        # Wait for transition
        await asyncio.sleep(5)

        # Capture light states
        states = self.capture_light_states(lights)

        # Train or predict
        if scene_id not in self.models:
            # Collect training data (first 20 activations)
            self.training_data[scene_id].append(states)
            if len(self.training_data[scene_id]) >= 20:
                self.train_model(scene_id)
        else:
            # Predict anomaly
            is_anomaly = self.models[scene_id].predict([states])[0] == -1
            if is_anomaly:
                # Re-activate scene
                await self.hass.services.async_call('scene', 'turn_on', {
                    'entity_id': f'scene.{scene_id}'
                })
```

**Pros**:
- ✅ No manual configuration needed
- ✅ Adapts to scene changes automatically
- ✅ Detects unknown failure modes
- ✅ Handles complex patterns (time-based, adaptive scenes)
- ✅ Can detect bulb degradation over time

**Cons**:
- ❌ **CRITICAL**: Requires 20+ activations per scene to train (214 scenes = months of data)
- ❌ **CRITICAL**: No validation during training period
- ❌ **CRITICAL**: Can't distinguish "wrong state" from "new normal"
- ❌ Requires machine learning libraries (sklearn, numpy)
- ❌ Black box (can't explain why anomaly detected)
- ❌ False positives during legitimate changes
- ❌ Model drift requires retraining
- ❌ High complexity for simple problem

**Technical Challenges**:
1. **Training Data**: Need historical activations
   - 214 scenes × 20 samples = 4,280 activations
   - If each scene used 2×/week = 107 weeks (~2 years!)
   - Cold start problem (no validation initially)

2. **Feature Engineering**: What to learn?
   - Brightness levels (continuous)
   - Color values (xy, hs, rgb?)
   - On/off states (binary)
   - Transitions times (temporal)
   - Normalization critical

3. **Anomaly Threshold**: When is deviation significant?
   - Too sensitive = false positives (triggers on legitimate changes)
   - Too lenient = misses actual failures
   - Must tune per scene (some scenes more variable)

4. **Model Storage**: Where to persist models?
   - Models are 10-100KB each × 214 scenes = 2-20MB
   - Must survive HA restarts
   - Version control for models?

**Complexity**: ❌ **VERY HIGH** (ML pipeline, feature engineering, model management)

**Maintenance**: ⚠️ **MEDIUM** (retraining needed periodically)

**Reliability**: ❌ **LOW** (unproven, requires training period, false positives)

**Time to Value**: ❌ **VERY LONG** (months to collect training data)

---

## Comparison Matrix

| Criteria | Approach 1: Inventory | Approach 2: Replication | Approach 3: Snapshot | Approach 4: Templates | Approach 5: ML |
|----------|----------------------|------------------------|---------------------|----------------------|---------------|
| **Complexity** | ⚠️ High | ⚠️ Medium | ⚠️ Medium | ❌ High | ❌ Very High |
| **Maintenance** | ⚠️ Medium | ❌ High | ✅ Low | ❌ High | ⚠️ Medium |
| **Sync Required** | ⚠️ Yes (re-export) | ❌ Yes (manual) | ✅ No | ❌ Yes (manual) | ✅ No |
| **Performance** | ⚠️ Medium | ✅ Fast | ✅ Fast | ❌ Slow | ⚠️ Medium |
| **Reliability** | ✅ High | ⚠️ Medium | ❌ Low | ⚠️ Medium | ❌ Low |
| **UX Impact** | ✅ None | ❌ High | ✅ None | ✅ None | ✅ None |
| **Entity Count** | ✅ 0 | ⚠️ +214 | ❌ +214 | ❌ +428 | ✅ 0 |
| **Custom Code** | ❌ Yes | ⚠️ Generator | ⚠️ Some | ✅ No | ❌ Yes |
| **Hue Features** | ✅ All | ❌ Limited | ✅ All | ⚠️ Most | ✅ All |
| **Time to Deploy** | ⚠️ 2-3 days | ⚠️ 1-2 days | ✅ 1 day | ❌ 3-4 days | ❌ Months |
| **Future-Proof** | ✅ Yes | ❌ No | ⚠️ Somewhat | ❌ No | ⚠️ Somewhat |

**Rating Key**: ✅ Good | ⚠️ Acceptable | ❌ Poor

---

## Recommendation

### 🏆 **Best Approach: Hybrid Inventory + Snapshot (1 + 3 Combined)**

**Why Not Pure Approach 1?**
- Color space conversion is complex and error-prone
- Effects (fire, sparkle) can't be validated accurately
- Tolerance tuning is difficult without knowing actual results

**Why Not Pure Approach 3?**
- No ground truth if initial activation fails
- Can't detect systematic issues

**Hybrid Solution**: Use inventory for critical validation, snapshot for complex features

**Implementation**:

```yaml
# automation:
- alias: "Validate Scene States"
  trigger:
    - platform: event
      event_type: call_service
      event_data:
        domain: scene
        service: turn_on
  variables:
    scene_entity: "{{ trigger.event.data.service_data.entity_id }}"
    scene_uid: "{{ state_attr(scene_entity, 'unique_id') }}"
  action:
    # Step 1: Wait for transition
    - delay:
        seconds: >
          {{ 3 + (state_attr(scene_entity, 'lights_count') | default(1) * 0.5) | int }}

    # Step 2: Create snapshot
    - service: scene.create
      data:
        scene_id: "snapshot_{{ scene_entity | replace('scene.', '') }}"
        snapshot_entities: >
          {{ ... }}  # Get lights from scene

    # Step 3: Validate critical attributes (brightness, on/off) via inventory
    - service: python_script.validate_scene_critical
      data:
        scene_uid: "{{ scene_uid }}"
        tolerance: 5  # 5% brightness tolerance

    # Step 4: If validation failed, retry once
    - condition: template
      value_template: "{{ states('sensor.scene_validation_result') == 'failed' }}"
    - service: scene.turn_on
      data:
        entity_id: "{{ scene_entity }}"
```

Python script (simplified):
```python
# validate_scene_critical.py
scene_uid = data.get('scene_uid')
tolerance = data.get('tolerance', 5)

# Load inventory (cached in memory)
inventory = hass.data.get('hue_inventory')
scene = next(s for s in inventory['scenes'] if s['id'] == scene_uid)

failures = []
for action in scene['actions']:
    light_uid = action['target']['rid']
    ha_entity = entity_registry.async_get_entity_id('light', 'hue', light_uid)

    if not ha_entity:
        continue  # Skip unavailable lights

    current_state = hass.states.get(ha_entity)

    # Validate on/off
    target_on = action['action']['on']['on']
    current_on = current_state.state == 'on'
    if target_on != current_on:
        failures.append(f"{ha_entity}: wrong state")
        continue

    # Validate brightness (if specified)
    if 'dimming' in action['action'] and action['action']['dimming']:
        target_brightness = action['action']['dimming']['brightness']
        current_brightness = current_state.attributes.get('brightness', 0) / 255 * 100

        if abs(target_brightness - current_brightness) > tolerance:
            failures.append(f"{ha_entity}: brightness {current_brightness}% != {target_brightness}%")

    # Skip color/effect validation (use snapshot for these)

# Store result
hass.states.set('sensor.scene_validation_result',
                'failed' if failures else 'success',
                {'failures': failures})
```

**Advantages of Hybrid**:
1. ✅ Validates critical attributes (on/off, brightness) against inventory (reliable)
2. ✅ Uses snapshot for complex attributes (color, effects) that are hard to compare
3. ✅ Single source of truth for core functionality
4. ✅ Handles Hue-specific features without complex conversion
5. ✅ Auto-corrects failures by re-triggering scene
6. ✅ Minimal entity overhead (only validation result sensors)
7. ✅ Inventory updates needed only when brightness targets change (rare)

**Deployment Plan**:

### Phase 1: Prototype (Week 1)
- Create validation script for 1 test scene
- Test with intentional failures (turn off light, change brightness)
- Tune timing and tolerance parameters

### Phase 2: Inventory Integration (Week 2)
- Export Hue inventories to HA config directory
- Create inventory loader in Python script
- Build light ID → entity_id mapping cache

### Phase 3: Automation Framework (Week 3)
- Create universal scene validation automation
- Add monitoring sensors (validation success rate)
- Implement retry logic with backoff

### Phase 4: Rollout (Week 4)
- Enable for all 214 scenes
- Monitor for false positives
- Create dashboard for validation metrics

**Maintenance**: Re-export inventory when scene brightness/on-off targets change (estimated: monthly).

---

## Alternative: Simplified Approach for Quick Win

If full hybrid solution is too complex initially, start with **Approach 3 (Snapshot)** for quick deployment:

### Quick Start (1-day implementation)
```yaml
- alias: "Scene Validation - Simple"
  mode: queued
  trigger:
    - platform: event
      event_type: call_service
      event_data:
        domain: scene
        service: turn_on
  action:
    - delay: 5
    - service: scene.create
      data:
        scene_id: "last_{{ trigger.event.data.service_data.entity_id | replace('scene.', '') }}"
        snapshot_entities: "{{ ... }}"
```

**Benefits**:
- Immediate deployment
- No custom code
- Captures actual states

**Limitations**:
- No validation if first activation fails
- No ground truth comparison
- Still useful for detecting drift over time

**Migration Path**: Once snapshot approach is running, gradually add inventory validation for high-priority scenes (bedrooms, security lights, etc.).

---

## Conclusion

**Recommended**: **Hybrid Inventory + Snapshot (Approach 1 + 3)**
- Best balance of reliability and complexity
- Validates critical attributes against inventory
- Uses snapshots for complex features
- Time to deploy: 3-4 weeks
- Maintenance: Monthly inventory re-export

**Quick Alternative**: **Pure Snapshot (Approach 3)**
- Fastest deployment (1 day)
- Good enough for detecting drift
- Migration path to hybrid later
- Limitation: No ground truth validation

**Avoid**:
- ❌ Approach 2 (Replication): Breaks Hue app usage, high sync overhead
- ❌ Approach 4 (Templates): Entity bloat, poor performance
- ❌ Approach 5 (ML): Overkill, long training period, unproven

**Next Steps**:
1. Decide: Hybrid (full solution) or Snapshot (quick win)?
2. If Hybrid: Export Hue inventories to HA config directory
3. If Snapshot: Identify scene → lights mapping
4. Create prototype automation for test scene
5. Iterate based on real-world testing
