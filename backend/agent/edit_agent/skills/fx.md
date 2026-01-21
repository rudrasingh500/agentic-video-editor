---
id: fx
title: FX
summary: Transitions, speed ramps, freeze frames, and stylized effects.
---

## transition - Transition
Summary: Add a transition at a track position.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "position": {"type": "integer"},
    "duration_ms": {"type": "number"},
    "transition_type": {"type": "string"}
  },
  "required": ["track_index", "position", "duration_ms"]
}
```

## speed_ramp - Speed Ramp
Summary: Apply variable speed segments within a clip.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "segments": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "start_ms": {"type": "number"},
          "end_ms": {"type": "number"},
          "speed": {"type": "number"}
        },
        "required": ["start_ms", "end_ms", "speed"]
      }
    }
  },
  "required": ["track_index", "clip_index", "segments"]
}
```

## freeze_frame - Freeze Frame
Summary: Insert a freeze frame at a timestamp.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "at_ms": {"type": "number"},
    "duration_ms": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "at_ms", "duration_ms"]
}
```

## blur - Blur
Summary: Apply a full-frame blur.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "radius": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```

## vignette - Vignette
Summary: Apply a vignette effect.
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

## grain - Grain
Summary: Apply film grain noise.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "amount": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```
