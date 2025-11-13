#!/usr/bin/env python3
"""
Home Assistant Hue Integration Inventory Export

This script exports the Philips Hue integration inventory from Home Assistant,
providing a complementary view to the direct aiohue API inventories.

Unlike aiohue inventories (which query Hue bridges directly), this script exports
the Home Assistant perspective: entity IDs, area assignments, user customizations,
and the integration state.

Usage:
    # Export all bridges (interactive)
    python3 export-ha-hue-inventory.py

    # Export specific bridge
    python3 export-ha-hue-inventory.py --bridge EG

    # Include current states
    python3 export-ha-hue-inventory.py --include-states

    # JSON output (machine-readable)
    python3 export-ha-hue-inventory.py --json

    # Custom output directory
    python3 export-ha-hue-inventory.py --output-dir /path/to/output

Requirements:
    - SSH access to Home Assistant server
    - SSH key at relative path: ../../../homeassistant_ssh_key
    - HA API token at /data/.ha_token on HA server
    - Configure HA_SSH_HOST environment variable or edit SSH_HOST in script

Output:
    JSON files per bridge in ha_inventory/ directory:
    - ha_Bridge_Name-abc123def456.json
    - ha_Bridge_Name2-xyz789ghi012.json

Exit Codes:
    0 - Success
    1 - Error (connection failed, no bridges found, etc.)
"""

import sys
import os
from pathlib import Path

# Auto-activate virtual environment
VENV_PATH = Path(__file__).parent.parent.parent / "venv"
if VENV_PATH.exists():
    venv_site_packages = VENV_PATH / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

import argparse
import json
import re
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any


# SSH Configuration
SSH_KEY = Path(__file__).parent.parent.parent / "homeassistant_ssh_key"
SSH_USER = os.getenv("HA_SSH_USER", "hassio")


def _load_ha_config() -> Dict[str, str]:
    """
    Load HA configuration from ha_config.json.

    Returns:
        Dict with ha_host, ha_user, ha_ssh_key, ha_inventory_dir (empty if file not found)
    """
    config_file = Path(__file__).parent.parent / "ha_config.json"

    if config_file.exists():
        try:
            with open(config_file) as f:
                config = json.load(f)
                return {
                    "ha_host": config.get("ha_host", ""),
                    "ha_user": config.get("ha_user", "hassio"),
                    "ha_ssh_key": config.get("ha_ssh_key", ""),
                    "ha_inventory_dir": config.get("ha_inventory_dir", "/homeassistant/hue_inventories")
                }
        except (json.JSONDecodeError, IOError):
            pass

    return {}


def _validate_ssh_host(host: str) -> str:
    """
    Validate SSH host to prevent command injection.

    Args:
        host: Hostname or IP address

    Returns:
        Validated host string

    Raises:
        SystemExit: If host is invalid or not set
    """
    if not host:
        print("Error: HA SSH host not configured", file=sys.stderr)
        print("", file=sys.stderr)
        print("Please configure via ha_config.json:", file=sys.stderr)
        print('  {"ha_host": "192.168.1.100", ...}', file=sys.stderr)
        print("", file=sys.stderr)
        print("Or set environment variable:", file=sys.stderr)
        print("  export HA_SSH_HOST=192.168.1.100", file=sys.stderr)
        sys.exit(1)

    # Allow only safe characters: alphanumeric, underscore, dots, hyphens, brackets (IPv6), colons (IPv6/port)
    if not re.match(r'^[\w\.\-\[\]:]+$', host):
        print(f"Error: Invalid HA_SSH_HOST format: {host}", file=sys.stderr)
        print("Host must contain only alphanumeric characters, underscores, dots, hyphens, brackets, and colons", file=sys.stderr)
        sys.exit(1)

    return host


# Load configuration from ha_config.json (preferred) or environment variables (fallback)
_ha_config = _load_ha_config()
SSH_HOST = _validate_ssh_host(_ha_config.get("ha_host") or os.getenv("HA_SSH_HOST", ""))
if _ha_config.get("ha_user"):
    SSH_USER = _ha_config["ha_user"]


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Export Home Assistant Hue integration inventory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Export all bridges
  %(prog)s --bridge EG                        # Export Bridge EG only
  %(prog)s --bridge abc123def456              # Export by unique ID
  %(prog)s --include-states                   # Include current entity states
  %(prog)s --json                             # Machine-readable output
  %(prog)s --output-dir /custom/path          # Custom output directory

Environment Variables:
  HA_SSH_HOST                                 # Home Assistant IP/hostname
  HA_SSH_USER                                 # SSH username (default: hassio)

Output Structure:
  The script creates JSON files with HA entity information grouped by bridge.
  Files are named: ha_<bridge_title>-<unique_id>.json

Comparison with aiohue Inventories:
  - aiohue: Direct Hue API v2 resources (technical, low-level)
  - HA:     Integration perspective (entity IDs, areas, user customization)

  Both are complementary and provide different views of the same devices.
        """
    )

    parser.add_argument(
        "--bridge",
        type=str,
        help="Export specific bridge only (by name or unique ID)"
    )

    parser.add_argument(
        "--include-states",
        action="store_true",
        help="Include current entity states (default: config only)"
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "bridges" / "ha_inventory",
        help="Output directory for inventory files"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output progress in JSON format (default: human-readable)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    return parser.parse_args()


def run_ssh_command(command: str) -> Optional[str]:
    """
    Execute command via SSH on Home Assistant.

    Args:
        command: Command to execute

    Returns:
        Command output as string, or None on error
    """
    try:
        result = subprocess.run(
            ["ssh", "-i", str(SSH_KEY), f"{SSH_USER}@{SSH_HOST}", command],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            print(f"SSH command failed: {result.stderr}", file=sys.stderr)
            return None

        return result.stdout

    except subprocess.TimeoutExpired:
        print("SSH command timed out", file=sys.stderr)
        return None
    except (subprocess.SubprocessError, OSError) as e:
        print(f"SSH error: {e}", file=sys.stderr)
        return None


def load_ha_storage_file(filepath: str) -> Optional[Dict]:
    """
    Load a JSON file from HA .storage directory.

    Args:
        filepath: Path to file on HA server

    Returns:
        Parsed JSON dict, or None on error
    """
    output = run_ssh_command(f"cat {filepath}")
    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON from {filepath}: {e}", file=sys.stderr)
        return None


def get_ha_version() -> Optional[str]:
    """Get Home Assistant version."""
    output = run_ssh_command("cat /homeassistant/.HA_VERSION")
    return output.strip() if output else None


def get_api_states() -> Optional[List[Dict]]:
    """
    Query HA API for all entity states.

    Returns:
        List of entity state dicts, or None on error
    """
    command = 'curl -s -H "Authorization: Bearer $(cat /data/.ha_token)" http://localhost:8123/api/states'
    output = run_ssh_command(command)

    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def filter_hue_bridges(config_entries: Dict) -> List[Dict]:
    """
    Filter Hue bridge config entries.

    Args:
        config_entries: Parsed core.config_entries data

    Returns:
        List of Hue bridge entries
    """
    return [
        entry for entry in config_entries.get("data", {}).get("entries", [])
        if entry.get("domain") == "hue"
    ]


def filter_bridge_entities(entity_registry: Dict, config_entry_id: str) -> List[Dict]:
    """
    Filter entities for specific bridge.

    Args:
        entity_registry: Parsed core.entity_registry data
        config_entry_id: Bridge config entry ID

    Returns:
        List of entity dicts for this bridge
    """
    return [
        entity for entity in entity_registry.get("data", {}).get("entities", [])
        if entity.get("platform") == "hue"
        and entity.get("config_entry_id") == config_entry_id
    ]


def get_device_info(device_registry: Dict, device_id: str) -> Optional[Dict]:
    """
    Get device information from registry.

    Args:
        device_registry: Parsed core.device_registry data
        device_id: Device ID to look up

    Returns:
        Device dict or None if not found
    """
    devices = device_registry.get("data", {}).get("devices", [])
    return next((d for d in devices if d.get("id") == device_id), None)


def enrich_entity_with_state(entity: Dict, api_states: List[Dict]) -> Dict:
    """
    Add current state to entity from API.

    Args:
        entity: Entity dict from registry
        api_states: List of all API states

    Returns:
        Entity dict with added current_state field
    """
    entity_id = entity.get("entity_id")
    state = next((s for s in api_states if s.get("entity_id") == entity_id), None)

    if state:
        entity["current_state"] = {
            "state": state.get("state"),
            "attributes": state.get("attributes", {})
        }

    return entity


def group_entities_by_type(entities: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Group entities by platform type.

    Args:
        entities: List of entity dicts

    Returns:
        Dict with entity_type as key, list of entities as value
    """
    grouped = {}

    for entity in entities:
        entity_id = entity.get("entity_id", "")

        # Extract type from entity_id (light.xxx, sensor.xxx, etc.)
        entity_type = entity_id.split(".")[0] if "." in entity_id else "unknown"

        if entity_type not in grouped:
            grouped[entity_type] = []

        grouped[entity_type].append(entity)

    return grouped


def get_mac_address(device: Dict) -> Optional[str]:
    """Get first MAC address from device connections."""
    for conn in device.get("connections", []):
        if conn[0] == "mac":
            return conn[1]
    return None


def get_all_mac_addresses(device: Dict) -> List[str]:
    """Get all MAC addresses from device connections."""
    return [conn[1] for conn in device.get("connections", []) if conn[0] == "mac"]


def create_bridge_inventory(
    bridge: Dict,
    entities: List[Dict],
    device_registry: Dict,
    include_states: bool,
    api_states: Optional[List[Dict]],
    ha_version: str
) -> Dict:
    """
    Create inventory structure for a single bridge.

    Args:
        bridge: Bridge config entry
        entities: List of entities for this bridge
        device_registry: Device registry data
        include_states: Whether to include current states
        api_states: API states (if include_states=True)
        ha_version: Home Assistant version

    Returns:
        Complete inventory dict for this bridge
    """
    # Find bridge device
    bridge_device = None
    devices = device_registry.get("data", {}).get("devices", [])
    for device in devices:
        if bridge["entry_id"] in device.get("config_entries", []):
            identifiers = device.get("identifiers", [])
            if identifiers and any(bridge["unique_id"] in str(ident) for ident in identifiers):
                bridge_device = device
                break

    # Enrich entities with device info and optionally states
    enriched_entities = []
    for entity in entities:
        enriched = entity.copy()

        # Add device info
        if entity.get("device_id"):
            device = get_device_info(device_registry, entity["device_id"])
            if device:
                enriched["device_info"] = {
                    "manufacturer": device.get("manufacturer"),
                    "model": device.get("model"),
                    "model_id": device.get("model_id"),
                    "sw_version": device.get("sw_version"),
                    "mac": get_mac_address(device)
                }

        # Add current state if requested
        if include_states and api_states:
            enriched = enrich_entity_with_state(enriched, api_states)

        enriched_entities.append(enriched)

    # Group by type
    grouped = group_entities_by_type(enriched_entities)

    # Create resources section
    resources = {}
    for entity_type, entity_list in grouped.items():
        resources[entity_type] = {
            "count": len(entity_list),
            "items": entity_list
        }

    # Build inventory
    inventory = {
        "metadata": {
            "source": "home_assistant",
            "ha_version": ha_version,
            "exported_at": datetime.now().isoformat(),
            "export_method": "ssh_api",
            "includes_states": include_states
        },
        "bridge_info": {
            "config_entry_id": bridge["entry_id"],
            "unique_id": bridge["unique_id"],
            "title": bridge["title"],
            "host": bridge.get("data", {}).get("host"),
            "api_version": bridge.get("data", {}).get("api_version"),
        },
        "resources": resources
    }

    # Add bridge device info if found
    if bridge_device:
        inventory["bridge_info"]["device"] = {
            "manufacturer": bridge_device.get("manufacturer"),
            "model": bridge_device.get("model"),
            "model_id": bridge_device.get("model_id"),
            "sw_version": bridge_device.get("sw_version"),
            "mac_addresses": get_all_mac_addresses(bridge_device)
        }

    return inventory


def sanitize_filename(name: str) -> str:
    """
    Sanitize bridge title for use in filename.

    Replaces problematic characters with safe alternatives:
    - Non-alphanumeric characters (except spaces and hyphens) → underscore
    - Multiple spaces/hyphens → single underscore
    - Leading/trailing underscores → removed

    Args:
        name: Bridge title to sanitize

    Returns:
        Safe filename string

    Examples:
        >>> sanitize_filename("My Bridge")
        'My_Bridge'
        >>> sanitize_filename("Bridge/2024")
        'Bridge_2024'
        >>> sanitize_filename("Test  --  Bridge")
        'Test_Bridge'
    """
    # Replace problematic characters with safe alternatives
    safe_name = re.sub(r'[^\w\s-]', '_', name)  # Keep alphanumeric, spaces, hyphens
    safe_name = re.sub(r'[-\s]+', '_', safe_name)  # Collapse spaces/hyphens to single underscore
    return safe_name.strip('_')  # Remove leading/trailing underscores


def main():
    """Main entry point."""
    args = parse_arguments()

    # Verify SSH key exists
    if not SSH_KEY.exists():
        print(f"Error: SSH key not found at {SSH_KEY}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not args.json:
        print("Home Assistant Hue Integration Inventory Export")
        print("=" * 70)
        print(f"\nConnecting to {SSH_HOST}...")

    # Get HA version
    ha_version = get_ha_version()
    if not ha_version:
        print("Error: Could not determine HA version", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print(f"Home Assistant Version: {ha_version}")

    # Load storage files
    if not args.json:
        print("\nLoading HA storage files...")

    config_entries = load_ha_storage_file("/homeassistant/.storage/core.config_entries")
    entity_registry = load_ha_storage_file("/homeassistant/.storage/core.entity_registry")
    device_registry = load_ha_storage_file("/homeassistant/.storage/core.device_registry")

    if not all([config_entries, entity_registry, device_registry]):
        print("Error: Failed to load required storage files", file=sys.stderr)
        sys.exit(1)

    # Get API states if requested
    api_states = None
    if args.include_states:
        if not args.json:
            print("Querying API for current states...")
        api_states = get_api_states()
        if not api_states:
            print("Warning: Could not load API states", file=sys.stderr)

    # Find Hue bridges
    bridges = filter_hue_bridges(config_entries)

    if not bridges:
        print("Error: No Hue bridges found in Home Assistant", file=sys.stderr)
        sys.exit(1)

    # Filter bridges if specific one requested
    if args.bridge:
        bridges = [
            b for b in bridges
            if args.bridge.lower() in b.get("title", "").lower()
            or args.bridge in b.get("unique_id", "")
        ]

        if not bridges:
            print(f"Error: No bridge found matching '{args.bridge}'", file=sys.stderr)
            sys.exit(1)

    if not args.json:
        print(f"\nFound {len(bridges)} Hue bridge(s)")
        print()

    # Export each bridge
    exported_files = []

    for bridge in bridges:
        bridge_title = bridge.get("title", "Unknown")
        bridge_id = bridge.get("unique_id", "unknown")

        if not args.json:
            print(f"Processing: {bridge_title} ({bridge_id})...")

        # Get entities for this bridge
        entities = filter_bridge_entities(entity_registry, bridge["entry_id"])

        if not args.json:
            print(f"  Found {len(entities)} entities")

        # Create inventory
        inventory = create_bridge_inventory(
            bridge,
            entities,
            device_registry,
            args.include_states,
            api_states,
            ha_version
        )

        # Generate filename
        safe_title = sanitize_filename(bridge_title)
        safe_id = sanitize_filename(bridge_id)
        filename = f"ha_{safe_title}-{safe_id or 'unknown_bridge'}.json"
        filepath = args.output_dir / filename

        # Write file
        with open(filepath, 'w') as f:
            json.dump(inventory, f, indent=2, ensure_ascii=False)

        exported_files.append(str(filepath))

        if not args.json:
            print(f"  Exported to: {filepath}")
            print()

    # Output results
    if args.json:
        result = {
            "success": True,
            "bridges_exported": len(exported_files),
            "files": exported_files
        }
        print(json.dumps(result, indent=2))
    else:
        print("=" * 70)
        print(f"Successfully exported {len(exported_files)} bridge(s)")
        print(f"\nOutput directory: {args.output_dir}")
        print("\nNext steps:")
        print("  - Compare with aiohue inventories in ../inventory/")
        print("  - Use for Home Assistant automation development")
        print("  - Track entity changes over time")

    sys.exit(0)


if __name__ == "__main__":
    main()
