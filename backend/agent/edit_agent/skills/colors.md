---
id: colors
title: Colors
summary: Patch operations for LUTs, grading, curves, and white balance.
category: editing
complexity: moderate
---

## lut - Apply LUT
Summary: Apply a LUT via add_effect.
Complexity: simple
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Apply a cinematic LUT",
  "operations": [
    {
      "operation_type": "add_effect",
      "operation_data": {
        "track_index": 0,
        "item_index": 0,
        "effect": {
          "OTIO_SCHEMA": "Effect.1",
          "effect_name": "LUT",
          "metadata": {
            "type": "lut",
            "path": "luts/film.cube",
            "intensity": 0.8
          }
        }
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
                  "effect_name": {"const": "LUT"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "lut"},
                      "path": {"type": "string"},
                      "intensity": {"type": "number"}
                    },
                    "required": ["type", "path"]
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

## grade - Basic Grade
Summary: Apply brightness/contrast/saturation/gamma via add_effect.
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
                  "effect_name": {"const": "ColorGrade"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "grade"},
                      "brightness": {"type": "number"},
                      "contrast": {"type": "number"},
                      "saturation": {"type": "number"},
                      "gamma": {"type": "number"}
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

## curves - Curves
Summary: Apply curves via add_effect.
Complexity: moderate
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
                  "effect_name": {"const": "Curves"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "curves"},
                      "preset": {"type": "string"},
                      "points": {"type": "string"}
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

## white_balance - White Balance
Summary: Adjust white balance via add_effect.
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
                  "effect_name": {"const": "WhiteBalance"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "white_balance"},
                      "red": {"type": "number"},
                      "green": {"type": "number"},
                      "blue": {"type": "number"}
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
