#!/usr/bin/env python3
"""
List Hue Bridge Credentials (Audit Tool)

This script lists and audits registered user credentials from Hue bridges.

IMPORTANT: Due to security changes in Hue API 1.31+, credentials CANNOT be deleted
via the local REST API. The DELETE endpoint has been permanently disabled by Philips.

To delete credentials, you MUST use the official cloud portal:
    https://www.account.philips-hue.com/homes

This script helps you:
    1. Identify which credentials exist on your bridges
    2. Filter credentials by age, name, username, etc.
    3. Export a list of credentials that need manual deletion via cloud portal

Security: Reads bridge configuration from config.json (excluded from git)
          No hardcoded IPs, bridge IDs, or credentials in this script.

Usage:
    # List all users
    python3 list-bridge-credentials.sh

    # Find stale credentials (not used in 1 year)
    python3 list-bridge-credentials.sh --last-use 1y

    # Find specific credentials to delete
    python3 list-bridge-credentials.sh --filter 'name~iPhone'
    python3 list-bridge-credentials.sh --file exposed-credentials.txt

Example Workflow:
    1. Run: python3 list-bridge-credentials.sh --last-use 1y
    2. Note the names of credentials to delete
    3. Go to: https://www.account.philips-hue.com/homes
    4. Search for those names and delete them via the portal
"""

import sys
import json
import argparse
import asyncio
import re
from pathlib import Path
from datetime import datetime, timedelta

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


def parse_time_period(time_str: str) -> timedelta:
    """
    Parse time period string like '8h', '1d', '2w', '3m', '1y' into timedelta.

    Args:
        time_str: Time string (e.g., '8h', '1d', '2w', '3m', '1y')

    Returns:
        timedelta object

    Raises:
        ValueError: If format is invalid
    """
    match = re.match(r'^(\d+)([hdwmy])$', time_str.lower())
    if not match:
        raise ValueError(
            f"Invalid time format: '{time_str}'. "
            "Use format like: 8h (hours), 1d (days), 2w (weeks), 3m (months), 1y (years)"
        )

    amount = int(match.group(1))
    unit = match.group(2)

    if unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    elif unit == 'w':
        return timedelta(weeks=amount)
    elif unit == 'm':
        # Approximate: 30 days per month
        return timedelta(days=amount * 30)
    elif unit == 'y':
        # Approximate: 365 days per year
        return timedelta(days=amount * 365)
    else:
        raise ValueError(f"Unknown time unit: {unit}")


def is_user_stale(last_use_str: str, cutoff_date: datetime) -> bool:
    """
    Check if user's last use date is before the cutoff date.

    Args:
        last_use_str: Last use date string from API (ISO format)
        cutoff_date: Cutoff datetime

    Returns:
        True if user hasn't been used since cutoff_date
    """
    if not last_use_str or last_use_str == "Unknown":
        # No last use date - consider it stale
        return True

    try:
        # Parse ISO date format: "2025-11-12T15:31:13"
        last_use = datetime.fromisoformat(last_use_str.replace('T', ' ').split('.')[0])
        return last_use < cutoff_date
    except (ValueError, AttributeError):
        # If we can't parse, consider it stale to be safe
        return True


def parse_filter(filter_str: str) -> dict:
    """
    Parse a filter string like "name~iPhone" or "username=abc123".

    Format: field operator value

    Fields:
        - name: Display name (e.g., "Hue#Cool iPhone")
        - username: UUID credential
        - created: Creation date
        - last_used: Last use date

    Operators:
        - = : Exact match
        - ~ : Contains (case-insensitive substring)
        - != : Not equal (exact)
        - !~ : Does not contain (case-insensitive)

    Args:
        filter_str: Filter string (e.g., "name~iPhone", "username=abc123")

    Returns:
        dict with 'field', 'operator', 'value'

    Raises:
        ValueError: If format is invalid or field name is unknown

    Examples:
        parse_filter("name=Hue#Cool iPhone")
        parse_filter("name~iPhone")
        parse_filter("name!~home-assistant")
        parse_filter("username=99aa3646-3584-47ff-a280-bfd8fdb4550c")
    """
    # Valid field names
    VALID_FIELDS = {'username', 'name', 'created', 'last_used', 'last-used', 'lastused'}

    # Try to match operators in order of specificity (longer first)
    if '!~' in filter_str:
        field, value = filter_str.split('!~', 1)
        field = field.strip().lower()
        if field not in VALID_FIELDS:
            raise ValueError(
                f"Unknown field: '{field}'. "
                "Valid fields: username, name, created, last_used"
            )
        return {'field': field, 'operator': '!~', 'value': value.strip()}
    elif '!=' in filter_str:
        field, value = filter_str.split('!=', 1)
        field = field.strip().lower()
        if field not in VALID_FIELDS:
            raise ValueError(
                f"Unknown field: '{field}'. "
                "Valid fields: username, name, created, last_used"
            )
        return {'field': field, 'operator': '!=', 'value': value.strip()}
    elif '~' in filter_str:
        field, value = filter_str.split('~', 1)
        field = field.strip().lower()
        if field not in VALID_FIELDS:
            raise ValueError(
                f"Unknown field: '{field}'. "
                "Valid fields: username, name, created, last_used"
            )
        return {'field': field, 'operator': '~', 'value': value.strip()}
    elif '=' in filter_str:
        field, value = filter_str.split('=', 1)
        field = field.strip().lower()
        if field not in VALID_FIELDS:
            raise ValueError(
                f"Unknown field: '{field}'. "
                "Valid fields: username, name, created, last_used"
            )
        return {'field': field, 'operator': '=', 'value': value.strip()}
    else:
        raise ValueError(
            f"Invalid filter format: '{filter_str}'. "
            "Use: field=value, field~value, field!=value, or field!~value"
        )


def matches_filter(user: dict, filter_spec: dict) -> bool:
    """
    Check if a user matches a filter specification.

    Args:
        user: User dict with 'username', 'name', 'created', 'last_used'
        filter_spec: Filter dict with 'field', 'operator', 'value'

    Returns:
        True if user matches the filter

    Raises:
        ValueError: If field name is unknown
    """
    field = filter_spec['field']
    operator = filter_spec['operator']
    value = filter_spec['value']

    # Normalize field names (support aliases)
    field_map = {
        'username': 'username',
        'name': 'name',
        'created': 'created',
        'last_used': 'last_used',
        'last-used': 'last_used',
        'lastused': 'last_used',
    }

    if field not in field_map:
        raise ValueError(
            f"Unknown field: '{field}'. "
            "Valid fields: username, name, created, last_used"
        )

    field_name = field_map[field]
    user_value = str(user.get(field_name, ""))

    # Apply operator
    if operator == '=':
        return user_value == value
    elif operator == '!=':
        return user_value != value
    elif operator == '~':
        return value.lower() in user_value.lower()
    elif operator == '!~':
        return value.lower() not in user_value.lower()
    else:
        return False


def matches_all_filters(user: dict, filters: list) -> bool:
    """
    Check if user matches filters using smart OR/AND logic.

    Logic:
        - Multiple filters on SAME field = OR (any must match)
        - Filters on DIFFERENT fields = AND (all must match)

    Examples:
        username=abc, username=def → Match if username is abc OR def
        name~iPhone, created~2022 → Match if name contains iPhone AND created contains 2022

    Args:
        user: User dict with 'username', 'name', 'created', 'last_used'
        filters: List of filter specifications

    Returns:
        True if user matches all filter groups (or if no filters provided)
    """
    if not filters:
        return True

    # Group filters by field
    from collections import defaultdict
    field_groups = defaultdict(list)
    for f in filters:
        # Normalize field names
        field = f['field']
        if field in ('last-used', 'lastused'):
            field = 'last_used'
        field_groups[field].append(f)

    # For each field group, check if ANY filter matches (OR logic)
    # All field groups must have at least one match (AND logic)
    for field, field_filters in field_groups.items():
        # Check if ANY filter in this field group matches
        if not any(matches_filter(user, f) for f in field_filters):
            return False

    return True


async def get_bridge_name(bridge_ip: str, username: str) -> str:
    """Get the bridge name from the API."""
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://{bridge_ip}/api/{username}/config",
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                config = await response.json()
                return config.get("name", "Unknown")
    except:
        return "Unknown"


async def list_users(bridge_ip: str, username: str, client_key: str):
    """List all registered users on a bridge."""
    import aiohttp

    try:
        # Use V1 API directly (whitelist is not available in V2 API)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://{bridge_ip}/api/{username}/config",
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                config = await response.json()

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



async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit Hue bridge credentials (list/filter only - deletion requires cloud portal)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
IMPORTANT: Local API deletion is disabled by Philips (API 1.31+).
To delete credentials, use: https://www.account.philips-hue.com/homes

This script identifies which credentials need deletion.
        """
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
        "--last-use",
        type=str,
        metavar="TIME",
        help="Filter users not used since TIME ago (e.g., 8h, 1d, 2w, 3m, 6m, 1y)"
    )

    parser.add_argument(
        "--filter",
        type=str,
        action='append',
        metavar="FILTER",
        help=(
            "Filter users by field (can be used multiple times for AND logic). "
            "Format: field OPERATOR value. "
            "Fields: name, username, created, last_used. "
            "Operators: = (exact), ~ (contains), != (not equal), !~ (not contains). "
            "Examples: --filter 'name~iPhone' --filter 'name!~home-assistant' "
            "--filter 'username=99aa3646-3584-47ff-a280-bfd8fdb4550c'"
        )
    )

    parser.add_argument(
        "--file",
        "-f",
        type=str,
        metavar="FILE",
        help=(
            "Read filters from file (one filter per line). "
            "Uses same syntax as --filter. "
            "Lines starting with # are ignored. "
            "Example file content: username=abc123, name~iPhone, name!~home-assistant"
        )
    )

    parser.add_argument(
        "--remove",
        action='store_true',
        help=(
            "Generate portal deletion command for matched credentials. "
            "Creates a file with credential names and shows the command to delete them via cloud portal."
        )
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

    # Parse last-use filter if provided
    last_use_filter = None
    if args.last_use:
        try:
            last_use_filter = parse_time_period(args.last_use)
            cutoff_date = datetime.now() - last_use_filter
            print(f"\nFiltering users not used since: {cutoff_date.strftime('%Y-%m-%d %H:%M')}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Parse field filters if provided
    field_filters = []

    # Read filters from file if --file provided
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Error: Filter file not found: {args.file}", file=sys.stderr)
            sys.exit(1)

        try:
            print(f"\nReading filters from: {args.file}")
            with open(file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    # Strip whitespace
                    line = line.strip()

                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Parse as filter
                    try:
                        field_filters.append(parse_filter(line))
                    except ValueError as e:
                        print(f"Error on line {line_num}: {e}", file=sys.stderr)
                        sys.exit(1)
        except IOError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)

    # Add command-line filters
    if args.filter:
        try:
            for filter_str in args.filter:
                field_filters.append(parse_filter(filter_str))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Show all filters
    if field_filters:
        print(f"\nApplying {len(field_filters)} field filter(s):")
        for f in field_filters:
            print(f"  - {f['field']} {f['operator']} {f['value']}")

    # List/audit mode (only mode available)
    print("\n" + "="*60)
    print("REGISTERED USERS AUDIT")
    print("="*60)

    if last_use_filter:
        cutoff_str = (datetime.now() - last_use_filter).strftime("%Y-%m-%d")
        print(f"(Not used since: {cutoff_str})")
        print("="*60)

    # Track totals for summary
    total_bridges = 0
    total_users = 0
    matching_users = 0

    # Collect ALL users (to check if credential is safe to delete)
    all_users_by_name = {}  # name -> list of all occurrences
    matching_users_by_name = {}  # name -> list of matching occurrences

    for bridge in bridges:
        if not bridge.get("registered"):
            continue

        total_bridges += 1
        bridge_id = bridge.get("id")
        bridge_ip = bridge.get("ip")
        username = bridge.get("username")
        client_key = bridge.get("client_key")

        # Get bridge name
        bridge_name = await get_bridge_name(bridge_ip, username)

        print(f"\nBridge: {bridge_name} [{bridge_id}] ({bridge_ip})")
        print("-" * 60)

        all_users = await list_users(bridge_ip, username, client_key)

        original_count = len(all_users)
        total_users += original_count

        # Track ALL users by name (for safe deletion check)
        for user in all_users:
            name = user['name']

            # Extract base app name (before #) for portal matching
            # Example: "all 4 hue#iOS" -> "all 4 hue"
            base_name = name.split('#')[0] if '#' in name else name

            if name not in all_users_by_name:
                all_users_by_name[name] = []
            all_users_by_name[name].append({
                'bridge': bridge_name,
                'user': user,
                'base_name': base_name
            })

        # Apply last-use filter if specified
        filtered_users = all_users
        if last_use_filter:
            cutoff_date = datetime.now() - last_use_filter
            filtered_users = [
                user for user in filtered_users
                if is_user_stale(user['last_used'], cutoff_date)
            ]

        # Apply field filters if specified
        if field_filters:
            filtered_users = [
                user for user in filtered_users
                if matches_all_filters(user, field_filters)
            ]

        # Track matching users by name
        for user in filtered_users:
            name = user['name']

            # Extract base app name (before #) for portal matching
            base_name = name.split('#')[0] if '#' in name else name

            if name not in matching_users_by_name:
                matching_users_by_name[name] = []
            matching_users_by_name[name].append({
                'bridge': bridge_name,
                'user': user,
                'base_name': base_name
            })

        users = filtered_users
        matching_users += len(users)

        # Show filter results
        if last_use_filter or field_filters:
            print(f"  Found {len(users)} matching users (out of {original_count} total)")

        if users:
            for user in users:
                print(f"  Name:     {user['name']}")
                print(f"  Username: {user['username']}")
                print(f"  Created:  {user['created']}")
                print(f"  Last use: {user['last_used']}")
                print()
        else:
            print("  No users found or error")

    # Print summary with cloud portal instructions
    print("\n" + "="*60)
    print("AUDIT SUMMARY")
    print("="*60)
    print(f"Total bridges: {total_bridges}")
    print(f"Total users: {total_users}")
    if last_use_filter or field_filters:
        print(f"Matching criteria: {matching_users}")

    if matching_users > 0:
        # If --remove flag was specified, determine which credentials are safe to delete
        if args.remove:
            print("\n" + "="*60)
            print("SAFE DELETION ANALYSIS (By Base App Name)")
            print("="*60)

            # Group by base app name (without #device)
            all_by_base = {}  # base_name -> list of all occurrences
            matching_by_base = {}  # base_name -> list of matching occurrences

            for name, occurrences in all_users_by_name.items():
                for occ in occurrences:
                    base = occ['base_name']
                    if base not in all_by_base:
                        all_by_base[base] = []
                    all_by_base[base].append({
                        'full_name': name,
                        'bridge': occ['bridge'],
                        'user': occ['user']
                    })

            for name, occurrences in matching_users_by_name.items():
                for occ in occurrences:
                    base = occ['base_name']
                    if base not in matching_by_base:
                        matching_by_base[base] = []
                    matching_by_base[base].append({
                        'full_name': name,
                        'bridge': occ['bridge'],
                        'user': occ['user']
                    })

            # Find base app names where ALL device entries are inactive
            safe_to_delete = []
            unsafe_to_delete = []

            for base_name in set(list(all_by_base.keys()) + list(matching_by_base.keys())):
                if base_name == 'Unknown':
                    continue

                total_entries = len(all_by_base.get(base_name, []))
                matching_entries = len(matching_by_base.get(base_name, []))

                if matching_entries > 0:
                    if total_entries == matching_entries:
                        # ALL device entries match filter - safe to delete
                        safe_to_delete.append(base_name)
                    else:
                        # Some device entries are still active - NOT safe to delete
                        unsafe_to_delete.append({
                            'name': base_name,
                            'total': total_entries,
                            'matching': matching_entries,
                            'active': total_entries - matching_entries
                        })

            # Show safe credentials
            if safe_to_delete:
                print(f"\n✅ Safe to delete (all device entries inactive):")
                for base_name in sorted(safe_to_delete):
                    entries = all_by_base[base_name]
                    print(f"\n  • {base_name}")
                    print(f"    Total device entries: {len(entries)}")
                    for entry in entries:
                        full_name = entry['full_name']
                        bridge = entry['bridge']
                        last_use = entry['user']['last_used']
                        print(f"      - {full_name} on {bridge}: last used {last_use}")

            # Show unsafe credentials
            if unsafe_to_delete:
                print(f"\n⚠️  NOT safe to delete (some device entries still active):")
                for item in sorted(unsafe_to_delete, key=lambda x: x['name']):
                    base_name = item['name']
                    print(f"\n  • {base_name}")
                    print(f"    Total: {item['total']} device entries | Inactive: {item['matching']} | Active: {item['active']}")

                    # Show details
                    all_entries = all_by_base[base_name]
                    matching_entries = matching_by_base.get(base_name, [])

                    for entry in all_entries:
                        full_name = entry['full_name']
                        bridge = entry['bridge']
                        username = entry['user']['username']
                        last_use = entry['user']['last_used']

                        is_matching = any(
                            m['bridge'] == bridge and m['user']['username'] == username
                            for m in matching_entries
                        )
                        status = "❌ INACTIVE" if is_matching else "✅ ACTIVE"
                        print(f"      {status} - {full_name} on {bridge}: last used {last_use}")

            # Generate deletion command for ALL matching entries (including partial deletions)
            if safe_to_delete or unsafe_to_delete:
                print("\n" + "="*60)
                print("PORTAL DELETION COMMAND")
                print("="*60)

                # Create a temporary file with credential names
                import tempfile
                temp_file = Path(tempfile.gettempdir()) / f"hue-credentials-to-delete-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"

                try:
                    import json

                    # Create detailed JSON format with cutoff date and UUIDs
                    deletion_data = {
                        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'cutoff_date': cutoff_date.strftime('%Y-%m-%d %H:%M:%S') if last_use_filter else None,
                        'apps': []
                    }

                    # Add safe apps (all entries will be deleted)
                    for base_name in sorted(safe_to_delete):
                        entries = all_by_base[base_name]
                        app_data = {
                            'base_name': base_name,
                            'entries_to_delete': []
                        }

                        for entry in entries:
                            app_data['entries_to_delete'].append({
                                'full_name': entry['full_name'],
                                'username': entry['user']['username'],
                                'bridge': entry['bridge'],
                                'last_used': entry['user']['last_used'],
                                'created': entry['user']['created']
                            })

                        deletion_data['apps'].append(app_data)

                    # Add unsafe apps (only matching/inactive entries will be deleted)
                    for item in sorted(unsafe_to_delete, key=lambda x: x['name']):
                        base_name = item['name']
                        matching_entries = matching_by_base.get(base_name, [])

                        app_data = {
                            'base_name': base_name,
                            'entries_to_delete': []
                        }

                        for entry in matching_entries:
                            app_data['entries_to_delete'].append({
                                'full_name': entry['full_name'],
                                'username': entry['user']['username'],
                                'bridge': entry['bridge'],
                                'last_used': entry['user']['last_used'],
                                'created': entry['user']['created']
                            })

                        if app_data['entries_to_delete']:  # Only add if there are entries
                            deletion_data['apps'].append(app_data)

                    with open(temp_file, 'w') as f:
                        json.dump(deletion_data, f, indent=2)

                    print(f"\n📝 Created credential list file: {temp_file}")
                    print(f"   Format: JSON with detailed entry information")

                    total_apps = len(deletion_data['apps'])
                    safe_apps_count = len(safe_to_delete)
                    partial_apps_count = total_apps - safe_apps_count

                    if safe_apps_count > 0:
                        print(f"   Apps (all entries deleted): {safe_apps_count}")
                    if partial_apps_count > 0:
                        print(f"   Apps (partial deletion): {partial_apps_count}")

                    total_entries = sum(len(app['entries_to_delete']) for app in deletion_data['apps'])
                    print(f"   Total device entries to delete: {total_entries}")

                    if last_use_filter:
                        print(f"   Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")

                    print("\n🚀 To delete these credentials via cloud portal, run:\n")
                    print(f"   ./list-hue-credentials-portal.py --manual-login --remove --file {temp_file}\n")

                    if partial_apps_count > 0:
                        print("⚠️  PARTIAL DELETION: Some apps have active entries that will NOT be deleted!")
                        print("    Only the specific inactive entries listed above will be removed.")
                    else:
                        print("⚠️  This will DELETE all listed device entries!")

                    print("="*60)

                except IOError as e:
                    print(f"\n❌ Error creating credential list file: {e}", file=sys.stderr)
                    print("\n💡 Alternative: Run portal deletion manually with credential names:")
                    all_bases = set(safe_to_delete) | set(item['name'] for item in unsafe_to_delete)
                    for name in sorted(all_bases):
                        print(f"   ./list-hue-credentials-portal.py --manual-login --remove --name \"{name}\"")
            else:
                print("\n⚠️  No matching credentials found for deletion.")

            print("="*60)

        else:
            print(f"\n⚠️  To delete these {matching_users} credentials:")
            print("1. Go to: https://www.account.philips-hue.com/homes")
            print("2. Log in with your Philips Hue account")
            print("3. Find and delete the credentials by their names listed above")
            print("\nNote: Local API deletion is disabled by Philips for security.")
            print("\n💡 Tip: Use --remove flag to analyze which credentials are safe to delete")
    else:
        print("\n✅ No matching credentials found.")

    print("="*60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(1)
