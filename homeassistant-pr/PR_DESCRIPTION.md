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
2. **Detecting activation via status field** - Monitor `scene.status.active` field changes (added in aiohue 4.8.0)
3. **Recording activations** - Call `_async_record_activation()` when scenes become active
4. **Using BaseScene** - Inherit from `BaseScene` instead of `SceneEntity` to enable state tracking

This follows the same pattern recently implemented for KNX scene activation detection (PR #151218).

## Changes

### Modified Files

**homeassistant/components/hue/scene.py:**
- Import `SceneActiveStatus` from aiohue
- Change `Scene as SceneEntity` → `Scene as BaseScene`
- Change `HueSceneEntityBase` base class: `SceneEntity` → `BaseScene`
- Rename `async_activate()` → `_async_activate()` (both scene classes)
- Add `on_update()` method to detect activation via EventStream (entities listen for their own updates)
- Smart scenes override `on_update()` to use `.state` instead of `.status` for activation tracking

### Key Changes Explained

**1. Base Class Change (Line 98):**
```python
# Before
class HueSceneEntityBase(HueBaseEntity, SceneEntity):

# After
class HueSceneEntityBase(HueBaseEntity, BaseScene):
```
`BaseScene` provides state tracking capabilities that `SceneEntity` lacks.

**2. Event Subscription (Lines 70-74):**
```python
# Only subscribe to new scenes - activation is handled by on_update()
config_entry.async_on_unload(
    api.scenes.subscribe(
        async_add_entity,
        event_filter=EventType.RESOURCE_ADDED,
    )
)
```
Entities listen for their own updates via the `on_update()` method inherited from `HueBaseEntity`.

**3. Activation Detection (Lines 135-147):**
```python
def on_update(self) -> None:
    """Handle EventStream updates for scene activation detection."""
    if (
        self.resource.status
        and self.resource.status.active != SceneActiveStatus.INACTIVE
    ):
        self._async_record_activation()
    super().on_update()
```
When the bridge activates a scene (from any source), it sets `status.active` to `STATIC` or `DYNAMIC_PALETTE`. This triggers state recording.

**4. Method Rename (Lines 169, 225):**
```python
# Before
async def async_activate(self, **kwargs: Any) -> None:

# After
async def _async_activate(self, **kwargs: Any) -> None:
```
Required by `BaseScene` to support both internal activation and state recording.

## Testing

Comprehensive testing performed with real Philips Hue bridges in both production and Docker test environments.

**Test Environment:**
- ✅ Production: Home Assistant OS (ARM64), 2 Hue bridges
- ✅ Test: Docker (homeassistant/home-assistant:2025.11.1), 1 Hue bridge
- ✅ Multiple scenes (regular and smart scenes)

**Tests Completed:**
1. ✅ **Code Quality & Review** - 6 iterations with CodeRabbit AI, all issues fixed, zero linting warnings
2. ✅ **Integration Loading** - Scene entities created successfully, no runtime errors
3. ✅ **HA-Initiated Activation** - Scene state updates correctly via Home Assistant API
4. ✅ **External Activation Detection** - **VERIFIED** scene state updates when activated via Hue mobile app

**Test 4 Evidence (Critical):**
- Baseline timestamp: `11:30:15 AM`
- Activated scene via Hue mobile app
- Updated timestamp: `11:31:52 AM` ✅
- **External activation detection confirmed working!**

**Test Results:**
- Scene entity state updates correctly for all activation methods (HA UI, API, Hue app)
- Scene activation visible in Home Assistant logbook
- Can trigger automations based on scene activation from any source
- No performance impact (uses existing EventStream connection)
- Smart scenes properly supported with state-based activation tracking

## Breaking Changes

**Scene entities now update their state when activated externally** (from Hue app, buttons, etc.).

This is a **behavioral change** but should not break existing automations:
- Automations that trigger on `scene.turn_on` service calls: **Still work** (unchanged)
- Automations that monitor scene entity state: **Now work better** (get updates from all sources)
- Scene activation service calls: **Still work** (internal method renamed but service unchanged)

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
- [ ] Tests added/updated (need assistance with test structure)
- [ ] Documentation updated (need assistance with integration docs)

## Additional Notes

This change enables powerful new use cases:
- **Scene validation** - Verify lights match scene configuration after activation
- **Activity tracking** - Know which scenes are used and when
- **Cross-platform automations** - React to scenes activated via Hue app
- **Scene monitoring** - Alert if scenes fail to activate correctly

The implementation is minimal (~20 lines added) and leverages existing infrastructure (EventStream, aiohue 4.8.0).

## Design Decisions

**No config option to disable detection:**
This feature aligns with KNX integration (PR #151218) which provides external scene activation detection without a config option. External activation detection is expected behavior for scene platforms using `BaseScene`, and disabling it would break the purpose of this enhancement.

**No custom event fired:**
State updates are sufficient and consistent with Home Assistant patterns. Scene entity state changes already trigger automations via state listeners. Adding a custom `hue_scene_activated` event would be redundant and add unnecessary maintenance burden.

**EventStream performance:**
No additional EventStream traffic is generated. The integration already maintains an EventStream connection that receives all resource updates. The `on_update()` method only adds a lightweight status check (single field comparison) when the entity receives an update.

---

## Contributors

**Implementation and Testing:** [@bastelbude1](https://github.com/bastelbude1)
- Guided the technical solution from concept to completion
- Performed comprehensive code reviews and testing
- Validated implementation with real Philips Hue bridge hardware
- Identified and resolved critical issues during development
- Deployed and tested in both production and Docker environments

This implementation was developed collaboratively with extensive testing and validation to ensure production readiness.

---

**Type of change:** Enhancement
**Affected components:** `hue`
**Related PRs:** #151218 (KNX scene activation)
