#!/usr/bin/env python3
"""
Philips Hue Bridge Automation Discovery Script

This script connects to registered Philips Hue bridges and retrieves comprehensive
automation data including smart scenes, behavior instances, behavior scripts,
geofence clients, and geolocation settings.

Usage:
    # Capture automations from all registered bridges
    python3 automation-hue-bridge.py

    # Capture from specific bridge by ID
    python3 automation-hue-bridge.py --bridge-id abc123def456

    # Use custom config file location
    python3 automation-hue-bridge.py --config /path/to/config.json

    # Save to custom output directory
    python3 automation-hue-bridge.py --output /path/to/automations

    # JSON output to stdout
    python3 automation-hue-bridge.py --json

    # Show help
    python3 automation-hue-bridge.py --help

Requirements:
    - aiohue library (auto-activated from /path/to/venv)
    - Registered bridges with credentials in config file

Output:
    - Saves automation data for each bridge to bridges/automations/{name}-{id}-automations.json
    - Interactive: Shows summary of automation resources found
    - JSON mode: Outputs complete automation data to stdout

Automation Resources Captured:
    - Smart Scenes: Time-based scheduled automations
    - Behavior Instances: Active running automations
    - Behavior Scripts: Available automation templates
    - Geofence Clients: Location-based triggers
    - Geolocation: Sun position data for sunrise/sunset

Exit Codes:
    0 - Success (automation data captured)
    1 - Error (connection failed or no registered bridges)
"""

import sys
import os
from pathlib import Path

# Auto-activate virtual environment
VENV_PATH = Path(__file__).parent.parent.parent / "venv"

if VENV_PATH.exists():
    # Add venv to sys.path
    venv_site_packages = VENV_PATH / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

import argparse
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle complex objects."""
    def default(self, obj):
        if isinstance(obj, Enum):
            return str(obj.value) if hasattr(obj, 'value') else str(obj)
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return str(obj)


# Default paths
DEFAULT_CONFIG_FILE = Path(__file__).parent.parent / "bridges" / "config.json"
DEFAULT_AUTOMATIONS_DIR = Path(__file__).parent.parent / "bridges" / "automations"


def sanitize_filename(name: str) -> str:
    """
    Sanitize a bridge name for use in filename.

    Args:
        name (str): Bridge name

    Returns:
        str: Sanitized name suitable for filename
    """
    import re
    # Replace spaces with underscores
    sanitized = name.replace(' ', '_')
    # Remove or replace special characters, keep only alphanumeric, underscore, hyphen
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', sanitized)
    return sanitized


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Capture automation data from Philips Hue bridges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                        # Capture all bridges
  %(prog)s --bridge-id abc123def456               # Capture specific bridge
  %(prog)s --config /path/to/config.json          # Use custom config file
  %(prog)s --output /path/to/automations          # Custom output directory
  %(prog)s --json                                 # JSON output to stdout

Automation Resources Captured:
  - Smart Scenes: Time-based scheduled automations
  - Behavior Instances: Active running automations
  - Behavior Scripts: Available automation templates
  - Geofence Clients: Location-based triggers
  - Geolocation: Sun position data for sunrise/sunset

For more information, visit: https://github.com/home-assistant-libs/aiohue
        """
    )

    parser.add_argument(
        "--config",
        metavar="FILE",
        type=str,
        default=str(DEFAULT_CONFIG_FILE),
        help=f"Path to bridges config JSON file (default: {DEFAULT_CONFIG_FILE})"
    )

    parser.add_argument(
        "--bridge-id",
        metavar="ID",
        type=str,
        help="Capture only this specific bridge ID"
    )

    parser.add_argument(
        "--output",
        metavar="DIR",
        type=str,
        default=str(DEFAULT_AUTOMATIONS_DIR),
        help=f"Output directory for automation files (default: {DEFAULT_AUTOMATIONS_DIR})"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output automation data in JSON format to stdout (does not save to files)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    return parser.parse_args()


def load_config(filepath: str) -> Optional[Dict]:
    """
    Load bridge configuration from JSON file.

    Args:
        filepath (str): Path to config JSON file

    Returns:
        dict: Bridge configuration data, or None on error
    """
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: Config file not found: {filepath}", file=sys.stderr)
        print("Run discover-hue-bridges.py first to create it.", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in config file: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error loading config file: {e}", file=sys.stderr)
        return None


def save_automations(automations: Dict, bridge_id: str, bridge_name: str, output_dir: str) -> bool:
    """
    Save bridge automation data to JSON file.

    Args:
        automations (dict): Automation data
        bridge_id (str): Bridge ID
        bridge_name (str): Bridge name
        output_dir (str): Output directory path

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Use format: {name}-{bridge_id}-automations.json
        sanitized_name = sanitize_filename(bridge_name)
        output_file = Path(output_dir) / f"{sanitized_name}-{bridge_id}-automations.json"
        with open(output_file, 'w') as f:
            json.dump(automations, f, indent=2, cls=CustomJSONEncoder)

        return True
    except Exception as e:
        print(f"Error saving automations: {e}", file=sys.stderr)
        return False


async def capture_automations(bridge_ip: str, username: str, client_key: Optional[str] = None) -> Optional[Dict]:
    """
    Connect to a Hue bridge and retrieve comprehensive automation data.

    Args:
        bridge_ip (str): IP address of the bridge
        username (str): API username
        client_key (str, optional): Client key for V2 API

    Returns:
        dict: Complete automation data, or None on error
    """
    try:
        from aiohue.v2 import HueBridgeV2

        print(f"   🔄 Connecting to bridge at {bridge_ip}...")

        bridge = HueBridgeV2(bridge_ip, username)

        try:
            await bridge.initialize()
            print(f"   ✅ Connected successfully")
        except Exception as e:
            print(f"   ❌ Failed to initialize bridge: {e}", file=sys.stderr)
            await bridge.close()
            return None

        automations = {
            "bridge_info": {
                "ip": bridge_ip,
                "captured_at": datetime.now().isoformat(),
            },
            "automations": {}
        }

        # Retrieve Smart Scenes
        try:
            print(f"      📅 Retrieving smart scenes...")
            smart_scenes = bridge.scenes.smart_scene.items
            automations["automations"]["smart_scenes"] = {
                "count": len(smart_scenes),
                "items": [
                    {
                        "id": scene.id,
                        "type": str(scene.type) if hasattr(scene, 'type') else None,
                        "metadata": scene.metadata.__dict__ if hasattr(scene, 'metadata') and scene.metadata is not None else None,
                        "group": str(scene.group) if hasattr(scene, 'group') and scene.group is not None else None,
                        "week_timeslots": [
                            {
                                "timeslots": [
                                    {
                                        "start_time": ts.start_time.__dict__ if hasattr(ts, 'start_time') and ts.start_time else None,
                                        "target": str(ts.target) if hasattr(ts, 'target') and ts.target else None
                                    }
                                    for ts in day.timeslots
                                ] if hasattr(day, 'timeslots') else [],
                                "recurrence": list(day.recurrence) if hasattr(day, 'recurrence') else []
                            }
                            for day in scene.week_timeslots
                        ] if hasattr(scene, 'week_timeslots') and scene.week_timeslots else [],
                        "state": scene.state if hasattr(scene, 'state') else None,
                        "active_timeslot": {
                            "timeslot_id": scene.active_timeslot.timeslot_id if scene.active_timeslot else None,
                            "weekday": scene.active_timeslot.weekday if scene.active_timeslot and hasattr(scene.active_timeslot, 'weekday') else None
                        } if hasattr(scene, 'active_timeslot') and scene.active_timeslot else None,
                        "transition_duration": scene.transition_duration if hasattr(scene, 'transition_duration') else None,
                    }
                    for scene in smart_scenes
                ]
            }
            print(f"      ✅ Found {len(smart_scenes)} smart scenes")
        except Exception as e:
            print(f"      ⚠️  Error retrieving smart scenes: {e}", file=sys.stderr)
            automations["automations"]["smart_scenes"] = {"error": str(e)}

        # Retrieve Behavior Instances
        try:
            print(f"      🤖 Retrieving behavior instances...")
            behavior_instances = bridge.config.behavior_instance.items
            automations["automations"]["behavior_instances"] = {
                "count": len(behavior_instances),
                "items": [
                    {
                        "id": instance.id,
                        "type": str(instance.type) if hasattr(instance, 'type') else None,
                        "metadata": instance.metadata.__dict__ if hasattr(instance, 'metadata') and instance.metadata is not None else None,
                        "script_id": instance.script_id if hasattr(instance, 'script_id') else None,
                        "enabled": instance.enabled if hasattr(instance, 'enabled') else None,
                        "status": instance.status if hasattr(instance, 'status') else None,
                        "configuration": instance.configuration if hasattr(instance, 'configuration') else None,
                        "state": instance.state if hasattr(instance, 'state') else None,
                        "last_error": instance.last_error if hasattr(instance, 'last_error') else None,
                        "dependees": [str(d) for d in instance.dependees] if hasattr(instance, 'dependees') and instance.dependees else [],
                        "migrated_from": instance.migrated_from if hasattr(instance, 'migrated_from') else None,
                    }
                    for instance in behavior_instances
                ]
            }
            print(f"      ✅ Found {len(behavior_instances)} behavior instances")
        except Exception as e:
            print(f"      ⚠️  Error retrieving behavior instances: {e}", file=sys.stderr)
            automations["automations"]["behavior_instances"] = {"error": str(e)}

        # Retrieve Behavior Scripts
        try:
            print(f"      📜 Retrieving behavior scripts...")
            behavior_scripts = bridge.config.behavior_script.items
            automations["automations"]["behavior_scripts"] = {
                "count": len(behavior_scripts),
                "items": [
                    {
                        "id": script.id,
                        "type": str(script.type) if hasattr(script, 'type') else None,
                        "metadata": script.metadata.__dict__ if hasattr(script, 'metadata') and script.metadata is not None else None,
                        "description": script.description if hasattr(script, 'description') else None,
                        "configuration_schema": script.configuration_schema if hasattr(script, 'configuration_schema') else None,
                        "trigger_schema": script.trigger_schema if hasattr(script, 'trigger_schema') else None,
                        "state_schema": script.state_schema if hasattr(script, 'state_schema') else None,
                        "version": script.version if hasattr(script, 'version') else None,
                        "supported_features": list(script.supported_features) if hasattr(script, 'supported_features') else [],
                        "max_number_instances": script.max_number_instances if hasattr(script, 'max_number_instances') else None,
                    }
                    for script in behavior_scripts
                ]
            }
            print(f"      ✅ Found {len(behavior_scripts)} behavior scripts")
        except Exception as e:
            print(f"      ⚠️  Error retrieving behavior scripts: {e}", file=sys.stderr)
            automations["automations"]["behavior_scripts"] = {"error": str(e)}

        # Retrieve Geofence Clients (via raw API)
        try:
            print(f"      📍 Retrieving geofence clients...")
            geofence_response = await bridge.request("get", "clip/v2/resource/geofence_client")

            if geofence_response and 'data' in geofence_response:
                geofence_clients = geofence_response['data']
                automations["automations"]["geofence_clients"] = {
                    "count": len(geofence_clients),
                    "items": geofence_clients
                }
                print(f"      ✅ Found {len(geofence_clients)} geofence clients")
            else:
                automations["automations"]["geofence_clients"] = {"count": 0, "items": []}
                print(f"      ℹ️  No geofence clients found")
        except Exception as e:
            print(f"      ⚠️  Error retrieving geofence clients: {e}", file=sys.stderr)
            automations["automations"]["geofence_clients"] = {"error": str(e)}

        # Retrieve Geolocation (via raw API)
        try:
            print(f"      🌍 Retrieving geolocation...")
            geolocation_response = await bridge.request("get", "clip/v2/resource/geolocation")

            if geolocation_response and 'data' in geolocation_response and geolocation_response['data']:
                # Usually only one geolocation entry
                geolocation = geolocation_response['data'][0]
                automations["automations"]["geolocation"] = geolocation
                print(f"      ✅ Retrieved geolocation data")
            else:
                automations["automations"]["geolocation"] = None
                print(f"      ℹ️  No geolocation data found")
        except Exception as e:
            print(f"      ⚠️  Error retrieving geolocation: {e}", file=sys.stderr)
            automations["automations"]["geolocation"] = {"error": str(e)}

        # Get bridge config/info
        try:
            print(f"      ⚙️  Retrieving bridge configuration...")
            config = bridge.config
            automations["bridge_info"]["config"] = {
                "bridge_id": config.bridge_id if hasattr(config, 'bridge_id') else None,
                "name": config.name if hasattr(config, 'name') else None,
                "model_id": config.model_id if hasattr(config, 'model_id') else None,
                "sw_version": config.sw_version if hasattr(config, 'sw_version') else None,
            }
            print(f"      ✅ Retrieved bridge configuration")
        except Exception as e:
            print(f"      ⚠️  Error retrieving config: {e}", file=sys.stderr)
            automations["bridge_info"]["config"] = {"error": str(e)}

        # Close bridge connection
        await bridge.close()

        return automations

    except ImportError as e:
        print(f"Error: Required library not found: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"❌ Automation capture error: {e}", file=sys.stderr)
        return None


async def capture_bridge_automations(config_data: Dict, args) -> Dict[str, Dict]:
    """
    Capture automations from bridges based on command-line arguments.

    Args:
        config_data (dict): Bridge configuration data
        args: Parsed command-line arguments

    Returns:
        dict: Mapping of bridge_id to automation data
    """
    bridges = config_data.get('bridges', [])

    if not bridges:
        print("No bridges found in config file.", file=sys.stderr)
        return {}

    # Filter registered bridges
    registered_bridges = [b for b in bridges if b.get('registered')]

    if not registered_bridges:
        print("No registered bridges found. Run register-hue-user.py first.", file=sys.stderr)
        return {}

    # Filter by bridge_id if specified
    if args.bridge_id:
        registered_bridges = [b for b in registered_bridges if b['id'] == args.bridge_id]
        if not registered_bridges:
            print(f"Bridge ID '{args.bridge_id}' not found or not registered.", file=sys.stderr)
            return {}

    print(f"\n📊 Starting automation capture from {len(registered_bridges)} bridge(s)...\n")

    results = {}

    for bridge in registered_bridges:
        bridge_id = bridge['id']
        bridge_ip = bridge['ip']
        username = bridge.get('username')
        client_key = bridge.get('client_key')

        print(f"Bridge: {bridge_id} ({bridge_ip})")

        if not username:
            print(f"   ⚠️  Skipping: No username found (not registered)")
            continue

        automations = await capture_automations(bridge_ip, username, client_key)

        if automations:
            results[bridge_id] = automations

            # Save to file unless JSON mode
            if not args.json:
                # Extract bridge name from automation data
                bridge_name = automations.get('bridge_info', {}).get('config', {}).get('name', bridge_id)

                if save_automations(automations, bridge_id, bridge_name, args.output):
                    sanitized_name = sanitize_filename(bridge_name)
                    output_file = Path(args.output) / f"{sanitized_name}-{bridge_id}-automations.json"
                    print(f"   💾 Saved automations to: {output_file}")
                else:
                    print(f"   ❌ Failed to save automations")

        print()  # Empty line between bridges

    return results


def print_summary(results: Dict[str, Dict]):
    """
    Print summary of automation capture results.

    Args:
        results (dict): Mapping of bridge_id to automation data
    """
    if not results:
        print("❌ No automation data collected.")
        return

    print("=" * 70)
    print(f"📊 Automation Capture Summary")
    print("=" * 70)
    print(f"\nCaptured data from {len(results)} bridge(s):\n")

    for bridge_id, automations in results.items():
        bridge_name = automations.get('bridge_info', {}).get('config', {}).get('name', bridge_id)
        print(f"Bridge: {bridge_name} ({bridge_id})")

        automation_data = automations.get('automations', {})

        smart_scenes = automation_data.get('smart_scenes', {})
        if 'count' in smart_scenes:
            print(f"   📅 Smart Scenes: {smart_scenes['count']}")

        behavior_instances = automation_data.get('behavior_instances', {})
        if 'count' in behavior_instances:
            enabled_count = sum(1 for item in behavior_instances.get('items', []) if item.get('enabled'))
            print(f"   🤖 Behavior Instances: {behavior_instances['count']} ({enabled_count} enabled)")

        behavior_scripts = automation_data.get('behavior_scripts', {})
        if 'count' in behavior_scripts:
            print(f"   📜 Behavior Scripts: {behavior_scripts['count']}")

        geofence_clients = automation_data.get('geofence_clients', {})
        if 'count' in geofence_clients:
            print(f"   📍 Geofence Clients: {geofence_clients['count']}")

        geolocation = automation_data.get('geolocation')
        if geolocation and isinstance(geolocation, dict) and 'error' not in geolocation:
            is_configured = geolocation.get('is_configured', False)
            print(f"   🌍 Geolocation: {'Configured' if is_configured else 'Not configured'}")

        print()


def main():
    """Main entry point for the script."""
    args = parse_arguments()

    # Load config file
    if not args.json:
        print(f"Loading config from: {args.config}")

    config_data = load_config(args.config)

    if config_data is None:
        sys.exit(1)

    # Capture automations
    try:
        results = asyncio.run(capture_bridge_automations(config_data, args))
    except KeyboardInterrupt:
        print("\n\n❌ Automation capture interrupted by user.")
        sys.exit(2)

    # Output results
    if args.json:
        # JSON mode - output to stdout
        print(json.dumps(results, indent=2, cls=CustomJSONEncoder))
    else:
        # Interactive mode - show summary
        print_summary(results)

        if results:
            print(f"✅ Automation capture complete! Files saved to: {args.output}")
        else:
            print("⚠️  No automation data collected.")
            sys.exit(1)

    sys.exit(0 if results else 1)


if __name__ == "__main__":
    main()
