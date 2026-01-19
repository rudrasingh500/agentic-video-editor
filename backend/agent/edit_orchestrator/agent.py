"""Main orchestrator agent loop.

This module implements the core orchestration logic that:
1. Receives user edit requests
2. Maintains conversation context
3. Calls the LLM with tools
4. Executes tool calls
5. Collects and returns proposed patches
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from openai import OpenAI
from sqlalchemy.orm import Session as DBSession

from database.models import AgentRun, Timeline
from operators.timeline_operator import get_timeline_snapshot, list_checkpoints

from . import session as session_ops
from .prompts import SYSTEM_PROMPT, build_context_prompt
from .session import SessionNotFoundError
from .sub_agents.types import EDLPatch, SubAgentType
from .tools import TOOLS, ToolContext, execute_tool
from .types import (
    EditPlan,
    EditRequest,
    EditSessionStatus,
    MessageRole,
    OrchestratorResult,
    PendingPatch,
    SubAgentCall,
)

logger = logging.getLogger(__name__)

MODEL = "google/gemini-3-pro-preview"
MAX_ITERATIONS = 15


def _get_client() -> OpenAI:
    """Get OpenRouter client."""
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


def _format_tool_result(
    tool_name: str,
    result: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    """Format tool result for inclusion in messages.

    For viewing tools that return media_content, emit a tool message payload
    plus a follow-up user message containing multimodal content parts that
    OpenRouter can forward to Gemini.

    Args:
        tool_name: Name of the tool that produced the result
        result: The tool's return value

    Returns:
        Tuple of (tool message content, optional follow-up user message)
    """
    media_content = result.get("media_content")
    if media_content and tool_name in ("view_asset", "view_rendered_output"):
        media_part = _build_media_part(media_content)

        tool_payload = dict(result)
        tool_payload["media_content"] = {
            "mime_type": media_content.get("mime_type"),
            "size_bytes": result.get("size_bytes"),
            "note": "Media content omitted; provided as multimodal input.",
        }

        if not media_part:
            tool_payload["media_content"]["note"] = (
                "Media content unavailable for multimodal input."
            )
            return json.dumps(tool_payload), None

        question = result.get("question")
        context_payload = {
            k: v
            for k, v in result.items()
            if k not in ("media_content", "question") and v is not None
        }
        text_blocks = []
        if question:
            text_blocks.append(f"Please analyze the media and answer: {question}")
        if context_payload:
            text_blocks.append(f"Context: {json.dumps(context_payload)}")
        text_prompt = "\n".join(text_blocks) if text_blocks else "Please analyze the media."

        followup_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": text_prompt},
                media_part,
            ],
        }

        return json.dumps(tool_payload), followup_message

    return json.dumps(result), None


def orchestrate_edit(
    project_id: str,
    user_id: str,
    request: EditRequest,
    db: DBSession,
) -> OrchestratorResult:
    """Process an edit request through the orchestrator.

    Args:
        project_id: Project UUID
        user_id: User making the request
        request: The edit request with user message
        db: Database session

    Returns:
        OrchestratorResult with proposed patches and response
    """
    client = _get_client()
    trace: list[dict[str, Any]] = []

    # Get or create session
    if request.session_id:
        try:
            session = session_ops.get_session(db, request.session_id)
        except SessionNotFoundError:
            return OrchestratorResult(
                session_id=request.session_id,
                message=f"Session {request.session_id} not found. Start a new session.",
                warnings=["Session not found"],
                trace=[],
            )
        if session.status != EditSessionStatus.ACTIVE:
            return OrchestratorResult(
                session_id=request.session_id,
                message=f"Session is {session.status.value}. Start a new session.",
                warnings=[f"Session is {session.status.value}"],
                trace=[],
            )
    else:
        # Get timeline for new session
        timeline = (
            db.query(Timeline)
            .filter(Timeline.project_id == project_id)
            .first()
        )
        if not timeline:
            return OrchestratorResult(
                session_id="",
                message="No timeline found for this project. Create a timeline first.",
                warnings=["No timeline found"],
                trace=[],
            )
        session = session_ops.create_session(
            db=db,
            project_id=project_id,
            timeline_id=str(timeline.timeline_id),
            user_id=user_id,
        )

    # Add user message to session
    session_ops.add_message(
        db=db,
        session_id=session.session_id,
        role=MessageRole.USER,
        content=request.message,
    )

    timeline_summary = _summarize_timeline(db, UUID(session.timeline_id))
    recent_edits = _summarize_recent_edits(db, UUID(session.timeline_id))
    conversation_summary = _summarize_conversation(session.messages)

    # Build conversation history for LLM
    messages = _build_messages(
        session.messages,
        request.message,
        timeline_summary=timeline_summary,
        recent_edits=recent_edits,
        conversation_summary=conversation_summary,
    )

    # Create tool execution context
    tool_context = ToolContext(
        db=db,
        project_id=project_id,
        timeline_id=session.timeline_id,
        conversation_context=_summarize_conversation(session.messages),
    )

    # Collected patches from sub-agents
    collected_patches: list[PendingPatch] = []
    collected_warnings: list[str] = []
    plan: EditPlan | None = None
    final_content = ""

    # Main agent loop
    for iteration in range(MAX_ITERATIONS):
        logger.debug(f"Orchestrator iteration {iteration + 1}/{MAX_ITERATIONS}")

        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return OrchestratorResult(
                session_id=session.session_id,
                message=f"Error communicating with AI service: {str(e)}",
                warnings=[str(e)],
                trace=trace,
            )

        message = response.choices[0].message
        final_content = message.content or ""

        # Build assistant message for history
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        if message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_msg)

        # Process tool calls
        if message.tool_calls:
            tool_results: list[dict[str, Any]] = []

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                trace_entry = {
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": tool_args,
                }

                logger.debug(f"Executing tool: {tool_name}")

                result = execute_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    context=tool_context,
                )

                trace_entry["result"] = result
                trace.append(trace_entry)

                # Collect patches from sub-agent dispatches
                if tool_name.startswith("dispatch_") and result.get("success"):
                    patch_data = result.get("patch")
                    if patch_data and patch_data.get("operations"):
                        agent_type_str = result.get("agent", "unknown")
                        try:
                            agent_type = SubAgentType(agent_type_str)
                        except ValueError:
                            agent_type = SubAgentType.CUT  # fallback

                        pending_patch = PendingPatch(
                            patch_id=str(uuid4()),
                            agent_type=agent_type,
                            patch=EDLPatch(**patch_data),
                            reasoning=result.get("reasoning", ""),
                            created_at=datetime.now(timezone.utc),
                        )
                        collected_patches.append(pending_patch)

                    # Collect warnings
                    if result.get("warnings"):
                        collected_warnings.extend(result["warnings"])

                # Format tool result for message
                # For viewing tools with media_content, we add a multimodal follow-up
                tool_result_content, followup_message = _format_tool_result(
                    tool_name,
                    result,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_content,
                })

                if followup_message:
                    messages.append(followup_message)

            # Add iteration context
            remaining = MAX_ITERATIONS - iteration - 1
            if remaining <= 3:
                messages.append({
                    "role": "user",
                    "content": (
                        f"[System: {remaining} iterations remaining. "
                        "Please finalize your response and summarize proposed changes.]"
                    ),
                })

        # Check if done
        if response.choices[0].finish_reason == "stop" and not message.tool_calls:
            logger.debug("Orchestrator finished")
            break
    else:
        logger.warning(f"Orchestrator reached max iterations ({MAX_ITERATIONS})")
        trace.append({
            "warning": "Max iterations reached",
            "iteration": MAX_ITERATIONS,
        })
        collected_warnings.append(
            "Processing reached iteration limit. Some operations may be incomplete."
        )

    # Try to extract plan from final content
    plan = _extract_plan(final_content, trace)

    # Store patches in session
    if collected_patches:
        session_ops.add_pending_patches(
            db=db,
            session_id=session.session_id,
            patches=collected_patches,
        )

    # Store assistant response in session
    session_ops.add_message(
        db=db,
        session_id=session.session_id,
        role=MessageRole.ASSISTANT,
        content=final_content,
        tool_calls=[t for t in trace if "tool" in t],
        agent_responses=[
            {"agent": p.agent_type.value, "reasoning": p.reasoning}
            for p in collected_patches
        ],
    )

    # Log the agent run
    _log_run(db, project_id, session.session_id, request.message, trace, collected_patches)

    return OrchestratorResult(
        session_id=session.session_id,
        plan=plan,
        pending_patches=collected_patches,
        applied=False,
        new_version=None,
        message=final_content or "Processing complete.",
        warnings=collected_warnings,
        trace=trace,
    )


def _build_messages(
    history: list,
    current_message: str,
    timeline_summary: str | None = None,
    recent_edits: list[str] | None = None,
    conversation_summary: str | None = None,
) -> list[dict[str, Any]]:
    """Build message list for LLM from session history."""
    system_prompt = SYSTEM_PROMPT + build_context_prompt(
        timeline_summary=timeline_summary,
        recent_edits=recent_edits,
        conversation_history=conversation_summary,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Add conversation history (last N messages to avoid context overflow)
    MAX_HISTORY = 10
    recent_history = history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history

    for msg in recent_history:
        if isinstance(msg, dict):
            role = msg.get("role", "user")
            content = msg.get("content", "")
        else:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            content = msg.content

        if role in ["user", "assistant"]:
            messages.append({"role": role, "content": content})

    # Ensure current message is included if not already
    last_user = next(
        (msg for msg in reversed(messages) if msg.get("role") == "user"),
        None,
    )
    if not last_user or last_user.get("content") != current_message:
        messages.append({"role": "user", "content": current_message})

    return messages


def _summarize_conversation(history: list) -> str:
    """Create a brief summary of conversation history."""
    if not history:
        return ""

    summaries = []
    for msg in history[-5:]:  # Last 5 messages
        if isinstance(msg, dict):
            role = msg.get("role", "")
            content = msg.get("content", "")[:100]
        else:
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            content = (msg.content or "")[:100]

        if content:
            summaries.append(f"{role}: {content}...")

    return "\n".join(summaries)


def _summarize_timeline(db: DBSession, timeline_id: UUID) -> str | None:
    """Build a concise textual summary of the current timeline."""
    try:
        snapshot = get_timeline_snapshot(db, timeline_id)
    except Exception:
        return None

    timeline = snapshot.timeline
    total_tracks = len(timeline.tracks.children)
    video_tracks = len(timeline.video_tracks)
    audio_tracks = len(timeline.audio_tracks)
    clip_count = len(timeline.find_clips())
    transitions = len(timeline.find_transitions())
    duration_ms = int(timeline.duration.to_milliseconds())

    return (
        "Timeline '{name}' v{version}. Duration: {duration_ms} ms. "
        "Tracks: {total_tracks} (video {video_tracks}, audio {audio_tracks}). "
        "Clips: {clip_count}. Transitions: {transitions}."
    ).format(
        name=timeline.name,
        version=snapshot.version,
        duration_ms=duration_ms,
        total_tracks=total_tracks,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        clip_count=clip_count,
        transitions=transitions,
    )


def _summarize_recent_edits(db: DBSession, timeline_id: UUID) -> list[str] | None:
    """Summarize recent timeline checkpoints for context."""
    try:
        checkpoints, _ = list_checkpoints(db, timeline_id, limit=5)
    except Exception:
        return None

    summaries: list[str] = []
    for checkpoint in checkpoints:
        description = checkpoint.description or ""
        created_by = checkpoint.created_by
        if description and created_by:
            summaries.append(f"v{checkpoint.version} by {created_by}: {description}")
        elif description:
            summaries.append(f"v{checkpoint.version}: {description}")
        else:
            summaries.append(f"v{checkpoint.version} by {created_by}")

    return summaries


def _build_media_part(media_content: dict[str, Any]) -> dict[str, Any] | None:
    """Build a multimodal content part for OpenRouter."""
    mime_type = media_content.get("mime_type")
    data = media_content.get("data")
    if not mime_type or not data:
        return None

    if mime_type.startswith("video/"):
        return {
            "type": "video_url",
            "video_url": {
                "url": f"data:{mime_type};base64,{data}",
            },
        }

    if mime_type.startswith("audio/"):
        format_suffix = mime_type.split("/", maxsplit=1)[1]
        format_map = {
            "mpeg": "mp3",
            "x-wav": "wav",
        }
        return {
            "type": "input_audio",
            "input_audio": {
                "data": data,
                "format": format_map.get(format_suffix, format_suffix),
            },
        }

    if mime_type.startswith("image/"):
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{data}",
            },
        }

    return None


def _extract_plan(content: str, trace: list[dict]) -> EditPlan | None:
    """Try to extract an edit plan from the orchestrator's response."""
    if not content and not trace:
        return None

    # Build plan from trace
    sub_agent_calls = []
    for entry in trace:
        tool_name = entry.get("tool", "")
        if tool_name.startswith("dispatch_"):
            args = entry.get("args", {})
            agent_name = tool_name.replace("dispatch_", "").replace("_agent", "")
            try:
                agent_type = SubAgentType(agent_name)
            except ValueError:
                continue

            sub_agent_calls.append(SubAgentCall(
                agent_type=agent_type,
                intent=args.get("intent", ""),
                focus_track_indices=args.get("focus_track_indices"),
                focus_time_range_ms=args.get("focus_time_range_ms"),
                asset_ids=args.get("asset_ids", []),
            ))

    if not sub_agent_calls and not content:
        return None

    estimated_changes = 0
    for entry in trace:
        if not entry.get("tool", "").startswith("dispatch_"):
            continue
        patch = entry.get("result", {}).get("patch")
        if isinstance(patch, dict):
            estimated_changes += len(patch.get("operations", []))

    return EditPlan(
        summary=content[:500] if content else "Edit operations processed",
        sub_agent_calls=sub_agent_calls,
        estimated_changes=estimated_changes,
        requires_assets=any(
            entry.get("tool") == "search_assets"
            for entry in trace
        ),
    )


def _log_run(
    db: DBSession,
    project_id: str,
    session_id: str,
    query: str,
    trace: list[dict],
    patches: list[PendingPatch],
) -> None:
    """Log the orchestrator run to AgentRun table."""
    try:
        run = AgentRun(
            run_id=uuid4(),
            project_id=project_id,
            trace={
                "agent": "edit_orchestrator",
                "session_id": session_id,
                "query": query,
                "iterations": len(set(t.get("iteration", 0) for t in trace)),
                "tool_calls": trace,
            },
            analysis_segments=[
                {
                    "patch_id": p.patch_id,
                    "agent": p.agent_type.value,
                    "operations": len(p.patch.operations) if p.patch else 0,
                }
                for p in patches
            ],
        )
        db.add(run)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log orchestrator run: {e}")
        db.rollback()
