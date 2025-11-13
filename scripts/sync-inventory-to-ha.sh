#!/bin/bash
#
# Sync Hue Bridge Inventories to Home Assistant
#
# This script:
# 1. Captures fresh inventories from Hue bridges
# 2. Copies JSON files to HA config directory
# 3. Verifies successful transfer
#
# Usage:
#   ./sync-inventory-to-ha.sh

set -e  # Exit on error

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_DIR="${SCRIPT_DIR}/../bridges/inventory"
HA_CONFIG_FILE="${SCRIPT_DIR}/../ha_config.json"

# Read HA configuration from ha_config.json if it exists
if [ -f "${HA_CONFIG_FILE}" ]; then
    HA_SSH_HOST=$(jq -r '.ha_host // empty' "${HA_CONFIG_FILE}")
    HA_SSH_USER=$(jq -r '.ha_user // "hassio"' "${HA_CONFIG_FILE}")
    HA_SSH_KEY_REL=$(jq -r '.ha_ssh_key // empty' "${HA_CONFIG_FILE}")
    HA_INVENTORY_DIR=$(jq -r '.ha_inventory_dir // "/homeassistant/hue_inventories"' "${HA_CONFIG_FILE}")

    # Resolve relative SSH key path
    if [ -n "${HA_SSH_KEY_REL}" ]; then
        if [[ "${HA_SSH_KEY_REL}" = /* ]]; then
            HA_SSH_KEY="${HA_SSH_KEY_REL}"
        else
            HA_SSH_KEY="${SCRIPT_DIR}/${HA_SSH_KEY_REL}"
        fi
    fi
fi

# Fallback to environment variables or defaults
HA_SSH_KEY="${HA_SSH_KEY:-${SCRIPT_DIR}/../../homeassistant_ssh_key}"
HA_SSH_USER="${HA_SSH_USER:-hassio}"
HA_SSH_HOST="${HA_SSH_HOST}"
HA_INVENTORY_DIR="${HA_INVENTORY_DIR:-/homeassistant/hue_inventories}"

# Validate required configuration
if [ -z "${HA_SSH_HOST}" ]; then
    echo "Error: HA host not configured!"
    echo ""
    echo "Please create ha_config.json in the project root:"
    echo '{'
    echo '  "ha_host": "192.168.1.100",'
    echo '  "ha_user": "hassio",'
    echo '  "ha_ssh_key": "../homeassistant_ssh_key",'
    echo '  "ha_inventory_dir": "/homeassistant/hue_inventories"'
    echo '}'
    echo ""
    echo "Or set via environment variable: export HA_SSH_HOST=192.168.1.100"
    exit 1
fi

echo "==================================================================="
echo "Hue Inventory Sync to Home Assistant"
echo "==================================================================="
echo ""

# Step 1: Capture fresh inventories
echo "Step 1: Capturing fresh Hue bridge inventories..."
cd "${SCRIPT_DIR}"
python3 inventory-hue-bridge.py

if [ $? -ne 0 ]; then
    echo "Error: Failed to capture inventories"
    exit 1
fi
echo "✓ Inventories captured"
echo ""

# Step 2: Create directory on HA if it doesn't exist
echo "Step 2: Ensuring HA inventory directory exists..."
ssh -i "${HA_SSH_KEY}" "${HA_SSH_USER}@${HA_SSH_HOST}" \
    "mkdir -p ${HA_INVENTORY_DIR}"

if [ $? -ne 0 ]; then
    echo "Error: Failed to create HA directory"
    exit 1
fi
echo "✓ Directory ready"
echo ""

# Step 3: Copy inventories to HA
echo "Step 3: Copying inventories to Home Assistant..."
scp -i "${HA_SSH_KEY}" \
    "${INVENTORY_DIR}"/*.json \
    "${HA_SSH_USER}@${HA_SSH_HOST}:${HA_INVENTORY_DIR}/"

if [ $? -ne 0 ]; then
    echo "Error: Failed to copy inventories"
    exit 1
fi
echo "✓ Inventories copied"
echo ""

# Step 4: Verify files on HA
echo "Step 4: Verifying files on Home Assistant..."
FILE_COUNT=$(ssh -i "${HA_SSH_KEY}" "${HA_SSH_USER}@${HA_SSH_HOST}" \
    "ls -1 ${HA_INVENTORY_DIR}/*.json 2>/dev/null | wc -l")

echo "Found ${FILE_COUNT} inventory file(s) on HA"
ssh -i "${HA_SSH_KEY}" "${HA_SSH_USER}@${HA_SSH_HOST}" \
    "ls -lh ${HA_INVENTORY_DIR}/*.json"

echo ""
echo "==================================================================="
echo "✓ Sync complete!"
echo "==================================================================="
echo ""
echo "Inventory files are now available at:"
echo "  ${HA_INVENTORY_DIR}/"
echo ""
echo "Next steps:"
echo "  - Create Python script for scene validation"
echo "  - Reference inventories via: /config/hue_inventories/*.json"
echo ""
