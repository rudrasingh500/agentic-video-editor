---
id: cuts
title: Cuts
summary: Structural edit actions for trims, splits, inserts, and pacing.
---

## trim - Trim Clip
Summary: Adjust clip in/out using source time in milliseconds.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "start_ms": {"type": "number"},
    "end_ms": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "start_ms", "end_ms"]
}
```

## split - Split Clip
Summary: Split a clip at an offset from the clip start.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "split_ms": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "split_ms"]
}
```

## insert - Insert Clip
Summary: Insert a new clip from an asset into a track.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "asset_id": {"type": "string"},
    "source_start_ms": {"type": "number"},
    "source_end_ms": {"type": "number"},
    "insert_index": {"type": "integer"},
    "name": {"type": "string"}
  },
  "required": ["track_index", "asset_id", "source_start_ms", "source_end_ms"]
}
```

## overwrite - Overwrite Clip Media
Summary: Replace a clip's media and trim it to a new source range.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "asset_id": {"type": "string"},
    "source_start_ms": {"type": "number"},
    "source_end_ms": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "asset_id", "source_start_ms", "source_end_ms"]
}
```

## move - Move Clip
Summary: Move a clip to a new track or position.
```json
{
  "type": "object",
  "properties": {
    "from_track": {"type": "integer"},
    "from_index": {"type": "integer"},
    "to_track": {"type": "integer"},
    "to_index": {"type": "integer"}
  },
  "required": ["from_track", "from_index", "to_track", "to_index"]
}
```

## slip - Slip Clip
Summary: Slip a clip's source range by a millisecond offset.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "offset_ms": {"type": "number"}
  },
  "required": ["track_index", "clip_index", "offset_ms"]
}
```

## slide - Slide Clip
Summary: Slide a clip to a new index within the same track.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "clip_index": {"type": "integer"},
    "to_index": {"type": "integer"}
  },
  "required": ["track_index", "clip_index", "to_index"]
}
```

## pacing - Adjust Gap Duration
Summary: Change a gap duration to improve pacing.
```json
{
  "type": "object",
  "properties": {
    "track_index": {"type": "integer"},
    "gap_index": {"type": "integer"},
    "duration_ms": {"type": "number"}
  },
  "required": ["track_index", "gap_index", "duration_ms"]
}
```
