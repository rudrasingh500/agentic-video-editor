---
id: captions
title: Captions
summary: Patch operations for caption generator clips.
---

## add - Add Captions
Summary: Add caption generator clips. If needed, add a "Captions" track first.
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
              "operation_type": {"const": "add_generator_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "generator_kind": {"const": "caption"},
                  "parameters": {
                    "type": "object",
                    "properties": {
                      "text": {"type": "string"},
                      "font": {"type": "string"},
                      "size": {"type": "number"},
                      "color": {"type": "string"},
                      "bg_color": {"type": "string"},
                      "x": {"type": "number"},
                      "y": {"type": "number"}
                    },
                    "required": ["text"]
                  },
                  "start_ms": {"type": "number"},
                  "end_ms": {"type": "number"},
                  "name": {"type": "string"}
                },
                "required": ["track_index", "generator_kind", "parameters", "start_ms", "end_ms"]
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

## title - Title Overlay
Summary: Add a single title overlay as a caption generator clip.
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
              "operation_type": {"const": "add_generator_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "generator_kind": {"const": "caption"},
                  "parameters": {
                    "type": "object",
                    "properties": {
                      "text": {"type": "string"},
                      "font": {"type": "string"},
                      "size": {"type": "number"},
                      "color": {"type": "string"},
                      "bg_color": {"type": "string"},
                      "x": {"type": "number"},
                      "y": {"type": "number"}
                    },
                    "required": ["text"]
                  },
                  "start_ms": {"type": "number"},
                  "end_ms": {"type": "number"},
                  "name": {"type": "string"}
                },
                "required": ["track_index", "generator_kind", "parameters", "start_ms", "end_ms"]
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
