---
id: silences
title: Silences
summary: Patch operations to remove silent ranges from clips.
---

## remove - Remove Silence Segments
Summary: Use split_clip and remove_clip operations to delete silent ranges. For each
segment, split at end_ms, split at start_ms, then remove the middle clip. Process
segments in reverse order to keep indices stable.
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 1,
      "items": {
        "anyOf": [
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "split_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "clip_index": {"type": "integer"},
                  "split_ms": {"type": "number"}
                },
                "required": ["track_index", "clip_index", "split_ms"]
              }
            },
            "required": ["operation_type", "operation_data"]
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "remove_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "clip_index": {"type": "integer"}
                },
                "required": ["track_index", "clip_index"]
              }
            },
            "required": ["operation_type", "operation_data"]
          }
        ]
      }
    }
  },
  "required": ["description", "operations"]
}
```
