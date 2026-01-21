---
id: colors
title: Colors
summary: Apply LUTs, grading, curves, and white balance adjustments.
---

## lut - Apply LUT
Summary: Apply a 3D LUT file with optional intensity.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "lut_path": {"type": "string"},
    "intensity": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "lut_path"]
}
```

## grade - Basic Grade
Summary: Apply brightness, contrast, saturation, and gamma adjustments.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "brightness": {"type": "number"},
    "contrast": {"type": "number"},
    "saturation": {"type": "number"},
    "gamma": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```

## curves - Curves
Summary: Apply a curves preset or explicit points.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "preset": {"type": "string"},
    "points": {"type": "string"}
  },
  "required": ["track_index", "clip_index"]
}
```

## white_balance - White Balance
Summary: Adjust white balance offsets for RGB channels.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "red": {"type": "number"},
    "green": {"type": "number"},
    "blue": {"type": "number"}
  },
  "required": ["track_index", "clip_index"]
}
```
