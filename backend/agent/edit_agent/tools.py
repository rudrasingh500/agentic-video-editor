from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, text, or_, cast
from sqlalchemy.dialects.postgresql import array, ARRAY
from sqlalchemy.types import String
from sqlalchemy.orm import Session

from database.models import Assets, ProjectEntity, EntitySimilarity, RenderJob
from models.timeline_models import (
    Clip,
    ExternalReference,
    GeneratorReference,
    Gap,
    MissingReference,
    RationalTime,
    Stack,
    TimeRange,
    Track,
    Transition,
)
from models.render_models import (
    RenderJobStatus,
    RenderJobType,
    RenderPreset,
    RenderRequest,
)
from operators.timeline_operator import (
    CheckpointNotFoundError,
    InvalidOperationError,
    VersionConflictError,
    diff_versions,
    get_timeline_snapshot,
    rollback_to_version,
)
from operators.render_operator import (
    create_render_job,
    dispatch_render_job,
    poll_job_status,
    update_job_status,
)
from utils.gcs_utils import generate_signed_url, parse_gcs_url
from utils.embeddings import get_query_embedding
from utils.video_utils import (
    extract_video_segment,
    get_video_duration,
    MAX_VIDEO_DURATION_SECONDS,
)

from .session_ops import execute_patch
from .types import EditOperation, EditPatch, ErrorSeverity, ToolError


DEFAULT_RENDER_WAIT_SECONDS = int(os.getenv("EDIT_AGENT_RENDER_WAIT_SECONDS", "60"))


# =============================================================================
# Asset Retrieval Tools (formerly in asset_retrieval module)
# =============================================================================

ASSET_RETRIEVAL_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_assets_summaries",
            "description": (
                "Get summaries of all assets in the project. "
                "CALL THIS FIRST to understand what content is available before searching. "
                "Returns asset IDs, names, types, summaries, and tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "enum": ["video", "audio", "image"],
                        "description": "Filter by media type (video, audio, or image)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_details",
            "description": (
                "Get full metadata for a specific asset including transcript, "
                "events, faces, objects, scenes, and technical details. "
                "Use this to drill into a specific asset after reviewing summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "UUID of the asset to retrieve",
                    },
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_by_tags",
            "description": (
                "Find assets that match specific tags. "
                "Use this to filter assets by content type, mood, style, or subject matter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tags to search for",
                    },
                    "match_all": {
                        "type": "boolean",
                        "description": (
                            "If true, assets must have ALL specified tags. "
                            "If false, assets with ANY of the tags will match. (default: false)"
                        ),
                    },
                },
                "required": ["tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_transcript",
            "description": (
                "Full-text search within transcripts to find spoken content. "
                "Returns matching segments with timestamps. "
                "Use this to find specific words, phrases, or topics discussed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for transcript content",
                    },
                    "speaker_id": {
                        "type": "string",
                        "description": "Optional: filter to segments from a specific speaker",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_faces_speakers",
            "description": (
                "Find assets containing specific faces or speakers. "
                "Returns timestamps where each person appears or speaks."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "face_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of face IDs to search for",
                    },
                    "speaker_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of speaker IDs to search for",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_events_scenes",
            "description": (
                "Search for specific events or scenes within assets. "
                "Events include key moments, transitions, actions. "
                "Scenes are continuous segments with consistent setting/mood."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "description": (
                            "Type of event to search for "
                            "(e.g., 'transition', 'highlight', 'action', 'speech')"
                        ),
                    },
                    "description_query": {
                        "type": "string",
                        "description": "Text to search for in event/scene descriptions",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_objects",
            "description": (
                "Find assets containing specific objects or visual elements. "
                "Returns timestamps and positions where objects appear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of object names to search for (e.g., 'car', 'phone', 'laptop')",
                    },
                    "prominence": {
                        "type": "string",
                        "enum": ["primary", "secondary", "background"],
                        "description": "Filter by object prominence in the frame",
                    },
                },
                "required": ["object_names"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": (
                "Search assets using natural language semantic similarity. "
                "Finds assets conceptually related to your query, even without exact keyword matches. "
                "Best for conceptual queries like 'energetic footage', 'calm nature scenes', "
                "'professional interview setup', or 'upbeat music'. "
                "Returns assets ranked by semantic similarity to your description."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what you're looking for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default 10)",
                    },
                    "min_similarity": {
                        "type": "number",
                        "description": "Minimum similarity score between 0 and 1 (default 0.5)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    # Entity linking tools
    {
        "type": "function",
        "function": {
            "name": "list_entities",
            "description": (
                "Get all detected entities (people, objects, speakers, locations) in the project. "
                "Shows which assets each entity appears in and any potential matches with other entities. "
                "Use this to understand who/what appears across your videos and find cross-asset connections."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["face", "object", "speaker", "location"],
                        "description": "Filter by entity type",
                    },
                    "asset_id": {
                        "type": "string",
                        "description": "Filter to entities from a specific asset",
                    },
                    "include_potential_matches": {
                        "type": "boolean",
                        "description": "Include potential matches for each entity (default: true)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of entities to return (default 50)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_details",
            "description": (
                "Get full details for a specific entity including source data, "
                "potential matches, and verification status. "
                "Use this to examine an entity before confirming matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "UUID of the entity",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_entity_match",
            "description": (
                "Confirm that two entities represent the same real-world thing "
                "(e.g., same person appearing in different videos). "
                "This improves future suggestions and allows merging entities."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_a_id": {
                        "type": "string",
                        "description": "First entity UUID",
                    },
                    "entity_b_id": {
                        "type": "string",
                        "description": "Second entity UUID",
                    },
                    "merge": {
                        "type": "boolean",
                        "description": "If true, merge entity_b into entity_a (default: false)",
                    },
                },
                "required": ["entity_a_id", "entity_b_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reject_entity_match",
            "description": (
                "Mark that two entities are definitely NOT the same thing. "
                "This prevents future false-positive suggestions for this pair."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_a_id": {
                        "type": "string",
                        "description": "First entity UUID",
                    },
                    "entity_b_id": {
                        "type": "string",
                        "description": "Second entity UUID",
                    },
                },
                "required": ["entity_a_id", "entity_b_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_entities",
            "description": (
                "Merge multiple entities into one named entity. "
                "Use when you've confirmed multiple detections across videos are the same thing. "
                "The first entity in the list becomes the primary, others are merged into it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of entity UUIDs to merge (first becomes primary)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the merged entity (e.g., 'John Smith', 'Company Logo')",
                    },
                },
                "required": ["entity_ids", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_entity",
            "description": "Rename an entity to a user-friendly name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity UUID",
                    },
                    "new_name": {
                        "type": "string",
                        "description": "New name for the entity",
                    },
                },
                "required": ["entity_id", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_entity_appearances",
            "description": (
                "Find all assets where a specific entity (and its merged equivalents) appears. "
                "Returns timestamps and appearance details for each asset. "
                "Optionally includes appearances from unconfirmed potential matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "Entity UUID",
                    },
                    "include_unconfirmed_matches": {
                        "type": "boolean",
                        "description": "Include appearances from potential (unconfirmed) matches (default: false)",
                    },
                },
                "required": ["entity_id"],
            },
        },
    },
]


# =============================================================================
# Edit Agent Tools
# =============================================================================

EDIT_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "skills_registry",
            "description": "List or read available skills and JSON schemas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read"]},
                    "skill_id": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline_snapshot",
            "description": "Inspect the timeline structure (tracks/clips) with indices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_timeline_versions",
            "description": (
                "Compare two timeline versions to see exactly what changed. "
                "Returns added/removed/modified tracks and clips with a summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "version_before": {"type": "integer"},
                    "version_after": {"type": "integer"},
                },
                "required": ["version_before", "version_after"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_timeline",
            "description": "Apply a patch (operations list) to the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "operations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "operation_type": {"type": "string"},
                                        "operation_data": {"type": "object"},
                                    },
                                    "required": ["operation_type", "operation_data"],
                                },
                                "minItems": 1,
                            },
                        },
                        "required": ["description", "operations"],
                    },
                    "apply": {"type": "boolean", "default": True},
                    "rollback_on_error": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "If true, rollback the timeline to the starting version "
                            "when any operation in the patch fails."
                        ),
                    },
                },
                "required": ["patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_to_version",
            "description": (
                "Restore the timeline to a previous version. "
                "Use this to undo edits if verification reveals problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_version": {
                        "type": "integer",
                        "description": "Timeline version to restore to",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the timeline is being restored",
                    },
                },
                "required": ["target_version"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_asset",
            "description": (
                "View an asset's visual content directly. The video/image will be shown to you "
                "so you can see exactly what it contains. For videos longer than 40 minutes, "
                "use t0_ms/t1_ms to view specific segments. Also returns cached analysis metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string", "description": "UUID of the asset to view"},
                    "t0_ms": {"type": "number", "description": "Start time in ms (for viewing specific segment)"},
                    "t1_ms": {"type": "number", "description": "End time in ms (for viewing specific segment)"},
                    "reason": {"type": "string", "description": "Why you need to view this asset"},
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_output",
            "description": "Render a preview output and return job details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeline_version": {"type": "integer"},
                    "preset": {"type": "object"},
                    "wait": {"type": "boolean", "default": True},
                    "wait_timeout_seconds": {"type": "integer"},
                    "poll_interval_seconds": {"type": "number"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_render_output",
            "description": (
                "View a render output directly. The rendered video will be shown to you so you "
                "can visually verify your edits. For renders longer than 40 minutes, use "
                "t0_ms/t1_ms to view segments around where you made edits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Render job UUID"},
                    "timeline_version": {"type": "integer", "description": "Timeline version to find render for"},
                    "t0_ms": {"type": "number", "description": "Start time in ms for segment viewing"},
                    "t1_ms": {"type": "number", "description": "End time in ms for segment viewing"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_quality_checks",
            "description": (
                "Run automated quality checks on a completed render. "
                "Detects common issues like black frames and loudness problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Render job UUID"},
                    "checks": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["black_frames", "audio_levels", "sync", "all"],
                        },
                        "description": "Which checks to run (default: all)",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
]


def _apply_additional_properties(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("type")
    if schema_type == "object" and "properties" in schema:
        schema.setdefault("additionalProperties", False)

    if "properties" in schema:
        for prop_schema in schema["properties"].values():
            if isinstance(prop_schema, dict):
                _apply_additional_properties(prop_schema)

    if "items" in schema:
        items_schema = schema["items"]
        if isinstance(items_schema, dict):
            _apply_additional_properties(items_schema)
        elif isinstance(items_schema, list):
            for entry in items_schema:
                if isinstance(entry, dict):
                    _apply_additional_properties(entry)

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            for entry in schema[key]:
                if isinstance(entry, dict):
                    _apply_additional_properties(entry)


def _enforce_strict_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for tool in tools:
        function = tool.get("function", {})
        function.setdefault("strict", True)
        parameters = function.get("parameters")
        if isinstance(parameters, dict):
            _apply_additional_properties(parameters)
    return tools


ASSET_RETRIEVAL_TOOLS = _enforce_strict_tools(ASSET_RETRIEVAL_TOOLS)
EDIT_AGENT_TOOLS = _enforce_strict_tools(EDIT_AGENT_TOOLS)

# Combined tools list
TOOLS: list[dict[str, Any]] = ASSET_RETRIEVAL_TOOLS + EDIT_AGENT_TOOLS


_ERROR_HINTS: dict[str, tuple[ErrorSeverity, str | None]] = {
    "UNKNOWN_TOOL": (ErrorSeverity.USER_INPUT, "Use a tool name from the tool list."),
    "VALIDATION_ERROR": (
        ErrorSeverity.VALIDATION,
        "Check the tool schema for required fields and valid types.",
    ),
    "INVALID_OPERATION": (
        ErrorSeverity.STATE_MISMATCH,
        "Use get_timeline_snapshot to verify indices and timeline state.",
    ),
    "VERSION_CONFLICT": (
        ErrorSeverity.STATE_MISMATCH,
        "Timeline changed. Refresh with get_timeline_snapshot and retry.",
    ),
    "CHECKPOINT_NOT_FOUND": (
        ErrorSeverity.STATE_MISMATCH,
        "Verify the target timeline version exists before retrying.",
    ),
    "ASSET_NOT_FOUND": (
        ErrorSeverity.USER_INPUT,
        "Use list_assets_summaries or get_asset_details to find valid asset IDs.",
    ),
    "NETWORK_ERROR": (
        ErrorSeverity.RECOVERABLE,
        "Temporary network issue. Retry the operation.",
    ),
    "UNKNOWN_ERROR": (ErrorSeverity.SYSTEM, None),
}


def _create_tool_error(
    code: str,
    message: str,
    context: dict[str, Any] | None = None,
    affected_field: str | None = None,
    severity: ErrorSeverity | None = None,
    recovery_hint: str | None = None,
) -> dict[str, Any]:
    inferred_severity, inferred_hint = _ERROR_HINTS.get(code, _ERROR_HINTS["UNKNOWN_ERROR"])
    error = ToolError(
        severity=severity or inferred_severity,
        code=code,
        message=message,
        recovery_hint=recovery_hint or inferred_hint,
        affected_field=affected_field,
        context=context or {},
    )
    return error.to_response()


def _categorize_exception(exc: Exception) -> tuple[str, ErrorSeverity]:
    if isinstance(exc, InvalidOperationError):
        return "INVALID_OPERATION", ErrorSeverity.STATE_MISMATCH
    if isinstance(exc, VersionConflictError):
        return "VERSION_CONFLICT", ErrorSeverity.STATE_MISMATCH
    if isinstance(exc, CheckpointNotFoundError):
        return "CHECKPOINT_NOT_FOUND", ErrorSeverity.STATE_MISMATCH
    if isinstance(exc, ValidationError):
        return "VALIDATION_ERROR", ErrorSeverity.VALIDATION
    if isinstance(exc, FileNotFoundError) or isinstance(exc, urllib.error.URLError):
        return "NETWORK_ERROR", ErrorSeverity.RECOVERABLE

    message = str(exc).lower()
    if "not found" in message:
        return "ASSET_NOT_FOUND", ErrorSeverity.USER_INPUT
    if "timeout" in message or "connection" in message or "network" in message:
        return "NETWORK_ERROR", ErrorSeverity.RECOVERABLE

    return "UNKNOWN_ERROR", ErrorSeverity.SYSTEM


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
) -> dict[str, Any]:
    tool_map = {
        # Asset retrieval tools
        "list_assets_summaries": _list_assets_summaries,
        "get_asset_details": _get_asset_details,
        "search_by_tags": _search_by_tags,
        "search_transcript": _search_transcript,
        "search_faces_speakers": _search_faces_speakers,
        "search_events_scenes": _search_events_scenes,
        "search_objects": _search_objects,
        "semantic_search": _semantic_search,
        # Entity linking tools
        "list_entities": _list_entities,
        "get_entity_details": _get_entity_details,
        "confirm_entity_match": _confirm_entity_match,
        "reject_entity_match": _reject_entity_match,
        "merge_entities": _merge_entities,
        "rename_entity": _rename_entity,
        "find_entity_appearances": _find_entity_appearances,
        # Edit agent tools
        "skills_registry": _skills_registry,
        "get_timeline_snapshot": _get_timeline_snapshot,
        "compare_timeline_versions": _compare_timeline_versions,
        "edit_timeline": _edit_timeline,
        "undo_to_version": _undo_to_version,
        "view_asset": _view_asset,
        "render_output": _render_output,
        "view_render_output": _view_render_output,
        "run_quality_checks": _run_quality_checks,
    }
    tool_fn = tool_map.get(tool_name)
    if not tool_fn:
        return _create_tool_error(
            "UNKNOWN_TOOL",
            f"Unknown tool: {tool_name}",
            context={"available_tools": sorted(tool_map.keys())},
            severity=ErrorSeverity.USER_INPUT,
        )

    try:
        return tool_fn(
            project_id=project_id,
            user_id=user_id,
            timeline_id=timeline_id,
            db=db,
            **arguments,
        )
    except ValidationError as exc:
        db.rollback()
        return _create_tool_error(
            "VALIDATION_ERROR",
            str(exc),
            context={"tool": tool_name, "arguments": arguments},
        )
    except (InvalidOperationError, VersionConflictError, CheckpointNotFoundError) as exc:
        db.rollback()
        code, severity = _categorize_exception(exc)
        return _create_tool_error(
            code,
            str(exc),
            context={"tool": tool_name, "arguments": arguments},
            severity=severity,
        )
    except Exception as exc:
        db.rollback()
        code, severity = _categorize_exception(exc)
        return _create_tool_error(
            code,
            str(exc),
            context={"tool": tool_name, "arguments": arguments},
            severity=severity,
        )


# =============================================================================
# Asset Retrieval Tool Implementations
# =============================================================================


def _list_assets_summaries(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    asset_type: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_summary,
        Assets.asset_tags,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    if asset_type:
        type_prefix = f"{asset_type}/"
        query = query.filter(Assets.asset_type.startswith(type_prefix))
    query = query.limit(limit)
    results = query.all()
    return {
        "count": len(results),
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "tags": row.asset_tags or [],
            }
            for row in results
        ],
    }


def _get_asset_details(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    asset_id: str,
) -> dict[str, Any]:
    asset = (
        db.query(Assets)
        .filter(
            Assets.asset_id == asset_id,
            Assets.project_id == project_id,
            Assets.indexing_status == "completed",
        )
        .first()
    )
    if not asset:
        return {"error": f"Asset not found: {asset_id}"}
    return {
        "asset_id": str(asset.asset_id),
        "name": asset.asset_name,
        "type": asset.asset_type,
        "summary": asset.asset_summary,
        "tags": asset.asset_tags or [],
        "transcript": asset.asset_transcript,
        "events": asset.asset_events,
        "notable_shots": asset.notable_shots,
        "scenes": asset.asset_scenes,
        "faces": asset.asset_faces,
        "speakers": asset.asset_speakers,
        "objects": asset.asset_objects,
        "audio_features": asset.audio_features,
        "audio_structure": asset.audio_structure,
        "colors": asset.asset_colors,
        "technical": asset.asset_technical,
    }


def _search_by_tags(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    tags: list[str],
    match_all: bool = False,
) -> dict[str, Any]:
    if not tags:
        return {"error": "No tags provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_summary,
        Assets.asset_tags,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    # Cast the array to text[] for proper JSONB ?| and ?& operator usage
    tags_array = cast(array(tags), ARRAY(String))
    if match_all:
        query = query.filter(Assets.asset_tags.op("?&")(tags_array))
    else:
        query = query.filter(Assets.asset_tags.op("?|")(tags_array))
    results = query.all()
    return {
        "count": len(results),
        "query_tags": tags,
        "match_mode": "all" if match_all else "any",
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "matched_tags": [t for t in (row.asset_tags or []) if t in tags],
            }
            for row in results
        ],
    }


def _search_transcript(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    query: str,
    speaker_id: str | None = None,
) -> dict[str, Any]:
    if not query.strip():
        return {"error": "Empty search query", "assets": []}
    ts_query = func.plainto_tsquery("english", query)
    db_query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_transcript,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
        Assets.transcript_tsv.op("@@")(ts_query),
    )
    results = db_query.all()
    output_assets = []
    for row in results:
        transcript = row.asset_transcript or {}
        segments = transcript.get("segments", [])
        if speaker_id:
            segments = [s for s in segments if s.get("speaker") == speaker_id]
        query_lower = query.lower()
        matching_segments = []
        for seg in segments:
            seg_text = seg.get("text", "")
            if query_lower in seg_text.lower():
                matching_segments.append(
                    {
                        "t0": seg.get("timestamp_ms", seg.get("start_ms", 0)),
                        "t1": seg.get("end_ms", seg.get("timestamp_ms", 0) + 5000),
                        "text": seg_text,
                        "speaker": seg.get("speaker"),
                    }
                )
        if matching_segments:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "segments": matching_segments,
                }
            )
    return {
        "count": len(output_assets),
        "query": query,
        "speaker_filter": speaker_id,
        "assets": output_assets,
    }


def _search_faces_speakers(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    face_ids: list[str] | None = None,
    speaker_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not face_ids and not speaker_ids:
        return {"error": "No face_ids or speaker_ids provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_faces,
        Assets.asset_speakers,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    output_assets = []
    for row in results:
        faces = row.asset_faces or []
        speakers = row.asset_speakers or []
        matched_faces = []
        matched_speakers = []
        if face_ids:
            for face in faces:
                if face.get("id") in face_ids:
                    matched_faces.append(
                        {
                            "id": face.get("id"),
                            "description": face.get("description"),
                            "appears_at_ms": face.get("appears_at_ms", []),
                            "screen_time_percentage": face.get(
                                "screen_time_percentage"
                            ),
                        }
                    )
        if speaker_ids:
            for speaker in speakers:
                if speaker.get("id") in speaker_ids:
                    matched_speakers.append(
                        {
                            "id": speaker.get("id"),
                            "description": speaker.get("description"),
                            "role": speaker.get("role"),
                            "speaking_time_percentage": speaker.get(
                                "speaking_time_percentage"
                            ),
                        }
                    )
        if matched_faces or matched_speakers:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_faces": matched_faces,
                    "matched_speakers": matched_speakers,
                }
            )
    return {
        "count": len(output_assets),
        "query_face_ids": face_ids or [],
        "query_speaker_ids": speaker_ids or [],
        "assets": output_assets,
    }


def _search_events_scenes(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    event_type: str | None = None,
    description_query: str | None = None,
) -> dict[str, Any]:
    if not event_type and not description_query:
        return {"error": "No event_type or description_query provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_events,
        Assets.asset_scenes,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    output_assets = []
    desc_lower = description_query.lower() if description_query else None
    for row in results:
        events = row.asset_events or []
        scenes = row.asset_scenes or []
        matched_events = []
        matched_scenes = []
        for event in events:
            matches = True
            if event_type and event.get("event_type") != event_type:
                matches = False
            if desc_lower and desc_lower not in event.get("description", "").lower():
                matches = False
            if matches:
                matched_events.append(
                    {
                        "t0": event.get("timestamp_ms", 0),
                        "t1": event.get("timestamp_ms", 0) + 3000,
                        "type": event.get("event_type"),
                        "description": event.get("description"),
                        "importance": event.get("importance"),
                    }
                )
        for scene in scenes:
            matches = True
            if desc_lower:
                scene_desc = (
                    scene.get("description", "") + " " + scene.get("key_content", "")
                )
                if desc_lower not in scene_desc.lower():
                    matches = False
            if matches and (not event_type or desc_lower):
                matched_scenes.append(
                    {
                        "t0": scene.get("start_ms", 0),
                        "t1": scene.get("end_ms", 0),
                        "description": scene.get("description"),
                        "location": scene.get("location"),
                        "mood": scene.get("mood"),
                    }
                )
        if matched_events or matched_scenes:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_events": matched_events,
                    "matched_scenes": matched_scenes,
                }
            )
    return {
        "count": len(output_assets),
        "query_event_type": event_type,
        "query_description": description_query,
        "assets": output_assets,
    }


def _search_objects(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    object_names: list[str],
    prominence: str | None = None,
) -> dict[str, Any]:
    if not object_names:
        return {"error": "No object_names provided", "assets": []}
    query = db.query(
        Assets.asset_id,
        Assets.asset_name,
        Assets.asset_type,
        Assets.asset_objects,
        Assets.notable_shots,
    ).filter(
        Assets.project_id == project_id,
        Assets.indexing_status == "completed",
    )
    results = query.all()
    search_names = [n.lower() for n in object_names]
    output_assets = []
    for row in results:
        objects = row.asset_objects or []
        notable_shots = row.notable_shots or []
        matched_objects = []
        for obj in objects:
            obj_name = obj.get("name", "").lower()
            if any(search_name in obj_name for search_name in search_names):
                if prominence and obj.get("prominence") != prominence:
                    continue
                matched_objects.append(
                    {
                        "name": obj.get("name"),
                        "description": obj.get("description"),
                        "position": obj.get("position"),
                        "prominence": obj.get("prominence"),
                        "brand": obj.get("brand"),
                    }
                )
        object_timestamps = []
        for shot in notable_shots:
            shot_desc = shot.get("description", "").lower()
            if any(search_name in shot_desc for search_name in search_names):
                object_timestamps.append(
                    {
                        "t0": shot.get("timestamp_ms", 0),
                        "description": shot.get("description"),
                    }
                )
        if matched_objects or object_timestamps:
            output_assets.append(
                {
                    "asset_id": str(row.asset_id),
                    "name": row.asset_name,
                    "type": row.asset_type,
                    "matched_objects": matched_objects,
                    "object_timestamps": object_timestamps,
                }
            )
    return {
        "count": len(output_assets),
        "query_objects": object_names,
        "prominence_filter": prominence,
        "assets": output_assets,
    }


def _semantic_search(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    query: str,
    limit: int = 10,
    min_similarity: float = 0.5,
) -> dict[str, Any]:
    if not query.strip():
        return {"error": "Empty search query", "assets": []}

    query_embedding = get_query_embedding(query)
    if not query_embedding:
        return {
            "error": "Failed to generate query embedding",
            "assets": [],
        }

    results = db.execute(
        text("""
            SELECT
                asset_id,
                asset_name,
                asset_type,
                asset_summary,
                asset_tags,
                1 - (embedding <=> :query_vector) AS similarity
            FROM assets
            WHERE project_id = :project_id
              AND indexing_status = 'completed'
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> :query_vector) >= :min_similarity
            ORDER BY embedding <=> :query_vector
            LIMIT :limit
        """),
        {
            "query_vector": str(query_embedding),
            "project_id": project_id,
            "min_similarity": min_similarity,
            "limit": limit,
        },
    ).fetchall()

    return {
        "count": len(results),
        "query": query,
        "min_similarity": min_similarity,
        "assets": [
            {
                "asset_id": str(row.asset_id),
                "name": row.asset_name,
                "type": row.asset_type,
                "summary": row.asset_summary,
                "tags": row.asset_tags or [],
                "similarity": round(row.similarity, 4),
            }
            for row in results
        ],
    }


# =============================================================================
# Entity Linking Tool Implementations
# =============================================================================


def _list_entities(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_type: str | None = None,
    asset_id: str | None = None,
    include_potential_matches: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """List all entities in a project with optional filtering."""
    query = db.query(ProjectEntity).filter(
        ProjectEntity.project_id == project_id,
        ProjectEntity.merged_into_id.is_(None),  # Only show non-merged entities
    )

    if entity_type:
        query = query.filter(ProjectEntity.entity_type == entity_type)

    if asset_id:
        query = query.filter(ProjectEntity.asset_id == asset_id)

    query = query.order_by(ProjectEntity.created_at.desc()).limit(limit)
    entities = query.all()

    result_entities = []
    for entity in entities:
        entity_data = {
            "entity_id": str(entity.entity_id),
            "type": entity.entity_type,
            "name": entity.name,
            "description": entity.description,
            "asset_id": str(entity.asset_id),
            "source_data": entity.source_data,
        }

        if include_potential_matches:
            # Get potential matches (unconfirmed similarities)
            similarities = db.query(EntitySimilarity).filter(
                or_(
                    EntitySimilarity.entity_a_id == entity.entity_id,
                    EntitySimilarity.entity_b_id == entity.entity_id,
                ),
                EntitySimilarity.is_confirmed.is_(None),
            ).order_by(EntitySimilarity.similarity_score.desc()).limit(5).all()

            potential_matches = []
            for sim in similarities:
                # Get the other entity in the pair
                other_id = (
                    sim.entity_b_id
                    if str(sim.entity_a_id) == str(entity.entity_id)
                    else sim.entity_a_id
                )
                other_entity = db.query(ProjectEntity).filter(
                    ProjectEntity.entity_id == other_id
                ).first()

                if other_entity:
                    potential_matches.append({
                        "entity_id": str(other_entity.entity_id),
                        "name": other_entity.name,
                        "asset_id": str(other_entity.asset_id),
                        "similarity": round(sim.similarity_score, 3),
                        "status": "unconfirmed",
                    })

            entity_data["potential_matches"] = potential_matches

        # Get confirmed matches (merged entities pointing to this one)
        merged_into = db.query(ProjectEntity).filter(
            ProjectEntity.merged_into_id == entity.entity_id
        ).all()

        if merged_into:
            entity_data["merged_entities"] = [
                {
                    "entity_id": str(m.entity_id),
                    "name": m.name,
                    "asset_id": str(m.asset_id),
                }
                for m in merged_into
            ]

        result_entities.append(entity_data)

    return {
        "count": len(result_entities),
        "entity_type_filter": entity_type,
        "asset_id_filter": asset_id,
        "entities": result_entities,
    }


def _get_entity_details(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_id: str,
) -> dict[str, Any]:
    """Get full details for a specific entity."""
    entity = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_id,
        ProjectEntity.project_id == project_id,
    ).first()

    if not entity:
        return {"error": f"Entity not found: {entity_id}"}

    # Get the asset this entity was detected in
    asset = db.query(Assets).filter(
        Assets.asset_id == entity.asset_id
    ).first()

    # Get all similarities involving this entity
    similarities = db.query(EntitySimilarity).filter(
        or_(
            EntitySimilarity.entity_a_id == entity.entity_id,
            EntitySimilarity.entity_b_id == entity.entity_id,
        )
    ).order_by(EntitySimilarity.similarity_score.desc()).all()

    potential_matches = []
    confirmed_matches = []
    rejected_matches = []

    for sim in similarities:
        other_id = (
            sim.entity_b_id
            if str(sim.entity_a_id) == str(entity.entity_id)
            else sim.entity_a_id
        )
        other_entity = db.query(ProjectEntity).filter(
            ProjectEntity.entity_id == other_id
        ).first()

        if not other_entity:
            continue

        match_data = {
            "entity_id": str(other_entity.entity_id),
            "name": other_entity.name,
            "description": other_entity.description,
            "asset_id": str(other_entity.asset_id),
            "similarity": round(sim.similarity_score, 3),
            "confirmed_by": sim.confirmed_by,
        }

        if sim.is_confirmed is None:
            potential_matches.append(match_data)
        elif sim.is_confirmed:
            confirmed_matches.append(match_data)
        else:
            rejected_matches.append(match_data)

    # Get entities merged into this one
    merged_entities = db.query(ProjectEntity).filter(
        ProjectEntity.merged_into_id == entity.entity_id
    ).all()

    return {
        "entity_id": str(entity.entity_id),
        "type": entity.entity_type,
        "name": entity.name,
        "description": entity.description,
        "source_data": entity.source_data,
        "asset": {
            "asset_id": str(asset.asset_id) if asset else None,
            "name": asset.asset_name if asset else None,
            "type": asset.asset_type if asset else None,
        },
        "merged_into": str(entity.merged_into_id) if entity.merged_into_id else None,
        "potential_matches": potential_matches,
        "confirmed_matches": confirmed_matches,
        "rejected_matches": rejected_matches,
        "merged_entities": [
            {
                "entity_id": str(m.entity_id),
                "name": m.name,
                "asset_id": str(m.asset_id),
            }
            for m in merged_entities
        ],
    }


def _confirm_entity_match(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_a_id: str,
    entity_b_id: str,
    merge: bool = False,
) -> dict[str, Any]:
    """Confirm that two entities represent the same real-world thing."""
    # Verify both entities exist and belong to this project
    entity_a = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_a_id,
        ProjectEntity.project_id == project_id,
    ).first()

    entity_b = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_b_id,
        ProjectEntity.project_id == project_id,
    ).first()

    if not entity_a:
        return {"error": f"Entity not found: {entity_a_id}"}
    if not entity_b:
        return {"error": f"Entity not found: {entity_b_id}"}

    # Find or create similarity record
    similarity = db.query(EntitySimilarity).filter(
        or_(
            (EntitySimilarity.entity_a_id == entity_a_id) & (EntitySimilarity.entity_b_id == entity_b_id),
            (EntitySimilarity.entity_a_id == entity_b_id) & (EntitySimilarity.entity_b_id == entity_a_id),
        )
    ).first()

    if similarity:
        similarity.is_confirmed = True
        similarity.confirmed_by = "agent"
        similarity.confirmed_at = datetime.now(timezone.utc)
    else:
        # Create new similarity record if it doesn't exist
        similarity = EntitySimilarity(
            id=uuid4(),
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            similarity_score=1.0,  # User/agent confirmed = perfect match
            is_confirmed=True,
            confirmed_by="agent",
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(similarity)

    result = {
        "success": True,
        "entity_a": {"entity_id": entity_a_id, "name": entity_a.name},
        "entity_b": {"entity_id": entity_b_id, "name": entity_b.name},
        "confirmed": True,
    }

    if merge:
        # Merge entity_b into entity_a
        entity_b.merged_into_id = entity_a.entity_id
        result["merged"] = True
        result["primary_entity"] = entity_a_id

    db.commit()
    return result


def _reject_entity_match(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_a_id: str,
    entity_b_id: str,
) -> dict[str, Any]:
    """Mark that two entities are NOT the same thing."""
    # Verify both entities exist
    entity_a = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_a_id,
        ProjectEntity.project_id == project_id,
    ).first()

    entity_b = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_b_id,
        ProjectEntity.project_id == project_id,
    ).first()

    if not entity_a:
        return {"error": f"Entity not found: {entity_a_id}"}
    if not entity_b:
        return {"error": f"Entity not found: {entity_b_id}"}

    # Find or create similarity record
    similarity = db.query(EntitySimilarity).filter(
        or_(
            (EntitySimilarity.entity_a_id == entity_a_id) & (EntitySimilarity.entity_b_id == entity_b_id),
            (EntitySimilarity.entity_a_id == entity_b_id) & (EntitySimilarity.entity_b_id == entity_a_id),
        )
    ).first()

    if similarity:
        similarity.is_confirmed = False
        similarity.confirmed_by = "agent"
        similarity.confirmed_at = datetime.now(timezone.utc)
    else:
        # Create new record marking them as not matching
        similarity = EntitySimilarity(
            id=uuid4(),
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            similarity_score=0.0,
            is_confirmed=False,
            confirmed_by="agent",
            confirmed_at=datetime.now(timezone.utc),
        )
        db.add(similarity)

    db.commit()

    return {
        "success": True,
        "entity_a": {"entity_id": entity_a_id, "name": entity_a.name},
        "entity_b": {"entity_id": entity_b_id, "name": entity_b.name},
        "rejected": True,
    }


def _merge_entities(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_ids: list[str],
    name: str,
) -> dict[str, Any]:
    """Merge multiple entities into one named entity."""
    if len(entity_ids) < 2:
        return {"error": "Need at least 2 entities to merge"}

    # Verify all entities exist
    entities = []
    for eid in entity_ids:
        entity = db.query(ProjectEntity).filter(
            ProjectEntity.entity_id == eid,
            ProjectEntity.project_id == project_id,
        ).first()
        if not entity:
            return {"error": f"Entity not found: {eid}"}
        entities.append(entity)

    # First entity becomes the primary
    primary = entities[0]
    primary.name = name

    # Merge others into primary
    for entity in entities[1:]:
        entity.merged_into_id = primary.entity_id

        # Create/update similarity record as confirmed
        similarity = db.query(EntitySimilarity).filter(
            or_(
                (EntitySimilarity.entity_a_id == primary.entity_id) & (EntitySimilarity.entity_b_id == entity.entity_id),
                (EntitySimilarity.entity_a_id == entity.entity_id) & (EntitySimilarity.entity_b_id == primary.entity_id),
            )
        ).first()

        if similarity:
            similarity.is_confirmed = True
            similarity.confirmed_by = "agent"
            similarity.confirmed_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "success": True,
        "primary_entity": {
            "entity_id": str(primary.entity_id),
            "name": name,
        },
        "merged_count": len(entities) - 1,
        "merged_entities": [
            {"entity_id": str(e.entity_id), "original_name": e.name}
            for e in entities[1:]
        ],
    }


def _rename_entity(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_id: str,
    new_name: str,
) -> dict[str, Any]:
    """Rename an entity."""
    entity = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_id,
        ProjectEntity.project_id == project_id,
    ).first()

    if not entity:
        return {"error": f"Entity not found: {entity_id}"}

    old_name = entity.name
    entity.name = new_name
    db.commit()

    return {
        "success": True,
        "entity_id": str(entity.entity_id),
        "old_name": old_name,
        "new_name": new_name,
    }


def _find_entity_appearances(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    entity_id: str,
    include_unconfirmed_matches: bool = False,
) -> dict[str, Any]:
    """Find all assets where an entity (and its merged equivalents) appears."""
    entity = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id == entity_id,
        ProjectEntity.project_id == project_id,
    ).first()

    if not entity:
        return {"error": f"Entity not found: {entity_id}"}

    # Start with the main entity
    entity_ids_to_find = [entity.entity_id]

    # Add merged entities
    merged = db.query(ProjectEntity).filter(
        ProjectEntity.merged_into_id == entity.entity_id
    ).all()
    entity_ids_to_find.extend([m.entity_id for m in merged])

    # Optionally add unconfirmed matches
    if include_unconfirmed_matches:
        similarities = db.query(EntitySimilarity).filter(
            or_(
                EntitySimilarity.entity_a_id == entity.entity_id,
                EntitySimilarity.entity_b_id == entity.entity_id,
            ),
            EntitySimilarity.is_confirmed.is_(None),
            EntitySimilarity.similarity_score >= 0.75,  # Only high-confidence
        ).all()

        for sim in similarities:
            other_id = (
                sim.entity_b_id
                if str(sim.entity_a_id) == str(entity.entity_id)
                else sim.entity_a_id
            )
            if other_id not in entity_ids_to_find:
                entity_ids_to_find.append(other_id)

    # Get all entities and their assets
    all_entities = db.query(ProjectEntity).filter(
        ProjectEntity.entity_id.in_(entity_ids_to_find)
    ).all()

    appearances = []
    for ent in all_entities:
        asset = db.query(Assets).filter(
            Assets.asset_id == ent.asset_id
        ).first()

        if not asset:
            continue

        is_primary = str(ent.entity_id) == str(entity.entity_id)
        is_merged = ent.merged_into_id is not None
        is_potential = not is_primary and not is_merged

        appearances.append({
            "asset_id": str(asset.asset_id),
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "entity_id": str(ent.entity_id),
            "entity_name": ent.name,
            "source_data": ent.source_data,
            "match_type": "primary" if is_primary else ("merged" if is_merged else "potential"),
        })

    return {
        "entity_id": str(entity.entity_id),
        "entity_name": entity.name,
        "entity_type": entity.entity_type,
        "total_appearances": len(appearances),
        "include_unconfirmed": include_unconfirmed_matches,
        "appearances": appearances,
    }


# =============================================================================
# Edit Agent Tool Implementations
# =============================================================================


def _extract_operation_types(schema: dict) -> list[str]:
    """Extract all operation_type const values from a skill schema."""
    operation_types: list[str] = []

    items = schema.get("properties", {}).get("operations", {}).get("items", {})

    # Direct case: items has properties with operation_type const
    if "properties" in items:
        op_type = items.get("properties", {}).get("operation_type", {}).get("const")
        if op_type:
            operation_types.append(op_type)

    # anyOf case: items contains anyOf with multiple operation types
    if "anyOf" in items:
        for variant in items["anyOf"]:
            op_type = variant.get("properties", {}).get("operation_type", {}).get("const")
            if op_type and op_type not in operation_types:
                operation_types.append(op_type)

    return operation_types


def _generate_example_patch(schema: dict, operation_type: str) -> dict:
    """Generate an example patch for a given operation_type based on schema."""
    # Find the operation_data schema for this operation_type
    items = schema.get("properties", {}).get("operations", {}).get("items", {})
    op_data_schema: dict = {}

    # Direct case
    if "properties" in items:
        if items.get("properties", {}).get("operation_type", {}).get("const") == operation_type:
            op_data_schema = items.get("properties", {}).get("operation_data", {})
    # anyOf case
    elif "anyOf" in items:
        for variant in items["anyOf"]:
            if variant.get("properties", {}).get("operation_type", {}).get("const") == operation_type:
                op_data_schema = variant.get("properties", {}).get("operation_data", {})
                break

    # Build example operation_data from required fields
    example_data: dict = {}
    required_fields = op_data_schema.get("required", [])
    props = op_data_schema.get("properties", {})

    for field in required_fields:
        field_schema = props.get(field, {})
        field_type = field_schema.get("type", "string")
        if field_type == "integer":
            example_data[field] = 0
        elif field_type == "number":
            example_data[field] = 0.0
        elif field_type == "string":
            example_data[field] = "<value>"
        elif field_type == "boolean":
            example_data[field] = True
        else:
            example_data[field] = "<value>"

    return {
        "description": "Describe what this edit does",
        "operations": [
            {
                "operation_type": operation_type,
                "operation_data": example_data,
            }
        ],
    }


def _skills_registry(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    action: str,
    skill_id: str | None = None,
) -> dict[str, Any]:
    from .skills_registry import list_skills, read_skill

    if action == "list":
        skills = list_skills()
        return {
            "usage_note": (
                "IMPORTANT: Skill IDs (e.g., 'cuts.insert') are NOT operation_types. "
                "After reading a skill's schema, use the operation_type value from the schema's "
                "'const' field (e.g., 'add_clip', 'trim_clip'). "
                "Use action='read' with a full subskill ID to get the exact schema."
            ),
            "skills": [
                {
                    "id": s.id,
                    "title": s.title,
                    "summary": s.summary,
                    "category": getattr(s, "category", "editing"),
                    "complexity": getattr(s, "complexity", "moderate"),
                    "subskills": [
                        {
                            "id": sub.id,
                            "title": sub.title,
                            "summary": sub.summary,
                            "complexity": getattr(sub, "complexity", "moderate"),
                        }
                        for sub in s.subskills
                    ],
                }
                for s in skills
            ],
        }
    if action == "read":
        if not skill_id:
            return {"error": "skill_id required for read"}

        # Check if this is a parent skill ID (no dot separator)
        if "." not in skill_id:
            skill = read_skill(skill_id)
            if not skill:
                return {"error": f"Skill not found: {skill_id}"}
            # Return all subskills with schemas and operation_type hints
            example_id = skill.subskills[0].id if skill.subskills else f"{skill_id}.xxx"

            subskills_with_usage = []
            for sub in skill.subskills:
                op_types = _extract_operation_types(sub.schema)
                primary_op = op_types[0] if op_types else None
                subskills_with_usage.append({
                    "id": sub.id,
                    "title": sub.title,
                    "summary": sub.summary,
                    "schema": sub.schema,
                    "complexity": getattr(sub, "complexity", "moderate"),
                    "prerequisites": getattr(sub, "prerequisites", []),
                    "common_errors": getattr(sub, "common_errors", []),
                    "tips": getattr(sub, "tips", []),
                    "examples": getattr(sub, "examples", []),
                    "steps": getattr(sub, "steps", []),
                    "operation_types": op_types,
                    "primary_operation_type": primary_op,
                    "usage_warning": (
                        f"Use operation_type='{primary_op}', NOT '{sub.id}'"
                        if primary_op
                        else "No operation_type defined for this subskill."
                    ),
                })

            return {
                "id": skill.id,
                "title": skill.title,
                "summary": skill.summary,
                "category": getattr(skill, "category", "editing"),
                "complexity": getattr(skill, "complexity", "moderate"),
                "hint": (
                    f"You requested parent skill '{skill_id}'. "
                    f"To get the patch schema, use the full subskill ID "
                    f"(e.g., skill_id='{example_id}'). "
                    f"CRITICAL: use the operation_type from the schema (e.g., 'add_clip'), "
                    f"NOT the skill ID (e.g., 'cuts.insert')."
                ),
                "subskills": subskills_with_usage,
            }

        # Full subskill ID provided
        parent_id = skill_id.split(".")[0]
        skill = read_skill(parent_id)
        if not skill:
            return {"error": f"Skill not found: {parent_id}"}
        sub = next((s for s in skill.subskills if s.id == skill_id), None)
        if not sub:
            available = [s.id for s in skill.subskills]
            return {
                "error": f"Subskill '{skill_id}' not found.",
                "available_subskills": available,
            }

        # Extract operation_types and generate example
        operation_types = _extract_operation_types(sub.schema)
        primary_op_type = operation_types[0] if operation_types else None
        example_patch = (
            _generate_example_patch(sub.schema, primary_op_type)
            if primary_op_type
            else None
        )

        return {
            "id": skill.id,
            "title": skill.title,
            "summary": skill.summary,
            "subskill": {
                "id": sub.id,
                "title": sub.title,
                "summary": sub.summary,
                "complexity": getattr(sub, "complexity", "moderate"),
                "prerequisites": getattr(sub, "prerequisites", []),
                "schema": sub.schema,
            },
            "USAGE": {
                "operation_types_to_use": operation_types,
                "primary_operation_type": primary_op_type,
                "warning": (
                    f"Use operation_type='{primary_op_type}' in your patch, "
                    f"NOT operation_type='{skill_id}'. The skill ID is only for "
                    f"looking up the schema; it is NOT a valid operation_type."
                    if primary_op_type
                    else "No operation_type defined for this subskill."
                ),
                "example_patch": example_patch,
            },
            "common_errors": getattr(sub, "common_errors", []),
            "tips": getattr(sub, "tips", []),
            "examples": getattr(sub, "examples", []),
            "steps": getattr(sub, "steps", []),
        }
    return {"error": f"Unknown action: {action}"}


def _get_timeline_snapshot(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    version: int | None = None,
) -> dict[str, Any]:
    snapshot = get_timeline_snapshot(db, UUID(timeline_id), version)
    timeline = snapshot.timeline
    tracks_summary: list[dict[str, Any]] = []

    for track_index, track in enumerate(timeline.tracks.children):
        if not isinstance(track, Track):
            tracks_summary.append(
                {
                    "track_index": track_index,
                    "name": getattr(track, "name", ""),
                    "kind": "unknown",
                    "items": [],
                }
            )
            continue

        items_summary: list[dict[str, Any]] = []
        for item_index, item in enumerate(track.children):
            entry: dict[str, Any] = {"index": item_index}

            if isinstance(item, Clip):
                entry["item_type"] = "clip"
                entry["name"] = item.name
                entry["source_range"] = _format_time_range(item.source_range)
                entry["duration_ms"] = item.duration.to_milliseconds()
                reference = item.media_reference
                if isinstance(reference, ExternalReference):
                    entry["reference_type"] = "external"
                    entry["asset_id"] = str(reference.asset_id)
                elif isinstance(reference, GeneratorReference):
                    entry["reference_type"] = "generator"
                    entry["generator_kind"] = reference.generator_kind
                elif isinstance(reference, MissingReference):
                    entry["reference_type"] = "missing"

            elif isinstance(item, Gap):
                entry["item_type"] = "gap"
                entry["duration_ms"] = item.duration.to_milliseconds()

            elif isinstance(item, Transition):
                entry["item_type"] = "transition"
                entry["transition_type"] = item.transition_type.value
                entry["duration_ms"] = item.duration.to_milliseconds()

            elif isinstance(item, Stack):
                entry["item_type"] = "stack"
                entry["name"] = item.name
                entry["child_count"] = len(item.children)

            else:
                entry["item_type"] = type(item).__name__

            items_summary.append(entry)

        tracks_summary.append(
            {
                "track_index": track_index,
                "name": track.name,
                "kind": track.kind.value,
                "items": items_summary,
            }
        )

    return {
        "version": snapshot.version,
        "timeline_name": timeline.name,
        "default_rate": timeline.metadata.get("default_rate", 24.0),
        "tracks": tracks_summary,
    }


def _compare_timeline_versions(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    version_before: int,
    version_after: int,
) -> dict[str, Any]:
    diff = diff_versions(
        db=db,
        timeline_id=UUID(timeline_id),
        from_version=version_before,
        to_version=version_after,
    )
    return diff.model_dump()


def _edit_timeline(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    patch: dict[str, Any],
    apply: bool = True,
    rollback_on_error: bool = True,
) -> dict[str, Any]:
    try:
        patch_model = EditPatch.model_validate(patch)
    except ValidationError as exc:
        return {"error": str(exc)}

    if not patch_model.operations:
        return {
            "applied": False,
            "new_version": None,
            "operations_applied": 0,
            "warnings": ["Patch contains no operations."],
        }

    snapshot = get_timeline_snapshot(db, UUID(timeline_id))
    normalized = _normalize_patch(patch_model, snapshot.timeline.metadata)

    if not apply:
        return {
            "applied": False,
            "new_version": snapshot.version,
            "operations_applied": 0,
            "warnings": ["apply=false; patch was not applied."],
            "patch": normalized.model_dump(),
        }

    result = execute_patch(
        db=db,
        timeline_id=UUID(timeline_id),
        patch=normalized,
        actor="agent:edit_agent",
        starting_version=int(snapshot.version),
        stop_on_error=True,
        rollback_on_error=rollback_on_error,
    )

    warnings: list[str] = []
    if result.errors:
        warnings.append("Patch was only partially applied.")

    response = {
        "applied": result.success,
        "new_version": result.final_version,
        "operations_applied": result.successful_operations,
        "errors": result.errors,
    }
    if result.rolled_back:
        response["rolled_back"] = True
        response["rollback_version"] = result.rollback_version
        response["rollback_target_version"] = result.rollback_target_version
    if warnings:
        response["warnings"] = warnings
    return response


def _undo_to_version(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    target_version: int,
    reason: str | None = None,
) -> dict[str, Any]:
    snapshot = get_timeline_snapshot(db, UUID(timeline_id))
    current_version = int(snapshot.version)

    if target_version >= current_version:
        return {
            "error": (
                f"Target version {target_version} must be less than current version "
                f"{current_version}."
            )
        }
    if target_version < 0:
        return {"error": "Target version must be >= 0."}

    checkpoint = rollback_to_version(
        db=db,
        timeline_id=UUID(timeline_id),
        target_version=target_version,
        rollback_by=f"agent:{user_id}",
        expected_version=current_version,
    )

    return {
        "success": True,
        "previous_version": current_version,
        "restored_version": target_version,
        "new_version": int(checkpoint.version),
        "reason": reason,
        "message": (
            f"Timeline restored to version {target_version}. "
            "All changes after that version were discarded."
        ),
    }


def _view_asset(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    asset_id: str,
    t0_ms: float | None = None,
    t1_ms: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """View an asset with visual content embedded for direct viewing by the agent."""
    asset = (
        db.query(Assets)
        .filter(Assets.project_id == project_id, Assets.asset_id == asset_id)
        .first()
    )
    if not asset:
        return {"error": f"Asset not found: {asset_id}"}

    asset_url = str(getattr(asset, "asset_url", "") or "")
    signed_url = _resolve_asset_signed_url(asset_url)
    content_type = asset.asset_type or "video/mp4"

    result: dict[str, Any] = {
        "asset_id": str(asset.asset_id),
        "asset_name": asset.asset_name,
        "asset_type": content_type,
        "t0_ms": t0_ms,
        "t1_ms": t1_ms,
        "reason": reason,
    }

    # Include cached analysis metadata as context
    if asset.indexing_status == "completed":
        result["metadata"] = {
            "summary": asset.asset_summary,
            "tags": asset.asset_tags,
            "transcript": asset.asset_transcript,
            "events": asset.asset_events,
            "notable_shots": asset.notable_shots,
            "faces": asset.asset_faces,
            "scenes": asset.asset_scenes,
        }

    # Download content
    if not signed_url:
        result["visual_content_included"] = False
        result["visual_error"] = "No URL available for asset"
        return result

    content = _download_url_bytes(signed_url, timeout_seconds=120)
    if content is None:
        result["visual_content_included"] = False
        result["visual_error"] = "Failed to download asset content"
        return result

    # Determine media type
    if content_type.startswith("video/"):
        media_type = "video"
    elif content_type.startswith("image/"):
        media_type = "image"
    else:
        result["visual_content_included"] = False
        result["visual_error"] = f"Unsupported content type: {content_type}"
        return result

    # For video, check duration and handle chunking
    content_to_embed = content
    if media_type == "video":
        duration = get_video_duration(content, content_type)
        result["duration_seconds"] = duration

        # Handle time range request
        if t0_ms is not None or t1_ms is not None:
            start_sec = (t0_ms or 0) / 1000.0
            if t1_ms is not None:
                duration_sec = (t1_ms - (t0_ms or 0)) / 1000.0
            else:
                duration_sec = min(
                    MAX_VIDEO_DURATION_SECONDS,
                    (duration or MAX_VIDEO_DURATION_SECONDS) - start_sec,
                )

            duration_sec = min(duration_sec, MAX_VIDEO_DURATION_SECONDS)

            segment = extract_video_segment(content, start_sec, duration_sec, content_type)
            if segment:
                content_to_embed = segment
                result["segment_extracted"] = True
                result["segment_start_ms"] = start_sec * 1000
                result["segment_duration_ms"] = duration_sec * 1000
            else:
                result["segment_extraction_failed"] = True

        # If no range specified but video is too long, extract first chunk
        elif duration and duration > MAX_VIDEO_DURATION_SECONDS:
            segment = extract_video_segment(content, 0, MAX_VIDEO_DURATION_SECONDS, content_type)
            if segment:
                content_to_embed = segment
                result["chunked"] = True
                result["chunk_start_ms"] = 0
                result["chunk_duration_ms"] = MAX_VIDEO_DURATION_SECONDS * 1000
                result["total_duration_ms"] = duration * 1000
                result["remaining_duration_ms"] = (duration - MAX_VIDEO_DURATION_SECONDS) * 1000
                result["chunk_message"] = (
                    f"Video is {duration / 60:.1f} minutes long. Showing first 40 minutes. "
                    f"Call view_asset again with t0_ms={int(MAX_VIDEO_DURATION_SECONDS * 1000)} to see more."
                )
            else:
                result["chunk_extraction_failed"] = True

    # Embed the content as base64
    b64_data = base64.b64encode(content_to_embed).decode("utf-8")
    result["_multimodal"] = {
        "type": media_type,
        "content_type": content_type,
        "data": b64_data,
    }
    result["visual_content_included"] = True
    result["size_bytes"] = len(content_to_embed)

    return result


def _coerce_render_preset(preset: dict[str, Any]) -> RenderPreset:
    if "video" in preset or "audio" in preset:
        if "name" not in preset:
            preset = {**preset, "name": "Preview"}
        return RenderPreset.model_validate(preset)

    name = preset.get("name") or "Preview"
    quality = preset.get("quality", "standard")

    video_settings: dict[str, Any] = {}
    for key in ("width", "height", "framerate", "bitrate", "crf", "preset"):
        if key in preset:
            video_settings[key] = preset[key]

    audio_settings: dict[str, Any] = {}
    if "audio_bitrate" in preset:
        audio_settings["bitrate"] = preset["audio_bitrate"]
    if "audio_sample_rate" in preset:
        audio_settings["sample_rate"] = preset["audio_sample_rate"]
    if "audio_channels" in preset:
        audio_settings["channels"] = preset["audio_channels"]

    normalized = {
        "name": name,
        "quality": quality,
        "video": video_settings,
        "audio": audio_settings,
        "use_gpu": preset.get("use_gpu", False),
    }
    return RenderPreset.model_validate(normalized)


def _render_output(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    timeline_version: int | None = None,
    preset: dict[str, Any] | None = None,
    wait: bool = True,
    wait_timeout_seconds: int | None = None,
    poll_interval_seconds: float | None = None,
) -> dict[str, Any]:
    render_preset = _coerce_render_preset(preset) if preset else None
    request = RenderRequest(
        job_type=RenderJobType.PREVIEW,
        timeline_version=timeline_version,
        preset=render_preset,
        metadata={},
    )
    job = create_render_job(db, UUID(project_id), request, created_by=f"agent:{user_id}")
    job_id = UUID(str(job.job_id))
    job = dispatch_render_job(db, job_id)

    if wait:
        if wait_timeout_seconds is None:
            wait_timeout_seconds = DEFAULT_RENDER_WAIT_SECONDS
        if wait_timeout_seconds is not None and wait_timeout_seconds <= 0:
            wait_timeout_seconds = None
        if poll_interval_seconds is None or poll_interval_seconds <= 0:
            poll_interval_seconds = 3.0

        start_time = time.monotonic()
        while True:
            job = poll_job_status(db, job_id) or job
            if job.status in (
                RenderJobStatus.COMPLETED.value,
                RenderJobStatus.FAILED.value,
                RenderJobStatus.CANCELLED.value,
            ):
                break

            output_url = _resolve_output_url(project_id, job)
            if output_url:
                signed_url = _maybe_sign_url(output_url)
                if signed_url:
                    check = _check_url(signed_url, 10)
                    if check.get("reachable"):
                        job = update_job_status(
                            db,
                            job_id,
                            RenderJobStatus.COMPLETED,
                            output_url=output_url,
                        ) or job
                        break

            if wait_timeout_seconds is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= wait_timeout_seconds:
                    break

            time.sleep(poll_interval_seconds)

    output_url = _resolve_output_url(project_id, job)
    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "output_url": output_url,
        "timeline_version": job.timeline_version,
    }


def _view_render_output(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    job_id: str | None = None,
    timeline_version: int | None = None,
    t0_ms: float | None = None,
    t1_ms: float | None = None,
) -> dict[str, Any]:
    """View a render output with visual content embedded for direct viewing."""
    resolved = _resolve_render_output(
        db=db,
        project_id=project_id,
        timeline_id=timeline_id,
        job_id=job_id,
        timeline_version=timeline_version,
    )
    if resolved.get("error"):
        return resolved

    signed_url = resolved.get("signed_url")
    if not signed_url:
        return {
            **resolved,
            "visual_content_included": False,
            "visual_error": "Unable to resolve signed URL for render output",
        }

    # Check reachability
    check = _check_url(signed_url, timeout_seconds=30)
    if not check.get("reachable"):
        return {
            **resolved,
            "visual_content_included": False,
            "visual_error": "Render output not reachable",
            "reachability_check": check,
        }

    # Update job status if needed
    if resolved.get("job_id") and not resolved.get("ready"):
        try:
            update_job_status(
                db,
                UUID(str(resolved["job_id"])),
                RenderJobStatus.COMPLETED,
                output_url=resolved.get("output_url"),
            )
        except Exception:
            pass

    # Download the render output
    content = _download_url_bytes(signed_url, timeout_seconds=120)
    if content is None:
        return {
            **resolved,
            "visual_content_included": False,
            "visual_error": "Failed to download render output",
        }

    content_type = check.get("content_type") or "video/mp4"

    # Build result
    result: dict[str, Any] = {
        "job_id": resolved.get("job_id"),
        "status": "completed",
        "timeline_version": resolved.get("timeline_version"),
        "content_type": content_type,
    }

    # Check duration and handle chunking
    content_to_embed = content
    duration = get_video_duration(content, content_type)
    result["duration_seconds"] = duration

    # Handle time range request
    if t0_ms is not None or t1_ms is not None:
        start_sec = (t0_ms or 0) / 1000.0
        if t1_ms is not None:
            duration_sec = (t1_ms - (t0_ms or 0)) / 1000.0
        else:
            duration_sec = min(
                MAX_VIDEO_DURATION_SECONDS,
                (duration or MAX_VIDEO_DURATION_SECONDS) - start_sec,
            )

        duration_sec = min(duration_sec, MAX_VIDEO_DURATION_SECONDS)

        segment = extract_video_segment(content, start_sec, duration_sec, content_type)
        if segment:
            content_to_embed = segment
            result["segment_extracted"] = True
            result["segment_start_ms"] = start_sec * 1000
            result["segment_duration_ms"] = duration_sec * 1000
        else:
            result["segment_extraction_failed"] = True

    # If video is too long, extract first chunk
    elif duration and duration > MAX_VIDEO_DURATION_SECONDS:
        segment = extract_video_segment(content, 0, MAX_VIDEO_DURATION_SECONDS, content_type)
        if segment:
            content_to_embed = segment
            result["chunked"] = True
            result["chunk_start_ms"] = 0
            result["chunk_duration_ms"] = MAX_VIDEO_DURATION_SECONDS * 1000
            result["total_duration_ms"] = duration * 1000
            result["remaining_duration_ms"] = (duration - MAX_VIDEO_DURATION_SECONDS) * 1000
            result["chunk_message"] = (
                f"Render is {duration / 60:.1f} minutes long. Showing first 40 minutes. "
                f"Call view_render_output again with t0_ms={int(MAX_VIDEO_DURATION_SECONDS * 1000)} to see more."
            )
        else:
            result["chunk_extraction_failed"] = True

    # Embed the video content
    b64_data = base64.b64encode(content_to_embed).decode("utf-8")

    result["_multimodal"] = {
        "type": "video",
        "content_type": content_type,
        "data": b64_data,
    }
    result["visual_content_included"] = True
    result["size_bytes"] = len(content_to_embed)

    return result


def _run_quality_checks(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    job_id: str,
    checks: list[str] | None = None,
) -> dict[str, Any]:
    resolved = _resolve_render_output(
        db=db,
        project_id=project_id,
        timeline_id=timeline_id,
        job_id=job_id,
    )
    if resolved.get("error"):
        return resolved

    status = resolved.get("status")
    if status and status not in {"completed", RenderJobStatus.COMPLETED.value}:
        return {
            "error": "Render job is not completed yet",
            "status": status,
            "job_id": resolved.get("job_id"),
        }

    signed_url = resolved.get("signed_url")
    if not signed_url:
        return {"error": "Unable to resolve signed URL for render output"}

    content = _download_url_bytes(signed_url, timeout_seconds=120)
    if content is None:
        return {"error": "Failed to download render output"}

    checks_to_run = checks or ["all"]
    run_all = "all" in checks_to_run

    results: dict[str, Any] = {
        "job_id": job_id,
        "status": resolved.get("status"),
        "timeline_version": resolved.get("timeline_version"),
        "checks_run": [],
        "issues_detected": [],
        "metrics": {},
    }

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
        temp_file.write(content)
        temp_path = temp_file.name

    try:
        if run_all or "audio_levels" in checks_to_run:
            results["checks_run"].append("audio_levels")
            loudness = _analyze_loudness(temp_path)
            results["metrics"]["loudness"] = loudness
            if loudness.get("error"):
                results["issues_detected"].append(loudness["error"])
            else:
                integrated = loudness.get("integrated_lufs")
                true_peak = loudness.get("true_peak_db")
                if integrated is not None and integrated < -24:
                    results["issues_detected"].append(
                        f"Audio may be too quiet (LUFS {integrated:.1f})."
                    )
                if true_peak is not None and true_peak > -1:
                    results["issues_detected"].append(
                        f"Audio may be clipping (true peak {true_peak:.1f} dB)."
                    )

        if run_all or "black_frames" in checks_to_run:
            results["checks_run"].append("black_frames")
            black_frames = _detect_black_frames(temp_path)
            results["metrics"]["black_frames"] = black_frames
            segments = black_frames.get("segments") if isinstance(black_frames, dict) else None
            if segments:
                for segment in segments[:5]:
                    results["issues_detected"].append(
                        "Black frames detected: "
                        f"{segment['start_ms']:.0f}ms - {segment['end_ms']:.0f}ms"
                    )

        if run_all or "sync" in checks_to_run:
            results["checks_run"].append("sync")
            sync_check = _check_av_sync(temp_path)
            results["metrics"]["sync"] = sync_check
            offset_ms = sync_check.get("offset_ms") if isinstance(sync_check, dict) else None
            if offset_ms is not None and abs(offset_ms) > 100:
                results["issues_detected"].append(
                    f"Possible A/V duration mismatch (~{offset_ms:.0f}ms)."
                )

    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass

    results["passed"] = len(results["issues_detected"]) == 0
    results["summary"] = (
        "All checks passed" if results["passed"] else f"{len(results['issues_detected'])} issue(s) detected"
    )
    return results


# =============================================================================
# Helper Functions
# =============================================================================


def _default_render_url(project_id: str, output_filename: str | None) -> str | None:
    if not output_filename:
        return None
    bucket = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")
    return f"gs://{bucket}/{project_id}/renders/{output_filename}"


def _resolve_output_url(project_id: str, job: RenderJob) -> str | None:
    output_url_value = getattr(job, "output_url", None)
    if output_url_value is not None:
        return str(output_url_value)
    output_filename_value = getattr(job, "output_filename", None)
    output_filename = (
        str(output_filename_value) if output_filename_value is not None else None
    )
    return _default_render_url(project_id, output_filename)


def _maybe_sign_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = parse_gcs_url(url)
    if not parsed:
        return url
    bucket, blob = parsed
    return generate_signed_url(bucket, blob, expiration=timedelta(hours=1))


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value))


def _resolve_asset_signed_url(asset_url: str | None) -> str | None:
    if not asset_url:
        return None
    cleaned = asset_url.strip()
    if not cleaned:
        return None
    parsed = parse_gcs_url(cleaned)
    if parsed:
        bucket, blob = parsed
        return generate_signed_url(bucket, blob, expiration=timedelta(hours=1))
    if _looks_like_url(cleaned):
        return cleaned
    bucket = os.getenv("GCS_BUCKET", "video-editor")
    return generate_signed_url(bucket, cleaned, expiration=timedelta(hours=1))


def _resolve_render_output(
    db: Session,
    project_id: str,
    timeline_id: str,
    job_id: str | None = None,
    timeline_version: int | None = None,
    output_url: str | None = None,
) -> dict[str, Any]:
    if output_url:
        return {
            "output_url": output_url,
            "signed_url": _maybe_sign_url(output_url),
            "ready": False,
        }

    query = db.query(RenderJob).filter(
        RenderJob.project_id == UUID(project_id),
        RenderJob.timeline_id == UUID(timeline_id),
    )

    job = None
    if job_id:
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return {"error": f"Invalid job_id: {job_id}"}
        job = query.filter(RenderJob.job_id == job_uuid).first()
    elif timeline_version is not None:
        job = _get_latest_render_job(query, timeline_version)
    else:
        job = _get_latest_render_job(query, None)

    if not job:
        return {"error": "Render job not found"}

    if job.status in (
        RenderJobStatus.QUEUED.value,
        RenderJobStatus.PROCESSING.value,
    ):
        job = poll_job_status(db, job.job_id) or job

    status = str(job.status)
    resolved_output_url = _resolve_output_url(project_id, job)

    ready = status == RenderJobStatus.COMPLETED.value
    signed_url = _maybe_sign_url(resolved_output_url) if resolved_output_url else None

    return {
        "job_id": str(job.job_id),
        "status": status,
        "timeline_version": job.timeline_version,
        "output_url": resolved_output_url,
        "signed_url": signed_url,
        "ready": ready,
    }


def _get_latest_render_job(query, timeline_version: int | None) -> RenderJob | None:
    filtered = query
    if timeline_version is not None:
        filtered = filtered.filter(RenderJob.timeline_version == timeline_version)

    completed = (
        filtered.filter(RenderJob.status == RenderJobStatus.COMPLETED.value)
        .order_by(RenderJob.completed_at.desc().nullslast(), RenderJob.created_at.desc())
        .first()
    )
    if completed:
        return completed

    return filtered.order_by(RenderJob.created_at.desc()).first()


def _check_url(url: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        request = urllib.request.Request(
            url, method="GET", headers={"Range": "bytes=0-0"}
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_range = response.headers.get("Content-Range")
            content_length = response.headers.get("Content-Length")
            total_length = None
            if content_range and "/" in content_range:
                total_length = content_range.split("/")[-1]
            return {
                "reachable": response.status in {200, 206},
                "status_code": response.status,
                "content_type": response.headers.get("Content-Type"),
                "content_length": total_length or content_length,
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": False,
            "status_code": exc.code,
            "error": str(exc),
        }
    except Exception as exc:
        return {"reachable": False, "error": str(exc)}


def _download_url_bytes(url: str, timeout_seconds: int) -> bytes | None:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except Exception:
        return None


def _resolve_binary(env_key: str, default: str) -> str:
    return os.getenv(env_key, default) or default


def _run_command(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except FileNotFoundError:
        return {"error": f"Binary not found: {command[0]}"}
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out"}
    except Exception as exc:
        return {"error": str(exc)}


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _analyze_loudness(video_path: str) -> dict[str, Any]:
    ffmpeg_bin = _resolve_binary("FFMPEG_BIN", "ffmpeg")
    command = [
        ffmpeg_bin,
        "-i",
        video_path,
        "-af",
        "loudnorm=print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = _run_command(command, timeout_seconds=60)
    if result.get("error"):
        return {"error": result["error"]}
    if result.get("returncode") not in {0, None}:
        stderr = result.get("stderr", "")
        return {"error": "Loudness analysis failed", "details": stderr[-500:]}

    stderr = result.get("stderr", "")
    match = re.search(r"\{[\s\S]*\}", stderr)
    if not match:
        return {"error": "Unable to parse loudnorm output"}

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"error": "Invalid loudnorm JSON output"}

    integrated = _safe_float(data.get("output_i") or data.get("input_i"))
    true_peak = _safe_float(data.get("output_tp") or data.get("input_tp"))
    lra = _safe_float(data.get("output_lra") or data.get("input_lra"))

    return {
        "integrated_lufs": integrated,
        "true_peak_db": true_peak,
        "lra": lra,
    }


def _detect_black_frames(video_path: str) -> dict[str, Any]:
    ffmpeg_bin = _resolve_binary("FFMPEG_BIN", "ffmpeg")
    command = [
        ffmpeg_bin,
        "-i",
        video_path,
        "-vf",
        "blackdetect=d=0.1:pix_th=0.10",
        "-f",
        "null",
        "-",
    ]
    result = _run_command(command, timeout_seconds=120)
    if result.get("error"):
        return {"error": result["error"]}

    stderr = result.get("stderr", "")
    pattern = re.compile(
        r"black_start:(?P<start>\d+(?:\.\d+)?)\s+"
        r"black_end:(?P<end>\d+(?:\.\d+)?)\s+"
        r"black_duration:(?P<duration>\d+(?:\.\d+)?)"
    )

    segments: list[dict[str, Any]] = []
    total_black_ms = 0.0
    for match in pattern.finditer(stderr):
        start = float(match.group("start"))
        end = float(match.group("end"))
        duration = float(match.group("duration"))
        segments.append(
            {
                "start_ms": start * 1000.0,
                "end_ms": end * 1000.0,
                "duration_ms": duration * 1000.0,
            }
        )
        total_black_ms += duration * 1000.0

    return {
        "segments": segments,
        "total_black_ms": total_black_ms,
    }


def _probe_stream_duration(video_path: str, stream_selector: str) -> float | None:
    ffprobe_bin = _resolve_binary("FFPROBE_BIN", "ffprobe")
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        stream_selector,
        "-show_entries",
        "stream=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = _run_command(command, timeout_seconds=30)
    if result.get("error"):
        return None
    if result.get("returncode") not in {0, None}:
        return None
    return _safe_float(result.get("stdout", "").strip())


def _check_av_sync(video_path: str) -> dict[str, Any]:
    video_duration = _probe_stream_duration(video_path, "v:0")
    audio_duration = _probe_stream_duration(video_path, "a:0")

    if video_duration is None or audio_duration is None:
        return {
            "error": "Unable to determine audio/video durations",
            "video_duration": video_duration,
            "audio_duration": audio_duration,
        }

    offset_ms = (video_duration - audio_duration) * 1000.0
    return {
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "offset_ms": offset_ms,
    }


def _format_time_range(time_range: TimeRange) -> dict[str, float]:
    start_ms, duration_ms = time_range.to_milliseconds()
    return {
        "start_ms": start_ms,
        "duration_ms": duration_ms,
        "end_ms": start_ms + duration_ms,
    }


def _normalize_patch(patch: EditPatch, metadata: dict[str, Any]) -> EditPatch:
    safe_metadata = metadata or {}
    rate = _get_default_rate(safe_metadata)
    normalized_ops = [_normalize_operation(op, rate) for op in patch.operations]
    return EditPatch(description=patch.description, operations=normalized_ops)


def _normalize_operation(operation, rate: float):
    data = dict(operation.operation_data)
    op_type = operation.operation_type

    if op_type == "trim_clip":
        if "new_source_range" not in data:
            start_ms = data.pop("start_ms", None)
            end_ms = data.pop("end_ms", None)
            duration_ms = data.pop("duration_ms", None)
            if start_ms is not None and end_ms is not None:
                new_range = TimeRange.from_milliseconds(
                    start_ms, end_ms - start_ms, rate
                )
                data["new_source_range"] = new_range.model_dump()
            elif start_ms is not None and duration_ms is not None:
                new_range = TimeRange.from_milliseconds(start_ms, duration_ms, rate)
                data["new_source_range"] = new_range.model_dump()

    elif op_type == "add_clip":
        if "source_range" not in data:
            start_ms = data.pop("source_start_ms", None)
            end_ms = data.pop("source_end_ms", None)
            duration_ms = data.pop("duration_ms", None)
            if start_ms is not None and end_ms is not None:
                source_range = TimeRange.from_milliseconds(
                    start_ms, end_ms - start_ms, rate
                )
                data["source_range"] = source_range.model_dump()
            elif start_ms is not None and duration_ms is not None:
                source_range = TimeRange.from_milliseconds(start_ms, duration_ms, rate)
                data["source_range"] = source_range.model_dump()

    elif op_type == "add_generator_clip":
        if "source_range" not in data:
            start_ms = data.pop("start_ms", None)
            end_ms = data.pop("end_ms", None)
            duration_ms = data.pop("duration_ms", None)
            if start_ms is not None and end_ms is not None:
                source_range = TimeRange.from_milliseconds(
                    start_ms, end_ms - start_ms, rate
                )
                data["source_range"] = source_range.model_dump()
            elif start_ms is not None and duration_ms is not None:
                source_range = TimeRange.from_milliseconds(start_ms, duration_ms, rate)
                data["source_range"] = source_range.model_dump()

    elif op_type == "split_clip":
        if "split_offset" not in data and "split_ms" in data:
            split_offset = RationalTime.from_milliseconds(data.pop("split_ms"), rate)
            data["split_offset"] = split_offset.model_dump()

    elif op_type == "slip_clip":
        if "offset" not in data and "offset_ms" in data:
            offset = RationalTime.from_milliseconds(data.pop("offset_ms"), rate)
            data["offset"] = offset.model_dump()

    elif op_type == "add_transition":
        if "in_offset" not in data or "out_offset" not in data:
            duration_ms = data.pop("duration_ms", None)
            if duration_ms is not None:
                duration_frames = (duration_ms / 1000.0) * rate
                half = RationalTime.from_frames(duration_frames / 2, rate)
                data["in_offset"] = half.model_dump()
                data["out_offset"] = half.model_dump()

    elif op_type == "adjust_gap_duration":
        if "new_duration" not in data and "duration_ms" in data:
            new_duration = RationalTime.from_milliseconds(data.pop("duration_ms"), rate)
            data["new_duration"] = new_duration.model_dump()

    elif op_type == "move_clip":
        if "from_track" not in data and "track_index" in data:
            data["from_track"] = data.pop("track_index")
        if "from_index" not in data and "clip_index" in data:
            data["from_index"] = data.pop("clip_index")
        if "to_track" not in data and "from_track" in data:
            data["to_track"] = data["from_track"]

    elif op_type == "replace_clip_media":
        if "new_asset_id" not in data and "asset_id" in data:
            data["new_asset_id"] = data.pop("asset_id")

    elif op_type == "add_effect":
        if "item_index" not in data and "clip_index" in data:
            data["item_index"] = data.pop("clip_index")

    return EditOperation(operation_type=op_type, operation_data=data)


def _get_default_rate(metadata: dict[str, Any]) -> float:
    rate = metadata.get("default_rate", 24.0)
    try:
        return float(rate)
    except (TypeError, ValueError):
        return 24.0
