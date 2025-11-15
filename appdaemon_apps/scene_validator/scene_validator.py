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
Version: 2.2.0-FORMATTED (Consistent logging format + debug flag)
"""

__VERSION__ = "2.2.0-FORMATTED"

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
        self.log(f"=== Initializing Scene Validator {__VERSION__} ===", level="WARNING")
        self.log(f"Version: {__VERSION__}", level="WARNING")

        # Configuration parameters
        self.inventory_dir = self.args.get('inventory_dir', '/homeassistant/hue_inventories')
        self.transition_delay = self.args.get('transition_delay', 5)
        self.validation_delay = self.args.get('validation_delay', 2)
        self.validation_debounce = self.args.get('validation_debounce', 30)
        self.level3_settle_delay = self.args.get('level3_settle_delay', 2)  # Delay after Level 3 control before final validation

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
        self.hue_id_to_entity_id = {}  # Hue unique_id -> HA entity_id mapping cache
        self.circuit_breaker_state = 'CLOSED'
        self.circuit_breaker_failures = 0
        self.circuit_breaker_successes = 0
        self.circuit_breaker_opened_at = None
        self.validation_timestamps = []
        self.scene_validation_timestamps = {}
        self.recent_validations = {}  # {scene_entity: timestamp}
        self.last_validation_failures = []  # Track what failed: 'on_off', 'brightness', 'color', 'color_temp'

        # Tolerances for state comparison
        self.brightness_tolerance = self.args.get('brightness_tolerance', 5)  # ±5%
        self.color_tolerance = self.args.get('color_tolerance', 0.01)  # ±0.01
        self.color_temp_tolerance = self.args.get('color_temp_tolerance', 50)  # ±50 mireds (lenient for Hue variations)

        # Debug logging - when False, only log failures and errors (not OK/success messages)
        self.debug_logging = self.args.get('debug_logging', False)

        # Load inventories
        if not self.load_inventories():
            self.error("Failed to load inventories - validator will not function")
            return

        # Load entity registry mapping (workaround for unique_id not available in state API)
        try:
            self.load_entity_registry_mapping()
        except Exception as e:  # noqa: BLE001
            self.error(f"Critical error loading entity registry: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")

        # Listen for scene activations from ANY source (HA, Hue app, switches)
        # Monitor state changes instead of call_service events
        self.setup_scene_listeners()

        self.log("Validator initialized successfully")
        self.log(f"Inventory directory: {self.inventory_dir}")
        self.log("Detection: Universal (HA, Hue app, switches)")
        self.log(f"Transition delay: {self.transition_delay}s")
        self.log(f"Validation delay: {self.validation_delay}s")
        self.log(f"Level 3 settle delay: {self.level3_settle_delay}s")
        self.log(f"Debounce window: {self.validation_debounce}s")
        self.log(f"Tolerances: brightness +/-{self.brightness_tolerance}%, color +/-{self.color_tolerance}, color_temp +/-{self.color_temp_tolerance} mirek")
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

    def load_entity_registry_mapping(self):
        """
        Load unique_id to entity_id mapping from entity registry.

        This is a workaround for Home Assistant's state API limitation:
        /api/states does NOT expose unique_id for ANY entity type (lights, scenes, sensors, etc.)
        even though unique_ids are present in the entity registry.

        We read the entity registry file during initialization and build a cache
        for O(1) lookup when mapping Hue resource IDs to HA entity_ids.

        Note: This reads internal HA storage which may change between versions,
        but is the only reliable way to map external IDs to entity_ids.
        """
        self.log("Loading entity registry mapping...", level="DEBUG"))
        registry_file = Path("/homeassistant/.storage/core.entity_registry")
        self.log(f"Registry file path: {registry_file}, exists: {registry_file.exists()}", level="DEBUG")

        if not registry_file.exists():
            self.error(f"Entity registry not found: {registry_file}")
            self.error("Entity ID mapping will not work - validation will fail")
            return

        try:
            with open(registry_file) as f:
                registry = json.load(f)

            entities = registry.get('data', {}).get('entities', [])

            # Build mapping for Hue platform entities only
            hue_count = 0
            for entry in entities:
                entity_id = entry.get('entity_id')
                unique_id = entry.get('unique_id')
                platform = entry.get('platform')

                # Only map Hue platform entities
                if platform == 'hue' and entity_id and unique_id:
                    self.hue_id_to_entity_id[unique_id] = entity_id
                    hue_count += 1

            self.log(f"Loaded entity registry mapping: {hue_count} Hue entities", level="DEBUG")
            self.log(f"Loaded entity registry mapping: {hue_count} Hue entities")

        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
            self.error(f"Failed to load entity registry: {e}")
            self.error("Entity ID mapping will not work - validation will fail")
        except Exception as e:  # noqa: BLE001
            self.error(f"Unexpected error loading entity registry: {e}")

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
            self.log(f"[{scene_entity}] LEVEL 1: Validating scene state")
            # Reset failure tracking for new validation
            self.last_validation_failures = []

            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"[{scene_entity}] [OK] Validation successful")
                self.record_success()
                return

            # Analyze what failed to determine adaptive delay
            only_color_temp_failed = (
                len(self.last_validation_failures) > 0 and
                all(failure == 'color_temp' for failure in self.last_validation_failures)
            )

            if only_color_temp_failed:
                delay_multiplier = 2
                self.log(f"[{scene_entity}] [ADAPTIVE] Only color_temp failed - using 2x delay for Level 2 ({self.validation_delay * delay_multiplier}s)", level="INFO")
            else:
                delay_multiplier = 1

            self.log(f"[{scene_entity}] [FAIL] Validation failed (failures: {set(self.last_validation_failures)})", level="WARNING")

            # LEVEL 2: Re-trigger scene (async scheduling to avoid blocking)
            self.log(f"[{scene_entity}] LEVEL 2: Re-triggering scene")
            self.call_service("scene/turn_on", entity_id=scene_entity)

            # Schedule level 2 validation after adaptive delay (non-blocking)
            level2_delay = self.validation_delay * delay_multiplier

            try:
                self.run_in(
                    self.perform_level2_validation,
                    level2_delay,
                    scene_entity=scene_entity,
                    scene_data=scene_data,
                    delay_multiplier=delay_multiplier  # Pass to Level 3
                )
                self.log(f"[{scene_entity}] [SCHEDULER] Level 2 validation scheduled in {level2_delay}s", level="INFO")
            except Exception as e:  # noqa: BLE001 - Broad catch to prevent scheduler failures from crashing app
                self.error(f"[SCHEDULER ERROR] Failed to schedule Level 2 validation: {e}")
                import traceback
                self.error(f"Traceback: {traceback.format_exc()}")

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
            kwargs: Contains scene_entity, scene_data, and delay_multiplier
        """
        # FIRST LINE: Log that callback was executed (to detect silent failures)
        self.log("[CALLBACK] perform_level2_validation called", level="INFO")

        try:
            scene_entity = kwargs.get('scene_entity')
            scene_data = kwargs.get('scene_data')
            level1_delay_multiplier = kwargs.get('delay_multiplier', 1)

            self.log(f"[{scene_entity}] [LEVEL 2] Validating (delay_multiplier={level1_delay_multiplier})", level="INFO")

            if not scene_entity or not scene_data:
                self.error("perform_level2_validation called without required parameters")
                return

            # Check if validation is possible (inventory format)
            actions = scene_data.get('actions', [])
            actions_are_strings = self._is_legacy_action_format(actions)

            if actions_are_strings:
                # Validation impossible due to inventory format
                # But re-trigger was performed, so consider it successful
                self.log(f"[{scene_entity}] [OK] Re-trigger completed (validation unavailable due to inventory format)")
                self.record_success()
                return

            # Level 2: Validate after re-trigger
            # Reset failure tracking for Level 2 validation
            self.last_validation_failures = []

            if self.validate_scene_state(scene_entity, scene_data):
                self.log(f"[{scene_entity}] [OK] Re-trigger successful")
                self.record_success()
                return

            # Analyze what failed in Level 2 to determine Level 3 delay
            only_color_temp_failed = (
                len(self.last_validation_failures) > 0 and
                all(failure == 'color_temp' for failure in self.last_validation_failures)
            )

            # If Level 1 already used 2x delay (color temp only) and Level 2 still failed with color temp,
            # use 3x delay for Level 3. Otherwise use original delay.
            if only_color_temp_failed and level1_delay_multiplier == 2:
                level3_delay_multiplier = 3
                level3_delay = self.validation_delay * level3_delay_multiplier
                self.log(f"[{scene_entity}] [ADAPTIVE] Only color_temp failed again - using 3x delay for Level 3 ({level3_delay}s)", level="INFO")
            else:
                level3_delay = self.validation_delay
                level3_delay_multiplier = 1

            self.log(f"[{scene_entity}] [FAIL] Re-trigger failed (failures: {set(self.last_validation_failures)})", level="WARNING")

            # LEVEL 3: Individual light control (with adaptive delay)
            self.log(f"[{scene_entity}] LEVEL 3: Controlling lights individually in {level3_delay}s")

            # Schedule Level 3 execution with adaptive delay
            try:
                self.run_in(
                    self.perform_level3_control,
                    level3_delay,
                    scene_entity=scene_entity,
                    scene_data=scene_data
                )
                self.log(f"[{scene_entity}] [SCHEDULER] Level 3 control scheduled in {level3_delay}s", level="INFO")
            except Exception as e:  # noqa: BLE001 - Broad catch to prevent scheduler failures from crashing app
                self.error(f"[SCHEDULER ERROR] Failed to schedule Level 3 control: {e}")
                import traceback
                self.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during level 2/3 validation: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def perform_level3_control(self, kwargs):
        """
        Perform Level 3 individual light control after adaptive delay.

        This is called after the Level 3 delay to give color temperature
        transitions more time to complete if that was the only failure.

        Args:
            kwargs: Contains scene_entity and scene_data
        """
        # FIRST LINE: Log that callback was executed (to detect silent failures)
        self.log("[CALLBACK] perform_level3_control called", level="INFO")

        try:
            scene_entity = kwargs.get('scene_entity')
            scene_data = kwargs.get('scene_data')

            self.log(f"[{scene_entity}] [LEVEL 3] Controlling lights individually", level="INFO")

            if not scene_entity or not scene_data:
                self.error("perform_level3_control called without required parameters")
                return

            # Control lights individually
            if not self.control_lights_individually(scene_data):
                self.error(f"[{scene_entity}] [FAIL] Level 3 control commands failed")
                self.record_failure()
                return

            # Schedule final validation after settle delay instead of blocking the worker thread
            def _final_level3_validation(_kwargs):
                self.log(
                    f"[{scene_entity}] [LEVEL 3] Final validation after {self.level3_settle_delay}s settle delay",
                    level="INFO",
                )
                self.last_validation_failures = []
                if self.validate_scene_state(scene_entity, scene_data):
                    self.log(f"[{scene_entity}] [OK] Level 3 successful - final validation PASSED")
                    self.record_success()
                else:
                    self.error(f"[{scene_entity}] [FAIL] Level 3 control executed, but final validation FAILED")
                    self.error(f"[{scene_entity}] [FAIL] Still failing: {set(self.last_validation_failures)}")
                    self.record_failure()

            self.run_in(_final_level3_validation, self.level3_settle_delay)

        except Exception as e:  # noqa: BLE001 - Broad catch to prevent app crash
            self.error(f"Exception during level 3 control: {e}")
            import traceback
            self.error(f"Traceback: {traceback.format_exc()}")
            self.record_failure()

    def find_scene_in_inventory(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Find scene data in loaded inventories using entity registry unique_id.

        Uses the entity registry to get the Hue scene ID (unique_id) for the given
        HA entity_id, then searches inventories for that exact scene ID.

        This provides 100% reliable scene matching with no ambiguity, unlike the
        previous name-based matching which failed when multiple scenes had the same
        name (e.g., 28 scenes named "Nachtlicht" across different rooms).

        Args:
            entity_id: Scene entity_id (e.g., scene.buro_markus_nachtlicht)

        Returns:
            Scene data dict or None if not found
        """
        # Get Hue scene ID from entity registry (unique_id = Hue scene ID)
        # The entity registry provides the direct 1:1 mapping:
        # scene.buro_markus_nachtlicht → f0309f80-9480-4b12-a0c3-a026790d87bf
        hue_scene_id = None
        for unique_id, mapped_entity_id in self.hue_id_to_entity_id.items():
            if mapped_entity_id == entity_id:
                hue_scene_id = unique_id
                break

        if not hue_scene_id:
            self.log(f"Could not find Hue scene ID for {entity_id} in entity registry", level="WARNING")
            return None

        # Search inventories for scene with this exact ID
        for inventory in self.inventories:
            scenes = inventory.get('resources', {}).get('scenes', {}).get('items', [])
            for scene in scenes:
                if scene.get('id') == hue_scene_id:
                    # Found exact scene match by ID - 100% reliable!
                    return scene

        # Scene not found in any inventory
        self.log(f"Scene {entity_id} (Hue ID: {hue_scene_id}) not found in inventories", level="WARNING")
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
                if not self.compare_light_states(entity_id, expected, actual_state, scene_entity):
                    all_match = False

            return all_match

        except AttributeError as e:
            self.log(f"Inventory format issue (actions are strings): {e}", level="WARNING")
            return False
        except Exception as e:  # noqa: BLE001
            self.error(f"Error validating scene state: {e}")
            return False

    def compare_light_states(self, entity_id: str, expected: Dict[str, Any],
                            actual_state: Dict[str, Any], scene_entity: str = "unknown") -> bool:
        """
        Compare expected and actual light states.

        Args:
            entity_id: Light entity_id
            expected: Expected state from scene
            actual_state: Actual state from HA
            scene_entity: Scene entity_id for logging

        Returns:
            True if states match within tolerances, False otherwise
        """
        actual_attrs = actual_state.get('attributes', {})
        actual_on = actual_state.get('state') == 'on'

        # Check on/off state
        expected_on = expected.get('on', {}).get('on', False)
        if expected_on != actual_on:
            self.log(f"[{scene_entity}] [{entity_id}] [ON_OFF] FAIL: exp {'ON' if expected_on else 'OFF'}, got {'ON' if actual_on else 'OFF'}", level="WARNING")
            self.last_validation_failures.append('on_off')
            return False

        # If light should be off, no need to check other attributes
        if not expected_on:
            return True

        # Check brightness
        expected_dimming = expected.get('dimming', {})
        if expected_dimming and 'brightness' in expected_dimming:
            expected_brightness = expected_dimming['brightness']

            # CRITICAL HUE RULE: When on:true, brightness 0.0 in scene means light will be at 0% in HA state
            # We DON'T convert 0.0 to 1.0 for validation - we accept 0% as the correct actual state
            # The conversion to 1% only happens when CONTROLLING the light (Level 3)

            actual_brightness = actual_attrs.get('brightness', 0)
            # Convert HA brightness (0-255) to percentage
            actual_brightness_pct = (actual_brightness / 255) * 100
            diff = abs(expected_brightness - actual_brightness_pct)

            if diff > self.brightness_tolerance:
                self.log(f"[{scene_entity}] [{entity_id}] [BRIGHTNESS] FAIL: exp {expected_brightness:.1f}%, got {actual_brightness_pct:.1f}%, diff {diff:.1f}% > tol {self.brightness_tolerance}%", level="WARNING")
                self.last_validation_failures.append('brightness')
                return False
            elif self.debug_logging:
                self.log(f"[{scene_entity}] [{entity_id}] [BRIGHTNESS] OK: exp {expected_brightness:.1f}%, got {actual_brightness_pct:.1f}%, diff {diff:.1f}% < tol {self.brightness_tolerance}%", level="INFO")

        # Check color (XY)
        expected_color = expected.get('color', {})
        if expected_color and 'xy' in expected_color:
            expected_xy = expected_color['xy']
            actual_xy = actual_attrs.get('xy_color')

            # Only validate if light has xy_color in state (skip if in CT mode)
            if actual_xy:
                x_diff = abs(expected_xy['x'] - actual_xy[0])
                y_diff = abs(expected_xy['y'] - actual_xy[1])
                if x_diff > self.color_tolerance or y_diff > self.color_tolerance:
                    self.log(f"[{scene_entity}] [{entity_id}] [COLOR_XY] FAIL: exp ({expected_xy['x']:.3f}, {expected_xy['y']:.3f}), got ({actual_xy[0]:.3f}, {actual_xy[1]:.3f}), diff (x:{x_diff:.3f}, y:{y_diff:.3f}) > tol {self.color_tolerance}", level="WARNING")
                    self.last_validation_failures.append('color')
                    return False
                elif self.debug_logging:
                    self.log(f"[{scene_entity}] [{entity_id}] [COLOR_XY] OK: exp ({expected_xy['x']:.3f}, {expected_xy['y']:.3f}), got ({actual_xy[0]:.3f}, {actual_xy[1]:.3f}), diff (x:{x_diff:.3f}, y:{y_diff:.3f}) < tol {self.color_tolerance}", level="INFO")

        # Check color temperature
        if 'color_temperature' in expected:
            if expected['color_temperature']:
                expected_ct = expected['color_temperature'].get('mirek')
                actual_ct = actual_attrs.get('color_temp')

                # Only validate if light has color_temp in state (skip if in XY mode)
                if actual_ct:
                    diff = abs(expected_ct - actual_ct)
                    if diff > self.color_temp_tolerance:
                        self.log(f"[{scene_entity}] [{entity_id}] [COLOR_TEMP] FAIL: exp {expected_ct}, got {actual_ct}, diff {diff} > tol {self.color_temp_tolerance}", level="WARNING")
                        self.last_validation_failures.append('color_temp')
                        return False
                    elif self.debug_logging:
                        self.log(f"[{scene_entity}] [{entity_id}] [COLOR_TEMP] OK: exp {expected_ct}, got {actual_ct}, diff {diff} < tol {self.color_temp_tolerance}", level="INFO")

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
            if dimming and 'brightness' in dimming:
                brightness_pct = dimming['brightness']

                # CRITICAL HUE RULE: When on:true, brightness 0.0 means "minimum brightness" (~1%), NOT off
                # This is Hue-specific behavior - see CLAUDE.md for details
                if brightness_pct == 0.0:
                    brightness_pct = 1.0  # Minimum brightness for ON lights

                # Convert percentage to 0-255
                brightness = int((brightness_pct / 100) * 255)
                service_data['brightness'] = max(brightness, 1)  # Ensure at least 1 in HA scale

            # Color (XY)
            color = expected.get('color', {})
            if color and 'xy' in color:
                xy = color['xy']
                service_data['xy_color'] = [xy['x'], xy['y']]

            # Color temperature
            if 'color_temperature' in expected:
                if expected['color_temperature']:
                    ct = expected['color_temperature'].get('mirek')
                    if ct:
                        service_data['color_temp'] = ct

            # Turn on light with parameters
            self.call_service("light/turn_on", **service_data)

        return all_success

    def get_entity_id_from_hue_id(self, hue_resource_id: str) -> Optional[str]:
        """
        Map Hue resource ID to HA entity_id using cached entity registry mapping.

        This uses the entity registry cache loaded during initialization instead
        of querying the state API, because the state API does NOT expose unique_id
        for any entity type (see HOME_ASSISTANT_API_LIMITATIONS.md).

        Args:
            hue_resource_id: Hue resource ID (UUID)

        Returns:
            HA entity_id or None if not found
        """
        # Try exact match first (resource ID is the unique_id)
        if hue_resource_id in self.hue_id_to_entity_id:
            return self.hue_id_to_entity_id[hue_resource_id]

        # Try partial match (unique_id contains resource ID with delimiters)
        for unique_id, entity_id in self.hue_id_to_entity_id.items():
            if (unique_id.endswith(hue_resource_id) or
                f"_{hue_resource_id}" in unique_id or
                f"-{hue_resource_id}" in unique_id):
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
