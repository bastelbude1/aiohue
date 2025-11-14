#!/usr/bin/env python3
"""
Philips Hue Bridge Inventory Script

This script connects to registered Philips Hue bridges and retrieves a comprehensive
inventory of all resources including devices, scenes, zones, rooms, automations, and more.

Usage:
    # Inventory all registered bridges
    python3 inventory-hue-bridge.py

    # Inventory specific bridge by ID
    python3 inventory-hue-bridge.py --bridge-id abc123def456

    # Use custom config file location
    python3 inventory-hue-bridge.py --config /path/to/config.json

    # Save to custom inventory directory
    python3 inventory-hue-bridge.py --output /path/to/inventory

    # JSON output to stdout
    python3 inventory-hue-bridge.py --json

    # Show help
    python3 inventory-hue-bridge.py --help

Requirements:
    - aiohue library (auto-activated from /path/to/venv)
    - Registered bridges with credentials in config file

Output:
    - Saves inventory for each bridge to bridges/inventory/{bridge-id}.json
    - Interactive: Shows summary of resources found
    - JSON mode: Outputs complete inventory to stdout

Exit Codes:
    0 - Success (inventory completed)
    1 - Error (connection failed or no registered bridges)
"""

import sys
import os
from pathlib import Path

# Auto-activate virtual environment
VENV_PATH = Path(__file__).parent.parent.parent / "venv"
VENV_ACTIVATE = VENV_PATH / "bin" / "activate_this.py"

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
# Import shared JSON encoder
from common.json_utils import CustomJSONEncoder

# NOTE: CustomJSONEncoder class moved to common/json_utils.py to avoid duplication
# The encoder provides: enum handling, circular reference protection, recursive serialization


# Default paths
DEFAULT_CONFIG_FILE = Path(__file__).parent.parent / "bridges" / "config.json"
DEFAULT_INVENTORY_DIR = Path(__file__).parent.parent / "bridges" / "inventory"


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
        description="Inventory resources from Philips Hue bridges",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                        # Inventory all bridges
  %(prog)s --bridge-id abc123def456               # Inventory specific bridge
  %(prog)s --config /path/to/config.json          # Use custom config file
  %(prog)s --output /path/to/inventory            # Custom output directory
  %(prog)s --json                                 # JSON output to stdout

Notes:
  - Only registered bridges will be inventoried
  - Inventory files are saved as {bridge-id}.json
  - Use --json for machine-readable output

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
        help="Inventory only this specific bridge ID"
    )

    parser.add_argument(
        "--output",
        metavar="DIR",
        type=str,
        default=str(DEFAULT_INVENTORY_DIR),
        help=f"Output directory for inventory files (default: {DEFAULT_INVENTORY_DIR})"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output inventory in JSON format to stdout (does not save to files)"
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


def save_inventory(inventory: Dict, bridge_id: str, bridge_name: str, output_dir: str) -> bool:
    """
    Save bridge inventory to JSON file.

    Args:
        inventory (dict): Inventory data
        bridge_id (str): Bridge ID
        bridge_name (str): Bridge name
        output_dir (str): Output directory path

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Use format: {name}-{bridge_id}.json
        sanitized_name = sanitize_filename(bridge_name)
        output_file = Path(output_dir) / f"{sanitized_name}-{bridge_id}.json"
        with open(output_file, 'w') as f:
            json.dump(inventory, f, indent=2, cls=CustomJSONEncoder)

        return True
    except Exception as e:
        print(f"Error saving inventory: {e}", file=sys.stderr)
        return False


async def inventory_bridge(bridge_ip: str, username: str, client_key: Optional[str] = None) -> Optional[Dict]:
    """
    Connect to a Hue bridge and retrieve comprehensive inventory.

    Args:
        bridge_ip (str): IP address of the bridge
        username (str): API username
        client_key (str, optional): Client key for V2 API

    Returns:
        dict: Complete inventory of bridge resources, or None on error
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

        inventory = {
            "bridge_info": {
                "ip": bridge_ip,
                "inventoried_at": datetime.now().isoformat(),
            },
            "resources": {}
        }

        # Retrieve devices
        try:
            print(f"      📱 Retrieving devices...")
            devices = bridge.devices.items
            inventory["resources"]["devices"] = {
                "count": len(devices),
                "items": [
                    {
                        "id": device.id,
                        "type": str(device.type) if hasattr(device, 'type') else None,
                        "product_data": device.product_data.__dict__ if hasattr(device, 'product_data') else None,
                        "metadata": device.metadata.__dict__ if hasattr(device, 'metadata') else None,
                        "services": [str(s) for s in device.services] if hasattr(device, 'services') else []
                    }
                    for device in devices
                ]
            }
            print(f"      ✅ Found {len(devices)} devices")
        except Exception as e:
            print(f"      ⚠️  Error retrieving devices: {e}", file=sys.stderr)
            inventory["resources"]["devices"] = {"error": str(e)}

        # Retrieve lights
        try:
            print(f"      💡 Retrieving lights...")
            lights = bridge.lights.items
            inventory["resources"]["lights"] = {
                "count": len(lights),
                "items": [
                    {
                        "id": light.id,
                        "type": str(light.type) if hasattr(light, 'type') else None,
                        "on": light.on.__dict__ if hasattr(light, 'on') and light.on is not None else None,
                        "dimming": light.dimming.__dict__ if hasattr(light, 'dimming') and light.dimming is not None else None,
                        "color": light.color.__dict__ if hasattr(light, 'color') and light.color is not None else None,
                        "color_temperature": light.color_temperature.__dict__ if hasattr(light, 'color_temperature') and light.color_temperature is not None else None,
                        "metadata": light.metadata.__dict__ if hasattr(light, 'metadata') and light.metadata is not None else None,
                        "owner": str(light.owner) if hasattr(light, 'owner') and light.owner is not None else None
                    }
                    for light in lights
                ]
            }
            print(f"      ✅ Found {len(lights)} lights")
        except Exception as e:
            print(f"      ⚠️  Error retrieving lights: {e}", file=sys.stderr)
            inventory["resources"]["lights"] = {"error": str(e)}

        # Retrieve scenes
        try:
            print(f"      🎨 Retrieving scenes...")
            scenes = bridge.scenes.items
            inventory["resources"]["scenes"] = {
                "count": len(scenes),
                "items": [
                    {
                        "id": scene.id,
                        "type": str(scene.type) if hasattr(scene, 'type') else None,
                        "metadata": scene.metadata.__dict__ if hasattr(scene, 'metadata') and scene.metadata is not None else None,
                        "group": str(scene.group) if hasattr(scene, 'group') and scene.group is not None else None,
                        "actions": scene.actions if hasattr(scene, 'actions') and scene.actions is not None else []
                    }
                    for scene in scenes
                ]
            }
            print(f"      ✅ Found {len(scenes)} scenes")
        except Exception as e:
            print(f"      ⚠️  Error retrieving scenes: {e}", file=sys.stderr)
            inventory["resources"]["scenes"] = {"error": str(e)}

        # Retrieve groups (zones, rooms)
        try:
            print(f"      🏠 Retrieving groups (zones/rooms)...")
            groups = bridge.groups.items

            zones = [g for g in groups if g.type == "zone"]
            rooms = [g for g in groups if g.type == "room"]

            inventory["resources"]["groups"] = {
                "total_count": len(groups),
                "zones": {
                    "count": len(zones),
                    "items": [
                        {
                            "id": zone.id,
                            "type": str(zone.type) if hasattr(zone, 'type') else None,
                            "metadata": zone.metadata.__dict__ if hasattr(zone, 'metadata') and zone.metadata is not None else None,
                            "children": [str(c) for c in zone.children] if hasattr(zone, 'children') and zone.children is not None else []
                        }
                        for zone in zones
                    ]
                },
                "rooms": {
                    "count": len(rooms),
                    "items": [
                        {
                            "id": room.id,
                            "type": str(room.type) if hasattr(room, 'type') else None,
                            "metadata": room.metadata.__dict__ if hasattr(room, 'metadata') and room.metadata is not None else None,
                            "children": [str(c) for c in room.children] if hasattr(room, 'children') and room.children is not None else []
                        }
                        for room in rooms
                    ]
                }
            }
            print(f"      ✅ Found {len(zones)} zones, {len(rooms)} rooms")
        except Exception as e:
            print(f"      ⚠️  Error retrieving groups: {e}", file=sys.stderr)
            inventory["resources"]["groups"] = {"error": str(e)}

        # Retrieve sensors
        try:
            print(f"      🌡️  Retrieving sensors...")
            sensors = bridge.sensors.items
            inventory["resources"]["sensors"] = {
                "count": len(sensors),
                "items": [
                    {
                        "id": sensor.id,
                        "type": str(sensor.type) if hasattr(sensor, 'type') else None,
                        "enabled": sensor.enabled if hasattr(sensor, 'enabled') else None,
                        "metadata": sensor.metadata.__dict__ if hasattr(sensor, 'metadata') and sensor.metadata is not None else None,
                        "owner": str(sensor.owner) if hasattr(sensor, 'owner') and sensor.owner is not None else None
                    }
                    for sensor in sensors
                ]
            }
            print(f"      ✅ Found {len(sensors)} sensors")
        except Exception as e:
            print(f"      ⚠️  Error retrieving sensors: {e}", file=sys.stderr)
            inventory["resources"]["sensors"] = {"error": str(e)}

        # Get bridge config/info
        try:
            print(f"      ⚙️  Retrieving bridge configuration...")
            config = bridge.config
            inventory["bridge_info"]["config"] = {
                "bridge_id": config.bridge_id if hasattr(config, 'bridge_id') else None,
                "name": config.name if hasattr(config, 'name') else None,
                "model_id": config.model_id if hasattr(config, 'model_id') else None,
                "sw_version": config.sw_version if hasattr(config, 'sw_version') else None,
            }
            print(f"      ✅ Retrieved bridge configuration")
        except Exception as e:
            print(f"      ⚠️  Error retrieving config: {e}", file=sys.stderr)
            inventory["bridge_info"]["config"] = {"error": str(e)}

        # Close bridge connection
        await bridge.close()

        return inventory

    except ImportError as e:
        print(f"Error: Required library not found: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"❌ Inventory error: {e}", file=sys.stderr)
        return None


async def inventory_bridges(config_data: Dict, args) -> Dict[str, Dict]:
    """
    Inventory bridges based on command-line arguments.

    Args:
        config_data (dict): Bridge configuration data
        args: Parsed command-line arguments

    Returns:
        dict: Mapping of bridge_id to inventory data
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

    print(f"\n📊 Starting inventory of {len(registered_bridges)} bridge(s)...\n")

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

        inventory = await inventory_bridge(bridge_ip, username, client_key)

        if inventory:
            results[bridge_id] = inventory

            # Save to file unless JSON mode
            if not args.json:
                # Extract bridge name from inventory
                bridge_name = inventory.get('bridge_info', {}).get('config', {}).get('name', bridge_id)

                if save_inventory(inventory, bridge_id, bridge_name, args.output):
                    sanitized_name = sanitize_filename(bridge_name)
                    output_file = Path(args.output) / f"{sanitized_name}-{bridge_id}.json"
                    print(f"   💾 Saved inventory to: {output_file}")
                else:
                    print(f"   ❌ Failed to save inventory")

        print()  # Empty line between bridges

    return results


def print_summary(results: Dict[str, Dict]):
    """
    Print summary of inventory results.

    Args:
        results (dict): Mapping of bridge_id to inventory data
    """
    if not results:
        print("❌ No inventory data collected.")
        return

    print("=" * 70)
    print(f"📊 Inventory Summary")
    print("=" * 70)
    print(f"\nInventoried {len(results)} bridge(s):\n")

    for bridge_id, inventory in results.items():
        bridge_name = inventory.get('bridge_info', {}).get('config', {}).get('name', bridge_id)
        print(f"Bridge: {bridge_name} ({bridge_id})")

        resources = inventory.get('resources', {})

        devices = resources.get('devices', {})
        if 'count' in devices:
            print(f"   📱 Devices: {devices['count']}")

        lights = resources.get('lights', {})
        if 'count' in lights:
            print(f"   💡 Lights: {lights['count']}")

        scenes = resources.get('scenes', {})
        if 'count' in scenes:
            print(f"   🎨 Scenes: {scenes['count']}")

        groups = resources.get('groups', {})
        if 'zones' in groups:
            print(f"   🏠 Zones: {groups['zones']['count']}, Rooms: {groups['rooms']['count']}")

        sensors = resources.get('sensors', {})
        if 'count' in sensors:
            print(f"   🌡️  Sensors: {sensors['count']}")

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

    # Inventory bridges
    try:
        results = asyncio.run(inventory_bridges(config_data, args))
    except KeyboardInterrupt:
        print("\n\n❌ Inventory interrupted by user.")
        sys.exit(2)

    # Output results
    if args.json:
        # JSON mode - output to stdout
        print(json.dumps(results, indent=2, cls=CustomJSONEncoder))
    else:
        # Interactive mode - show summary
        print_summary(results)

        if results:
            print(f"✅ Inventory complete! Files saved to: {args.output}")
        else:
            print("⚠️  No inventory data collected.")
            sys.exit(1)

    sys.exit(0 if results else 1)


if __name__ == "__main__":
    main()
