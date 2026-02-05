---
id: brolls
title: B-Rolls
summary: Patch operations for b-roll overlays and picture-in-picture.
category: editing
complexity: moderate
---

## add - Add B-Roll Clip
Summary: Add a b-roll clip and optional effects (position/blur/mask). If needed,
add a "B-roll" video track first.
Complexity: moderate
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Add a b-roll clip over the main footage",
  "operations": [
    {
      "operation_type": "add_clip",
      "operation_data": {
        "track_index": 1,
        "asset_id": "<asset-id>",
        "source_start_ms": 0,
        "source_end_ms": 4000,
        "insert_index": 0,
        "name": "B-roll overlay"
      }
    }
  ]
}
```
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
              "operation_type": {"const": "add_track"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "name": {"type": "string"},
                  "kind": {"type": "string", "enum": ["Video", "Audio"]},
                  "index": {"type": "integer"}
                },
                "required": ["name"]
              }
            },
            "required": ["operation_type", "operation_data"]
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "add_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "asset_id": {"type": "string"},
                  "source_start_ms": {"type": "number"},
                  "source_end_ms": {"type": "number"},
                  "insert_index": {"type": "integer"},
                  "name": {"type": "string"}
                },
                "required": ["track_index", "asset_id", "source_start_ms", "source_end_ms"]
              }
            },
            "required": ["operation_type", "operation_data"]
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "add_effect"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "item_index": {"type": "integer"},
                  "effect": {
                    "type": "object",
                    "properties": {
                      "OTIO_SCHEMA": {"const": "Effect.1"},
                      "effect_name": {"type": "string"},
                      "metadata": {"type": "object"}
                    },
                    "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
                  }
                },
                "required": ["track_index", "item_index", "effect"]
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

Effect guidance:
- Position: effect_name "Position", metadata {"type": "position", "x", "y", "width", "height"}
- Blur: effect_name "Blur", metadata {"type": "blur", "radius"}
- Mask: effect_name "Mask", metadata {"type": "mask", "x", "y", "width", "height"}
