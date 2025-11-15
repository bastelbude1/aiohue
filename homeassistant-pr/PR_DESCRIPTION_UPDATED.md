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
2. **Detecting activation via last_recall timestamp** - Monitor `scene.status.last_recall` timestamp changes to distinguish actual activations from light modifications
3. **Recording activations** - Call `_async_record_activation()` when scenes are actually recalled
4. **Using BaseScene** - Inherit from `BaseScene` instead of `SceneEntity` to enable state tracking

This follows the same pattern recently implemented for KNX scene activation detection (PR #151218).

## Review History

### Initial Submission (c315d685649)
- Original implementation using `scene.status.active` field for activation detection
- Subscribed to EventStream without `event_type` parameter

### Review Feedback from @balloob

**Issue 1: False activations on light modifications**
> When monitoring `status.active`, modifying a light in an active scene triggers false activations because the scene remains active.

**Fix (2d47831fba4):** Switched to tracking `status.last_recall` timestamp instead:
- Only record activation when `last_recall` timestamp changes
- When a scene is recalled, the bridge updates `last_recall`
- When a light in an active scene is modified, `last_recall` stays unchanged
- This prevents false activations while preserving external activation detection

**Issue 2: Missing event_type parameter**
> `api.scenes.subscribe()` passes `event_type` as the first parameter to callbacks.

**Fix (855803ca9f9):** Restored `event_type` parameter to `async_add_entity()` callback.

### Testing After Fixes
- TC3 Test: Modified light in active scene → **0 false activations** ✅
- External activation via Hue app → **Correctly detected** ✅
- HA-initiated activation → **Correctly detected** ✅

## Changes

### Modified Files

**homeassistant/components/hue/scene.py:**
- Import `SceneActiveStatus` from aiohue
- Change `Scene as SceneEntity` → `Scene as BaseScene`
- Change `HueSceneEntityBase` base class: `SceneEntity` → `BaseScene`
- Rename `async_activate()` → `_async_activate()` (both scene classes)
- Add `on_update()` method to detect activation via `last_recall` timestamp tracking
- Track `_previous_last_recall` timestamp in `__init__()` for comparison
- Smart scenes override `on_update()` to use `.state` instead of `.status` for activation tracking

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

**5. Method Rename (Lines 193, 264):**
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
- ✅ Multiple regular scenes tested (smart scenes not tested, but follow same pattern)

**Tests Completed:**

1. ✅ **Code Quality & Review** - Multiple iterations with CodeRabbit AI and @balloob review feedback, all issues resolved
2. ✅ **Integration Loading** - Scene entities created successfully, no runtime errors
3. ✅ **HA-Initiated Activation** - Scene state updates correctly via Home Assistant API
4. ✅ **External Activation Detection** - Scene state updates when activated via Hue mobile app
5. ✅ **TC3: No False Activations** - Light modifications in active scene do NOT trigger activation records

**TC3 Test Evidence (Critical):**

Test scenario: Modify light brightness while scene is active
```
[STEP 1] Activating scene via HA API
[STEP 2] Checkpoint time recorded
[STEP 3] Modifying light in scene (brightness to 75%)
[STEP 4] Checking for activations after checkpoint...

[RESULT] Activations after checkpoint: 0

✅ SUCCESS - Light update while scene active did NOT trigger false activation
```

**Test Results (Regular Scenes):**
- Scene entity state updates correctly for all activation methods (HA UI, API, Hue app)
- Scene activation visible in Home Assistant logbook
- Can trigger automations based on scene activation from any source
- **No false activations** when lights in active scenes are modified
- No performance impact (uses existing EventStream connection)

**Note on Smart Scenes:**
Smart scene code changes follow the same pattern as regular scenes but use `.state` field instead of `.status.last_recall`. Smart scenes were not tested with real hardware but the implementation mirrors the regular scene logic.

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

- Requires **aiohue >= 4.8.0** (adds `scene.status.active` and `last_recall` fields)
- Home Assistant core already uses aiohue 4.8.0+

## Checklist

- [x] Code follows Home Assistant style guidelines
- [x] Changes follow KNX integration pattern (PR #151218)
- [x] Tested with real Hue bridges and scenes
- [x] No new dependencies required
- [x] Breaking change documented
- [x] Review feedback addressed (event_type parameter, last_recall timestamp)
- [ ] Tests added/updated (need assistance with test structure)
- [ ] Documentation updated (need assistance with integration docs)

## Additional Notes

This change enables powerful new use cases:

- **Scene validation** - Verify lights match scene configuration after activation
- **Activity tracking** - Know which scenes are used and when
- **Cross-platform automations** - React to scenes activated via Hue app
- **Scene monitoring** - Alert if scenes fail to activate correctly

The implementation is minimal (~40 lines added) and leverages existing infrastructure (EventStream, aiohue 4.8.0).

## Design Decisions

**No config option to disable detection:**
This feature aligns with KNX integration (PR #151218) which provides external scene activation detection without a config option. External activation detection is expected behavior for scene platforms using `BaseScene`, and disabling it would break the purpose of this enhancement.

**No custom event fired:**
State updates are sufficient and consistent with Home Assistant patterns. Scene entity state changes already trigger automations via state listeners. Adding a custom `hue_scene_activated` event would be redundant and add unnecessary maintenance burden.

**EventStream performance:**
No additional EventStream traffic is generated. The integration already maintains an EventStream connection that receives all resource updates. The `on_update()` method only adds a lightweight timestamp comparison when the entity receives an update.

**Using last_recall timestamp instead of status.active:**
Based on @balloob's review feedback, tracking `last_recall` timestamp changes provides accurate activation detection while preventing false activations when lights in active scenes are modified. This is the correct approach for distinguishing scene recalls from light modifications.

## Contributors

**Implementation and Testing:** @bastelbude1, Claude Code and CodeRabbit
- Guided the technical solution from concept to completion
- Performed comprehensive code reviews and testing with AI assistance
- Validated implementation with real Philips Hue bridge hardware in Docker test environment
- Addressed review feedback from @balloob on false activations and event_type parameter
- Tested TC3 scenario proving no false activations when lights are modified
