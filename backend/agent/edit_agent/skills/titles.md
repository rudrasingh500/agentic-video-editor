---
id: titles
title: Titles
summary: Patch operations for advanced title overlays and lower thirds.
category: editing
complexity: moderate
---

## title - Title Overlay
Summary: Add a styled title overlay using a generator clip.
Complexity: moderate
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add a centered title with a soft shadow",
  "operations": [
    {
      "operation_type": "add_generator_clip",
      "operation_data": {
        "track_index": 1,
        "generator_kind": "title",
        "parameters": {
          "text": "Product Launch",
          "size": 72,
          "color": "#FFFFFF",
          "shadow_color": "#000000@0.6",
          "shadow_offset_x": 4,
          "shadow_offset_y": 4,
          "shadow_blur": 6,
          "align": "center",
          "animation": {"type": "fade_in", "duration_ms": 600}
        },
        "start_ms": 0,
        "end_ms": 4000,
        "name": "Title"
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
                  "generator_kind": {"const": "title"},
                  "parameters": {
                    "type": "object",
                    "properties": {
                      "text": {"type": "string"},
                      "font": {"type": "string"},
                      "size": {"type": "number"},
                      "color": {"type": "string"},
                      "bg_color": {"type": "string"},
                      "bg_padding": {"type": "number"},
                      "bg_radius": {"type": "number"},
                      "outline_color": {"type": "string"},
                      "outline_width": {"type": "number"},
                      "shadow_color": {"type": "string"},
                      "shadow_offset_x": {"type": "number"},
                      "shadow_offset_y": {"type": "number"},
                      "shadow_blur": {"type": "number"},
                      "align": {"type": "string", "enum": ["left", "center", "right"]},
                      "text_gradient": {"type": "object"},
                      "max_width": {"type": "number"},
                      "line_spacing": {"type": "number"},
                      "x": {"type": "number"},
                      "y": {"type": "number"},
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
        ]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## lower_third - Lower Third
Summary: Add a lower-third name/title bar.
Complexity: moderate
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add a lower third for the speaker",
  "operations": [
    {
      "operation_type": "add_generator_clip",
      "operation_data": {
        "track_index": 1,
        "generator_kind": "lower_third",
        "parameters": {
          "name": "Jordan Lee",
          "title": "Product Lead",
          "bg_color": "#111111@0.8",
          "accent_color": "#00AEEF",
          "animation": {"type": "slide_in", "direction": "left"}
        },
        "start_ms": 1200,
        "end_ms": 5200,
        "name": "Lower third"
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
              "generator_kind": {"const": "lower_third"},
              "parameters": {
                "type": "object",
                "properties": {
                  "name": {"type": "string"},
                  "title": {"type": "string"},
                  "font": {"type": "string"},
                  "name_size": {"type": "number"},
                  "title_size": {"type": "number"},
                  "name_color": {"type": "string"},
                  "title_color": {"type": "string"},
                  "bg_color": {"type": "string"},
                  "accent_color": {"type": "string"},
                  "padding": {"type": "number"},
                  "bar_height": {"type": "number"},
                  "bar_width": {"type": "number"},
                  "accent_width": {"type": "number"},
                  "radius": {"type": "number"},
                  "x": {"type": "number"},
                  "y": {"type": "number"},
                  "opacity": {"type": "number"},
                  "animation": {"type": "object"}
                },
                "required": ["name"]
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
