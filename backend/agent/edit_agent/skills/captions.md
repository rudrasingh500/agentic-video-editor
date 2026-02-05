---
id: captions
title: Captions
summary: Patch operations for caption generator clips.
category: editing
complexity: moderate
---

## add - Add Captions
Summary: Add caption generator clips. If needed, add a "Captions" track first.
Complexity: moderate
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Add a caption clip for the intro",
  "operations": [
    {
      "operation_type": "add_generator_clip",
      "operation_data": {
        "track_index": 1,
        "generator_kind": "caption",
        "parameters": {"text": "Welcome to the show"},
        "start_ms": 0,
        "end_ms": 3000,
        "name": "Intro caption"
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
Complexity: simple
Prerequisites: get_timeline_snapshot
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
