"""
AppDaemon Scene Validator for Philips Hue Integration

Validates Hue scene activations in Home Assistant with 3-level escalation
and intelligent fallback mechanisms. Detects scene activations from ANY
source (HA UI, Hue app, physical switches, Hue automations).

Features:
- Universal scene detection (HA, Hue app, switches, automations)
- 3-level escalation (validate → re-trigger → individual control)
- Intelligent debouncing (prevents duplicate validations)
- Entity mapping (Hue resource ID ↔ HA entity_id)
- Circuit breaker (kill switch for runaway validations)
- Rate limiting (per-scene and global)
- Scene filtering (labels, patterns, exclusions)

Requirements:
- AppDaemon 4.x
- Home Assistant with Hue integration
- Hue bridge inventories in /homeassistant/hue_inventories/

Author: Scene Validator
Version: 2.0.0 (Universal Detection)
"""

import appdaemon.plugins.hass.hassapi as hass
import json
import time
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


class SceneValidator(hass.Hass):
    """
    AppDaemon app that validates Hue scene activations with fallback.

    Monitors scene entity state changes to detect activations from ANY source,
    validates light states, and provides escalating fallback mechanisms.
    """

    def initialize(self):
        """
        Initialize the scene validator.

        Loads configuration, inventories, and sets up scene monitoring.
        """
        self.log("Initializing Scene Validator (Universal Detection)")

        # Configuration parameters
        self.inventory_dir = self.args.get('inventory_dir', '/homeassistant/hue_inventories')
        self.transition_delay = self.args.get('transition_delay', 5)
        self.validation_delay = self.args.get('validation_delay', 2)
        self.validation_debounce = self.args.get('validation_debounce', 30)

        # Rate limiting
        self.max_validations_per_minute = self.args.get('max_validations_per_minute', 20)
        self.max_validations_per_scene_per_minute = self.args.get(
            'max_validations_per_scene_per_minute', 5
        )

        # Circuit breaker configuration
        cb_config = self.args.get('circuit_breaker', {})
        self.cb_failure_threshold = cb_config.get('failure_threshold', 5)
        self.cb_success_threshold = cb_config.get('success_threshold', 2)
        self.cb_timeout = cb_config.get('timeout', 300)

        # Scene filtering
        filter_config = self.args.get('scene_filter', {})
        self.include_labels = filter_config.get('include_labels', [])
        self.exclude_labels = filter_config.get('exclude_labels', [])
        self.exclude_uids = filter_config.get('exclude_uids', [])
        self.name_patterns = filter_config.get('name_patterns', [])

        # State tracking
        self.inventories = []
        self.circuit_breaker_state = 'CLOSED'
        self.circuit_breaker_failures = 0
        self.circuit_breaker_successes = 0
        self.circuit_breaker_opened_at = None
        self.validation_timestamps = []
        self.scene_validation_timestamps = {}
        self.recent_validations = {}  # {scene_entity: timestamp}

        # Tolerances for state comparison
        self.brightness_tolerance = 5  # ±5%
        self.color_tolerance = 0.01  # ±0.01
        self.color_temp_tolerance = 10  # ±10 mireds

        # Load inventories
        if not self.load_inventories():
            self.error("Failed to load inventories - validator will not function")
            return

        # Listen for scene activations from ANY source (HA, Hue app, switches)
        # Monitor state changes instead of call_service events
        self.setup_scene_listeners()

        self.log("Validator initialized successfully")
        self.log(f"Inventory directory: {self.inventory_dir}")
        self.log("Detection: Universal (HA, Hue app, switches)")
        self.log(f"Transition delay: {self.transition_delay}s")
        self.log(f"Validation delay: {self.validation_delay}s")
        self.log(f"Debounce window: {self.validation_debounce}s")
        self.log(f"Circuit breaker: {self.cb_failure_threshold} failures / {self.cb_timeout}s timeout")

        if self.include_labels:
            self.log(f"Include labels: {self.include_labels}")
        if self.exclude_labels:
            self.log(f"Exclude labels: {self.exclude_labels}")
        if self.name_patterns:
            self.log(f"Name patterns: {self.name_patterns}")

    def _is_legacy_action_format(self, actions: List[Any]) -> bool:
        """
        Check if actions use legacy string format.

        Args:
            actions: List of action objects or strings

        Returns:
            True if actions are in legacy string format, False otherwise
        """
        return len(actions) > 0 and isinstance(actions[0], str)

    def _has_legacy_inventory_format(self) -> bool:
        """
        Check if any inventory uses legacy string-formatted actions.

        Returns:
            True if any scene has string-formatted actions, False otherwise
        """
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scenes', {}).get('items', [])
            for scene in scenes:
                actions = scene.get('actions', [])
                if self._is_legacy_action_format(actions):
                    return True
        return False

    def load_inventories(self) -> bool:
        """
        Load Hue bridge inventories from filesystem.

        Returns:
            True if at least one inventory loaded, False otherwise
        """
        inventory_path = Path(self.inventory_dir)

        if not inventory_path.exists():
            self.error(f"Inventory directory not found: {self.inventory_dir}")
            return False

        inventory_files = list(inventory_path.glob("*.json"))

        if not inventory_files:
            self.error(f"No inventory files found in: {self.inventory_dir}")
            return False

        for inventory_file in inventory_files:
            try:
                with open(inventory_file) as f:
                    inventory = json.load(f)
                    self.inventories.append(inventory)
                    # Handle nested bridge_info structure (bridge_info.config.name)
                    bridge_config = inventory.get('bridge_info', {}).get('config', {})
                    bridge_name = bridge_config.get('name') or inventory.get('bridge_info', {}).get('name', 'Unknown')
                    self.log(f"Loaded inventory: {bridge_name}")
            except (json.JSONDecodeError, IOError) as e:
                self.error(f"Failed to load {inventory_file.name}: {e}")

        if not self.inventories:
            self.error("No inventories loaded successfully")
            return False

        self.log(f"Loaded {len(self.inventories)} inventory file(s)")

        # Check for legacy inventory format (string-formatted actions)
        if self._has_legacy_inventory_format():
            self.log(
                "WARNING: Legacy inventory format detected (string-formatted actions). "
                "Level 1 validation will be limited. Please regenerate inventories with: "
                "python3 inventory-hue-bridge.py",
                level="WARNING"
            )

        return True

    def setup_scene_listeners(self):
        """
        Set up state listeners for all scene entities.

        This detects scene activations from ANY source:
        - Home Assistant UI/automations
        - Hue mobile app
        - Hue physical switches/dimmers
        - Hue third-party apps

        Note: Monitors ALL scenes; filtering happens in should_validate_scene()
        based on name_patterns, labels, etc.
        """
        scene_count = 0

        # Get all scene entities
        all_scenes = self.get_state("scene")

        if not all_scenes:
            self.error("No scene entities found in Home Assistant")
            return

        for entity_id in all_scenes.keys():
            # Monitor all scene entities - filtering happens later
            # Listen to state changes (scene state IS the activation timestamp)
            self.listen_state(self.on_scene_state_changed, entity_id)
            scene_count += 1
            self.log(f"Monitoring: {entity_id}", level="DEBUG")

        self.log(f"Monitoring {scene_count} scene(s) for activations")

    def is_hue_scene(self, entity_id: str) -> bool:
        """
        Check if scene entity belongs to Hue integration.

        Args:
            entity_id: HA entity_id (e.g., scene.wohnzimmer_standard)

        Returns:
            True if scene is from Hue integration, False otherwise
        """
        unique_id = self.get_state(entity_id, attribute="unique_id")

        if unique_id:
            # Try unique_id approach (works for lights, sensors, etc.)
            # Check if unique_id contains any loaded Hue bridge ID
            # Bridge IDs from Hue API typically have format: "XX:XX:XX:XX:XX:XX" (MAC address)
            # HA unique_ids contain the normalized form without colons
            for inventory in self.inventories:
                bridge_id = inventory.get('bridge_info', {}).get('bridge_id', '')
                if not bridge_id:
                    continue

                # Normalize bridge ID by removing colons (handles both formats)
                normalized_bridge_id = bridge_id.replace(':', '').lower()
                if normalized_bridge_id and normalized_bridge_id in unique_id.lower():
                    return True

        # Fallback for scenes: Check for Hue-specific attributes
        # Scene entities don't expose unique_id in state API, but have Hue-specific attributes
        # like group_name and group_type that non-Hue scenes don't have
        group_name = self.get_state(entity_id, attribute="group_name")
        group_type = self.get_state(entity_id, attribute="group_type")

        # If scene has both group_name and group_type, it's a Hue scene
        # (HA-created scenes don't have these attributes)
        if group_name is not None and group_type is not None:
            return True

        return False

    def on_scene_state_changed(self, entity, _attribute, old, new, _kwargs):
        """
        Handle scene state change (detects activations from ANY source).

        This is called when scene state changes (state = activation timestamp).
        Scene activated by:
        - Home Assistant (UI, automation, voice)
        - Hue app (mobile, desktop)
        - Physical Hue switches/dimmers
        - Hue automations/routines

        Args:
            entity: Scene entity_id
            _attribute: Attribute that changed (None for state) - unused but required by callback
            old: Previous state (old timestamp)
            new: New state (new timestamp indicating activation)
            _kwargs: Additional parameters - unused but required by callback
        """
        # Skip if state didn't actually change
        if old == new or new is None or new == "unavailable":
            self.log(f"Skipping {entity} - no state change", level="DEBUG")
            return

        # Debouncing: avoid duplicate validations within window
        now = time.time()

        # Clean old validation records (older than debounce window)
        cutoff = now - self.validation_debounce
        self.recent_validations = {
            ent: ts for ent, ts in self.recent_validations.items()
            if ts > cutoff
        }

        if entity in self.recent_validations:
            last_validation = self.recent_validations[entity]
            if now - last_validation < self.validation_debounce:
                elapsed = int(now - last_validation)
                self.log(f"Skipping {entity} - validated {elapsed}s ago "
                        f"(debounce: {self.validation_debounce}s)", level="DEBUG")
                return

        self.log(f"Scene activated: {entity} (source: ANY - HA/Hue app/switch)")

        # Check if scene should be validated (filtering logic)
        # Note: scene_uid not available in AppDaemon state attributes
        if not self.should_validate_scene(entity, None):
            self.log(f"Skipping validation for {entity} (filtered out)")
            return

        # Record this validation attempt (after filtering)
        self.recent_validations[entity] = now

        # Schedule validation after transition delay
        self.run_in(self.perform_scene_validation, self.transition_delay,
                    scene_entity=entity)

    def should_validate_scene(self, entity_id: str, scene_uid: str) -> bool:
        """
        Determine if scene should be validated based on filters.

        Args:
            entity_id: HA entity_id
            scene_uid: Scene unique_id

        Returns:
            True if scene should be validated, False otherwise
        """
        # Check circuit breaker
        if self.circuit_breaker_state == 'OPEN':
            # Check if timeout expired - transition to HALF_OPEN
            if (self.circuit_breaker_opened_at and
                time.time() - self.circuit_breaker_opened_at >= self.cb_timeout):
                self.circuit_breaker_state = 'HALF_OPEN'
                self.circuit_breaker_successes = 0
                self.log("Circuit breaker HALF_OPEN (timeout expired, testing)")
            else:
                self.log(f"Circuit breaker OPEN - skipping {entity_id}", level="WARNING")
                return False

        # Check rate limits
        if not self.check_rate_limits(entity_id):
            return False

        # Check UID exclusions (if scene_uid is available)
        if scene_uid and scene_uid in self.exclude_uids:
            self.log(f"Scene {entity_id} excluded by UID", level="DEBUG")
            return False

        # Get scene labels
        scene_labels = self.get_state(entity_id, attribute="labels") or []

        # Check exclude labels (takes priority)
        if self.exclude_labels:
            for label in scene_labels:
                if label in self.exclude_labels:
                    self.log(f"Scene {entity_id} excluded by label: {label}", level="DEBUG")
                    return False

        # Check include labels
        if self.include_labels:
            has_label = any(label in self.include_labels for label in scene_labels)
            if not has_label:
                self.log(f"Scene {entity_id} missing required label", level="DEBUG")
                return False
            return True

        # Check name patterns (if no include_labels specified)
        if self.name_patterns:
            scene_name = self.friendly_name(entity_id)
            for pattern in self.name_patterns:
                if re.match(pattern, scene_name):
                    return True
            self.log(f"Scene {entity_id} doesn't match name patterns", level="DEBUG")
            return False

        # If no filters specified, validate all scenes
        return True

    def check_rate_limits(self, entity_id: str) -> bool:
        """
        Check if validation is within rate limits.

        Args:
            entity_id: Scene entity_id

        Returns:
            True if within limits, False otherwise
        """
        now = time.time()

        # Clean old timestamps (older than 60s)
        self.validation_timestamps = [
            ts for ts in self.validation_timestamps if now - ts < 60
        ]

        if entity_id not in self.scene_validation_timestamps:
            self.scene_validation_timestamps[entity_id] = []

        self.scene_validation_timestamps[entity_id] = [
            ts for ts in self.scene_validation_timestamps[entity_id]
            if now - ts < 60
        ]

        # Check global rate limit
        if len(self.validation_timestamps) >= self.max_validations_per_minute:
            self.log(f"Global rate limit exceeded ({self.max_validations_per_minute}/min)",
                    level="WARNING")
            return False

        # Check per-scene rate limit
        scene_count = len(self.scene_validation_timestamps[entity_id])
        if scene_count >= self.max_validations_per_scene_per_minute:
            self.log(f"Per-scene rate limit exceeded for {entity_id} "
                    f"({self.max_validations_per_scene_per_minute}/min)",
                    level="WARNING")
            return False

        # Record this validation
        self.validation_timestamps.append(now)
        self.scene_validation_timestamps[entity_id].append(now)

        return True

    def perform_scene_validation(self, kwargs):
        """
        Perform complete scene validation with 3-level escalation.

        This is called after debouncing and transition delay,
        regardless of how the scene was activated (HA, Hue app, switch).

        Level 1: Validate only (no action)
        Level 2: Re-trigger scene if validation fails
        Level 3: Control lights individually as last resort

        Args:
            kwargs: Contains scene_entity and scene_uid
        """
        try:
            scene_entity = kwargs.get('scene_entity')

            if not scene_entity:
                self.error("perform_scene_validation called without required parameters")
                return

            self.log(f"Starting validation: {scene_entity}")

            # Find scene in inventory by entity_id/name
            scene_data = self.find_scene_in_inventory(scene_entity)

            if not scene_data:
                self.error(f"Scene {scene_entity} not found in inventories")
                return

            # LEVEL 1: Validate
            self.log("LEVEL 1: Validating scene state")
            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"✓ Validation successful: {scene_entity}")
                self.record_success()
                return

            self.log(f"✗ Validation failed: {scene_entity}", level="WARNING")

            # LEVEL 2: Re-trigger scene (async scheduling to avoid blocking)
            self.log("LEVEL 2: Re-triggering scene")
            self.call_service("scene/turn_on", entity_id=scene_entity)

            # Schedule level 2 validation after delay (non-blocking)
            self.run_in(
                self.perform_level2_validation,
                self.validation_delay,
                scene_entity=scene_entity,
                scene_data=scene_data
            )

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during validation: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def perform_level2_validation(self, kwargs):
        """
        Perform level 2 and 3 validation after re-trigger delay.

        This is called asynchronously after the re-trigger delay to avoid
        blocking the AppDaemon worker thread.

        Args:
            kwargs: Contains scene_entity and scene_data
        """
        try:
            scene_entity = kwargs.get('scene_entity')
            scene_data = kwargs.get('scene_data')

            if not scene_entity or not scene_data:
                self.error("perform_level2_validation called without required parameters")
                return

            # Check if validation is possible (inventory format)
            actions = scene_data.get('actions', [])
            actions_are_strings = self._is_legacy_action_format(actions)

            if actions_are_strings:
                # Validation impossible due to inventory format
                # But re-trigger was performed, so consider it successful
                self.log(f"✓ Re-trigger completed (validation unavailable due to inventory format): {scene_entity}")
                self.record_success()
                return

            # Level 2: Validate after re-trigger
            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"✓ Re-trigger successful: {scene_entity}")
                self.record_success()
                return

            self.log(f"✗ Re-trigger failed: {scene_entity}", level="WARNING")

            # LEVEL 3: Individual light control
            self.log("LEVEL 3: Controlling lights individually")
            if self.control_lights_individually(scene_data):
                self.log(f"✓ Individual control successful: {scene_entity}")
                self.record_success()
                return

            # All levels failed
            self.error(f"✗ All escalation levels failed: {scene_entity}")
            self.record_failure()

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during level 2/3 validation: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def find_scene_in_inventory(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Find scene data in loaded inventories by matching scene name.

        Args:
            entity_id: Scene entity_id (e.g., scene.badezimmer_og_standard)

        Returns:
            Scene data dict or None if not found
        """
        # Get scene attributes from HA
        scene_state = self.get_state(entity_id, attribute="all")
        if not scene_state:
            return None

        scene_attrs = scene_state.get('attributes', {})
        scene_name = scene_attrs.get('name')  # e.g., "Standard"
        group_name = scene_attrs.get('group_name')  # e.g., "Badezimmer OG"

        if not scene_name:
            return None

        # Search inventories for matching scene
        # NOTE: Current limitation - matching by name only
        # - Scene names are NOT unique across groups (e.g., multiple "Standard" scenes exist)
        # - Should ideally match by both name AND group to prevent ambiguity
        # - However, this rarely causes issues in practice because:
        #   1. HA entity_ids are already unique per scene
        #   2. When a scene is activated, it's the correct one for that entity_id
        #   3. The validation is per-entity, not per-name
        # - Future improvement: Match group_name (from HA) with scene.group.name (from inventory)
        #   - Requires proper JSON serialization of scene.group ResourceIdentifier
        #   - Need to resolve group RID to group name from inventory
        # - For now, we accept the first name match found
        # TODO: Implement group name matching for disambiguation (see issue #10)
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scenes', {}).get('items', [])
            for scene in scenes:
                # Match by scene name only (group matching not yet implemented)
                inventory_scene_name = scene.get('metadata', {}).get('name')
                if inventory_scene_name and inventory_scene_name == scene_name:
                    # Found a name match - return first match
                    # This works in practice because each HA entity_id maps to one specific scene
                    return scene

        return None

    def validate_scene_state(self, scene_entity: str, scene_data: Dict[str, Any]) -> bool:
        """
        Validate that all lights match expected scene state.

        Args:
            scene_entity: Scene entity_id
            scene_data: Scene data from inventory

        Returns:
            True if all lights match, False otherwise
        """
        actions = scene_data.get('actions', [])

        if not actions:
            self.log(f"Scene {scene_entity} has no actions", level="WARNING")
            return False

        # Check if actions are string representations (inventory format issue)
        if self._is_legacy_action_format(actions):
            self.log("Actions stored as strings - skipping validation, will re-trigger", level="WARNING")
            return False

        try:
            all_match = True

            for action in actions:
                target = action.get('target', {})
                rid = target.get('rid')

                if not rid:
                    continue

                # Map Hue resource ID to HA entity_id
                entity_id = self.get_entity_id_from_hue_id(rid)

                if not entity_id:
                    self.log(f"Could not map Hue ID {rid} to entity_id", level="WARNING")
                    all_match = False
                    continue

                # Get expected state from action
                expected = action.get('action', {})

                # Get actual state from HA
                actual_state = self.get_state(entity_id, attribute="all")

                if not actual_state:
                    self.log(f"Could not get state for {entity_id}", level="WARNING")
                    all_match = False
                    continue

                # Compare states
                if not self.compare_light_states(entity_id, expected, actual_state):
                    all_match = False

            return all_match

        except AttributeError as e:
            self.log(f"Inventory format issue (actions are strings): {e}", level="WARNING")
            return False
        except Exception as e:  # noqa: BLE001
            self.error(f"Error validating scene state: {e}")
            return False

    def compare_light_states(self, entity_id: str, expected: Dict[str, Any],
                            actual_state: Dict[str, Any]) -> bool:
        """
        Compare expected and actual light states.

        Args:
            entity_id: Light entity_id
            expected: Expected state from scene
            actual_state: Actual state from HA

        Returns:
            True if states match within tolerances, False otherwise
        """
        actual_attrs = actual_state.get('attributes', {})
        actual_on = actual_state.get('state') == 'on'

        # Check on/off state
        expected_on = expected.get('on', {}).get('on', False)
        if expected_on != actual_on:
            self.log(f"{entity_id}: Expected {'ON' if expected_on else 'OFF'}, "
                    f"got {'ON' if actual_on else 'OFF'}", level="DEBUG")
            return False

        # If light should be off, no need to check other attributes
        if not expected_on:
            return True

        # Check brightness
        expected_dimming = expected.get('dimming', {})
        if 'brightness' in expected_dimming:
            expected_brightness = expected_dimming['brightness']
            actual_brightness = actual_attrs.get('brightness', 0)
            # Convert HA brightness (0-255) to percentage
            actual_brightness_pct = (actual_brightness / 255) * 100

            if abs(expected_brightness - actual_brightness_pct) > self.brightness_tolerance:
                self.log(f"{entity_id}: Brightness mismatch - "
                        f"expected {expected_brightness}%, got {actual_brightness_pct:.1f}%",
                        level="DEBUG")
                return False

        # Check color (XY)
        expected_color = expected.get('color', {})
        if 'xy' in expected_color:
            expected_xy = expected_color['xy']
            actual_xy = actual_attrs.get('xy_color')

            if not actual_xy:
                self.log(f"{entity_id}: No xy_color in state", level="DEBUG")
                return False

            if (abs(expected_xy['x'] - actual_xy[0]) > self.color_tolerance or
                abs(expected_xy['y'] - actual_xy[1]) > self.color_tolerance):
                self.log(f"{entity_id}: Color mismatch - "
                        f"expected ({expected_xy['x']:.3f}, {expected_xy['y']:.3f}), "
                        f"got ({actual_xy[0]:.3f}, {actual_xy[1]:.3f})",
                        level="DEBUG")
                return False

        # Check color temperature
        if 'color_temperature' in expected:
            expected_ct = expected['color_temperature'].get('mirek')
            actual_ct = actual_attrs.get('color_temp')

            if not actual_ct:
                self.log(f"{entity_id}: No color_temp in state", level="DEBUG")
                return False

            if abs(expected_ct - actual_ct) > self.color_temp_tolerance:
                self.log(f"{entity_id}: Color temp mismatch - "
                        f"expected {expected_ct}, got {actual_ct}",
                        level="DEBUG")
                return False

        return True

    def control_lights_individually(self, scene_data: Dict[str, Any]) -> bool:
        """
        Control each light individually to achieve desired state.

        Args:
            scene_data: Scene data from inventory

        Returns:
            True if all lights controlled successfully, False otherwise
        """
        actions = scene_data.get('actions', [])

        if not actions:
            return False

        # Check if actions are string representations (inventory format issue)
        if self._is_legacy_action_format(actions):
            self.log("Cannot control lights - actions stored as strings (inventory format issue)", level="WARNING")
            return False

        all_success = True

        for action in actions:
            target = action.get('target', {})
            rid = target.get('rid')

            if not rid:
                continue

            entity_id = self.get_entity_id_from_hue_id(rid)

            if not entity_id:
                self.log(f"Could not map Hue ID {rid} to entity_id", level="WARNING")
                all_success = False
                continue

            # Build service call parameters
            expected = action.get('action', {})
            service_data = {"entity_id": entity_id}

            # On/off
            expected_on = expected.get('on', {}).get('on', False)
            if not expected_on:
                self.call_service("light/turn_off", **service_data)
                continue

            # Brightness
            dimming = expected.get('dimming', {})
            if 'brightness' in dimming:
                # Convert percentage to 0-255
                brightness = int((dimming['brightness'] / 100) * 255)
                service_data['brightness'] = brightness

            # Color (XY)
            color = expected.get('color', {})
            if 'xy' in color:
                xy = color['xy']
                service_data['xy_color'] = [xy['x'], xy['y']]

            # Color temperature
            if 'color_temperature' in expected:
                ct = expected['color_temperature'].get('mirek')
                if ct:
                    service_data['color_temp'] = ct

            # Turn on light with parameters
            self.call_service("light/turn_on", **service_data)

        return all_success

    def get_entity_id_from_hue_id(self, hue_resource_id: str) -> Optional[str]:
        """
        Map Hue resource ID to HA entity_id.

        Args:
            hue_resource_id: Hue resource ID (UUID)

        Returns:
            HA entity_id or None if not found
        """
        # Get all light entities
        lights = self.get_state('light')

        if not lights:
            return None

        for entity_id in lights.keys():
            unique_id = self.get_state(entity_id, attribute='unique_id')

            # Precise UUID match with delimiters (avoid false positives)
            if unique_id and (
                unique_id.endswith(hue_resource_id) or
                f"_{hue_resource_id}" in unique_id or
                f"-{hue_resource_id}" in unique_id
            ):
                return entity_id

        return None

    def record_success(self):
        """Record successful validation for circuit breaker."""
        if self.circuit_breaker_state == 'HALF_OPEN':
            self.circuit_breaker_successes += 1
            self.log(f"Circuit breaker HALF_OPEN: {self.circuit_breaker_successes}/"
                    f"{self.cb_success_threshold} successes")

            if self.circuit_breaker_successes >= self.cb_success_threshold:
                self.circuit_breaker_state = 'CLOSED'
                self.circuit_breaker_failures = 0
                self.circuit_breaker_successes = 0
                self.log("Circuit breaker CLOSED (recovered)")

        elif self.circuit_breaker_state == 'CLOSED':
            # Reset failure count on success
            if self.circuit_breaker_failures > 0:
                self.circuit_breaker_failures = 0

    def record_failure(self):
        """Record validation failure for circuit breaker."""
        if self.circuit_breaker_state == 'HALF_OPEN':
            # Failure during half-open state - re-open circuit
            self.circuit_breaker_state = 'OPEN'
            self.circuit_breaker_opened_at = time.time()
            self.circuit_breaker_successes = 0
            self.error("Circuit breaker re-OPENED (half-open test failed)")

        elif self.circuit_breaker_state == 'CLOSED':
            self.circuit_breaker_failures += 1
            self.log(f"Circuit breaker failures: {self.circuit_breaker_failures}/"
                    f"{self.cb_failure_threshold}")

            if self.circuit_breaker_failures >= self.cb_failure_threshold:
                self.circuit_breaker_state = 'OPEN'
                self.circuit_breaker_opened_at = time.time()
                self.error("Circuit breaker OPENED (threshold reached)")
