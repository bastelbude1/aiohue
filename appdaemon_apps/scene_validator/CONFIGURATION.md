# AppDaemon Configuration Guide

Complete guide to understanding how AppDaemon configuration works with `apps.yaml` and how Python apps receive their settings.

## Table of Contents

- [Overview](#overview)
- [How Configuration Works](#how-configuration-works)
- [The `self.args` Mechanism](#the-selfargs-mechanism)
- [Complete Example Flow](#complete-example-flow)
- [Best Practices](#best-practices)
- [Scene Validator Configuration](#scene-validator-configuration)
- [Troubleshooting](#troubleshooting)

---

## Overview

AppDaemon uses YAML configuration files to define and configure apps. The system automatically:
1. Reads your `apps.yaml` configuration
2. Loads the specified Python module
3. Instantiates the specified class
4. Passes all configuration parameters as a dictionary (`self.args`)
5. Calls your app's `initialize()` method

**No manual YAML parsing needed!** AppDaemon handles everything automatically.

---

## How Configuration Works

### 1. AppDaemon Loads the YAML

When AppDaemon starts, it reads `/homeassistant/appdaemon/apps/apps.yaml`:

```yaml
scene_validator:                    # ← App name/identifier
  module: scene_validator           # ← Which Python file to load
  class: SceneValidator             # ← Which class to instantiate

  # These become configuration parameters
  transition_delay: 5               # ← Your custom setting
  validation_delay: 2
  brightness_tolerance: 5
  debug_logging: true
```

**Key Points:**
- `scene_validator` is the app identifier (used in logs)
- `module` tells AppDaemon which Python file to load (`.py` extension implied)
- `class` specifies which class in that module to instantiate
- All other keys become configuration parameters

### 2. AppDaemon Creates the App Instance

AppDaemon automatically:
1. Finds `scene_validator.py` in the apps directory
2. Imports the module
3. Finds the `SceneValidator` class
4. Creates an instance: `app = SceneValidator()`
5. Sets `app.args` with all the YAML parameters
6. Calls `app.initialize()`

**Pseudo-code of what AppDaemon does internally:**

```python
import importlib

# Load the YAML configuration
config = yaml.load('/homeassistant/appdaemon/apps/apps.yaml')

# For each app defined in the YAML
for app_name, app_config in config.items():
    # Import the module
    module = importlib.import_module(app_config['module'])

    # Get the class
    app_class = getattr(module, app_config['class'])

    # Create instance
    app_instance = app_class(
        app_daemon,              # AppDaemon instance
        app_name,                # 'scene_validator'
        logger,                  # Logging instance
        error,                   # Error handler
        app_config,              # All YAML parameters
        global_vars              # Global variables
    )

    # Store config as self.args
    app_instance.args = app_config

    # Initialize the app
    app_instance.initialize()
```

### 3. Configuration Becomes `self.args`

All YAML parameters are automatically passed to your app as a dictionary called `self.args`:

```python
self.args = {
    'module': 'scene_validator',
    'class': 'SceneValidator',
    'transition_delay': 5,           # ← From YAML
    'validation_delay': 2,           # ← From YAML
    'brightness_tolerance': 5,       # ← From YAML
    'debug_logging': True,           # ← From YAML (YAML true → Python True)
    'inventory_dir': '/homeassistant/hue_inventories',
    'scene_filter': {
        'name_patterns': ['.*Standard$', '.*Nachtlicht$']
    },
    # ... all other config from YAML
}
```

**Type Conversions:**
- YAML `true/false` → Python `True/False`
- YAML `123` → Python `123` (int)
- YAML `123.45` → Python `123.45` (float)
- YAML `"text"` → Python `"text"` (str)
- YAML lists `[]` → Python lists `[]`
- YAML dictionaries `{}` → Python dictionaries `{}`

### 4. Your Code Reads from `self.args`

In your `scene_validator.py`, the `initialize()` method reads these values:

```python
class SceneValidator(hass.Hass):
    def initialize(self):
        # Read configuration with defaults
        self.transition_delay = self.args.get('transition_delay', 5)
        self.validation_delay = self.args.get('validation_delay', 2)
        self.debug_logging = self.args.get('debug_logging', False)

        # Required parameters (no default)
        self.inventory_dir = self.args.get('inventory_dir')
        if not self.inventory_dir:
            self.error("inventory_dir is required in configuration")
            return

        # Nested configuration
        scene_filter = self.args.get('scene_filter', {})
        self.name_patterns = scene_filter.get('name_patterns', [])

        # Log the configuration
        self.log(f"Transition delay: {self.transition_delay}s")
        self.log(f"Debug logging: {self.debug_logging}")
```

---

## The `self.args` Mechanism

### The `.get()` Method

```python
self.args.get('key_name', default_value)
               ↑                ↑
               Key to find      Value if key doesn't exist
```

**How it works:**

| In `apps.yaml` | Code | Result |
|----------------|------|--------|
| `transition_delay: 5` | `self.args.get('transition_delay', 10)` | `5` (uses YAML value) |
| `transition_delay: 5` | `self.args.get('transition_delay')` | `5` (uses YAML value) |
| *(key missing)* | `self.args.get('transition_delay', 10)` | `10` (uses default) |
| *(key missing)* | `self.args.get('transition_delay')` | `None` (no default provided) |
| *(key missing)* | `self.args['transition_delay']` | **KeyError!** (crashes) |

**Best Practice: Always use `.get()` with a sensible default**

```python
# ✅ GOOD - Safe with default
self.transition_delay = self.args.get('transition_delay', 5)
# If user forgets to add it to YAML, still works with default value

# ❌ BAD - Will crash if key missing
self.transition_delay = self.args['transition_delay']
# KeyError if user forgets to add it to YAML!

# ⚠️ ACCEPTABLE - For required parameters
self.inventory_dir = self.args.get('inventory_dir')
if not self.inventory_dir:
    self.error("inventory_dir is required!")
    return
```

### Accessing Nested Configuration

For nested YAML structures:

```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  circuit_breaker:
    failure_threshold: 10
    success_threshold: 2
    timeout: 600

  scene_filter:
    name_patterns:
      - ".*Standard$"
      - ".*Nachtlicht$"
```

Access in Python:

```python
def initialize(self):
    # Get nested dictionary
    circuit_breaker = self.args.get('circuit_breaker', {})

    # Extract values from nested dict
    self.failure_threshold = circuit_breaker.get('failure_threshold', 10)
    self.success_threshold = circuit_breaker.get('success_threshold', 2)
    self.timeout = circuit_breaker.get('timeout', 600)

    # Get nested list
    scene_filter = self.args.get('scene_filter', {})
    self.name_patterns = scene_filter.get('name_patterns', [])
```

---

## Complete Example Flow

Let's trace what happens when you change a configuration value.

### Step 1: Edit `apps.yaml`

```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator
  transition_delay: 10  # ← Changed from 5 to 10
  debug_logging: false  # ← Changed from true to false
```

### Step 2: Restart AppDaemon

```bash
# Via Home Assistant CLI
ha addons restart a0d7b954_appdaemon

# OR via API
curl -X POST -H "Authorization: Bearer $(cat /data/.ha_token)" \
  http://localhost:8123/api/services/homeassistant/restart
```

### Step 3: AppDaemon Reads YAML

```python
# AppDaemon internally does:
config = yaml.load('apps.yaml')

# Result:
# config['scene_validator'] = {
#     'module': 'scene_validator',
#     'class': 'SceneValidator',
#     'transition_delay': 10,      # ← Your new value
#     'debug_logging': False,      # ← Your new value
#     ...
# }
```

### Step 4: AppDaemon Creates App

```python
# AppDaemon internally:
app_instance = SceneValidator()
app_instance.args = config['scene_validator']
app_instance.initialize()
```

### Step 5: Your `initialize()` Runs

```python
def initialize(self):
    self.transition_delay = self.args.get('transition_delay', 5)
    # self.args['transition_delay'] = 10 (from YAML)
    # So: self.transition_delay = 10 ✓

    self.debug_logging = self.args.get('debug_logging', False)
    # self.args['debug_logging'] = False (from YAML)
    # So: self.debug_logging = False ✓

    self.log(f"Transition delay: {self.transition_delay}s")
    # Logs: "Transition delay: 10s"

    self.log(f"Debug logging: {self.debug_logging}")
    # Logs: "Debug logging: False"
```

### Step 6: Verify in Logs

```bash
# Check AppDaemon logs
ha addons logs a0d7b954_appdaemon | grep "Transition delay"

# Output:
# INFO scene_validator: Transition delay: 10s
```

---

## Visual Diagram

```
apps.yaml                          scene_validator.py
─────────────                      ──────────────────

scene_validator:
  transition_delay: 10   ──────────────────────┐
  validation_delay: 2    ────────────────┐     │
  debug_logging: true    ──────────┐     │     │
                                   │     │     │
                                   ↓     ↓     ↓
                          def initialize(self):
                              self.debug_logging = self.args.get('debug_logging', False)
                              self.validation_delay = self.args.get('validation_delay', 2)
                              self.transition_delay = self.args.get('transition_delay', 5)

                              # Results:
                              # self.transition_delay = 10 (from YAML)
                              # self.validation_delay = 2 (from YAML)
                              # self.debug_logging = True (from YAML)

                              # App is now configured!
```

---

## Best Practices

### 1. Always Use Defaults

```python
# ✅ GOOD - Provides default if config missing
self.transition_delay = self.args.get('transition_delay', 5)

# ❌ BAD - Crashes if config missing
self.transition_delay = self.args['transition_delay']
```

### 2. Validate Required Parameters

```python
def initialize(self):
    # Required parameter
    self.inventory_dir = self.args.get('inventory_dir')
    if not self.inventory_dir:
        self.error("inventory_dir is required in apps.yaml")
        return  # Don't continue initialization

    # Optional with default
    self.debug_logging = self.args.get('debug_logging', False)
```

### 3. Log Configuration at Startup

```python
def initialize(self):
    # Load all config
    self.transition_delay = self.args.get('transition_delay', 5)
    self.validation_delay = self.args.get('validation_delay', 2)

    # Log configuration for debugging
    self.log("=== Configuration ===")
    self.log(f"Transition delay: {self.transition_delay}s")
    self.log(f"Validation delay: {self.validation_delay}s")
    self.log(f"Debug logging: {self.debug_logging}")
```

### 4. Document All Parameters

In your app's docstring:

```python
"""
Scene Validator for Philips Hue

Configuration Parameters (apps.yaml):
    transition_delay (int): Wait time after scene activation (default: 5)
    validation_delay (int): Wait before re-validation (default: 2)
    debug_logging (bool): Enable verbose logging (default: False)
    inventory_dir (str): Path to Hue inventories (required)

Example Configuration:
    scene_validator:
      module: scene_validator
      class: SceneValidator
      transition_delay: 5
      validation_delay: 2
      debug_logging: true
      inventory_dir: /homeassistant/hue_inventories
"""
```

### 5. Use Type Hints

```python
def initialize(self):
    # Type hints help with IDE autocomplete and documentation
    self.transition_delay: int = self.args.get('transition_delay', 5)
    self.validation_delay: int = self.args.get('validation_delay', 2)
    self.debug_logging: bool = self.args.get('debug_logging', False)
    self.inventory_dir: str = self.args.get('inventory_dir', '')
```

---

## Scene Validator Configuration

### Full Configuration Example

**File:** `/homeassistant/appdaemon/apps/apps.yaml`

```yaml
scene_validator:
  module: scene_validator
  class: SceneValidator

  # Inventory paths
  inventory_dir: /homeassistant/hue_inventories

  # Timing Configuration (all values in seconds)
  transition_delay: 5              # Wait after scene activation
  validation_delay: 2              # Wait before Level 2 re-trigger
  level3_settle_delay: 3           # Wait after Level 3 individual control
  validation_debounce: 30          # Prevent duplicate validations

  # Validation Tolerances
  color_temp_tolerance: 50         # Mirek units (±50)
  brightness_tolerance: 5          # Percentage points (±5%)
  color_tolerance: 0.01            # CIE xy units (±0.01)

  # Debug Logging
  debug_logging: true              # Show all checks (true) or only failures (false)

  # Rate Limiting (validations per minute)
  max_validations_per_minute: 20
  max_validations_per_scene_per_minute: 5

  # Circuit Breaker
  circuit_breaker:
    failure_threshold: 10          # Failures before circuit opens
    success_threshold: 2           # Successes to close circuit
    timeout: 600                   # Cooldown period (seconds)

  # Scene Filtering
  scene_filter:
    include_labels: []             # Hue scene labels to include
    exclude_labels: []             # Hue scene labels to exclude
    exclude_uids: []               # Specific Hue scene IDs to exclude
    name_patterns:                 # Regex patterns
      - ".*Standard$"              # Scenes ending with "Standard"
      - ".*Nachtlicht$"            # Scenes ending with "Nachtlicht"
```

### How Scene Validator Reads This

**File:** `scene_validator.py`

```python
class SceneValidator(hass.Hass):
    def initialize(self):
        # Inventory path
        self.inventory_dir = self.args.get('inventory_dir')
        if not self.inventory_dir:
            self.error("inventory_dir is required!")
            return

        # Timing configuration
        self.transition_delay = self.args.get('transition_delay', 5)
        self.validation_delay = self.args.get('validation_delay', 2)
        self.level3_settle_delay = self.args.get('level3_settle_delay', 3)
        self.validation_debounce = self.args.get('validation_debounce', 30)

        # Validation tolerances
        self.color_temp_tolerance = self.args.get('color_temp_tolerance', 50)
        self.brightness_tolerance = self.args.get('brightness_tolerance', 5)
        self.color_tolerance = self.args.get('color_tolerance', 0.01)

        # Debug logging
        self.debug_logging = self.args.get('debug_logging', False)

        # Rate limiting
        self.max_validations_per_minute = self.args.get('max_validations_per_minute', 20)
        self.max_validations_per_scene_per_minute = self.args.get(
            'max_validations_per_scene_per_minute', 5
        )

        # Circuit breaker (nested config)
        circuit_breaker = self.args.get('circuit_breaker', {})
        self.failure_threshold = circuit_breaker.get('failure_threshold', 10)
        self.success_threshold = circuit_breaker.get('success_threshold', 2)
        self.circuit_timeout = circuit_breaker.get('timeout', 600)

        # Scene filter (nested config)
        scene_filter = self.args.get('scene_filter', {})
        self.include_labels = scene_filter.get('include_labels', [])
        self.exclude_labels = scene_filter.get('exclude_labels', [])
        self.exclude_uids = scene_filter.get('exclude_uids', [])
        self.name_patterns = scene_filter.get('name_patterns', [])

        # Log configuration
        self.log("=== Initializing Scene Validator ===")
        self.log(f"Transition delay: {self.transition_delay}s")
        self.log(f"Validation delay: {self.validation_delay}s")
        self.log(f"Debug logging: {self.debug_logging}")
```

---

## Troubleshooting

### Configuration Not Loading

**Problem:** Changed `apps.yaml` but app still uses old values

**Solution:**
```bash
# Restart AppDaemon addon
ha addons restart a0d7b954_appdaemon

# Check logs for errors
ha addons logs a0d7b954_appdaemon | grep -i error
```

### App Not Starting

**Problem:** App doesn't initialize

**Common Causes:**
1. **YAML syntax error**
   ```bash
   # Check YAML syntax
   python3 -c "import yaml; yaml.safe_load(open('apps.yaml'))"
   ```

2. **Module not found**
   ```yaml
   # ❌ BAD - Wrong module name
   module: scenevalidator  # No such file!

   # ✅ GOOD - Matches filename
   module: scene_validator  # Matches scene_validator.py
   ```

3. **Class not found**
   ```yaml
   # ❌ BAD - Wrong class name
   class: SceneVal  # No such class!

   # ✅ GOOD - Matches class name in Python file
   class: SceneValidator  # Matches class SceneValidator(hass.Hass)
   ```

### Missing Configuration Values

**Problem:** `KeyError: 'some_param'`

**Solution:** Use `.get()` with defaults
```python
# ❌ BAD - Crashes if missing
value = self.args['some_param']

# ✅ GOOD - Uses default if missing
value = self.args.get('some_param', default_value)
```

### Type Mismatch

**Problem:** Expected integer, got string

**YAML:**
```yaml
transition_delay: "5"  # ← String, not int!
```

**Solution:** Remove quotes for numbers
```yaml
transition_delay: 5    # ← Integer
```

**Or convert in Python:**
```python
self.transition_delay = int(self.args.get('transition_delay', 5))
```

---

## Testing Configuration Changes

### 1. Edit Configuration

```bash
# SSH to Home Assistant
ssh -i /home/baste/HA/homeassistant_ssh_key hassio@192.168.188.42

# Edit apps.yaml
sudo nano /homeassistant/appdaemon/apps/apps.yaml
```

### 2. Restart AppDaemon

```bash
export SUPERVISOR_TOKEN=$(grep 'SUPERVISOR_TOKEN=' /etc/profile.d/*.sh | cut -d'"' -f2)
ha addons restart a0d7b954_appdaemon
```

### 3. Check Logs

```bash
# Wait for restart
sleep 10

# Check initialization logs
ha addons logs a0d7b954_appdaemon | grep scene_validator

# Look for your configuration values
ha addons logs a0d7b954_appdaemon | grep "Transition delay"
```

### 4. Verify Settings

```bash
# Should show your new value
ha addons logs a0d7b954_appdaemon | tail -30
```

---

## Summary

**The AppDaemon configuration system is simple:**

1. **Write YAML** → Define your app and settings in `apps.yaml`
2. **AppDaemon reads** → Automatically loads and parses YAML
3. **`self.args` created** → All settings available as dictionary
4. **Your code reads** → Use `self.args.get()` to access values
5. **Change config** → Edit YAML, restart AppDaemon, done!

**Key Takeaways:**
- ✅ Use `self.args.get(key, default)` always
- ✅ Provide sensible defaults for optional parameters
- ✅ Validate required parameters in `initialize()`
- ✅ Log configuration at startup for debugging
- ✅ Document all parameters in docstrings

**No manual YAML parsing needed** - AppDaemon handles everything!
