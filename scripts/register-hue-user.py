#!/usr/bin/env python3
"""
Philips Hue Bridge User Registration Script

This script registers with Philips Hue bridges by creating API users (application keys).
It reads bridge information from a JSON file, prompts you to press the physical button
on each bridge, and saves the authentication credentials.

Usage:
    # Register with all unregistered bridges
    python3 register-hue-user.py

    # Specify custom bridges file location
    python3 register-hue-user.py --bridges /path/to/bridges

    # Register with specific bridge by ID
    python3 register-hue-user.py --bridge-id ecb5faa015bb

    # Force re-registration (even if already registered)
    python3 register-hue-user.py --force

    # Show help
    python3 register-hue-user.py --help

Requirements:
    - aiohue library (auto-activated from /home/baste/HA/venv)
    - Physical access to press the bridge button
    - Bridges file from discover-hue-bridges.py

Process:
    1. Reads bridge information from file
    2. For each unregistered bridge:
       a. Prompts you to press the physical button
       b. Waits for your confirmation
       c. Attempts to register and create API user
       d. Saves credentials (username/client_key) to file

Exit Codes:
    0 - Success (all bridges registered)
    1 - Error (registration failed or file error)
    2 - User cancelled
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
import socket
from datetime import datetime


# Default bridges file location
DEFAULT_BRIDGES_FILE = Path(__file__).parent.parent / "bridges" / "config.json"


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Register with Philips Hue bridges to create API users",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                        # Register all unregistered bridges
  %(prog)s --bridges /path/to/bridges             # Use custom bridges file
  %(prog)s --bridge-id ecb5faa015bb               # Register specific bridge
  %(prog)s --force                                # Force re-registration
  %(prog)s --app-name "My Home Automation"        # Custom application name

Notes:
  - You must physically press the button on each bridge within 30 seconds
  - Credentials are saved back to the bridges file
  - Use --force to re-register already registered bridges

For more information, visit: https://github.com/home-assistant-libs/aiohue
        """
    )

    parser.add_argument(
        "--bridges",
        metavar="FILE",
        type=str,
        default=str(DEFAULT_BRIDGES_FILE),
        help=f"Path to bridges JSON file (default: {DEFAULT_BRIDGES_FILE})"
    )

    parser.add_argument(
        "--bridge-id",
        metavar="ID",
        type=str,
        help="Register only this specific bridge ID"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-registration even if already registered"
    )

    parser.add_argument(
        "--app-name",
        metavar="NAME",
        type=str,
        default="aiohue-script",
        help="Application name for registration (default: aiohue-script)"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0"
    )

    return parser.parse_args()


def load_bridges(filepath):
    """
    Load bridge information from JSON file.

    Args:
        filepath (str): Path to bridges JSON file

    Returns:
        dict: Bridge data dictionary, or None on error
    """
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: Bridges file not found: {filepath}", file=sys.stderr)
        print("Run discover-hue-bridges.py first to create it.", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in bridges file: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error loading bridges file: {e}", file=sys.stderr)
        return None


def save_bridges(data, filepath):
    """
    Save bridge information to JSON file.

    Args:
        data (dict): Bridge data dictionary
        filepath (str): Path to bridges JSON file

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving bridges file: {e}", file=sys.stderr)
        return False


def get_dns_name(ip_address):
    """
    Resolve DNS name from IP address.

    Args:
        ip_address (str): IP address to resolve

    Returns:
        str: DNS name if found, None otherwise
    """
    try:
        hostname, _, _ = socket.gethostbyaddr(ip_address)
        return hostname
    except (socket.herror, socket.gaierror, socket.timeout):
        return None


def prompt_for_button_press(bridge_id, bridge_ip, dns_name=None):
    """
    Prompt user to press the bridge button and wait for confirmation.

    Args:
        bridge_id (str): Bridge ID
        bridge_ip (str): Bridge IP address
        dns_name (str, optional): DNS hostname for the bridge

    Returns:
        bool: True if user confirmed, False if cancelled
    """
    print("\n" + "=" * 70)
    print(f"Bridge:   {bridge_id}")
    print(f"IP:       {bridge_ip}")
    if dns_name:
        print(f"DNS Name: {dns_name}")
    print("=" * 70)
    print("\n⚠️  ACTION REQUIRED:")
    print("   1. Physically press the button on your Hue bridge")
    print("   2. You have 30 seconds after pressing to confirm below")
    print()

    response = input("Press ENTER after pressing the bridge button (or 'skip' to skip, 'quit' to exit): ").strip().lower()

    if response == 'quit':
        print("\n❌ Registration cancelled by user.")
        return None
    elif response == 'skip':
        print("⏭️  Skipping this bridge.")
        return False

    return True


async def register_bridge(bridge_ip, app_name, supports_v2=False):
    """
    Register with a Hue bridge to create an API user.

    Args:
        bridge_ip (str): IP address of the bridge
        app_name (str): Application name for registration
        supports_v2 (bool): If True, also request client_key for V2 Entertainment API

    Returns:
        dict: {"username": str, "clientkey": str | None} if successful
        None: if registration failed

    Note:
        V1 bridges: Returns username only (clientkey will be None)
        V2 bridges: Returns username + clientkey when supports_v2=True
        The client key enables Entertainment API but is NOT required for basic light control.
    """
    try:
        from aiohttp import ClientSession
        from aiohue.errors import LinkButtonNotPressed, raise_from_error, AiohueException

        print("\n🔄 Attempting to register with bridge...")

        # Prepare registration payload
        data = {"devicetype": app_name}
        if supports_v2:
            data["generateclientkey"] = True
            print("   Requesting V2 credentials (username + clientkey)...")
        else:
            print("   Requesting V1 credentials (username only)...")

        # Try HTTPS first (V2), then HTTP (V1)
        async with ClientSession() as session:
            for proto in ["https", "http"]:
                try:
                    url = f"{proto}://{bridge_ip}/api"
                    async with session.post(url, json=data, ssl=False, timeout=30) as resp:
                        resp.raise_for_status()
                        result = await resp.json()
                        result = result[0]

                        if "error" in result:
                            raise_from_error(result["error"])

                        success = result["success"]
                        return {
                            "username": success["username"],
                            "clientkey": success.get("clientkey")  # None for V1 or V2 without flag
                        }
                except Exception as exc:
                    if proto == "http":  # Last attempt failed
                        raise exc

    except LinkButtonNotPressed:
        print("❌ Error: Link button was not pressed or timeout occurred.", file=sys.stderr)
        print("   Please press the button and try again within 30 seconds.", file=sys.stderr)
        return None
    except ImportError as e:
        print(f"Error: Required library not found: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"❌ Registration error: {e}", file=sys.stderr)
        return None


async def register_bridges(bridges_data, args):
    """
    Register with bridges based on command-line arguments.

    Args:
        bridges_data (dict): Bridge data dictionary
        args: Parsed command-line arguments

    Returns:
        bool: True if any registrations were successful
    """
    bridges = bridges_data.get('bridges', [])

    if not bridges:
        print("No bridges found in file.", file=sys.stderr)
        return False

    # Filter bridges based on arguments
    bridges_to_register = []
    for bridge in bridges:
        # Skip if specific bridge requested and this isn't it
        if args.bridge_id and bridge['id'] != args.bridge_id:
            continue

        # Skip if already registered and not forcing
        if bridge.get('registered') and not args.force:
            print(f"ℹ️  Bridge {bridge['id']} already registered (use --force to re-register)")
            continue

        bridges_to_register.append(bridge)

    if not bridges_to_register:
        print("\nNo bridges to register.")
        if args.bridge_id:
            print(f"Bridge ID '{args.bridge_id}' not found or already registered.")
        return False

    print(f"\nFound {len(bridges_to_register)} bridge(s) to register.\n")

    success_count = 0

    for bridge in bridges_to_register:
        bridge_id = bridge['id']
        bridge_ip = bridge['ip']
        supports_v2 = bridge.get('api_version') == 'v2'

        # Resolve DNS name
        dns_name = get_dns_name(bridge_ip)

        # Prompt for button press
        result = prompt_for_button_press(bridge_id, bridge_ip, dns_name)

        if result is None:  # User quit
            return success_count > 0
        elif result is False:  # User skipped
            continue

        # Attempt registration with V2 support if available
        credentials = await register_bridge(bridge_ip, args.app_name, supports_v2)

        if credentials:
            # Update bridge data
            bridge['registered'] = True
            bridge['username'] = credentials['username']
            bridge['client_key'] = credentials.get('clientkey')  # Map clientkey -> client_key for consistency
            bridge['registered_at'] = datetime.now().isoformat()
            bridge['app_name'] = args.app_name

            print(f"✅ Successfully registered with bridge {bridge_id}")
            print(f"   API Version: {'V2' if supports_v2 else 'V1'}")
            print(f"   Username:    {credentials['username']}")
            if credentials.get('clientkey'):
                print(f"   Client Key:  {credentials['clientkey'][:20]}...")
                print(f"   Note: Client key enables Entertainment API features")
            else:
                reason = 'V1 bridge' if not supports_v2 else 'Not available'
                print(f"   Client Key:  None ({reason})")
            success_count += 1
        else:
            print(f"❌ Failed to register with bridge {bridge_id}")

    # Update timestamp
    bridges_data['last_updated'] = datetime.now().isoformat()

    return success_count > 0


def main():
    """Main entry point for the script."""
    args = parse_arguments()

    # Load bridges file
    print(f"Loading bridges from: {args.bridges}")
    bridges_data = load_bridges(args.bridges)

    if bridges_data is None:
        sys.exit(1)

    # Register with bridges
    try:
        success = asyncio.run(register_bridges(bridges_data, args))
    except KeyboardInterrupt:
        print("\n\n❌ Registration interrupted by user.")
        sys.exit(2)

    # Save updated bridges file
    if success:
        print(f"\n💾 Saving credentials to: {args.bridges}")
        if save_bridges(bridges_data, args.bridges):
            print("✅ Bridges file updated successfully!")
            print("\nYou can now use these credentials to control your Hue lights.")
        else:
            print("❌ Failed to save bridges file.")
            sys.exit(1)
    else:
        print("\n⚠️  No successful registrations to save.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
