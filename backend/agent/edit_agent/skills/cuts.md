---
id: cuts
title: Cuts
summary: Patch operations for trims, splits, inserts, moves, and pacing.
category: editing
complexity: moderate
---

## trim - Trim Clip
Summary: Apply a trim_clip operation (ms convenience fields supported).
Complexity: simple
Prerequisites: get_timeline_snapshot

Common Errors:
- clip not found: Use get_timeline_snapshot to confirm track_index/clip_index.
- invalid time range: Ensure start_ms < end_ms and within the clip duration.

Example:
```json
{
  "description": "Trim the first clip to start at 2s",
  "operations": [
    {
      "operation_type": "trim_clip",
      "operation_data": {
        "track_index": 0,
        "clip_index": 0,
        "start_ms": 2000,
        "end_ms": 12000
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
          "operation_type": {"const": "trim_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "clip_index": {"type": "integer"},
              "start_ms": {"type": "number"},
              "end_ms": {"type": "number"}
            },
            "required": ["track_index", "clip_index", "start_ms", "end_ms"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## split - Split Clip
Summary: Apply a split_clip operation at a millisecond offset.
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
      }
    }
  },
  "required": ["description", "operations"]
}
```

## insert - Insert Clip
Summary: Apply an add_clip operation using a source time range.
Complexity: simple
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Insert a b-roll clip into track 1",
  "operations": [
    {
      "operation_type": "add_clip",
      "operation_data": {
        "track_index": 1,
        "asset_id": "<asset-id>",
        "source_start_ms": 0,
        "source_end_ms": 5000,
        "insert_index": 2,
        "name": "B-roll insert"
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
          "operation_type": {"const": "add_clip"},
          "operation_data": {
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
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## overwrite - Overwrite Clip Media
Summary: Replace clip media, then trim to a new range. Order: replace_clip_media -> trim_clip.
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
              "operation_type": {"const": "replace_clip_media"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "clip_index": {"type": "integer"},
                  "new_asset_id": {"type": "string"}
                },
                "required": ["track_index", "clip_index", "new_asset_id"]
              }
            },
            "required": ["operation_type", "operation_data"]
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "trim_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "clip_index": {"type": "integer"},
                  "start_ms": {"type": "number"},
                  "end_ms": {"type": "number"}
                },
                "required": ["track_index", "clip_index", "start_ms", "end_ms"]
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

## move - Move Clip
Summary: Move a clip across tracks or positions.
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
          "operation_type": {"const": "move_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "from_track": {"type": "integer"},
              "from_index": {"type": "integer"},
              "to_track": {"type": "integer"},
              "to_index": {"type": "integer"}
            },
            "required": ["from_track", "from_index", "to_track", "to_index"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## slip - Slip Clip
Summary: Slip a clip's source range by a millisecond offset.
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
          "operation_type": {"const": "slip_clip"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "clip_index": {"type": "integer"},
              "offset_ms": {"type": "number"}
            },
            "required": ["track_index", "clip_index", "offset_ms"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## slide - Slide Clip
Summary: Move a clip within the same track.
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
        "anyOf": [
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "move_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "clip_index": {"type": "integer"},
                  "to_index": {"type": "integer"}
                },
                "required": ["track_index", "clip_index", "to_index"]
              }
            },
            "required": ["operation_type", "operation_data"]
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "move_clip"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "from_track": {"type": "integer"},
                  "from_index": {"type": "integer"},
                  "to_track": {"type": "integer"},
                  "to_index": {"type": "integer"}
                },
                "required": ["from_track", "from_index", "to_track", "to_index"]
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

## pacing - Adjust Gap Duration
Summary: Adjust the duration of a gap.
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
          "operation_type": {"const": "adjust_gap_duration"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "gap_index": {"type": "integer"},
              "duration_ms": {"type": "number"}
            },
            "required": ["track_index", "gap_index", "duration_ms"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```
