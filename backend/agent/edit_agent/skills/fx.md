---
id: fx
title: FX
summary: Patch operations for transitions, speed ramps, freeze frames, and stylized effects.
category: editing
complexity: moderate
---

## transition - Transition
Summary: Add a transition with a duration in milliseconds.
Complexity: simple
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Add a dissolve transition between the first two clips",
  "operations": [
    {
      "operation_type": "add_transition",
      "operation_data": {
        "track_index": 0,
        "position": 1,
        "duration_ms": 600,
        "transition_type": "SMPTE_Dissolve"
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

## speed_ramp - Speed Ramp
Summary: Use split_clip operations to isolate segments, then add LinearTimeWarp effects.
Complexity: complex
Prerequisites: get_timeline_snapshot
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 2,
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
              "operation_type": {"const": "add_effect"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "item_index": {"type": "integer"},
                  "effect": {
                    "type": "object",
                    "properties": {
                      "OTIO_SCHEMA": {"const": "LinearTimeWarp.1"},
                      "time_scalar": {"type": "number"}
                    },
                    "required": ["OTIO_SCHEMA", "time_scalar"]
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

## freeze_frame - Freeze Frame
Summary: Split around a time range, then add a FreezeFrame effect to the middle clip.
Complexity: moderate
Prerequisites: get_timeline_snapshot
```json
{
  "type": "object",
  "properties": {
    "description": {"type": "string"},
    "operations": {
      "type": "array",
      "minItems": 2,
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
              "operation_type": {"const": "add_effect"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "item_index": {"type": "integer"},
                  "effect": {
                    "type": "object",
                    "properties": {
                      "OTIO_SCHEMA": {"const": "FreezeFrame.1"}
                    },
                    "required": ["OTIO_SCHEMA"]
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

## blur - Blur
Summary: Apply a blur via add_effect.
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
                  "effect_name": {"const": "Blur"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "blur"},
                      "radius": {"type": "number"}
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

## vignette - Vignette
Summary: Apply a vignette via add_effect.
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
                  "effect_name": {"const": "Vignette"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "vignette"},
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

## grain - Grain
Summary: Apply grain via add_effect.
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
                  "effect_name": {"const": "Grain"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "grain"},
                      "amount": {"type": "number"}
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
