---
id: mix
title: Mix
summary: Audio transitions, ducking, and loudness normalization.
---

## crossfade - Crossfade
Summary: Add an audio/video crossfade between clips.
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

## ducking - Audio Ducking
Summary: Apply ducking with explicit attenuation segments.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "target_db": {"type": "number"},
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
    }
  },
  "required": ["track_index", "clip_index"]
}
```

## loudness - Loudness Normalize
Summary: Normalize loudness to a target LUFS value.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "target_lufs": {"type": "number"},
    "lra": {"type": "number"},
    "true_peak": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```
