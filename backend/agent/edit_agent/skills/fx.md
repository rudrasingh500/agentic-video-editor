---
id: fx
title: FX
summary: Patch operations for transitions, speed ramps, freeze frames, and stylized effects.
category: editing
complexity: moderate
---

## transition - Transition
Summary: Add a transition with a duration in milliseconds.
Complexity: simple
Prerequisites: get_timeline_snapshot

Example:
```json
{
  "description": "Add a dissolve transition between the first two clips",
  "operations": [
    {
      "operation_type": "add_transition",
      "operation_data": {
        "track_index": 0,
        "position": 1,
        "duration_ms": 600,
        "transition_type": "SMPTE_Dissolve"
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
          "operation_type": {"const": "add_transition"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "position": {"type": "integer"},
              "duration_ms": {"type": "number"},
                "transition_type": {
                  "type": "string",
                  "enum": [
                    "SMPTE_Dissolve",
                    "FadeIn",
                    "FadeOut",
                    "Wipe",
                    "Slide",
                    "Custom",
                    "fade",
                    "wipeleft",
                    "wiperight",
                    "wipeup",
                    "wipedown",
                    "slideleft",
                    "slideright",
                    "slideup",
                    "slidedown",
                    "circlecrop",
                    "rectcrop",
                    "distance",
                    "fadeblack",
                    "fadewhite",
                    "radial",
                    "smoothleft",
                    "smoothright",
                    "smoothup",
                    "smoothdown",
                    "circleopen",
                    "circleclose",
                    "vertopen",
                    "vertclose",
                    "horzopen",
                    "horzclose",
                    "dissolve",
                    "pixelize",
                    "diagtl",
                    "diagtr",
                    "diagbl",
                    "diagbr",
                    "hlslice",
                    "hrslice",
                    "vuslice",
                    "vdslice",
                    "hblur",
                    "fadegrays",
                    "wipetl",
                    "wipetr",
                    "wipebl",
                    "wipebr",
                    "squeezeh",
                    "squeezev",
                    "zoomin",
                    "fadefast",
                    "fadeslow",
                    "hlwind",
                    "hrwind",
                    "vuwind",
                    "vdwind",
                    "coverleft",
                    "coverright",
                    "coverup",
                    "coverdown",
                    "revealleft",
                    "revealright",
                    "revealup",
                    "revealdown"
                  ]
                }
            },
            "required": ["track_index", "position", "duration_ms"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## speed_ramp - Speed Ramp
Summary: Use split_clip operations to isolate segments, then add LinearTimeWarp effects.
Complexity: complex
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
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "add_effect"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "item_index": {"type": "integer"},
                  "effect": {
                    "type": "object",
                    "properties": {
                      "OTIO_SCHEMA": {"const": "LinearTimeWarp.1"},
                      "time_scalar": {"type": "number"}
                    },
                    "required": ["OTIO_SCHEMA", "time_scalar"]
                  }
                },
                "required": ["track_index", "item_index", "effect"]
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

## freeze_frame - Freeze Frame
Summary: Split around a time range, then add a FreezeFrame effect to the middle clip.
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
          },
          {
            "type": "object",
            "properties": {
              "operation_type": {"const": "add_effect"},
              "operation_data": {
                "type": "object",
                "properties": {
                  "track_index": {"type": "integer"},
                  "item_index": {"type": "integer"},
                  "effect": {
                    "type": "object",
                    "properties": {
                      "OTIO_SCHEMA": {"const": "FreezeFrame.1"}
                    },
                    "required": ["OTIO_SCHEMA"]
                  }
                },
                "required": ["track_index", "item_index", "effect"]
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

## blur - Blur
Summary: Apply a blur via add_effect.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Blur"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "blur"},
                      "radius": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## vignette - Vignette
Summary: Apply a vignette via add_effect.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Vignette"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "vignette"},
                      "strength": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## grain - Grain
Summary: Apply grain via add_effect.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Grain"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "grain"},
                      "amount": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## glow - Glow
Summary: Add a soft glow/bloom effect.
Complexity: simple
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add a glow to the highlight clip",
  "operations": [
    {
      "operation_type": "add_effect",
      "operation_data": {
        "track_index": 0,
        "item_index": 2,
        "effect": {
          "OTIO_SCHEMA": "Effect.1",
          "effect_name": "Glow",
          "metadata": {"type": "glow", "strength": 0.7, "blur": 18}
        }
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Glow"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "glow"},
                      "strength": {"type": "number"},
                      "blur": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## chromatic_aberration - Chromatic Aberration
Summary: Shift RGB channels for a lens fringe effect.
Complexity: simple
Prerequisites: get_timeline_snapshot
Example:
```json
{
  "description": "Add subtle chromatic aberration",
  "operations": [
    {
      "operation_type": "add_effect",
      "operation_data": {
        "track_index": 0,
        "item_index": 1,
        "effect": {
          "OTIO_SCHEMA": "Effect.1",
          "effect_name": "ChromaticAberration",
          "metadata": {"type": "chromatic_aberration", "amount": 2}
        }
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "ChromaticAberration"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "chromatic_aberration"},
                      "amount": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## sharpen - Sharpen
Summary: Enhance detail with unsharp masking.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Sharpen"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "sharpen"},
                      "amount": {"type": "number"},
                      "radius": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## black_and_white - Black and White
Summary: Desaturate to monochrome.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "BlackAndWhite"},
                  "metadata": {
                    "type": "object",
                    "properties": {"type": {"const": "black_and_white"}},
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## sepia - Sepia
Summary: Apply a warm sepia tone.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Sepia"},
                  "metadata": {
                    "type": "object",
                    "properties": {"type": {"const": "sepia"}},
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## pixelate - Pixelate
Summary: Pixelate the image.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Pixelate"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "pixelate"},
                      "block_size": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## edge_glow - Edge Glow
Summary: Stylized edges blended back on top.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "EdgeGlow"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "edge_glow"},
                      "strength": {"type": "number"},
                      "low": {"type": "number"},
                      "high": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```

## tint - Tint
Summary: Apply a color tint.
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
          "operation_type": {"const": "add_effect"},
          "operation_data": {
            "type": "object",
            "properties": {
              "track_index": {"type": "integer"},
              "item_index": {"type": "integer"},
              "effect": {
                "type": "object",
                "properties": {
                  "OTIO_SCHEMA": {"const": "Effect.1"},
                  "effect_name": {"const": "Tint"},
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "type": {"const": "tint"},
                      "color": {"type": "string"},
                      "amount": {"type": "number"}
                    },
                    "required": ["type"]
                  }
                },
                "required": ["OTIO_SCHEMA", "effect_name", "metadata"]
              }
            },
            "required": ["track_index", "item_index", "effect"]
          }
        },
        "required": ["operation_type", "operation_data"]
      }
    }
  },
  "required": ["description", "operations"]
}
```
