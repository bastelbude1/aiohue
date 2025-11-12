#!/usr/bin/env python3
"""
Delete Hue Bridge Credentials

This script helps delete specific user credentials from Hue bridges.
Requires physical access to press the link button on each bridge.

Security: Reads bridge configuration from config.json (excluded from git)
          No hardcoded IPs, bridge IDs, or credentials in this script.

Usage:
    # Interactive mode - lists all users and lets you select
    python3 delete-bridge-credentials.sh

    # Delete specific users (provide usernames as arguments)
    python3 delete-bridge-credentials.sh username1 username2 username3

Example:
    python3 delete-bridge-credentials.sh --bridge-id abc123def456 --list
    python3 delete-bridge-credentials.sh --bridge-id abc123def456 --user xyz123
"""

import sys
import json
import argparse
import asyncio
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Auto-activate virtual environment
VENV_PATH = Path(__file__).parent.parent.parent / "venv"
if VENV_PATH.exists():
    venv_site_packages = VENV_PATH / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if venv_site_packages.exists():
        sys.path.insert(0, str(venv_site_packages))

try:
    from aiohue.v2 import HueBridgeV2
except ImportError:
    print("Error: aiohue library not found. Please install it:", file=sys.stderr)
    print("  pip install aiohue", file=sys.stderr)
    sys.exit(1)

# Default paths
DEFAULT_CONFIG = Path(__file__).parent.parent / "bridges" / "config.json"


def load_bridges(config_path: Path):
    """Load bridge configuration."""
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        print("Run discover-hue-bridges.py first.", file=sys.stderr)
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    return config.get("bridges", [])


async def list_users(bridge_ip: str, username: str, client_key: str):
    """List all registered users on a bridge."""
    try:
        async with HueBridgeV2(bridge_ip, username, client_key) as bridge:
            await bridge.initialize()

            # Get whitelist via raw API (not available in typed controller)
            config = await bridge.request("get", "api/{}/config".format(username))

            if "whitelist" not in config:
                print(f"  Error: Could not retrieve user list", file=sys.stderr)
                return []

            users = []
            for user_id, user_data in config["whitelist"].items():
                users.append({
                    "username": user_id,
                    "name": user_data.get("name", "Unknown"),
                    "created": user_data.get("create date", "Unknown"),
                    "last_used": user_data.get("last use date", "Unknown")
                })

            return users

    except Exception as e:
        print(f"  Error connecting to bridge: {e}", file=sys.stderr)
        return []


async def delete_user_interactive(bridge_ip: str):
    """
    Delete users interactively using physical button.
    This method creates temporary admin access via link button press.
    """
    import aiohttp

    print(f"\n{'='*60}")
    print(f"Bridge: {bridge_ip}")
    print(f"{'='*60}")
    print("\n⚠️  Please press the LINK BUTTON on this bridge now!")
    print("    (You have 30 seconds after pressing)")
    print()
    input("Press Enter after pressing the button...")

    # Try to get temporary admin access
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"https://{bridge_ip}/api",
                json={"devicetype": "credential_cleanup#script"},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()

                if isinstance(result, list) and len(result) > 0:
                    if "success" in result[0]:
                        temp_user = result[0]["success"]["username"]
                        print(f"✅ Got temporary admin access")
                        return temp_user
                    elif "error" in result[0]:
                        error_msg = result[0]["error"].get("description", "Unknown error")
                        print(f"❌ Failed: {error_msg}")
                        print("   Make sure you pressed the link button!")
                        return None

        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return None


async def delete_user(bridge_ip: str, admin_user: str, target_user: str, description: str = ""):
    """Delete a specific user from the bridge."""
    import aiohttp

    print(f"\n  Deleting: {description or target_user}")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.delete(
                f"https://{bridge_ip}/api/{admin_user}/config/whitelist/{target_user}",
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                result = await response.json()

                if isinstance(result, list) and len(result) > 0:
                    if "success" in result[0]:
                        print(f"    ✅ Deleted successfully")
                        return True
                    elif "error" in result[0]:
                        error_msg = result[0]["error"].get("description", "Unknown")
                        print(f"    ❌ Failed: {error_msg}")
                        return False

        except Exception as e:
            print(f"    ❌ Error: {e}")
            return False


async def cleanup_temp_admin(bridge_ip: str, admin_user: str):
    """Remove temporary admin access."""
    import aiohttp

    async with aiohttp.ClientSession() as session:
        try:
            await session.delete(
                f"https://{bridge_ip}/api/{admin_user}/config/whitelist/{admin_user}",
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=5)
            )
            print(f"\n  ✅ Temporary admin access cleaned up")
        except:
            pass  # Don't fail if cleanup fails


async def interactive_delete(bridges):
    """Interactive mode: list users and let user select which to delete."""
    print("\n" + "="*60)
    print("INTERACTIVE CREDENTIAL DELETION")
    print("="*60)
    print("\nThis will show all registered users on each bridge.")
    print("You can select which ones to delete.\n")

    for bridge in bridges:
        bridge_id = bridge.get("id", "unknown")
        bridge_ip = bridge.get("ip")
        username = bridge.get("username")
        client_key = bridge.get("client_key")

        if not bridge.get("registered"):
            print(f"\nBridge {bridge_id}: Not registered, skipping")
            continue

        print(f"\n{'='*60}")
        print(f"Bridge: {bridge_id} ({bridge_ip})")
        print(f"{'='*60}")

        # List all users
        print("\nFetching registered users...")
        users = await list_users(bridge_ip, username, client_key)

        if not users:
            print("  No users found or error fetching users")
            continue

        print(f"\nFound {len(users)} registered users:")
        print()
        for idx, user in enumerate(users, 1):
            print(f"  [{idx:2d}] {user['name']}")
            print(f"       Username: {user['username']}")
            print(f"       Created:  {user['created']}")
            print(f"       Last use: {user['last_used']}")
            print()

        # Ask which to delete
        print("Enter the numbers of users to delete (comma-separated), or 'skip':")
        selection = input("> ").strip()

        if selection.lower() in ['skip', 's', '']:
            print("  Skipping this bridge")
            continue

        try:
            indices = [int(x.strip()) - 1 for x in selection.split(",")]
            users_to_delete = [users[i] for i in indices if 0 <= i < len(users)]
        except (ValueError, IndexError):
            print("  Invalid selection, skipping this bridge")
            continue

        if not users_to_delete:
            print("  No valid users selected")
            continue

        print(f"\nWill delete {len(users_to_delete)} users:")
        for user in users_to_delete:
            print(f"  - {user['name']} ({user['username']})")

        confirm = input("\nConfirm deletion? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Cancelled")
            continue

        # Get admin access via button press
        admin_user = await delete_user_interactive(bridge_ip)
        if not admin_user:
            print("  Failed to get admin access, skipping this bridge")
            continue

        # Delete selected users
        for user in users_to_delete:
            await delete_user(bridge_ip, admin_user, user["username"], user["name"])

        # Cleanup temp admin
        await cleanup_temp_admin(bridge_ip, admin_user)

    print("\n" + "="*60)
    print("✅ COMPLETE")
    print("="*60)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Delete Hue bridge credentials",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG),
        help=f"Path to bridges config file (default: {DEFAULT_CONFIG})"
    )

    parser.add_argument(
        "--bridge-id",
        type=str,
        help="Specific bridge ID to work with"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List all registered users (read-only)"
    )

    args = parser.parse_args()

    # Load bridges
    config_path = Path(args.config)
    bridges = load_bridges(config_path)

    if not bridges:
        print("No bridges found in config", file=sys.stderr)
        sys.exit(1)

    # Filter by bridge ID if specified
    if args.bridge_id:
        bridges = [b for b in bridges if b.get("id") == args.bridge_id]
        if not bridges:
            print(f"Bridge {args.bridge_id} not found", file=sys.stderr)
            sys.exit(1)

    # List mode
    if args.list:
        print("\n" + "="*60)
        print("REGISTERED USERS")
        print("="*60)

        for bridge in bridges:
            if not bridge.get("registered"):
                continue

            bridge_id = bridge.get("id")
            bridge_ip = bridge.get("ip")
            username = bridge.get("username")
            client_key = bridge.get("client_key")

            print(f"\nBridge: {bridge_id} ({bridge_ip})")
            print("-" * 60)

            users = await list_users(bridge_ip, username, client_key)
            if users:
                for user in users:
                    print(f"  {user['name']}")
                    print(f"    Username: {user['username']}")
                    print(f"    Created:  {user['created']}")
                    print(f"    Last use: {user['last_used']}")
                    print()
            else:
                print("  No users found or error")

        return

    # Interactive delete mode
    await interactive_delete(bridges)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
