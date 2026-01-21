---
id: silences
title: Silences
summary: Remove silent ranges using transcript or silence analysis.
---

## remove - Remove Silence Segments
Summary: Remove silent ranges from a clip using start/end offsets.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "segments": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "start_ms": {"type": "number"},
          "end_ms": {"type": "number"}
        },
        "required": ["start_ms", "end_ms"]
      }
    }
  },
  "required": ["track_index", "clip_index", "segments"]
}
```
