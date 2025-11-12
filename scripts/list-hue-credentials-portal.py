#!/usr/bin/env python3
"""
List/Delete Hue Bridge Credentials via Cloud Portal

Lists or deletes Hue credentials by logging into the Philips cloud portal.
This script uses Playwright to automate the browser interaction.

Security:
- NO hardcoded credentials
- Prompts for username/password interactively
- Credentials are ONLY kept in memory during execution
- Nothing is saved to disk

Usage:
    # List all credentials (default - safe)
    python3 list-hue-credentials-portal.py

    # List credentials matching filter
    python3 list-hue-credentials-portal.py --name "aiohue-script"
    python3 list-hue-credentials-portal.py --file exposed-credentials-to-delete.txt

    # Delete credentials (requires --remove flag)
    python3 list-hue-credentials-portal.py --remove --file exposed-credentials-to-delete.txt
    python3 list-hue-credentials-portal.py --remove --name "aiohue-script"

Examples:
    # Safe: Just list credentials
    python3 list-hue-credentials-portal.py --file exposed-credentials.txt

    # Dangerous: Delete credentials
    python3 list-hue-credentials-portal.py --remove --file exposed-credentials.txt
"""

import sys
import argparse
import getpass
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Portal URL
PHILIPS_HUE_PORTAL = "https://www.account.philips-hue.com/homes"


def prompt_credentials():
    """Prompt user for credentials interactively."""
    print("\n" + "="*60)
    print("PHILIPS HUE PORTAL LOGIN")
    print("="*60)
    print("This script will log in to your Philips Hue account.")
    print("Your credentials will NOT be saved anywhere.\n")

    email = input("Email: ").strip()
    if not email:
        print("❌ Email cannot be empty")
        sys.exit(1)

    password = getpass.getpass("Password: ")
    if not password:
        print("❌ Password cannot be empty")
        sys.exit(1)

    return email, password


def load_credential_names(file_path=None, names=None):
    """
    Load credential names to filter/delete.

    Args:
        file_path: Path to file with credential names (one per line) or JSON format
        names: List of credential names from command line

    Returns:
        Tuple: (credential_names, detailed_data)
        - credential_names: Set of credential names, or None if no filter specified
        - detailed_data: Dict with detailed deletion info (JSON format), or None
    """
    credential_names = set()
    detailed_data = None

    if file_path:
        try:
            with open(file_path, 'r') as f:
                content = f.read()

            # Try to parse as JSON first
            try:
                import json
                data = json.loads(content)

                # Check if it's our detailed format
                if isinstance(data, dict) and 'apps' in data:
                    print(f"📋 Loaded detailed JSON format")
                    print(f"   Generated: {data.get('generated', 'Unknown')}")
                    if data.get('cutoff_date'):
                        print(f"   Cutoff date: {data['cutoff_date']}")
                    print(f"   Apps: {len(data['apps'])}")

                    detailed_data = data

                    # Also extract base names for backwards compatibility
                    for app in data['apps']:
                        credential_names.add(app['base_name'])
                else:
                    print(f"⚠️  JSON format not recognized, treating as text")
                    # Fall through to text parsing

            except json.JSONDecodeError:
                # Not JSON, parse as text file
                for line in content.splitlines():
                    line = line.strip()
                    # Skip comments and empty lines
                    if line and not line.startswith('#'):
                        # Support both plain names and filter syntax
                        if line.startswith('name='):
                            credential_names.add(line.split('=', 1)[1])
                        elif line.startswith('name~'):
                            credential_names.add(f"CONTAINS:{line.split('~', 1)[1]}")
                        else:
                            credential_names.add(line)

        except FileNotFoundError:
            print(f"❌ File not found: {file_path}")
            sys.exit(1)

    if names:
        credential_names.update(names)

    # Return None if no filter specified (will list all)
    return (credential_names if credential_names else None, detailed_data)


def matches_credential(credential_name, pattern):
    """Check if credential name matches pattern."""
    if pattern.startswith("CONTAINS:"):
        search_term = pattern.replace("CONTAINS:", "")
        return search_term.lower() in credential_name.lower()
    else:
        return credential_name == pattern


def list_or_delete_credentials(email, password, credential_names=None, detailed_data=None, remove=False, headless=True, timeout=30000, manual_login=False):
    """
    List or delete credentials from Philips Hue portal.

    Args:
        email: Philips Hue account email (None if manual_login=True)
        password: Account password (None if manual_login=True)
        credential_names: Set of credential names to filter/delete (None = list all)
        detailed_data: Dict with detailed deletion info (JSON format with UUIDs and dates), or None
        remove: If True, delete credentials. If False, only list them (default: False)
        headless: Run browser in headless mode (default: True)
        timeout: Timeout in milliseconds (default: 30000)
        manual_login: If True, wait for user to login manually (default: False)
    """
    mode = "DELETION" if remove else "LISTING"
    print("\n" + "="*60)
    print(f"STARTING AUTOMATED CREDENTIAL {mode}")
    print("="*60)
    print(f"Portal URL: {PHILIPS_HUE_PORTAL}")
    print(f"Mode: {'DELETE' if remove else 'LIST ONLY (SAFE)'}")
    if credential_names:
        print(f"Filter: {len(credential_names)} pattern(s)")
    else:
        print(f"Filter: None (list all)")
    print(f"Headless mode: {headless}")
    print()

    deleted_count = 0
    listed_count = 0
    failed_credentials = []

    with sync_playwright() as p:
        print("🚀 Launching browser...")
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Navigate to portal
            print(f"🌐 Navigating to {PHILIPS_HUE_PORTAL}...")
            page.goto(PHILIPS_HUE_PORTAL, timeout=timeout)
            page.wait_for_load_state('networkidle')

            # Wait for React to render
            print("⏳ Waiting for page to fully load (React SPA)...")
            page.wait_for_timeout(5000)

            # Manual login mode
            if manual_login:
                print("\n" + "="*60)
                print("MANUAL LOGIN MODE")
                print("="*60)
                print("🌐 Browser is now open at the login page")
                print("👤 Please log in manually:")
                print("   1. Enter your email")
                print("   2. Enter your password")
                print("   3. Enter your 2FA code")
                print("   4. Wait until you see your homes/credentials page")
                print("   5. Then press ENTER here to continue...")
                print("="*60)

                input("\n⏸️  Press ENTER after you have logged in successfully: ")

                print("\n✅ Continuing with credential management...")
                # Wait a bit more for page to stabilize
                page.wait_for_timeout(3000)

            else:
                # Automatic login mode
                # Check if login is required
                print("🔐 Checking login status...")

                # Look for login form or already logged in
                email_inputs = page.locator('input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="E-Mail" i]').all()

                if len(email_inputs) > 0:
                    print("📝 Login form detected, logging in...")

                    # Fill email
                    print("  📧 Filling email field...")
                    email_input = email_inputs[0]
                    email_input.click()
                    email_input.fill(email)
                    page.wait_for_timeout(1000)

                    # Fill password
                    print("  🔑 Filling password field...")
                    password_inputs = page.locator('input[type="password"], input[name="password"], input[placeholder*="password" i], input[placeholder*="Passwort" i]').all()
                    if len(password_inputs) > 0:
                        password_input = password_inputs[0]
                        password_input.click()
                        password_input.fill(password)
                        page.wait_for_timeout(1000)
                    else:
                        print("  ❌ Password field not found!")
                        sys.exit(1)

                    # Click login button
                    print("  🔘 Clicking login button...")
                    login_buttons = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("Sign in"), button:has-text("Log in"), button:has-text("Anmelden"), button:has-text("Weiter")').all()
                    if len(login_buttons) > 0:
                        login_buttons[0].click()
                    else:
                        print("  ❌ Login button not found!")
                        sys.exit(1)

                    print("⏳ Waiting for login to complete...")
                    page.wait_for_timeout(5000)  # Give it time to redirect
                    page.wait_for_load_state('networkidle', timeout=timeout)

                    # Wait for React to render after login
                    page.wait_for_timeout(3000)

                    # Check if 2FA is required
                    mfa_inputs = page.locator('input[type="text"][placeholder*="code" i], input[name*="code" i], input[name*="otp" i], input[placeholder*="verification" i]').all()

                    if len(mfa_inputs) > 0:
                        print("🔐 2FA/MFA detected - verification code required")
                        print("   Please enter the code from your authenticator app:")

                        mfa_code = input("   2FA Code: ").strip()
                        if not mfa_code:
                            print("❌ 2FA code cannot be empty")
                            sys.exit(1)

                        print("  📱 Entering 2FA code...")
                        mfa_input = mfa_inputs[0]
                        mfa_input.click()
                        mfa_input.fill(mfa_code)
                        page.wait_for_timeout(1000)

                        # Click verify/continue button
                        verify_buttons = page.locator('button[type="submit"], button:has-text("Verify"), button:has-text("Continue"), button:has-text("Bestätigen"), button:has-text("Weiter")').all()
                        if len(verify_buttons) > 0:
                            print("  ✅ Submitting 2FA code...")
                            verify_buttons[0].click()

                            print("⏳ Waiting for 2FA verification...")
                            page.wait_for_timeout(5000)
                            page.wait_for_load_state('networkidle', timeout=timeout)
                            page.wait_for_timeout(3000)
                        else:
                            print("  ⚠️  Verify button not found, trying Enter key...")
                            mfa_input.press('Enter')
                            page.wait_for_timeout(5000)
                            page.wait_for_load_state('networkidle', timeout=timeout)
                            page.wait_for_timeout(3000)

                    # Check if login was successful by looking for password field
                    password_still_there = page.locator('input[type="password"]').count() > 0
                    if password_still_there:
                        print("❌ Login failed! Please check your credentials.")
                        print(f"   Current URL: {page.url}")
                        print(f"   Page content: {page.locator('body').inner_text()[:300]}")
                        sys.exit(1)

                    print("✅ Login successful!")
                else:
                    print("✅ Already logged in or no login required")

            # We're already on the right page (/homes shows all integrations)
            print("✅ On Philips Hue portal - ready to list/manage credentials")

            # This is a React SPA - we need to wait for content to render
            print("⏳ Waiting for React app to load content...")
            page.wait_for_timeout(5000)  # Give React time to render

            # Try to click "Alle Anwendungen" if it exists
            try:
                alle_anwendungen = page.locator('text="Alle Anwendungen", text="All applications"').first
                if alle_anwendungen.is_visible(timeout=3000):
                    print("🔘 Clicking 'Alle Anwendungen' to expand...")
                    alle_anwendungen.click()
                    page.wait_for_timeout(3000)
            except:
                pass

            # Click "Weitere Informationen" button to show more credentials
            try:
                weitere_info_button = page.locator(
                    'button#expand-button-integrations, '
                    'button:has-text("Weitere Informationen"), '
                    'button:has-text("More information")'
                ).first
                if weitere_info_button.is_visible(timeout=3000):
                    print("🔘 Clicking 'Weitere Informationen' to show all credentials...")
                    weitere_info_button.click()
                    page.wait_for_timeout(3000)  # Wait for expanded content to load
            except Exception as e:
                print(f"   ℹ️  'Weitere Informationen' button not found or already expanded: {e}")

            # Scroll down to load lazy-loaded content
            print("📜 Scrolling down to load all content...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)

            # Scroll back up
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(2000)

            print("\n" + "="*60)
            if remove:
                print("DELETING CREDENTIALS")
            else:
                print("LISTING CREDENTIALS")
            print("="*60)

            # Wait a bit more for dynamic content
            page.wait_for_timeout(2000)

            # Debug: Show page content
            print("🔍 DEBUG: Checking page content...")
            page_text = page.locator('body').inner_text()
            if 'aiohue' in page_text.lower():
                print("   ✅ Found 'aiohue' text on page")
            else:
                print("   ⚠️  'aiohue' text not found on page")

            # On /homes page, credentials are shown as cards
            # Each card has a title <h4><span>name</span></h4>
            # The cards themselves are clickable and navigate to /local-integration/{name}
            # The DELETE button is on the detail page, NOT on /homes!

            print("🔍 Finding credential names on /homes page...")

            # Find all credential names (h4 with span)
            credential_titles = page.locator('h4 span').all()
            print(f"   Found {len(credential_titles)} h4 span elements")

            credential_cards = []
            for title_elem in credential_titles:
                try:
                    credential_name = title_elem.inner_text().strip()

                    # Skip empty or very short names
                    if not credential_name or len(credential_name) < 3:
                        continue

                    # Skip navigation/menu items
                    skip_items = ['Produkte', 'Support', 'Einstellungen', 'Mein Philips', 'Abmelden',
                                  'Zuhause', 'Home', 'Meine', 'Kein', 'Alle', 'Diese', 'Du']
                    if any(skip in credential_name for skip in skip_items):
                        continue

                    # Skip items that don't look like app names
                    # App names are usually single words or hyphenated
                    if len(credential_name) > 50:  # Too long to be an app name
                        continue

                    # Try to find the description paragraph (contains bridge/home info)
                    description = ""
                    try:
                        # The description is in a <p> tag that follows the <h4>
                        # Get the parent container and look for the description
                        parent = title_elem.locator('xpath=ancestor::div[contains(@class, "LinearLayout")]').first

                        # Try to find all paragraphs and pick the one with bridge names and last used date
                        desc_paragraphs = parent.locator('p[id$="-description"] span').all()
                        for desc_elem in desc_paragraphs:
                            text = desc_elem.inner_text().strip()
                            # Look for descriptions containing "Zuletzt verwendet" (last used)
                            if 'Zuletzt verwendet' in text or 'Last used' in text:
                                description = text
                                break
                            # If no "Zuletzt verwendet", take the first non-summary description
                            # (avoid generic summaries like "3 Hue Bridges | 1 Mitglied")
                            elif 'Hue Bridges' not in text and 'Mitglied' not in text and len(text) > 5:
                                description = text
                    except:
                        pass

                    # Build the URL for this credential
                    detail_url = f"https://www.account.philips-hue.com/local-integration/{credential_name}"

                    credential_cards.append({
                        'name': credential_name,
                        'description': description,
                        'url': detail_url,
                        'button': None  # Will be found on detail page
                    })

                    if description:
                        print(f"   ✅ Found credential: '{credential_name}' ({description[:50]}...)")
                    else:
                        print(f"   ✅ Found credential: '{credential_name}'")

                except Exception as e:
                    print(f"   ⚠️  Error processing title: {e}")

            print(f"\n   Total credentials found: {len(credential_cards)}")

            integration_links = []  # Keep for compatibility below

            # If no filter specified, list ALL credentials
            if credential_names is None:
                print("📋 Listing all credentials:\n")

                for i, card in enumerate(credential_cards, 1):
                    print(f"{i}. {card['name']}")
                    if card['description']:
                        print(f"   Info: {card['description']}")
                    print(f"   Detail URL: {card['url']}")
                    listed_count += 1

                print(f"\n✅ Listed {listed_count} credentials")
            else:
                # Filter/delete specific credentials
                for pattern in credential_names:
                    print(f"\n🔍 Looking for credential: {pattern}")

                    credential_found = False

                    # Check each credential card
                    for card in credential_cards:
                        try:
                            app_name = card['name']

                            # Check if this app matches the pattern
                            if pattern.startswith("CONTAINS:"):
                                search_term = pattern.replace("CONTAINS:", "")
                                matches = search_term.lower() in app_name.lower()
                            else:
                                matches = app_name == pattern

                            if matches:
                                print(f"  ✅ Found matching credential: {app_name}")

                                if remove:
                                    # DELETE MODE: Navigate to detail page and delete individual entries
                                    print(f"  🌐 Navigating to detail page...")
                                    detail_url = card['url']

                                    try:
                                        page.goto(detail_url, timeout=timeout)
                                        page.wait_for_load_state('networkidle')
                                        page.wait_for_timeout(3000)  # Wait for React to render

                                        # Check if we have detailed data (JSON format with UUIDs)
                                        app_detail = None
                                        if detailed_data:
                                            # Find this app in detailed_data
                                            for app in detailed_data['apps']:
                                                if app['base_name'] == app_name:
                                                    app_detail = app
                                                    break

                                        if app_detail:
                                            # DETAILED MODE: Delete specific entries by matching full names and dates
                                            print(f"  📋 Detailed deletion mode: selectively deleting {len(app_detail['entries_to_delete'])} entries")

                                            entries_deleted = 0

                                            # Helper function to parse portal date format (German or English)
                                            def parse_portal_date(text):
                                                """
                                                Extract and parse date from portal format.
                                                Supports both German and English formats:
                                                - German: 'Zuletzt verwendet am 01.11.21, 22:23'
                                                - English: 'Last used on November 12, 2025, 10:36'
                                                - English: 'Last used on Nov 12, 2025, 10:36'
                                                - English short: 'Last used on 11/12/25, 10:36'
                                                """
                                                import re
                                                from datetime import datetime

                                                try:
                                                    # Pattern 1: German format "Zuletzt verwendet am DD.MM.YY, HH:MM"
                                                    match = re.search(r'Zuletzt verwendet am (\d{2})\.(\d{2})\.(\d{2}), (\d{2}):(\d{2})', text)
                                                    if match:
                                                        day, month, year, hour, minute = match.groups()
                                                        year_full = int(year)
                                                        if year_full < 50:
                                                            year_full += 2000
                                                        else:
                                                            year_full += 1900
                                                        return datetime(year_full, int(month), int(day), int(hour), int(minute))

                                                    # Pattern 2: English with full month name "Last used on November 12, 2025, 10:36"
                                                    match = re.search(
                                                        r'Last used on ([A-Za-z]+) (\d{1,2}), (\d{4}), (\d{1,2}):(\d{2})',
                                                        text
                                                    )
                                                    if match:
                                                        month_name, day, year, hour, minute = match.groups()
                                                        # Parse month name
                                                        month_map = {
                                                            'january': 1, 'february': 2, 'march': 3, 'april': 4,
                                                            'may': 5, 'june': 6, 'july': 7, 'august': 8,
                                                            'september': 9, 'october': 10, 'november': 11, 'december': 12,
                                                            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                                                            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                                                            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                                                        }
                                                        month = month_map.get(month_name.lower())
                                                        if month:
                                                            return datetime(int(year), month, int(day), int(hour), int(minute))

                                                    # Pattern 3: English short date "Last used on 11/12/25, 10:36" (MM/DD/YY)
                                                    match = re.search(r'Last used on (\d{1,2})/(\d{1,2})/(\d{2}), (\d{1,2}):(\d{2})', text)
                                                    if match:
                                                        month, day, year, hour, minute = match.groups()
                                                        year_full = int(year)
                                                        if year_full < 50:
                                                            year_full += 2000
                                                        else:
                                                            year_full += 1900
                                                        return datetime(year_full, int(month), int(day), int(hour), int(minute))

                                                    # Pattern 4: English with 2-digit year "Last used on Nov 12, 25, 10:36"
                                                    match = re.search(
                                                        r'Last used on ([A-Za-z]+) (\d{1,2}), (\d{2}), (\d{1,2}):(\d{2})',
                                                        text
                                                    )
                                                    if match:
                                                        month_name, day, year, hour, minute = match.groups()
                                                        month_map = {
                                                            'january': 1, 'february': 2, 'march': 3, 'april': 4,
                                                            'may': 5, 'june': 6, 'july': 7, 'august': 8,
                                                            'september': 9, 'october': 10, 'november': 11, 'december': 12,
                                                            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
                                                            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
                                                            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                                                        }
                                                        month = month_map.get(month_name.lower())
                                                        if month:
                                                            year_full = int(year)
                                                            if year_full < 50:
                                                                year_full += 2000
                                                            else:
                                                                year_full += 1900
                                                            return datetime(year_full, month, int(day), int(hour), int(minute))

                                                except Exception:
                                                    # Avoid raising on unexpected formats
                                                    pass

                                                return None

                                            # Parse expected date from JSON
                                            def parse_iso_date(iso_string):
                                                """Parse ISO format: 2021-11-01T21:23:34"""
                                                from datetime import datetime
                                                try:
                                                    # Handle with or without microseconds
                                                    if '.' in iso_string:
                                                        return datetime.fromisoformat(iso_string.split('.')[0])
                                                    else:
                                                        return datetime.fromisoformat(iso_string.replace('T', ' '))
                                                except:
                                                    return None

                                            for entry_to_delete in app_detail['entries_to_delete']:
                                                full_name = entry_to_delete['full_name']
                                                last_used_iso = entry_to_delete['last_used']
                                                expected_date = parse_iso_date(last_used_iso)

                                                print(f"    🔍 Looking for: {full_name} (last used: {last_used_iso})")

                                                # Find all device entry cards on the detail page
                                                entry_cards = page.locator('div[class*="LinearLayout"]').all()

                                                found_entry = False
                                                for entry_card in entry_cards:
                                                    try:
                                                        # Try to find h4 with the full name
                                                        title_elem = entry_card.locator('h4 span').first
                                                        if not title_elem.is_visible(timeout=1000):
                                                            continue

                                                        title_text = title_elem.inner_text().strip()

                                                        if title_text == full_name:
                                                            # Found matching name, now check the date
                                                            desc_elem = entry_card.locator('span[class*="Span"]').first
                                                            desc_text = desc_elem.inner_text() if desc_elem.is_visible(timeout=1000) else ""

                                                            # Check if this has "Zuletzt verwendet" in description
                                                            if "Zuletzt verwendet" in desc_text or "Last used" in desc_text:
                                                                # Parse the date from the page (supports German and English)
                                                                page_date = parse_portal_date(desc_text)

                                                                # Match by date (must match within 2 hour tolerance for timezone differences)
                                                                date_matches = False
                                                                if page_date and expected_date:
                                                                    time_diff = abs((page_date - expected_date).total_seconds())
                                                                    # Allow up to 2 hours difference (timezone + potential DST)
                                                                    date_matches = time_diff < 7200  # 2 hours tolerance

                                                                if date_matches:
                                                                    print(f"      ✅ Found EXACT MATCH: {title_text}")
                                                                    print(f"         Details: {desc_text[:100]}...")
                                                                    print(f"         Date match: {page_date} ≈ {expected_date}")

                                                                    # Find the "Zugang widerrufen" button for THIS specific entry
                                                                    revoke_btn = entry_card.locator(
                                                                        'button:has-text("Zugang widerrufen"), '
                                                                        'button:has-text("Revoke access")'
                                                                    ).first

                                                                    if revoke_btn.is_visible(timeout=2000):
                                                                        print(f"      🗑️  Clicking 'Zugang widerrufen'...")
                                                                        revoke_btn.click()
                                                                        page.wait_for_timeout(2000)

                                                                        # Confirm deletion
                                                                        confirm_btn = page.locator(
                                                                            'button:has-text("Ja, entfernen"), '
                                                                            'button:has-text("Yes, remove")'
                                                                        ).first

                                                                        if confirm_btn.is_visible(timeout=5000):
                                                                            print(f"      ✔️  Confirming deletion...")
                                                                            confirm_btn.click()
                                                                            page.wait_for_timeout(2000)

                                                                            # After confirmation, there's another popup with "Fertig" button
                                                                            print(f"      ⏳  Looking for 'Fertig' button...")
                                                                            done_btn = page.locator(
                                                                                'button:has-text("Fertig"), '
                                                                                'button:has-text("Done"), '
                                                                                'button:has-text("OK"), '
                                                                                'button:has-text("Close")'
                                                                            ).first

                                                                            if done_btn.is_visible(timeout=5000):
                                                                                print(f"      ✔️  Clicking 'Fertig'...")
                                                                                done_btn.click()
                                                                                page.wait_for_timeout(2000)
                                                                            else:
                                                                                print(f"      ℹ️  'Fertig' button not found (may not be needed)")

                                                                            entries_deleted += 1
                                                                            print(f"      ✅ Entry deleted!")

                                                                            found_entry = True
                                                                            break
                                                                    else:
                                                                        print(f"      ⚠️  Delete button not found for this entry")
                                                                else:
                                                                    # Date didn't match or couldn't be parsed
                                                                    if page_date is None:
                                                                        print(f"      ⏭️  Skipping: Could not parse date from portal")
                                                                        print(f"         Description text: {desc_text[:100]}")
                                                                        print(f"         Expected date: {expected_date}")
                                                                        print(f"         Please report this format for future support")
                                                                    else:
                                                                        print(f"      ⏭️  Skipping: Date doesn't match (page: {page_date}, expected: {expected_date})")
                                                    except Exception as e:
                                                        # Skip this card, try next
                                                        continue

                                                if not found_entry:
                                                    print(f"      ⚠️  Entry not found on page (or already deleted)")

                                            if entries_deleted > 0:
                                                deleted_count += entries_deleted
                                                print(f"  ✅ Deleted {entries_deleted} entries for '{app_name}'!")
                                            else:
                                                print(f"  ⚠️  No entries were deleted")

                                            # Navigate back to /homes
                                            print("  ↩️  Navigating back to /homes...")
                                            page.goto(PHILIPS_HUE_PORTAL, timeout=timeout)
                                            page.wait_for_load_state('networkidle')
                                            page.wait_for_timeout(3000)

                                        else:
                                            # SIMPLE MODE: Delete ALL entries (no detailed data provided)
                                            print(f"  ⚠️  Simple deletion mode: This will delete ALL entries!")
                                            print(f"  ℹ️  Skipping - use JSON format file for selective deletion")

                                            # Navigate back to /homes
                                            page.goto(PHILIPS_HUE_PORTAL, timeout=timeout)
                                            page.wait_for_load_state('networkidle')
                                            page.wait_for_timeout(3000)

                                    except Exception as e:
                                        print(f"  ⚠️  Error during deletion: {e}")
                                        import traceback
                                        traceback.print_exc()
                                        # Try to navigate back to /homes
                                        try:
                                            page.goto(PHILIPS_HUE_PORTAL, timeout=timeout)
                                            page.wait_for_load_state('networkidle')
                                            page.wait_for_timeout(3000)
                                        except:
                                            pass
                                else:
                                    # LIST MODE: Just show the credential info
                                    print(f"     Name: {app_name}")
                                    if card['description']:
                                        print(f"     Info: {card['description']}")
                                    print(f"     Detail URL: {card['url']}")
                                    listed_count += 1

                                credential_found = True

                        except Exception as e:
                            action = "deleting" if remove else "listing"
                            print(f"  ⚠️  Error {action} credential: {e}")
                            continue

                    if not credential_found:
                        action = "deleted" if remove else "listed"
                        print(f"  ❌ Credential not found or could not be {action}")
                        failed_credentials.append(pattern)

            print("\n" + "="*60)
            if remove:
                print("DELETION SUMMARY")
            else:
                print("LISTING SUMMARY")
            print("="*60)

            if credential_names:
                print(f"Total attempted: {len(credential_names)}")
                if remove:
                    print(f"Successfully deleted: {deleted_count}")
                else:
                    print(f"Successfully listed: {listed_count}")
                print(f"Failed: {len(failed_credentials)}")

                if failed_credentials:
                    print("\nFailed credentials:")
                    for cred in failed_credentials:
                        print(f"  - {cred}")
            else:
                print(f"Listed all credentials on portal")

            print("="*60)

        except PlaywrightTimeout as e:
            print(f"\n❌ Timeout error: {e}")
            print("The page took too long to load. Try again or check your internet connection.")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            # Keep browser open for a while if not headless
            interrupted = False
            if not headless:
                print("\n⏸️  Browser will stay open for 300 seconds (5 minutes) for inspection...")
                print("   Press Ctrl+C to close immediately, or wait...")
                try:
                    page.wait_for_timeout(300000)
                except KeyboardInterrupt:
                    print("\n   Interrupted by user")
                    interrupted = True

            print("\n🔒 Closing browser...")
            try:
                context.close()
                browser.close()
            except Exception as e:
                print(f"   Warning: Error closing browser: {e}")
                pass

            # If interrupted, exit immediately after cleanup
            if interrupted:
                import os
                print("\n✅ Done!")
                os._exit(0)

    print("\n✅ Done!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="List or delete Hue bridge credentials via Philips cloud portal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Security Notes:
- This script does NOT store your credentials anywhere
- Credentials are only kept in memory during execution
- Use at your own risk - this automates browser actions
- Default mode is SAFE (list only) - requires --remove flag to delete

Examples:
    # List all credentials (safe - default)
    python3 list-hue-credentials-portal.py

    # List credentials from file
    python3 list-hue-credentials-portal.py --file exposed-credentials.txt

    # List specific credential by name
    python3 list-hue-credentials-portal.py --name "aiohue-script"

    # Delete credentials from file (requires --remove)
    python3 list-hue-credentials-portal.py --remove --file exposed-credentials.txt

    # Delete specific credential (requires --remove)
    python3 list-hue-credentials-portal.py --remove --name "aiohue-script"

    # Run with visible browser (for debugging)
    python3 list-hue-credentials-portal.py --no-headless --file credentials.txt
        """
    )

    parser.add_argument(
        "--file",
        type=str,
        help="File containing credential names to filter (one per line)"
    )

    parser.add_argument(
        "--name",
        type=str,
        action='append',
        help="Specific credential name to filter (can be used multiple times)"
    )

    parser.add_argument(
        "--remove",
        action='store_true',
        help="DELETE mode - actually remove credentials (default: list only)"
    )

    parser.add_argument(
        "--no-headless",
        action='store_true',
        help="Run browser in visible mode (useful for debugging)"
    )

    parser.add_argument(
        "--manual-login",
        action='store_true',
        help="Manual login mode - browser stays open, you log in yourself, then press Enter"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Timeout in milliseconds (default: 30000)"
    )

    args = parser.parse_args()

    # Load credential names (None if no filter) and detailed data (if JSON format)
    credential_names, detailed_data = load_credential_names(args.file, args.name)

    print("\n" + "="*60)
    print("PHILIPS HUE CREDENTIAL TOOL")
    print("="*60)
    print(f"Mode: {'DELETE' if args.remove else 'LIST ONLY (SAFE)'}")

    if detailed_data:
        print(f"Format: Detailed JSON (selective deletion by date/UUID)")
        print(f"Apps: {len(detailed_data['apps'])}")
        if detailed_data.get('cutoff_date'):
            print(f"Cutoff: {detailed_data['cutoff_date']}")
    elif credential_names:
        print(f"Filter: {len(credential_names)} pattern(s)")
        for name in sorted(credential_names):
            print(f"  - {name}")
    else:
        print(f"Filter: None (will list all credentials)")
    print()

    # Confirm deletion if in remove mode
    if args.remove:
        print("⚠️  WARNING: You are about to DELETE credentials!")
        confirm = input("⚠️  Proceed with DELETION? (yes/no): ").strip().lower()
        if confirm != 'yes':
            print("❌ Deletion cancelled by user")
            sys.exit(0)

    # Prompt for credentials (skip if manual login)
    if args.manual_login:
        email, password = None, None
        print("\n⚠️  Manual login mode activated")
        print("   Browser will stay open for you to log in manually")
    else:
        email, password = prompt_credentials()

    # List or delete credentials
    list_or_delete_credentials(
        email=email,
        password=password,
        credential_names=credential_names,
        detailed_data=detailed_data,
        remove=args.remove,
        headless=not args.no_headless and not args.manual_login,  # Manual login always visible
        timeout=args.timeout,
        manual_login=args.manual_login
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelled by user (Ctrl+C)")
        # Force exit immediately
        import os
        os._exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
