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

        self.log(f"Validator initialized successfully")
        self.log(f"Inventory directory: {self.inventory_dir}")
        self.log(f"Detection: Universal (HA, Hue app, switches)")
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
                    bridge_name = inventory.get('bridge_info', {}).get('name', 'Unknown')
                    self.log(f"Loaded inventory: {bridge_name}")
            except (json.JSONDecodeError, IOError) as e:
                self.error(f"Failed to load {inventory_file.name}: {e}")

        if not self.inventories:
            self.error("No inventories loaded successfully")
            return False

        self.log(f"Loaded {len(self.inventories)} inventory file(s)")
        return True

    def setup_scene_listeners(self):
        """
        Set up state listeners for all Hue scene entities.

        This detects scene activations from ANY source:
        - Home Assistant UI/automations
        - Hue mobile app
        - Hue physical switches/dimmers
        - Hue third-party apps
        """
        scene_count = 0

        # Get all scene entities
        all_scenes = self.get_state("scene")

        if not all_scenes:
            self.error("No scene entities found in Home Assistant")
            return

        for entity_id in all_scenes.keys():
            if self.is_hue_scene(entity_id):
                # Listen to last_triggered attribute changes
                self.listen_state(self.on_scene_state_changed, entity_id,
                                attribute="last_triggered")
                scene_count += 1
                self.log(f"Monitoring: {entity_id}", level="DEBUG")

        self.log(f"Monitoring {scene_count} Hue scene(s) for activations")

    def is_hue_scene(self, entity_id: str) -> bool:
        """
        Check if scene entity belongs to Hue integration.

        Args:
            entity_id: HA entity_id (e.g., scene.wohnzimmer_standard)

        Returns:
            True if scene is from Hue integration, False otherwise
        """
        unique_id = self.get_state(entity_id, attribute="unique_id")

        if not unique_id:
            return False

        # Check if unique_id contains any loaded Hue bridge ID
        for inventory in self.inventories:
            bridge_id = inventory.get('bridge_info', {}).get('bridge_id', '')
            if bridge_id and bridge_id.replace(':', '') in unique_id:
                return True

        return False

    def on_scene_state_changed(self, entity, attribute, old, new, kwargs):
        """
        Handle scene state change (detects activations from ANY source).

        This is called when last_triggered attribute changes, indicating
        the scene was activated by:
        - Home Assistant (UI, automation, voice)
        - Hue app (mobile, desktop)
        - Physical Hue switches/dimmers
        - Hue automations/routines

        Args:
            entity: Scene entity_id
            attribute: Attribute that changed (last_triggered)
            old: Previous value
            new: New value
            kwargs: Additional parameters
        """
        # Skip if last_triggered didn't actually change
        if old == new or new is None:
            self.log(f"Skipping {entity} - no state change", level="DEBUG")
            return

        # Debouncing: avoid duplicate validations within window
        now = time.time()
        if entity in self.recent_validations:
            last_validation = self.recent_validations[entity]
            if now - last_validation < self.validation_debounce:
                elapsed = int(now - last_validation)
                self.log(f"Skipping {entity} - validated {elapsed}s ago "
                        f"(debounce: {self.validation_debounce}s)", level="DEBUG")
                return

        # Record this validation attempt
        self.recent_validations[entity] = now

        # Get scene unique_id for inventory lookup
        scene_uid = self.get_state(entity, attribute="unique_id")

        self.log(f"Scene activated: {entity} (source: ANY - HA/Hue app/switch)")

        # Check if scene should be validated (filtering logic)
        if not self.should_validate_scene(entity, scene_uid):
            self.log(f"Skipping validation for {entity} (filtered out)")
            return

        # Schedule validation after transition delay
        self.run_in(self.perform_scene_validation, self.transition_delay,
                    scene_entity=entity, scene_uid=scene_uid)

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
            self.log(f"Circuit breaker OPEN - skipping {entity_id}", level="WARNING")
            return False

        # Check rate limits
        if not self.check_rate_limits(entity_id):
            return False

        # Check UID exclusions
        if scene_uid in self.exclude_uids:
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
            scene_uid = kwargs.get('scene_uid')

            if not scene_entity or not scene_uid:
                self.error("perform_scene_validation called without required parameters")
                return

            self.log(f"Starting validation: {scene_entity} (uid: {scene_uid})")

            # Find scene in inventory
            scene_data = self.find_scene_in_inventory(scene_uid)

            if not scene_data:
                self.error(f"Scene {scene_entity} not found in inventories")
                return

            # LEVEL 1: Validate
            self.log(f"LEVEL 1: Validating scene state")
            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"✓ Validation successful: {scene_entity}")
                self.record_success()
                return

            self.log(f"✗ Validation failed: {scene_entity}", level="WARNING")

            # LEVEL 2: Re-trigger scene
            self.log(f"LEVEL 2: Re-triggering scene")
            self.call_service("scene/turn_on", entity_id=scene_entity)
            self.sleep(self.validation_delay)

            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"✓ Re-trigger successful: {scene_entity}")
                self.record_success()
                return

            self.log(f"✗ Re-trigger failed: {scene_entity}", level="WARNING")

            # LEVEL 3: Individual light control
            self.log(f"LEVEL 3: Controlling lights individually")
            if self.control_lights_individually(scene_data):
                self.log(f"✓ Individual control successful: {scene_entity}")
                self.record_success()
                return

            # All levels failed
            self.error(f"✗ All escalation levels failed: {scene_entity}")
            self.record_failure()

        except Exception as e:
            self.error(f"Exception during validation: {e}")
            self.record_failure()

    def find_scene_in_inventory(self, scene_uid: str) -> Optional[Dict[str, Any]]:
        """
        Find scene data in loaded inventories.

        Args:
            scene_uid: Scene unique_id

        Returns:
            Scene data dict or None if not found
        """
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scene', {}).get('items', [])
            for scene in scenes:
                # Match by resource ID
                if scene.get('id') in scene_uid:
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

            if unique_id and hue_resource_id in unique_id:
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
                self.error(f"Circuit breaker OPENED (threshold reached)")

        # Check if timeout expired (transition to HALF_OPEN)
        if self.circuit_breaker_state == 'OPEN':
            if self.circuit_breaker_opened_at:
                elapsed = time.time() - self.circuit_breaker_opened_at
                if elapsed >= self.cb_timeout:
                    self.circuit_breaker_state = 'HALF_OPEN'
                    self.circuit_breaker_successes = 0
                    self.log("Circuit breaker HALF_OPEN (timeout expired, testing)")
