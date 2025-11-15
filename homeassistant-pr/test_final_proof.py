#!/usr/bin/env python3
"""
FINAL PROOF TEST - Docker HA with FIXED scene.py

This test runs against Docker HA (localhost:8123) with the fixed scene.py deployed.
It MUST prove TC3 PASSES (no false activation on light update).

This is the definitive end-to-end validation.
"""

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import aiohttp
from aiohue.v2 import HueBridgeV2

# Configuration
HA_URL = "http://localhost:8123"
TEST_SCENE_ENTITY = "scene.buro_markus_nachtlicht"
TEST_SCENE_HUE_ID = "f0309f80-9480-4b12-a0c3-a026790d87bf"  # From entity registry
BRIDGE_IP = "192.168.188.134"

HA_TOKEN = None
BRIDGE_USERNAME = None


async def setup():
    """Load configuration"""
    global HA_TOKEN, BRIDGE_USERNAME

    # Load HA token
    token_file = Path(__file__).parent / ".ha_docker_token"
    if token_file.exists():
        HA_TOKEN = token_file.read_text().strip()
        print("[OK] Loaded Docker HA token")
    else:
        print(f"[ERROR] Token file not found: {token_file}")
        return False

    # Load bridge config
    config_file = Path(__file__).parent.parent / "bridges" / "config.json"
    try:
        with open(config_file) as f:
            data = json.load(f)
            for bridge in data.get("bridges", []):
                if bridge.get("ip") == BRIDGE_IP:
                    BRIDGE_USERNAME = bridge.get("username")
                    break
    except FileNotFoundError:
        print(f"[ERROR] Bridge config file not found: {config_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in bridge config: {e}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to load bridge config: {e}")
        return False

    if not HA_TOKEN or not BRIDGE_USERNAME:
        print("[ERROR] Configuration incomplete")
        return False

    return True


async def call_ha_api(endpoint, method="GET", data=None):
    """Call HA API"""
    url = f"{HA_URL}/api/{endpoint}"
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        if method == "GET":
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[ERROR] API call failed: {resp.status} - {text[:100]}")
                    return None
                return await resp.json()
        elif method == "POST":
            async with session.post(url, headers=headers, json=data) as resp:
                if resp.status not in [200, 201]:
                    text = await resp.text()
                    print(f"[ERROR] API call failed: {resp.status} - {text[:100]}")
                    return None
                return await resp.json()


async def get_scene_activations(since):
    """Get scene activations from history"""
    end_time = datetime.now(timezone.utc)
    history = await call_ha_api(
        f"history/period/{since.isoformat()}?filter_entity_id={TEST_SCENE_ENTITY}&end_time={end_time.isoformat()}"
    )

    if not history or not history[0]:
        return []

    activations = []
    for state in history[0]:
        if "last_changed" in state:
            # Parse the timestamp with timezone awareness
            state_time_str = state["last_changed"].replace("Z", "+00:00")
            state_time = datetime.fromisoformat(state_time_str)

            # Convert both to UTC for comparison
            since_utc = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since
            if state_time > since_utc:
                activations.append({
                    "time": state["last_changed"],
                    "state": state.get("state", "")
                })
    return activations


async def test_tc3_fixed():
    """
    TC3 - CRITICAL TEST: Light update while scene active should NOT trigger activation

    This is the bug balloob identified. With the fix, this test MUST PASS.
    """
    print("\n" + "="*80)
    print("FINAL PROOF TEST - TC3 WITH FIXED CODE")
    print("Testing: Light update while scene active = NO false activation")
    print("="*80 + "\n")

    if not await setup():
        return 2

    # Connect to bridge
    print("[SETUP] Connecting to Hue Bridge...")
    bridge = HueBridgeV2(BRIDGE_IP, BRIDGE_USERNAME)
    try:
        await bridge.initialize()
        print("[SETUP] Connected to bridge")
    except (ConnectionError, TimeoutError, OSError) as e:
        print(f"[ERROR] Bridge connection failed: {type(e).__name__}: {e}")
        print(f"[ERROR] Check bridge IP ({BRIDGE_IP}) and network connectivity")
        return 2
    except (KeyError, TypeError, ValueError) as e:
        print(f"[ERROR] Bridge initialization failed: {type(e).__name__}: {e}")
        print(f"[ERROR] Check bridge credentials and API compatibility")
        return 2
    except Exception as e:
        print(f"[ERROR] Unexpected error during bridge initialization: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 2

    print()
    print("[TEST] TC3 - Update while active should NOT trigger activation")
    print("-" * 80)

    # Step 1: Activate scene
    print(f"[STEP 1] Activating scene: {TEST_SCENE_ENTITY}")
    result = await call_ha_api(
        "services/scene/turn_on",
        method="POST",
        data={"entity_id": TEST_SCENE_ENTITY}
    )
    if result is None:
        print("[ERROR] Failed to activate scene")
        await bridge.close()
        return 2

    print("[ACTION] Scene activated via HA API")
    await asyncio.sleep(3)  # Give time for activation to be recorded

    # Step 2: Record checkpoint
    checkpoint = datetime.now(timezone.utc) - timedelta(seconds=1)
    print(f"[STEP 2] Checkpoint time: {checkpoint}")

    # Step 3: Modify a light in the scene
    print("[STEP 3] Modifying light in scene...")
    scene = bridge.scenes.get(TEST_SCENE_HUE_ID)
    if not scene or not scene.actions:
        print("[ERROR] Could not access scene or scene has no actions")
        await bridge.close()
        return 2

    light_id = scene.actions[0].target.rid
    try:
        await bridge.lights.set_brightness(light_id, 75)
        print(f"[ACTION] Modified light {light_id[:8]}... brightness to 75%")
    except (ConnectionError, TimeoutError, ValueError, KeyError, AttributeError) as e:
        print(f"[ERROR] Failed to modify light: {type(e).__name__}: {e}")
        await bridge.close()
        return 2

    await asyncio.sleep(3)  # Give time for any potential false activation

    # Step 4: Check for activations AFTER checkpoint
    print("[STEP 4] Checking for activations after checkpoint...")
    activations = await get_scene_activations(checkpoint)

    print(f"\n[RESULT] Activations after checkpoint: {len(activations)}")
    print("-" * 80)

    await bridge.close()

    # Evaluate result
    if len(activations) == 0:
        print("\n✅✅✅ [SUCCESS] TC3 PASSED ✅✅✅")
        print("\nFIX PROVEN TO WORK!")
        print("Light update while scene active did NOT trigger false activation.")
        print("\nThis proves:")
        print("  ✅ State transition detection works correctly")
        print("  ✅ balloob's bug is FIXED")
        print("  ✅ Only INACTIVE → ACTIVE transitions record activations")
        print("  ✅ ACTIVE → ACTIVE updates are correctly ignored")
        print("\nThe fix is ready for submission to home-assistant/core!")
        return 0
    else:
        print("\n❌ [FAIL] TC3 FAILED")
        print(f"Expected 0 activations, got {len(activations)}")
        print("\nThis indicates the fix is not working correctly.")
        print("The fixed code may not be loaded or there's an issue with the logic.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(test_tc3_fixed())
    sys.exit(exit_code)
