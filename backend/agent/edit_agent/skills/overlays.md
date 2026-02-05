---
id: overlays
title: Overlays
summary: Patch operations for image, shape, and call-out overlays.
category: editing
complexity: moderate
---

## watermark - Watermark Overlay
Summary: Add an image watermark overlay.
Complexity: simple
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add the logo as a watermark bottom right",
  "operations": [
    {
      "operation_type": "add_generator_clip",
      "operation_data": {
        "track_index": 1,
        "generator_kind": "watermark",
        "parameters": {
          "asset_id": "<logo-asset-uuid>",
          "scale": 0.2,
          "opacity": 0.6,
          "position": "bottom_right"
        },
        "start_ms": 0,
        "end_ms": 10000,
        "name": "Watermark"
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
          "operation_type": {"const": "add_generator_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "generator_kind": {"const": "watermark"},
              "parameters": {
                "type": "object",
                "properties": {
                  "asset_id": {"type": "string"},
                  "image_path": {"type": "string"},
                  "scale": {"type": "number"},
                  "opacity": {"type": "number"},
                  "position": {
                    "type": "string",
                    "enum": ["top_left", "top_right", "bottom_left", "bottom_right", "center"]
                  },
                  "x": {"type": "number"},
                  "y": {"type": "number"},
                  "width": {"type": "number"},
                  "height": {"type": "number"},
                  "margin": {"type": "number"},
                  "animation": {"type": "object"}
                },
                "required": []
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
    }
  },
  "required": ["description", "operations"]
}
```

## shape - Shape Overlay
Summary: Add a basic shape overlay.
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
          "operation_type": {"const": "add_generator_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "generator_kind": {"const": "shape"},
              "parameters": {
                "type": "object",
                "properties": {
                  "shape": {
                    "type": "string",
                    "enum": ["rect", "rounded_rect", "circle", "line", "arrow"]
                  },
                  "color": {"type": "string"},
                  "stroke_color": {"type": "string"},
                  "stroke_width": {"type": "number"},
                  "width": {"type": "number"},
                  "height": {"type": "number"},
                  "x": {"type": "number"},
                  "y": {"type": "number"},
                  "radius": {"type": "number"},
                  "opacity": {"type": "number"},
                  "gradient": {"type": "object"},
                  "animation": {"type": "object"}
                },
                "required": ["shape"]
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
    }
  },
  "required": ["description", "operations"]
}
```

## call_out - Call-out
Summary: Draw a call-out box pointing at a target.
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
          "operation_type": {"const": "add_generator_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "generator_kind": {"const": "call_out"},
              "parameters": {
                "type": "object",
                "properties": {
                  "text": {"type": "string"},
                  "font": {"type": "string"},
                  "size": {"type": "number"},
                  "box_x": {"type": "number"},
                  "box_y": {"type": "number"},
                  "box_width": {"type": "number"},
                  "box_height": {"type": "number"},
                  "box_color": {"type": "string"},
                  "radius": {"type": "number"},
                  "color": {"type": "string"},
                  "padding": {"type": "number"},
                  "line_color": {"type": "string"},
                  "line_width": {"type": "number"},
                  "target_x": {"type": "number"},
                  "target_y": {"type": "number"},
                  "arrow_size": {"type": "number"},
                  "opacity": {"type": "number"},
                  "animation": {"type": "object"}
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
    }
  },
  "required": ["description", "operations"]
}
```
