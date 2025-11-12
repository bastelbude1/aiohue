# Script Security Standards

This document explains the security standards for all scripts in this repository.

---

## 🔐 Absolute Rule: NO Hardcoded Sensitive Data

All scripts in this directory follow these security principles:

### ❌ NEVER Include in Scripts:
- Real IP addresses
- Real bridge IDs
- Real usernames/credentials
- Personal names or hostnames
- Absolute file paths with personal info
- Any data from `bridges/config.json`

### ✅ ALWAYS Do Instead:
- Read configuration from `bridges/config.json`
- Use command-line arguments for IDs
- Provide interactive prompts for user selection
- Use relative paths
- Include only generic examples in help text

---

## 📁 Script Categories

### Production Scripts (Tracked in Git):
These scripts contain NO sensitive data:

- `discover-hue-bridges.py` - Bridge discovery
- `register-hue-user.py` - User registration
- `inventory-hue-bridge.py` - Inventory capture
- `automation-hue-bridge.py` - Automation capture
- `query-hue-inventory.py` - Query inventory
- `query-hue-automation.py` - Query automations
- **`delete-bridge-credentials.sh`** - Delete credentials (NEW)

All these scripts:
- ✅ Read from `bridges/config.json`
- ✅ Accept command-line arguments
- ✅ Provide interactive modes
- ✅ Have generic examples only

### Temporary Scripts (NEVER Commit):
If you create one-time scripts with hardcoded data:

- ✅ Name them: `*-exposed-*.sh` or `delete-exposed-*.sh`
- ✅ They will be auto-ignored by `.gitignore`
- ✅ Delete them after use
- ❌ NEVER commit them to git

---

## 🛡️ Credential Deletion Pattern

### ❌ Wrong Way (Hardcoded):
```bash
#!/bin/bash
# BAD: Hardcoded IP and username
curl -X DELETE https://192.168.188.134/api/AbS1AjZ.../config/whitelist/xyz123
```

### ✅ Right Way (Config-Based):
```python
#!/usr/bin/env python3
# GOOD: Reads from config.json
import json
from pathlib import Path

config = json.load(open("bridges/config.json"))
bridge_ip = config["bridges"][0]["ip"]
username = config["bridges"][0]["username"]
# ... use variables, never hardcode
```

---

## 🔄 delete-bridge-credentials.sh Usage

The NEW generic credential deletion script follows all security standards:

```bash
# List all registered users (read-only)
python3 delete-bridge-credentials.sh --list

# Interactive mode - select which users to delete
python3 delete-bridge-credentials.sh

# Work with specific bridge
python3 delete-bridge-credentials.sh --bridge-id abc123def456
```

**Security features:**
- ✅ Reads bridge IPs from `bridges/config.json`
- ✅ Lists users interactively
- ✅ No hardcoded credentials
- ✅ Safe to commit to git
- ✅ Reusable for future credential management

---

## 📋 Script Review Checklist

Before committing any script, verify:

- [ ] No real IP addresses (except localhost examples)
- [ ] No real bridge IDs
- [ ] No real usernames or credentials
- [ ] No personal names or hostnames
- [ ] No absolute paths with personal directories
- [ ] Reads configuration from excluded files
- [ ] Examples use generic placeholders (abc123def456, 192.168.1.100, etc.)
- [ ] Script filename doesn't contain "exposed" or sensitive terms

---

## 🚨 What to Do If You Committed Sensitive Data

1. **Stop immediately** - Don't make more commits
2. **Notify team** - Alert others to the exposure
3. **Rewrite git history** - Use `git filter-branch` to remove data
4. **Force push** - Update remote repository
5. **Rotate credentials** - Delete exposed credentials from bridges
6. **Document** - Note what was exposed and when

---

## 📚 Examples

### Good Examples:
```python
# Reads from config.json
DEFAULT_CONFIG = Path(__file__).parent.parent / "bridges" / "config.json"

# Command-line argument
parser.add_argument("--bridge-id", help="Bridge ID (e.g., abc123def456)")

# Interactive prompt
bridge_ip = input("Enter bridge IP: ")
```

### Bad Examples:
```python
# NEVER DO THIS:
BRIDGE_IP = "192.168.188.134"  # ❌ Hardcoded
BRIDGE_ID = "ecb5faa015bb"     # ❌ Hardcoded
USERNAME = "AbS1AjZ7EFyu..."   # ❌ Hardcoded
```

---

## 🔍 Automated Checks

Before pushing commits, run:

```bash
# Check for sensitive data in tracked files
git ls-files | xargs grep -iE "192\.168\.188|ecb5fa|001788|c42996" || echo "✅ Clean"

# Check .gitignore is working
git status | grep -E "exposed|config\.json" && echo "❌ Problem!" || echo "✅ Clean"
```

---

## 📖 Related Documentation

- `CLAUDE.md` - General security rules for all development
- `bridges/README.md` - Security for bridges directory
- `.gitignore` - Patterns for excluded files

---

*Last updated: 2025-11-12*
*These standards are mandatory for all scripts in this repository.*
