---
id: animations
title: Animations
summary: Patch operations for animated text and progress overlays.
category: editing
complexity: moderate
---

## animated_text - Animated Text
Summary: Add animated text (typewriter, slide, bounce, fade).
Complexity: moderate
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add a typewriter headline",
  "operations": [
    {
      "operation_type": "add_generator_clip",
      "operation_data": {
        "track_index": 1,
        "generator_kind": "animated_text",
        "parameters": {
          "text": "New Feature",
          "size": 64,
          "color": "#FFFFFF",
          "animation_type": "typewriter",
          "animation": {"duration_ms": 900, "easing": "ease_in_out"}
        },
        "start_ms": 500,
        "end_ms": 3500,
        "name": "Animated text"
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
              "generator_kind": {"const": "animated_text"},
              "parameters": {
                "type": "object",
                "properties": {
                  "text": {"type": "string"},
                  "font": {"type": "string"},
                  "size": {"type": "number"},
                  "color": {"type": "string"},
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
                  "animation_type": {
                    "type": "string",
                    "enum": ["typewriter", "fade_words", "fade_in", "fade_out", "slide_in", "slide_out", "bounce", "morph"]
                  },
                  "animation": {
                    "type": "object",
                    "properties": {
                      "type": {"type": "string"},
                      "start_ms": {"type": "number"},
                      "duration_ms": {"type": "number"},
                      "easing": {"type": "string"},
                      "direction": {"type": "string"},
                      "distance": {"type": "number"}
                    }
                  }
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

## progress_bar - Progress Bar
Summary: Add a progress bar overlay with optional animation.
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
              "generator_kind": {"const": "progress_bar"},
              "parameters": {
                "type": "object",
                "properties": {
                  "progress": {"type": "number"},
                  "progress_start": {"type": "number"},
                  "progress_end": {"type": "number"},
                  "width": {"type": "number"},
                  "height": {"type": "number"},
                  "x": {"type": "number"},
                  "y": {"type": "number"},
                  "bg_color": {"type": "string"},
                  "fg_color": {"type": "string"},
                  "border_color": {"type": "string"},
                  "border_width": {"type": "number"},
                  "radius": {"type": "number"},
                  "opacity": {"type": "number"},
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
