---
id: motions
title: Motions
summary: Stabilization, reframing, position, and zoom effects.
---

## stabilize - Stabilize Clip
Summary: Apply stabilization with optional strength.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "strength": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```

## reframe - Reframe Crop
Summary: Crop to a specific region for reframing.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "x": {"type": "number"},
    "y": {"type": "number"},
    "width": {"type": "number"},
    "height": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "width", "height"]
}
```

## position - Position Clip
Summary: Scale and pad a clip to a position (PiP style).
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "x": {"type": "number"},
    "y": {"type": "number"},
    "width": {"type": "number"},
    "height": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "width", "height"]
}
```

## zoom - Zoom
Summary: Apply a zoom with start/end values and center.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "start_zoom": {"type": "number"},
    "end_zoom": {"type": "number"},
    "center_x": {"type": "number"},
    "center_y": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```
