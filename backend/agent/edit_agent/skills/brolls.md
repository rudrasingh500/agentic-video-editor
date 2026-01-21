---
id: brolls
title: B-Rolls
summary: Place b-roll, picture-in-picture, and masked overlays.
---

## add - Add B-Roll Clip
Summary: Insert a b-roll clip, optionally positioned as PiP.
```json
{
  "type": "object",
  "properties": {
    "asset_id": {"type": "string"},
    "source_start_ms": {"type": "number"},
    "source_end_ms": {"type": "number"},
    "track_index": {"type": "integer"},
    "insert_index": {"type": "integer"},
    "name": {"type": "string"},
    "position": {
      "type": "object",
      "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"}
      }
    },
    "blur": {"type": "number"},
    "mask": {
      "type": "object",
      "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"}
      }
    }
  },
  "required": ["asset_id", "source_start_ms", "source_end_ms"]
}
```
