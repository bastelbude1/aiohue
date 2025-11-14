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

1. **Listening to EventStream updates** - Subscribe to `RESOURCE_UPDATED` events in addition to `RESOURCE_ADDED`
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
- Add `on_update()` method to detect activation via EventStream
- Update event subscription to include `EventType.RESOURCE_UPDATED`

### Key Changes Explained

**1. Base Class Change (Line 98):**
```python
# Before
class HueSceneEntityBase(HueBaseEntity, SceneEntity):

# After
class HueSceneEntityBase(HueBaseEntity, BaseScene):
```
`BaseScene` provides state tracking capabilities that `SceneEntity` lacks.

**2. Event Subscription (Lines 69-73):**
```python
# Before
api.scenes.subscribe(async_add_entity, event_filter=EventType.RESOURCE_ADDED)

# After
api.scenes.subscribe(
    async_add_entity,
    event_filter=(EventType.RESOURCE_ADDED, EventType.RESOURCE_UPDATED),
)
```
Now listens for scene updates in addition to creation.

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

Tested with:
- ✅ 3 Philips Hue bridges (v2 API)
- ✅ Multiple scenes ("Standard", "Nachtlicht", etc.)
- ✅ Activation via Hue mobile app
- ✅ Activation via Home Assistant UI
- ✅ Activation via Home Assistant automations

**Test Results:**
- Scene entity state updates correctly for all activation methods
- Scene activation visible in Home Assistant logbook
- Can trigger automations based on scene activation
- No performance impact (uses existing EventStream connection)

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

## Questions for Reviewers

1. Should we add a config option to disable external activation detection?
2. Should we fire a custom event (`hue_scene_activated`) in addition to state update?
3. Any concerns about EventStream message volume with `RESOURCE_UPDATED`?

---

**Type of change:** Enhancement
**Affected components:** `hue`
**Related PRs:** #151218 (KNX scene activation)
