---
id: mix
title: Mix
summary: Patch operations for audio transitions, ducking, and loudness normalization.
---

## crossfade - Crossfade
Summary: Add a transition with a duration in milliseconds.
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "operation_type": {"const": "add_transition"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "position": {"type": "integer"},
              "duration_ms": {"type": "number"},
              "transition_type": {"type": "string"}
            },
            "required": ["track_index", "position", "duration_ms"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## ducking - Audio Ducking
Summary: Apply ducking via an add_effect operation.
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 1,
      "items": {
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
                  "effect_name": {"const": "Ducking"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "ducking"},
                      "segments": {
                        "type": "array",
                        "items": {
                          "type": "object",
                          "properties": {
                            "start_ms": {"type": "number"},
                            "end_ms": {"type": "number"},
                            "gain_db": {"type": "number"}
                          },
                          "required": ["start_ms", "end_ms", "gain_db"]
                        }
                      },
                      "target_db": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## loudness - Loudness Normalize
Summary: Normalize loudness via an add_effect operation.
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 1,
      "items": {
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
                  "effect_name": {"const": "Loudness"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "loudness"},
                      "target_lufs": {"type": "number"},
                      "lra": {"type": "number"},
                      "true_peak": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```
