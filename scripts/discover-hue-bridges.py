#!/usr/bin/env python3
"""
Philips Hue Bridge Discovery Script

This script scans the local network for Philips Hue bridges using the
aiohue library and Philips' N-UPnP discovery service.

Usage:
    # Interactive mode (human-readable output)
    python3 discover-hue-bridges.py

    # JSON mode (machine-readable output for scripting)
    python3 discover-hue-bridges.py --json

    # Save discovered bridges to file
    python3 discover-hue-bridges.py --save /home/baste/HA/aiohue/bridges

    # Show help
    python3 discover-hue-bridges.py --help

Requirements:
    - aiohue library (auto-activated from /home/baste/HA/venv)
    - Network connectivity to Philips discovery service

Output:
    - Interactive: Formatted table with bridge information
    - JSON: Structured JSON array with bridge details

Exit Codes:
    0 - Success (bridges found)
    1 - Error (discovery failed or no bridges found)
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


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Discover Philips Hue bridges on the local network",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Interactive mode
  %(prog)s --json                             # JSON output for scripting
  %(prog)s --save /path/to/bridges            # Save to file
  %(prog)s --save ../bridges --json           # Save and display JSON
  %(prog)s --json | jq .                      # Pretty JSON with jq

For more information, visit: https://github.com/home-assistant-libs/aiohue
        """
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format (default: human-readable)"
    )

    parser.add_argument(
        "--save",
        metavar="FILE",
        type=str,
        help="Save discovered bridges to FILE in JSON format with metadata"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    return parser.parse_args()


async def discover_bridges():
    """
    Discover Philips Hue bridges using N-UPnP service.

    Returns:
        list: List of dictionaries containing bridge information
        None: If discovery fails
    """
    try:
        from aiohue.discovery import discover_nupnp

        bridges = await discover_nupnp()

        if not bridges:
            return []

        bridge_list = []
        for bridge in bridges:
            bridge_info = {
                'id': bridge.id,
                'ip': bridge.host,
                'supports_v2': bridge.supports_v2 if hasattr(bridge, 'supports_v2') else None
            }
            bridge_list.append(bridge_info)

        return bridge_list

    except ImportError as e:
        print(f"Error: aiohue library not found. Please ensure the virtual environment is set up correctly.", file=sys.stderr)
        print(f"Details: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error during discovery: {e}", file=sys.stderr)
        return None


def print_interactive(bridges):
    """
    Print bridge information in human-readable format.

    Args:
        bridges (list): List of bridge information dictionaries
    """
    if not bridges:
        print("No Philips Hue bridges found on the network.")
        print("\nTroubleshooting:")
        print("  - Ensure your Hue bridge is powered on and connected to the network")
        print("  - Check that your computer is on the same network as the bridge")
        print("  - Verify network connectivity")
        return

    print("Philips Hue Bridge Discovery")
    print("=" * 70)
    print(f"\nFound {len(bridges)} bridge(s):\n")

    for i, bridge in enumerate(bridges, 1):
        print(f"Bridge #{i}:")
        print(f"  ID:              {bridge['id']}")
        print(f"  IP Address:      {bridge['ip']}")
        if bridge.get('supports_v2') is not None:
            api_version = "v2 (modern)" if bridge['supports_v2'] else "v1 (legacy)"
            print(f"  API Support:     {api_version}")
        print("-" * 70)

    print("\nNext Steps:")
    print("  1. Note the IP address of the bridge you want to connect to")
    print("  2. Press the physical button on your Hue bridge")
    print("  3. Run the registration script within 30 seconds")
    print(f"     (Registration script will be available soon)")


def print_json(bridges):
    """
    Print bridge information in JSON format.

    Args:
        bridges (list): List of bridge information dictionaries
    """
    output = {
        'count': len(bridges) if bridges else 0,
        'bridges': bridges if bridges else []
    }
    print(json.dumps(output, indent=2))


def save_bridges(bridges, filepath):
    """
    Save bridge information to a JSON file with metadata.

    Args:
        bridges (list): List of bridge information dictionaries
        filepath (str): Path to save the file

    Returns:
        bool: True if save successful, False otherwise
    """
    try:
        # Create output structure with metadata
        output = {
            'discovered': datetime.now().strftime('%Y-%m-%d'),
            'timestamp': datetime.now().isoformat(),
            'count': len(bridges) if bridges else 0,
            'bridges': []
        }

        # Enhance bridge data with registration fields
        for bridge in bridges if bridges else []:
            bridge_data = {
                'id': bridge['id'],
                'ip': bridge['ip'],
                'api_version': 'v2' if bridge.get('supports_v2') else 'v1',
                'registered': False,
                'username': None,
                'client_key': None
            }
            output['bridges'].append(bridge_data)

        # Write to file
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"✓ Bridges saved to: {filepath}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"Error saving to file: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point for the script."""
    args = parse_arguments()

    # Discover bridges
    bridges = asyncio.run(discover_bridges())

    # Handle discovery failure
    if bridges is None:
        sys.exit(1)

    # Save to file if requested
    if args.save:
        if not save_bridges(bridges, args.save):
            sys.exit(1)

    # Output results (unless only saving)
    if not args.save or args.json:
        if args.json:
            print_json(bridges)
        else:
            print_interactive(bridges)
    elif args.save and not args.json:
        # When saving without --json, show brief confirmation
        if bridges:
            print(f"Discovered {len(bridges)} bridge(s) and saved to {args.save}")
        else:
            print("No bridges found")

    # Exit with appropriate code
    sys.exit(0 if bridges else 1)


if __name__ == "__main__":
    main()
