---
id: captions
title: Captions
summary: Caption and text overlay generation tied to transcript ranges.
---

## add - Add Captions
Summary: Add caption clips with text and styling.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "captions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "text": {"type": "string"},
          "start_ms": {"type": "number"},
          "end_ms": {"type": "number"},
          "font": {"type": "string"},
          "size": {"type": "number"},
          "color": {"type": "string"},
          "bg_color": {"type": "string"},
          "x": {"type": "number"},
          "y": {"type": "number"},
          "name": {"type": "string"}
        },
        "required": ["text", "start_ms", "end_ms"]
      }
    }
  },
  "required": ["captions"]
}
```
