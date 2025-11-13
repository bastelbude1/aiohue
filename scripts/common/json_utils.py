"""JSON utilities for aiohue scripts.

This module provides custom JSON encoders for handling complex aiohue objects.
"""

import json
from enum import Enum


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle complex objects with circular reference protection.

    This encoder handles:
    - Enum types (preserving original value type)
    - Objects with __dict__ attributes (recursively serialized)
    - Circular references (detected and replaced with descriptive string)
    - Private attributes (starting with '_' are excluded)

    Usage:
        json.dumps(obj, cls=CustomJSONEncoder, indent=2)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._visited = set()

    def default(self, obj):
        """Convert objects to JSON-serializable types.

        Args:
            obj: Object to convert

        Returns:
            JSON-serializable representation of the object
        """
        # Handle Enum types - return value directly (not string)
        if isinstance(obj, Enum):
            return obj.value if hasattr(obj, 'value') else str(obj)

        # Handle objects with __dict__ (most aiohue objects)
        if hasattr(obj, '__dict__'):
            # Circular reference protection
            obj_id = id(obj)
            if obj_id in self._visited:
                return f"<circular reference to {type(obj).__name__}>"

            self._visited.add(obj_id)
            try:
                # Recursively convert nested objects
                result = {}
                for k, v in obj.__dict__.items():
                    # Skip private attributes
                    if k.startswith('_'):
                        continue

                    # Recursively handle nested objects
                    if hasattr(v, '__dict__') and not isinstance(v, (str, int, float, bool, type(None))):
                        result[k] = self.default(v)
                    elif isinstance(v, list):
                        result[k] = [self.default(item) if hasattr(item, '__dict__') else item for item in v]
                    elif isinstance(v, dict):
                        result[k] = {dk: (self.default(dv) if hasattr(dv, '__dict__') else dv) for dk, dv in v.items()}
                    else:
                        result[k] = v
                return result
            finally:
                # Clean up visited set after processing
                self._visited.discard(obj_id)

        # Last resort: convert to string
        return str(obj)
