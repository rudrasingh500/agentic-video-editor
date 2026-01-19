"""Tool definitions for the Edit Orchestrator.

The orchestrator has access to tools for:
1. Reading timeline state and history
2. Searching for assets (via asset_retrieval agent)
3. Dispatching to sub-agents
4. Viewing video content (assets and rendered segments)
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session as DBSession

from agent.asset_retrieval import find_assets
from database.models import Assets, RenderJob, VideoOutput
from operators.timeline_operator import (
    get_timeline_by_project,
    get_timeline_snapshot,
    list_checkpoints,
)
from utils.gcs_utils import download_file

from .sub_agents import (
    AssetContext,
    EDLPatch,
    SubAgentRequest,
    SubAgentResponse,
    SubAgentType,
    TimelineSlice,
    dispatch_to_agent,
)

logger = logging.getLogger(__name__)

GCS_BUCKET = os.getenv("GCS_BUCKET", "video-editor")


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_timeline",
            "description": (
                "Get the current timeline state (EDL) including all tracks, clips, gaps, "
                "and transitions. Returns the full timeline structure. "
                "CALL THIS FIRST to understand the current state of the video project."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "version": {
                        "type": "integer",
                        "description": "Specific version to retrieve (default: current version)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_timeline_history",
            "description": (
                "Get the history of timeline changes (checkpoints). "
                "Each checkpoint has a version number, description, and author. "
                "Use this to understand what edits have been made recently."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of checkpoints to return (default: 10)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": (
                "Search for assets in the project using natural language. "
                "This uses AI-powered semantic search to find relevant video clips, "
                "audio files, or images based on content, mood, speakers, objects, etc. "
                "Returns ranked candidates with relevance scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what assets to find",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_asset",
            "description": (
                "View a source asset (video, audio, or image file) to understand its content. "
                "This loads the actual media file and returns it for visual/audio analysis. "
                "Use this to see what a clip looks like before making edit decisions. "
                "For videos, you can specify a time range to view only a portion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "UUID of the asset to view",
                    },
                    "start_time_ms": {
                        "type": "integer",
                        "description": "Start time in milliseconds (optional, for video/audio)",
                    },
                    "end_time_ms": {
                        "type": "integer",
                        "description": "End time in milliseconds (optional, for video/audio)",
                    },
                    "question": {
                        "type": "string",
                        "description": "Specific question to answer about this asset (e.g., 'What is the speaker saying?', 'Describe the visual mood')",
                    },
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_details",
            "description": (
                "Get detailed metadata about an asset including transcript, detected faces, "
                "scene boundaries, objects, colors, and technical information. "
                "Use this to understand asset content without viewing the actual video."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "UUID of the asset",
                    },
                    "include_transcript": {
                        "type": "boolean",
                        "description": "Include full transcript with timestamps (default: true)",
                    },
                    "include_scenes": {
                        "type": "boolean",
                        "description": "Include scene boundary information (default: true)",
                    },
                    "include_faces": {
                        "type": "boolean",
                        "description": "Include detected faces/speakers (default: true)",
                    },
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_rendered_output",
            "description": (
                "View a previously rendered video output. Use this to see the final "
                "result of the timeline after rendering. Returns the rendered video for analysis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "render_job_id": {
                        "type": "string",
                        "description": "UUID of the completed render job",
                    },
                    "question": {
                        "type": "string",
                        "description": "Specific question to answer about the rendered output",
                    },
                },
                "required": ["render_job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_rendered_outputs",
            "description": (
                "List available rendered video outputs for the project. "
                "Use this to find completed renders that can be viewed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["completed", "all"],
                        "description": "Filter by status (default: completed)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_cut_agent",
            "description": (
                "Delegate to the CutAgent for trimming, splitting, inserting, "
                "overwriting, moving, slipping, or sliding clips. "
                "Also handles pacing fixes and rhythm adjustments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the cut agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Track indices to focus on (optional)",
                    },
                    "focus_time_range_ms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Time range [start_ms, end_ms] to focus on (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Additional constraints (ripple_edit, preserve_audio_sync)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_silence_agent",
            "description": (
                "Delegate to the SilenceAgent for detecting and removing silence. "
                "Analyzes audio tracks and transcripts to identify silent regions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the silence agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Audio track indices to analyze (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (silence_threshold_db, minimum_silence_duration_ms, preserve_breaths)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_broll_agent",
            "description": (
                "Delegate to the BrollAgent for placing b-roll footage, "
                "picture-in-picture, masks, and blur effects. "
                "Maintains dialogue continuity while adding supplementary visuals."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the b-roll agent should accomplish",
                    },
                    "asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Asset IDs to use for b-roll (from search_assets)",
                    },
                    "focus_time_range_ms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Time range to add b-roll to (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (maintain_dialogue_continuity, allow_pip)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_captions_agent",
            "description": (
                "Delegate to the CaptionsAgent for creating captions, "
                "lower-thirds, and text overlays based on the transcript."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the captions agent should accomplish",
                    },
                    "focus_time_range_ms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Time range to add captions to (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (max_characters_per_line, position, style_preset)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_mix_agent",
            "description": (
                "Delegate to the MixAgent for audio mixing including J/L cuts, "
                "crossfades, volume keyframes, ducking, and loudness normalization."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the mix agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Audio track indices to process (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (target_loudness_lufs, enable_ducking, duck_amount_db)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_color_agent",
            "description": (
                "Delegate to the ColorAgent for color grading including LUTs, "
                "curves, white balance, and color matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the color agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Video track indices to process (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (global_look_lut, match_reference_clip)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_motion_agent",
            "description": (
                "Delegate to the MotionAgent for stabilization, auto-reframing, "
                "and position/scale/crop keyframes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the motion agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Video track indices to process (optional)",
                    },
                    "focus_time_range_ms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Time range to process (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (stabilization_strength, auto_reframe_aspect)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_fx_agent",
            "description": (
                "Delegate to the FXAgent for visual effects including transitions, "
                "speed ramps, freeze frames, vignette, grain, and blur."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "What the FX agent should accomplish",
                    },
                    "focus_track_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Track indices to process (optional)",
                    },
                    "focus_time_range_ms": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Time range to process (optional)",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Constraints (transition_style, speed_ramp_smoothness)",
                    },
                },
                "required": ["intent"],
            },
        },
    },
]


# Context that gets passed to tool execution
class ToolContext:
    """Context for tool execution."""

    def __init__(
        self,
        db: DBSession,
        project_id: str,
        timeline_id: str,
        current_timeline_snapshot: dict[str, Any] | None = None,
        current_version: int = 0,
        conversation_context: str = "",
    ):
        self.db = db
        self.project_id = project_id
        self.timeline_id = timeline_id
        self.current_timeline_snapshot = current_timeline_snapshot
        self.current_version = current_version
        self.conversation_context = conversation_context
        # Cache for asset details
        self._asset_cache: dict[str, AssetContext] = {}


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any]:
    """Execute a tool and return the result.

    Args:
        tool_name: Name of the tool to execute
        arguments: Tool arguments from LLM
        context: Execution context with DB session and project info

    Returns:
        Tool result as a dictionary
    """
    tool_map = {
        "get_timeline": _get_timeline,
        "get_timeline_history": _get_timeline_history,
        "search_assets": _search_assets,
        # Viewing tools
        "view_asset": _view_asset,
        "get_asset_details": _get_asset_details,
        "view_rendered_output": _view_rendered_output,
        "list_rendered_outputs": _list_rendered_outputs,
        # Sub-agent dispatch tools
        "dispatch_cut_agent": _dispatch_cut_agent,
        "dispatch_silence_agent": _dispatch_silence_agent,
        "dispatch_broll_agent": _dispatch_broll_agent,
        "dispatch_captions_agent": _dispatch_captions_agent,
        "dispatch_mix_agent": _dispatch_mix_agent,
        "dispatch_color_agent": _dispatch_color_agent,
        "dispatch_motion_agent": _dispatch_motion_agent,
        "dispatch_fx_agent": _dispatch_fx_agent,
    }

    tool_fn = tool_map.get(tool_name)
    if not tool_fn:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return tool_fn(context=context, **arguments)
    except Exception as e:
        logger.exception(f"Tool execution failed: {tool_name}")
        return {"error": f"Tool execution failed: {type(e).__name__}: {str(e)}"}


def _get_timeline(
    context: ToolContext,
    version: int | None = None,
) -> dict[str, Any]:
    """Get the current or specified version of the timeline."""
    try:
        timeline_data = get_timeline_by_project(context.db, context.project_id)
        if not timeline_data:
            return {"error": "No timeline found for this project"}

        snapshot = get_timeline_snapshot(
            context.db,
            str(timeline_data.timeline_id),
            version=version,
        )

        # Update context with current snapshot
        if version is None:
            context.current_timeline_snapshot = snapshot.timeline.model_dump()
            context.current_version = snapshot.version

        return {
            "timeline_id": str(timeline_data.timeline_id),
            "name": timeline_data.name,
            "version": snapshot.version,
            "timeline": snapshot.timeline.model_dump(),
            "settings": timeline_data.settings,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_timeline_history(
    context: ToolContext,
    limit: int = 10,
) -> dict[str, Any]:
    """Get recent timeline checkpoints."""
    try:
        timeline_data = get_timeline_by_project(context.db, context.project_id)
        if not timeline_data:
            return {"error": "No timeline found for this project"}

        checkpoints, total = list_checkpoints(
            context.db,
            str(timeline_data.timeline_id),
            limit=limit,
        )

        return {
            "current_version": timeline_data.current_version,
            "total_checkpoints": total,
            "checkpoints": [
                {
                    "version": cp.version,
                    "description": cp.description,
                    "created_by": cp.created_by,
                    "created_at": cp.created_at,
                    "is_approved": cp.is_approved,
                }
                for cp in checkpoints
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def _search_assets(
    context: ToolContext,
    query: str,
) -> dict[str, Any]:
    """Search for assets using the asset retrieval agent."""
    try:
        result = find_assets(
            project_id=context.project_id,
            query=query,
            db=context.db,
        )

        # Cache asset details for later sub-agent use
        for candidate in result.candidates:
            if candidate.media_id not in context._asset_cache:
                asset = (
                    context.db.query(Assets)
                    .filter(Assets.asset_id == candidate.media_id)
                    .first()
                )
                if asset:
                    context._asset_cache[candidate.media_id] = AssetContext(
                        asset_id=asset.asset_id,
                        asset_name=asset.asset_name,
                        asset_type=asset.asset_type,
                        duration_ms=None,  # Could extract from technical
                        summary=asset.asset_summary,
                        tags=asset.asset_tags or [],
                        transcript=asset.asset_transcript,
                        faces=asset.asset_faces,
                        speakers=asset.asset_speakers,
                        scenes=asset.asset_scenes,
                        technical=asset.asset_technical,
                    )

        return {
            "count": len(result.candidates),
            "candidates": [c.model_dump() for c in result.candidates],
        }
    except Exception as e:
        return {"error": str(e)}


def _build_sub_agent_request(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    focus_time_range_ms: list[int] | None = None,
    asset_ids: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> SubAgentRequest:
    """Build a SubAgentRequest from tool arguments."""
    # Ensure we have a timeline snapshot
    if not context.current_timeline_snapshot:
        timeline_result = _get_timeline(context)
        if "error" in timeline_result:
            raise ValueError(timeline_result["error"])

    # Build asset contexts from cache or provided IDs
    assets = []
    if asset_ids:
        for asset_id in asset_ids:
            if asset_id in context._asset_cache:
                assets.append(context._asset_cache[asset_id])
            else:
                # Fetch from DB if not cached
                asset = (
                    context.db.query(Assets)
                    .filter(Assets.asset_id == asset_id)
                    .first()
                )
                if asset:
                    asset_ctx = AssetContext(
                        asset_id=asset.asset_id,
                        asset_name=asset.asset_name,
                        asset_type=asset.asset_type,
                        summary=asset.asset_summary,
                        tags=asset.asset_tags or [],
                        transcript=asset.asset_transcript,
                        faces=asset.asset_faces,
                        speakers=asset.asset_speakers,
                        scenes=asset.asset_scenes,
                        technical=asset.asset_technical,
                    )
                    context._asset_cache[asset_id] = asset_ctx
                    assets.append(asset_ctx)

    time_range = None
    if focus_time_range_ms and len(focus_time_range_ms) == 2:
        time_range = (focus_time_range_ms[0], focus_time_range_ms[1])

    return SubAgentRequest(
        request_id=str(uuid4()),
        intent=intent,
        timeline_slice=TimelineSlice(
            full_snapshot=context.current_timeline_snapshot,
            focus_track_indices=focus_track_indices,
            focus_time_range_ms=time_range,
            current_version=context.current_version,
        ),
        assets=assets,
        constraints=constraints or {},
        conversation_context=context.conversation_context,
    )


def _dispatch_agent(
    context: ToolContext,
    agent_type: SubAgentType,
    intent: str,
    focus_track_indices: list[int] | None = None,
    focus_time_range_ms: list[int] | None = None,
    asset_ids: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generic dispatcher for sub-agents."""
    try:
        request = _build_sub_agent_request(
            context=context,
            intent=intent,
            focus_track_indices=focus_track_indices,
            focus_time_range_ms=focus_time_range_ms,
            asset_ids=asset_ids,
            constraints=constraints,
        )

        response = dispatch_to_agent(agent_type, request)

        return {
            "agent": agent_type.value,
            "request_id": response.request_id,
            "success": response.success,
            "patch": response.patch.model_dump() if response.patch else None,
            "reasoning": response.reasoning,
            "warnings": response.warnings,
            "error": response.error,
        }
    except Exception as e:
        return {
            "agent": agent_type.value,
            "success": False,
            "error": str(e),
        }


def _dispatch_cut_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    focus_time_range_ms: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.CUT, intent,
        focus_track_indices, focus_time_range_ms, None, constraints
    )


def _dispatch_silence_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.SILENCE, intent,
        focus_track_indices, None, None, constraints
    )


def _dispatch_broll_agent(
    context: ToolContext,
    intent: str,
    asset_ids: list[str] | None = None,
    focus_time_range_ms: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.BROLL, intent,
        None, focus_time_range_ms, asset_ids, constraints
    )


def _dispatch_captions_agent(
    context: ToolContext,
    intent: str,
    focus_time_range_ms: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.CAPTIONS, intent,
        None, focus_time_range_ms, None, constraints
    )


def _dispatch_mix_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.MIX, intent,
        focus_track_indices, None, None, constraints
    )


def _dispatch_color_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.COLOR, intent,
        focus_track_indices, None, None, constraints
    )


def _dispatch_motion_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    focus_time_range_ms: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.MOTION, intent,
        focus_track_indices, focus_time_range_ms, None, constraints
    )


def _dispatch_fx_agent(
    context: ToolContext,
    intent: str,
    focus_track_indices: list[int] | None = None,
    focus_time_range_ms: list[int] | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _dispatch_agent(
        context, SubAgentType.FX, intent,
        focus_track_indices, focus_time_range_ms, None, constraints
    )


# -----------------------------------------------------------------------------
# Viewing Tools - For multimodal asset and render output viewing
# -----------------------------------------------------------------------------


def _extract_gcs_path(url: str) -> str | None:
    """Extract GCS blob path from a gs:// or https://storage URL."""
    if not url:
        return None
    if url.startswith("gs://"):
        # gs://bucket-name/path/to/file -> path/to/file
        parts = url.replace("gs://", "").split("/", 1)
        return parts[1] if len(parts) > 1 else None
    if "storage.googleapis.com" in url:
        # https://storage.googleapis.com/bucket-name/path/to/file
        parts = url.split("/", 4)
        return parts[4] if len(parts) > 4 else None
    # Assume it's already a blob path
    return url


def _get_mime_type(asset_type: str, filename: str) -> str:
    """Determine MIME type from asset type and filename."""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mime_map = {
        "mp4": "video/mp4",
        "mpeg": "video/mpeg",
        "mpg": "video/mpeg",
        "mpe": "video/mpeg",
        "mov": "video/mov",
        "webm": "video/webm",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "aif": "audio/aiff",
        "aifc": "audio/aiff",
        "aiff": "audio/aiff",
        "aac": "audio/aac",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "m4a": "audio/m4a",
        "pcm16": "audio/pcm16",
        "pcm24": "audio/pcm24",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    if ext in mime_map:
        return mime_map[ext]
    # Fallback based on asset_type
    type_map = {
        "video": "video/mp4",
        "audio": "audio/mpeg",
        "image": "image/jpeg",
    }
    return type_map.get(asset_type, "application/octet-stream")


def _view_asset(
    context: ToolContext,
    asset_id: str,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """View a source asset by downloading from GCS and returning for multimodal analysis.

    Returns media content that can be passed to Gemini for native video/audio/image understanding.
    """
    try:
        asset = (
            context.db.query(Assets)
            .filter(Assets.asset_id == asset_id)
            .first()
        )
        if not asset:
            return {"error": f"Asset not found: {asset_id}"}

        # Extract blob path from asset URL
        blob_path = _extract_gcs_path(asset.asset_url)
        if not blob_path:
            return {"error": f"Invalid asset URL: {asset.asset_url}"}

        # Download the file from GCS
        file_bytes = download_file(GCS_BUCKET, blob_path)
        if file_bytes is None:
            return {"error": f"Failed to download asset from GCS: {blob_path}"}

        # Encode as base64 for multimodal content
        encoded_data = base64.b64encode(file_bytes).decode("utf-8")
        mime_type = _get_mime_type(asset.asset_type, asset.asset_name)

        result = {
            "asset_id": str(asset.asset_id),
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
            # Multimodal content for Gemini
            "media_content": {
                "type": "base64",
                "mime_type": mime_type,
                "data": encoded_data,
            },
        }

        # Add time range info if specified (for context, not for clipping)
        if start_time_ms is not None or end_time_ms is not None:
            result["focus_range"] = {
                "start_ms": start_time_ms,
                "end_ms": end_time_ms,
                "note": "Focus on this time range when analyzing",
            }

        if question:
            result["question"] = question

        # Include summary context
        if asset.asset_summary:
            result["summary"] = asset.asset_summary

        return result

    except Exception as e:
        logger.exception(f"Error viewing asset {asset_id}")
        return {"error": f"Failed to view asset: {str(e)}"}


def _get_asset_details(
    context: ToolContext,
    asset_id: str,
    include_transcript: bool = True,
    include_scenes: bool = True,
    include_faces: bool = True,
) -> dict[str, Any]:
    """Get detailed metadata about an asset from the database.

    Returns pre-computed analysis data without downloading the actual media file.
    """
    try:
        asset = (
            context.db.query(Assets)
            .filter(Assets.asset_id == asset_id)
            .first()
        )
        if not asset:
            return {"error": f"Asset not found: {asset_id}"}

        result = {
            "asset_id": str(asset.asset_id),
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type,
            "summary": asset.asset_summary,
            "tags": asset.asset_tags or [],
            "indexing_status": asset.indexing_status,
        }

        # Technical metadata (duration, resolution, codec, etc.)
        if asset.asset_technical:
            result["technical"] = asset.asset_technical

        # Transcript with word-level timestamps
        if include_transcript and asset.asset_transcript:
            result["transcript"] = asset.asset_transcript

        # Scene boundaries and descriptions
        if include_scenes and asset.asset_scenes:
            result["scenes"] = asset.asset_scenes

        # Detected faces and speakers
        if include_faces:
            if asset.asset_faces:
                result["faces"] = asset.asset_faces
            if asset.asset_speakers:
                result["speakers"] = asset.asset_speakers

        # Additional analysis data
        if asset.asset_objects:
            result["objects"] = asset.asset_objects
        if asset.asset_colors:
            result["colors"] = asset.asset_colors
        if asset.asset_events:
            result["events"] = asset.asset_events
        if asset.notable_shots:
            result["notable_shots"] = asset.notable_shots
        if asset.audio_features:
            result["audio_features"] = asset.audio_features
        if asset.audio_structure:
            result["audio_structure"] = asset.audio_structure

        return result

    except Exception as e:
        logger.exception(f"Error getting asset details for {asset_id}")
        return {"error": f"Failed to get asset details: {str(e)}"}


def _view_rendered_output(
    context: ToolContext,
    render_job_id: str,
    question: str | None = None,
) -> dict[str, Any]:
    """View a completed render job output by downloading from GCS.

    Returns the rendered video for multimodal analysis.
    """
    try:
        render_job = (
            context.db.query(RenderJob)
            .filter(RenderJob.job_id == render_job_id)
            .filter(RenderJob.project_id == context.project_id)
            .first()
        )
        if not render_job:
            return {"error": f"Render job not found: {render_job_id}"}

        if render_job.status != "completed":
            return {
                "error": f"Render job is not completed. Status: {render_job.status}",
                "job_id": str(render_job.job_id),
                "status": render_job.status,
                "progress": render_job.progress,
            }

        if not render_job.output_url:
            return {"error": "Render job completed but no output URL available"}

        # Extract blob path from output URL
        blob_path = _extract_gcs_path(render_job.output_url)
        if not blob_path:
            return {"error": f"Invalid output URL: {render_job.output_url}"}

        # Download the rendered video
        file_bytes = download_file(GCS_BUCKET, blob_path)
        if file_bytes is None:
            return {"error": f"Failed to download render output from GCS: {blob_path}"}

        # Encode as base64 for multimodal content
        encoded_data = base64.b64encode(file_bytes).decode("utf-8")
        # Rendered outputs are typically mp4
        mime_type = "video/mp4"

        result = {
            "job_id": str(render_job.job_id),
            "job_type": render_job.job_type,
            "timeline_version": render_job.timeline_version,
            "output_filename": render_job.output_filename,
            "size_bytes": render_job.output_size_bytes or len(file_bytes),
            "completed_at": str(render_job.completed_at) if render_job.completed_at else None,
            # Multimodal content for Gemini
            "media_content": {
                "type": "base64",
                "mime_type": mime_type,
                "data": encoded_data,
            },
        }

        if question:
            result["question"] = question

        # Include preset info for context
        if render_job.preset:
            result["preset"] = render_job.preset

        return result

    except Exception as e:
        logger.exception(f"Error viewing render output {render_job_id}")
        return {"error": f"Failed to view render output: {str(e)}"}


def _list_rendered_outputs(
    context: ToolContext,
    limit: int = 5,
    status: str = "completed",
) -> dict[str, Any]:
    """List available render jobs for the project.

    Returns job info without downloading the actual files.
    """
    try:
        query = (
            context.db.query(RenderJob)
            .filter(RenderJob.project_id == context.project_id)
            .order_by(RenderJob.created_at.desc())
        )

        if status != "all":
            query = query.filter(RenderJob.status == status)

        render_jobs = query.limit(limit).all()

        return {
            "count": len(render_jobs),
            "jobs": [
                {
                    "job_id": str(job.job_id),
                    "job_type": job.job_type,
                    "status": job.status,
                    "progress": job.progress,
                    "timeline_version": job.timeline_version,
                    "output_filename": job.output_filename,
                    "output_size_bytes": job.output_size_bytes,
                    "created_at": str(job.created_at) if job.created_at else None,
                    "completed_at": str(job.completed_at) if job.completed_at else None,
                    "error_message": job.error_message,
                    "preset": job.preset,
                }
                for job in render_jobs
            ],
        }

    except Exception as e:
        logger.exception("Error listing render outputs")
        return {"error": f"Failed to list render outputs: {str(e)}"}
