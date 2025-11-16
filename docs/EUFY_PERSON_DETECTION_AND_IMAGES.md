# Eufy Security - Person Detection and Image Handling

**Date:** 2025-11-16
**Topic:** Person name detection and snapshot image extraction from Eufy Security events

---

## Key Findings

### ✅ Person Names ARE Available

**Contrary to common belief, person names (facial recognition) ARE accessible via the Eufy Security Home Assistant integration!**

The integration receives `personName` events from Eufy devices:

```javascript
Response: {
  type: 'event',
  event: {
    source: 'device',
    event: 'property changed',
    serialNumber: 'T8213P112207080D',
    name: 'personName',
    value: 'GrossMeister'  // ← Facial recognition name!
  }
}
```

**What This Means:**
- ✅ Eufy devices send facial recognition names to HA
- ✅ The Eufy Security integration exposes this data
- ✅ You can use person names in automations
- ✅ Not limited to Eufy app only

---

## Image Data from Events

### Image Download Events

When a person detection occurs, the Eufy integration provides the **complete JPEG image** as a Buffer:

```javascript
Response: {
  type: 'event',
  event: {
    source: 'station',
    event: 'image downloaded',
    serialNumber: 'T8030P23222914A0',
    file: '/zx/hdd_data0/Camera03/202511/20251113124545/snapshort.jpg',
    image: {
      data: {
        type: 'Buffer',
        data: [255, 216, 255, 224, ...] // Full JPEG data (~42KB)
      },
      type: {
        ext: 'jpg',
        mime: 'image/jpeg'
      }
    }
  }
}
```

### JPEG Magic Bytes Verification

The Buffer data starts with valid JPEG markers:
- `[255, 216]` = `FF D8` (JPEG start marker)
- `[255, 224]` = `FF E0` (JFIF APP0 marker)

**Hex dump of first 20 bytes:**
```
ff d8 ff e0 00 10 4a 46 49 46 00 01 01 00 00 01 00 01 00 00
```

**This is a complete, valid JPEG image ready to be saved!**

---

## How to Extract and Save Images

### Method 1: JavaScript/Node.js

```javascript
const fs = require('fs');

// When receiving 'image downloaded' event
function handleImageDownloaded(event) {
  if (event.event === 'image downloaded') {
    // Convert Buffer data to actual Buffer
    const imageBuffer = Buffer.from(event.image.data.data);

    // Extract person name if available
    const personName = event.personName || 'unknown';
    const timestamp = Date.now();

    // Save to file
    const filename = `/config/www/eufy_snapshots/${personName}_${timestamp}.jpg`;
    fs.writeFileSync(filename, imageBuffer);

    console.log(`✅ Image saved: ${filename}`);

    // Image is now accessible at:
    // http://homeassistant.local:8123/local/eufy_snapshots/[filename].jpg
  }
}
```

### Method 2: Python (For HA Integrations)

```python
import time
from pathlib import Path

def save_eufy_snapshot(event_data):
    """Save Eufy snapshot from event data."""

    # Extract image buffer data
    image_data = event_data['image']['data']['data']
    image_bytes = bytes(image_data)

    # Extract metadata
    person_name = event_data.get('personName', 'unknown')
    timestamp = int(time.time())

    # Create directory if needed
    snapshot_dir = Path('/config/www/eufy_snapshots')
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Save image
    filename = snapshot_dir / f"{person_name}_{timestamp}.jpg"
    with open(filename, 'wb') as f:
        f.write(image_bytes)

    print(f"✅ Snapshot saved: {filename}")

    # Return URL for HA use
    return f"/local/eufy_snapshots/{person_name}_{timestamp}.jpg"
```

### Method 3: Node-RED Flow

```javascript
// Flow: Eufy Event → Process → Save Image

// Node 1: Listen for Eufy events
// (eufy-security node)

// Node 2: Function - Extract and Save Image
const fs = require('fs');

if (msg.payload.event === 'image downloaded') {
    // Convert to buffer
    const buffer = Buffer.from(msg.payload.image.data.data);

    // Generate filename
    const person = msg.payload.personName || 'unknown';
    const filename = `/config/www/eufy/${person}_${Date.now()}.jpg`;

    // Save
    fs.writeFileSync(filename, buffer);

    // Pass URL to next node
    msg.image_url = `/local/eufy/${person}_${Date.now()}.jpg`;
    msg.person_name = person;

    return msg;
}

// Node 3: Send notification with image
// (notify service node)
```

---

## Integration with Home Assistant

### Custom Event Handler

Add to your Eufy Security integration or custom component:

```python
from homeassistant.core import callback

@callback
def handle_eufy_image_downloaded(hass, event):
    """Handle Eufy image downloaded event."""

    # Extract image data
    image_buffer = bytes(event['image']['data']['data'])
    person_name = event.get('personName', 'unknown')
    serial_number = event.get('serialNumber', 'unknown')

    # Save to HA's www directory
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'/config/www/eufy_snapshots/{person_name}_{timestamp}.jpg'

    with open(filename, 'wb') as f:
        f.write(image_buffer)

    # Fire HA event for automations
    hass.bus.fire('eufy_snapshot_saved', {
        'person': person_name,
        'camera': serial_number,
        'file': filename,
        'url': f'/local/eufy_snapshots/{person_name}_{timestamp}.jpg'
    })
```

### Automation Example

Use saved snapshots in notifications:

```yaml
automation:
  - alias: "Eufy Person Detected - Send Notification"
    trigger:
      - platform: event
        event_type: eufy_snapshot_saved
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.person != 'unknown' }}"
    action:
      # Send notification with image
      - service: notify.mobile_app_phone
        data:
          title: "Person Detected"
          message: "{{ trigger.event.data.person }} detected at front door"
          data:
            image: "{{ trigger.event.data.url }}"
            priority: high

      # Log to logbook
      - service: logbook.log
        data:
          name: "Eufy Detection"
          message: "{{ trigger.event.data.person }} detected"
          entity_id: camera.front_door
```

### Advanced: AI Processing

Process saved images with additional AI:

```python
from PIL import Image
import face_recognition

def process_eufy_snapshot(image_path, known_faces_db):
    """
    Additional facial recognition on Eufy snapshots.

    Args:
        image_path: Path to saved JPEG
        known_faces_db: Dictionary of known face encodings

    Returns:
        List of recognized persons with confidence scores
    """

    # Load image
    image = face_recognition.load_image_file(image_path)

    # Find faces
    face_locations = face_recognition.face_locations(image)
    face_encodings = face_recognition.face_encodings(image, face_locations)

    recognized = []

    for encoding in face_encodings:
        # Compare with known faces
        matches = face_recognition.compare_faces(
            list(known_faces_db.values()),
            encoding,
            tolerance=0.6
        )

        if True in matches:
            match_index = matches.index(True)
            name = list(known_faces_db.keys())[match_index]

            # Calculate confidence
            face_distances = face_recognition.face_distance(
                list(known_faces_db.values()),
                encoding
            )
            confidence = 1 - face_distances[match_index]

            recognized.append({
                'name': name,
                'confidence': confidence
            })

    return recognized
```

---

## Event Data Structure

### Person Name Event

```javascript
{
  type: 'event',
  event: {
    source: 'device',
    event: 'property changed',
    serialNumber: 'T8213P112207080D',  // Camera serial number
    name: 'personName',                // Property name
    value: 'GrossMeister'              // Recognized person name
  }
}
```

### Image Download Event

```javascript
{
  type: 'event',
  event: {
    source: 'station',                  // From HomeBase
    event: 'image downloaded',
    serialNumber: 'T8030P23222914A0',   // Camera/station serial
    file: '/zx/hdd_data0/Camera03/202511/20251113124545/snapshort.jpg',  // Internal path
    image: {
      data: {
        type: 'Buffer',
        data: [255, 216, ...]           // JPEG bytes (typically ~40-50KB)
      },
      type: {
        ext: 'jpg',
        mime: 'image/jpeg'
      }
    }
  }
}
```

### Complete Detection Event Example

```javascript
{
  device_sn: 'T8600P1023480725',
  event_count: 1,
  crop_local_path: '/zx/hdd_data0/Camera08/202511/20251113124541/snapshort.jpg',
  personName: 'GrossMeister',
  image: {
    data: { type: 'Buffer', data: [...] },
    type: { ext: 'jpg', mime: 'image/jpeg' }
  }
}
```

---

## Storage Locations

### HomeBase Internal Storage

**Path format:** `/zx/hdd_data0/Camera[XX]/[YYYYMM]/[YYYYMMDDHHMMSS]/snapshort.jpg`

**Example:** `/zx/hdd_data0/Camera08/202511/20251113124541/snapshort.jpg`

**Components:**
- `/zx/hdd_data0/` - HomeBase HDD mount point
- `Camera08/` - Camera identifier (numbered)
- `202511/` - Year-Month (2025 November)
- `20251113124541/` - Timestamp (YYYYMMDDHHMMSS)
- `snapshort.jpg` - Snapshot file (note: Eufy's typo "snapshort" not "snapshot")

**Access:**
- ❌ Not directly accessible via HA integration
- ❌ No SSH access by default on HomeBase
- ✅ Images downloaded via events (as shown above)

### Home Assistant Storage

**Recommended location:** `/config/www/eufy_snapshots/`

**Accessible at:** `http://homeassistant.local:8123/local/eufy_snapshots/[filename].jpg`

**Example structure:**
```
/config/www/eufy_snapshots/
├── GrossMeister_20251116124541.jpg
├── GrossMeister_20251116125632.jpg
├── unknown_20251116130045.jpg
└── FamilyMember_20251116131522.jpg
```

---

## Best Practices

### 1. Automatic Cleanup

Prevent storage bloat:

```python
import os
from datetime import datetime, timedelta
from pathlib import Path

def cleanup_old_snapshots(snapshot_dir='/config/www/eufy_snapshots', days_to_keep=7):
    """Delete snapshots older than specified days."""

    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    snapshot_path = Path(snapshot_dir)

    deleted_count = 0
    for snapshot in snapshot_path.glob('*.jpg'):
        # Get file modification time
        mtime = datetime.fromtimestamp(snapshot.stat().st_mtime)

        if mtime < cutoff_date:
            snapshot.unlink()
            deleted_count += 1

    print(f"Cleaned up {deleted_count} old snapshots")
```

### 2. Organize by Date

```python
def save_snapshot_organized(image_bytes, person_name):
    """Save snapshot organized by date."""

    today = datetime.now()
    date_dir = f"/config/www/eufy_snapshots/{today.strftime('%Y-%m-%d')}"
    Path(date_dir).mkdir(parents=True, exist_ok=True)

    timestamp = today.strftime('%H%M%S')
    filename = f"{date_dir}/{person_name}_{timestamp}.jpg"

    with open(filename, 'wb') as f:
        f.write(image_bytes)

    return filename
```

### 3. Database Logging

Track all detections:

```python
import sqlite3

def log_detection(person_name, image_path, camera_sn):
    """Log detection to database."""

    conn = sqlite3.connect('/config/eufy_detections.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            person_name TEXT,
            camera_serial TEXT,
            image_path TEXT
        )
    ''')

    cursor.execute(
        'INSERT INTO detections (person_name, camera_serial, image_path) VALUES (?, ?, ?)',
        (person_name, camera_sn, image_path)
    )

    conn.commit()
    conn.close()
```

---

## Troubleshooting

### Image Not Saving

**Check buffer data is valid:**
```python
# First 2 bytes should be JPEG magic number
if image_data[0] == 255 and image_data[1] == 216:
    print("✅ Valid JPEG header")
else:
    print("❌ Invalid JPEG data")
```

**Check file permissions:**
```bash
ls -la /config/www/eufy_snapshots/
chmod 755 /config/www/eufy_snapshots/
```

### Images Not Loading in Browser

**Check www directory is accessible:**
```yaml
# configuration.yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 127.0.0.1
```

**Verify URL format:**
- ✅ Correct: `/local/eufy_snapshots/image.jpg`
- ❌ Wrong: `/config/www/eufy_snapshots/image.jpg`

### Person Names Show "unknown"

**Check Eufy app settings:**
1. Open Eufy Security app
2. Go to Camera Settings → Detection Settings
3. Enable "Facial Recognition"
4. Add faces to "Familiar Faces" library

**Check event data:**
```javascript
// Verify personName is in event
console.log(event.personName);  // Should show name, not undefined
```

---

## Resources

### Eufy Security Integration

- **GitHub:** https://github.com/fuatakgun/eufy_security
- **HA Community:** https://community.home-assistant.io/t/eufy-security-integration/318353

### Related Tools

- **Face Recognition Library:** https://github.com/ageitgey/face_recognition
- **DeepStack AI:** https://www.deepstack.cc/
- **Frigate NVR:** https://frigate.video/

---

## Summary

**Key Takeaways:**

1. ✅ **Person names ARE available** via Eufy Security HA integration
2. ✅ **Complete JPEG images** are provided as Buffer data in events
3. ✅ **Easy to extract and save** images to HA's www directory
4. ✅ **Can be used in automations** for notifications, logging, AI processing
5. ✅ **HomeBase internal storage** path is visible but not directly accessible

**This completely changes the capabilities of Eufy Security in Home Assistant!**

You can now build:
- Named person notifications with images
- Automatic photo albums by person
- Enhanced security logging
- AI-powered face verification
- Custom dashboards with recent detections

---

**Document Version:** 1.0
**Last Updated:** 2025-11-16
**Author:** Claude Code with bastelbude1
