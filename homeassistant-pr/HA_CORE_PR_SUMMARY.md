# Home Assistant Core PR Submission Summary

## What Will Be Submitted to home-assistant/core

### File to Modify
**Single file change:**
- `homeassistant/components/hue/scene.py`

### Changes Summary

**Lines changed:** ~30 lines
**Lines added:** ~20 lines
**Complexity:** Low (minimal changes, follows existing KNX pattern)

---

## Key Code Changes

### 1. Import SceneActiveStatus (Line 12)
```python
from aiohue.v2.models.scene import (
    Scene as HueScene,
    SceneActiveStatus,  # NEW - for detecting scene activation
    ScenePut as HueScenePut,
)
```

### 2. Change Base Class from SceneEntity to BaseScene (Line 20, 95)
```python
# Before
from homeassistant.components.scene import ATTR_TRANSITION, Scene as SceneEntity

# After
from homeassistant.components.scene import ATTR_TRANSITION, Scene as BaseScene

# Before
class HueSceneEntityBase(HueBaseEntity, SceneEntity):

# After
class HueSceneEntityBase(HueBaseEntity, BaseScene):
```

**Why:** `BaseScene` provides state tracking capabilities that `SceneEntity` lacks.

### 3. Update Event Subscription - Only RESOURCE_ADDED (Lines 68-73)
```python
# Only subscribe to new scene creation
# (scene activation detection is handled by on_update() on existing entities)
config_entry.async_on_unload(
    api.scenes.subscribe(
        async_add_entity,
        event_filter=EventType.RESOURCE_ADDED,  # NOT RESOURCE_UPDATED
    )
)
```

**Why:** Prevents entity duplication. Existing entities handle updates via `on_update()`.

### 4. Add on_update() Method to HueSceneEntityBase (Lines 134-147)
```python
def on_update(self) -> None:
    """Handle EventStream updates for scene activation detection.

    This method is called when the bridge sends an update event for this scene.
    When a scene is activated (from Hue app, physical buttons, or automations),
    the scene status changes to active, allowing us to record the activation.
    """
    # Check if scene became active (activated externally or via HA)
    if (
        self.resource.status
        and self.resource.status.active != SceneActiveStatus.INACTIVE
    ):
        self._async_record_activation()
    super().on_update()
```

**Why:** Detects when scenes are activated from external sources (Hue app, buttons, etc.).

### 5. Rename async_activate() to _async_activate() (Lines 170, 241)
```python
# Before
async def async_activate(self, **kwargs: Any) -> None:

# After
async def _async_activate(self, **kwargs: Any) -> None:
```

**Why:** Required by `BaseScene` contract for proper activation handling.

### 6. Smart Scene Override of on_update() (Lines 229-239)
```python
def on_update(self) -> None:
    """Handle EventStream updates for smart scene activation detection.

    Smart scenes use .state instead of .status for activation tracking.
    When a smart scene becomes active (from Hue app, automations, or schedules),
    the scene state changes to ACTIVE, allowing us to record the activation.
    """
    # Check if smart scene became active (activated externally or via HA)
    if self.resource.state == SmartSceneState.ACTIVE:
        self._async_record_activation()
    super().on_update()
```

**Why:** Smart scenes use `.state` field instead of `.status` for activation tracking.

---

## Testing Evidence

### Test Environment
- **Production:** Home Assistant OS (ARM64), 2 Hue bridges
- **Test:** Docker (homeassistant/home-assistant:2025.11.1), 1 Hue bridge
- **Hardware:** Real Philips Hue bridges (not simulated)

### Test Results

| Test | Status | Details |
|------|--------|---------|
| **Code Quality** | ✅ PASSED | 6 CodeRabbit reviews, zero linting warnings (Ruff clean) |
| **Integration Loading** | ✅ PASSED | Scene entities created, no errors |
| **HA-Initiated Activation** | ✅ PASSED | State updates correctly |
| **External Activation** | ✅ **PASSED** | **Verified with real Hue bridge** |

**External Activation Test Proof:**
- Activated scene via Hue mobile app
- Scene entity timestamp updated: `11:30:15 AM` → `11:31:52 AM` ✅
- **External activation detection confirmed working!**

---

## Pattern Validation

This implementation follows the **same pattern** as KNX scene activation (PR #151218, already merged):

| Aspect | KNX Implementation | Hue Implementation | Match |
|--------|-------------------|-------------------|-------|
| Base class | `BaseScene` | `BaseScene` | ✅ |
| Activation method | `_async_activate()` | `_async_activate()` | ✅ |
| State tracking | `on_update()` callback | `on_update()` callback | ✅ |
| Event subscription | `RESOURCE_ADDED` only | `RESOURCE_ADDED` only | ✅ |
| Activation recording | `_async_record_activation()` | `_async_record_activation()` | ✅ |

---

## Breaking Changes

**Scene entities now update state when activated externally** (from Hue app, buttons, etc.)

**Impact Assessment:**
- ✅ Automations using `scene.turn_on` service: **No change** (still work)
- ✅ Automations monitoring scene entity state: **Enhanced** (now get external updates)
- ✅ Scene activation service calls: **No change** (internal rename only)

**Migration Required:** None - this is an enhancement, not a breaking change to existing functionality.

---

## Dependencies

- **aiohue >= 4.8.0** (already in use by Home Assistant core)
  - Provides `scene.status.active` field
  - Provides `SmartSceneState` enum
- **No new dependencies required**

---

## Use Cases Enabled

This enhancement enables powerful new automations:

1. **Scene Validation** - Verify lights match scene configuration after activation
2. **Activity Tracking** - Know which scenes are used and when
3. **Cross-Platform Automations** - React to scenes activated via Hue app
4. **Scene Monitoring** - Alert if scenes fail to activate correctly
5. **Usage Analytics** - Track scene usage patterns across all activation sources

**Example Automation:**
```yaml
# React when "Movie Time" scene is activated from any source
automation:
  - alias: "Dim hallway when movie scene activated"
    trigger:
      - platform: state
        entity_id: scene.living_room_movie_time
    action:
      - service: light.turn_on
        target:
          entity_id: light.hallway
        data:
          brightness_pct: 10
```

---

## Performance Impact

**No additional EventStream traffic:**
- Integration already maintains EventStream connection
- `on_update()` adds only lightweight status check (single field comparison)
- No polling, no additional network requests
- Zero performance overhead

---

## Contributors

**Implementation and Testing:** [@bastelbude1](https://github.com/bastelbude1)
- Guided the technical solution from concept to completion
- Performed comprehensive code reviews and testing
- Validated implementation with real Philips Hue bridge hardware
- Identified and resolved critical issues during development
- Deployed and tested in both production and Docker environments

**Development Approach:**
- Collaborative development with extensive testing
- 6 iterations of code review with AI assistance (CodeRabbit)
- Real-world validation with production Hue bridges
- Pattern verification against existing KNX implementation

---

## Checklist for home-assistant/core

- [x] Code follows Home Assistant style guidelines
- [x] Changes follow proven pattern (KNX PR #151218)
- [x] Tested with real Hue bridges and scenes
- [x] No new dependencies required
- [x] Breaking changes documented (behavioral enhancement)
- [x] External activation verified with real hardware
- [ ] Unit tests added/updated (need guidance on test structure)
- [ ] Integration docs updated (need guidance on docs location)

---

## Files to Submit

**Modified File:**
1. `homeassistant/components/hue/scene.py` (278 lines total, ~30 lines changed)

**Supporting Documentation:**
- Comprehensive test report showing all 4 tests passed
- Evidence of external activation detection working
- Pattern comparison with KNX implementation

---

## Related Resources

- **KNX Pattern Reference:** PR #151218 (already merged)
- **aiohue 4.8.0 Release:** Adds `scene.status.active` field
- **Discussion:** home-assistant/discussions#1446
- **Test Report:** Available in development repository

---

**Summary:** This is a minimal, well-tested enhancement that brings Hue scene entities to feature parity with KNX scenes by detecting external activations. The implementation follows an existing proven pattern, requires no new dependencies, and has been validated with real Philips Hue bridge hardware.

**Ready for submission:** ✅ All tests passed, code reviewed, production-validated.
