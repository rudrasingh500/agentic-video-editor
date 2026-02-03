---
id: motions
title: Motions
summary: Patch operations for stabilization, reframing, positioning, and zoom.
---

## stabilize - Stabilize Clip
Summary: Apply stabilization via add_effect.
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
                  "effect_name": {"const": "Stabilize"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "stabilize"},
                      "strength": {"type": "number"}
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

## reframe - Reframe Crop
Summary: Apply a reframe via add_effect.
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
                  "effect_name": {"const": "Reframe"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "reframe"},
                      "x": {"type": "number"},
                      "y": {"type": "number"},
                      "width": {"type": "number"},
                      "height": {"type": "number"}
                    },
                    "required": ["type", "width", "height"]
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

## position - Position Clip
Summary: Apply a position effect (PiP) via add_effect.
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
                  "effect_name": {"const": "Position"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "position"},
                      "x": {"type": "number"},
                      "y": {"type": "number"},
                      "width": {"type": "number"},
                      "height": {"type": "number"}
                    },
                    "required": ["type", "width", "height"]
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

## zoom - Zoom
Summary: Apply a zoom effect via add_effect.
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
                  "effect_name": {"const": "Zoom"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "zoom"},
                      "start_zoom": {"type": "number"},
                      "end_zoom": {"type": "number"},
                      "center_x": {"type": "number"},
                      "center_y": {"type": "number"}
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
