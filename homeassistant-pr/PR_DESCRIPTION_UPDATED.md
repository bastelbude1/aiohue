# Add External Scene Activation Detection to Hue Integration

## Summary

This PR adds support for detecting Hue scene activations from external sources (Hue mobile app, physical buttons, voice assistants, Hue automations) in addition to Home Assistant-initiated activations.

## Problem

Currently, Hue scene entities in Home Assistant only update their state when activated **through Home Assistant** (UI, automations, API calls). When scenes are activated via:

- Hue mobile app
- Physical Hue switches/dimmers
- Hue automations
- Voice assistants (Alexa/Google/Siri)

...the scene entity state in HA does **not update**, making it impossible to:

- Trigger automations based on scene activation
- Track scene usage
- Know which scene is currently active
- Validate scene states

## Solution

This PR implements external scene activation detection by:

1. **Listening to EventStream updates** - Entities listen for updates via `on_update()` method (only subscribe to `RESOURCE_ADDED` for entity creation)
2. **Detecting activations** - Two approaches based on scene type:
   - **Regular scenes:** Monitor `scene.status.last_recall` timestamp changes
   - **Smart scenes:** Track state transitions (INACTIVE → ACTIVE)
3. **Recording activations** - Call `_async_record_activation()` when scenes are actually recalled
4. **Using BaseScene** - Inherit from `BaseScene` instead of `SceneEntity` to enable state tracking

This follows the same pattern recently implemented for KNX scene activation detection (PR #151218).

## Review History

### Initial Submission (c315d685649)
- Original implementation using `scene.status.active` field for activation detection
- Subscribed to EventStream without `event_type` parameter

### Review Feedback from @balloob

#### Issue 1: False activations on light modifications
> When monitoring `status.active`, modifying a light in an active scene triggers false activations because the scene remains active.

#### Fix (2d47831fba4)
Switched to tracking `status.last_recall` timestamp instead:
- Only record activation when `last_recall` timestamp changes
- When a scene is recalled, the bridge updates `last_recall`
- When a light in an active scene is modified, `last_recall` stays unchanged
- This prevents false activations while preserving external activation detection

#### Issue 2: Missing event_type parameter
> `api.scenes.subscribe()` passes `event_type` as the first parameter to callbacks.

#### Fix (855803ca9f9)
Restored `event_type` parameter to `async_add_entity()` callback.

#### Issue 3: Smart scenes have same false activation bug
> After fixing regular scenes, testing revealed smart scenes had the identical false activation bug. The `on_update()` method we added for smart scenes was checking `state == ACTIVE` instead of detecting state transitions.

#### Fix (5e23b1e9103)
Applied state transition detection to smart scenes:
- Track previous state in `__init__` for smart scenes
- Only record activation when state transitions from NOT ACTIVE → ACTIVE
- When a smart scene is activated, state changes to ACTIVE
- When a light in an active smart scene is modified, state stays ACTIVE
- This prevents false activations while preserving activation detection

### Testing After All Fixes
**Regular Scenes (TC3):**
- Modified light in active scene → **0 false activations** ✅
- External activation via Hue app → **Correctly detected** ✅
- HA-initiated activation → **Correctly detected** ✅

**Smart Scenes (TC3-SS):**
- Modified light in active smart scene → **0 false activations** ✅
- Smart scene activation detection → **Working correctly** ✅

## Changes

### Modified Files

**homeassistant/components/hue/scene.py:**
- Import `SceneActiveStatus` from aiohue
- Change `Scene as SceneEntity` → `Scene as BaseScene`
- Change `HueSceneEntityBase` base class: `SceneEntity` → `BaseScene`
- Rename `async_activate()` → `_async_activate()` (both scene classes)
- Add `on_update()` method to detect activation via `last_recall` timestamp tracking (regular scenes)
- Track `_previous_last_recall` timestamp in `__init__()` for comparison (regular scenes)
- Add `on_update()` override for smart scenes using state transition detection
- Track `_previous_state` in `__init__()` for comparison (smart scenes)

### Key Changes Explained

**1. Base Class Change (Line 97):**
```python
# Before
class HueSceneEntityBase(HueBaseEntity, SceneEntity):

# After
class HueSceneEntityBase(HueBaseEntity, BaseScene):
```
`BaseScene` provides state tracking capabilities that `SceneEntity` lacks.

**2. Event Subscription (Lines 54-73):**
```python
@callback
def async_add_entity(
    event_type: EventType, resource: HueScene | HueSmartScene
) -> None:
    """Add entity from Hue resource."""
    if isinstance(resource, HueSmartScene):
        async_add_entities([HueSmartSceneEntity(bridge, api.scenes, resource)])
    else:
        async_add_entities([HueSceneEntity(bridge, api.scenes, resource)])

# add all current items in controller
for item in api.scenes:
    async_add_entity(EventType.RESOURCE_ADDED, item)

# register listener for new items only
config_entry.async_on_unload(
    api.scenes.subscribe(
        async_add_entity,
        event_filter=EventType.RESOURCE_ADDED,
    )
)
```
Entities listen for their own updates via the `on_update()` method inherited from `HueBaseEntity`. The subscription only handles new scene creation.

**3. Timestamp Tracking in __init__ (Lines 117-122):**
```python
# Track last_recall timestamp for scene activation detection (regular scenes only)
self._previous_last_recall = (
    resource.status.last_recall
    if isinstance(resource, HueScene) and resource.status
    else None
)
```
Initialize tracking of the `last_recall` timestamp to detect changes.

**4. Activation Detection via last_recall (Lines 140-170):**
```python
def on_update(self) -> None:
    """Handle EventStream updates for scene activation detection.

    For regular scenes (HueScene), we track the last_recall timestamp to detect
    actual scene activations (from Hue app, buttons, or automations) while
    avoiding false activations when lights in an active scene are modified.

    When a scene is recalled, the bridge updates last_recall timestamp.
    When a light in an active scene is modified, last_recall stays unchanged.

    SmartScenes override this method with their own activation logic.
    """
    # Only track activations for regular scenes (HueScene)
    if isinstance(self.resource, HueScene):
        current_last_recall = (
            self.resource.status.last_recall if self.resource.status else None
        )

        # Only record activation if last_recall timestamp has changed
        if (
            current_last_recall is not None
            and current_last_recall != self._previous_last_recall
        ):
            self._async_record_activation()

        # Update tracked timestamp
        self._previous_last_recall = current_last_recall

    super().on_update()
```
When the bridge recalls a scene (from any source), it updates `status.last_recall` timestamp. This triggers state recording **only when the timestamp changes**, preventing false activations from light modifications.

**5. Smart Scene State Transition Detection (Lines 256-278):**
```python
def on_update(self) -> None:
    """Handle EventStream updates for smart scene activation detection.

    Smart scenes use state transition detection to avoid false activations.
    We only record activation when the state transitions TO active (not while
    staying active), preventing false activations when lights are modified.

    When a scene is activated, the state changes to ACTIVE.
    When a light in an active scene is modified, the state stays ACTIVE.
    """
    current_state = self.resource.state

    # Only record activation on state transition TO active
    if (
        current_state == SmartSceneState.ACTIVE
        and self._previous_state != SmartSceneState.ACTIVE
    ):
        self._async_record_activation()

    # Update tracked state
    self._previous_state = current_state

    super().on_update()
```
Smart scenes override the base `on_update()` method to use state transition detection instead of timestamp tracking. This prevents false activations when lights in an active smart scene are modified.

**6. Method Rename (Lines 193, 264):**
```python
# Before
async def async_activate(self, **kwargs: Any) -> None:

# After
async def _async_activate(self, **kwargs: Any) -> None:
```
Required by `BaseScene` to support both internal activation and state recording.

## Testing

Comprehensive testing performed with real Philips Hue bridge in Docker test environment.

**Test Environment:**
- ✅ Docker HA: homeassistant/home-assistant:2025.11.1
- ✅ Real Hue Bridge: Connected to Docker HA instance
- ✅ Regular scenes tested with timestamp-based detection
- ✅ Smart scenes tested with state-transition detection

**Test Cases:**

- ✅ **Code Quality & Review** - Multiple iterations with CodeRabbit AI and @balloob review feedback, all issues resolved

**TC1: Integration Loading**
- ✅ Scene entities created successfully
- ✅ No runtime errors
- ✅ EventStream subscription working

**TC2: HA-Initiated Activation**
- ✅ Scene state updates correctly via Home Assistant API
- ✅ `scene.turn_on` service works as expected
- ✅ Activation visible in logbook

**TC3: No False Activations (Critical - balloob's bug)**
- ✅ Light modifications in active scene do NOT trigger activation records
- ✅ Only actual scene recalls are recorded
- ✅ Timestamp-based detection prevents false positives

**TC4: External Activation Detection**
- ✅ Scene state updates when activated via Hue mobile app
- ✅ External activations visible in Home Assistant
- ✅ Can trigger automations based on external activation

**TC3-SS: Smart Scene False Activation Test (Critical)**
- ✅ Light modifications in active smart scene do NOT trigger activation records
- ✅ Only actual smart scene activations are recorded
- ✅ State-transition detection prevents false positives

**TC3 Test Evidence (Regular Scenes - Critical):**

Test scenario: Modify light brightness while scene is active
```text
[STEP 1] Activating scene via HA API
[STEP 2] Checkpoint time recorded
[STEP 3] Modifying light in scene (brightness to 75%)
[STEP 4] Checking for activations after checkpoint...

[RESULT] Activations after checkpoint: 0

✅ SUCCESS - Light update while scene active did NOT trigger false activation
```

**TC3-SS Test Evidence (Smart Scenes - Critical):**

Test scenario: Modify light brightness while smart scene is active
```text
[STEP 1] Activating smart scene via HA API
[STEP 2] Checkpoint time recorded
[STEP 3] Modifying light in room (brightness to 50%)
[STEP 4] Checking for activations after checkpoint...

[RESULT] Activations after checkpoint: 0

✅ SUCCESS - Light update while smart scene active did NOT trigger false activation
```

**Test Results:**
- Scene entity state updates correctly for all activation methods (HA UI, API, Hue app)
- Scene activation visible in Home Assistant logbook
- Can trigger automations based on scene activation from any source
- **No false activations** when lights in active scenes are modified
- No performance impact (uses existing EventStream connection)

**Note on Smart Scenes:**
Smart scenes use a different activation detection approach than regular scenes because they don't have a `status.last_recall` field. Instead, smart scenes use **state transition detection** (tracking when state changes from NOT ACTIVE → ACTIVE). This was discovered after testing revealed smart scenes had the same false activation bug as regular scenes when using simple `state == ACTIVE` checking. Both scene types now correctly detect only actual activations and prevent false activations when lights are modified.

## Breaking Changes

Scene entities now update their state when activated externally (from Hue app, buttons, etc.).

This is a behavioral change but should not break existing automations:

- **Automations that trigger on `scene.turn_on` service calls:** Still work (unchanged)
- **Automations that monitor scene entity state:** Now work better (get updates from all sources)
- **Scene activation service calls:** Still work (internal method renamed but service unchanged)

## Related Issues

- Closes [home-assistant/discussions#1446](https://github.com/orgs/home-assistant/discussions/1446)
- Implements same pattern as KNX integration (PR #151218)

## Dependencies

- Requires **aiohue >= 4.8.0** (provides `scene.status.last_recall` field for regular scene activation detection, and `SmartScene.state` for smart scene detection)
- Home Assistant core already uses aiohue 4.8.0+

## Additional Notes

This change enables powerful new use cases:

- **Scene validation** - Verify lights match scene configuration after activation
- **Activity tracking** - Know which scenes are used and when
- **Cross-platform automations** - React to scenes activated via Hue app
- **Scene monitoring** - Alert if scenes fail to activate correctly

The implementation is minimal (~40 lines added) and leverages existing infrastructure (EventStream, aiohue 4.8.0).

## Contributors

**Implementation and Testing:** @bastelbude1, Claude Code and CodeRabbit
- Guided the technical solution from concept to completion
- Performed comprehensive code reviews and testing with AI assistance
- Validated implementation with real Philips Hue bridge hardware in Docker test environment
- Addressed review feedback from @balloob on false activations and event_type parameter
- Executed test cases TC1-TC4 for regular scenes and TC3-SS for smart scenes
- Both TC3 and TC3-SS proved no false activations when lights are modified in active scenes
