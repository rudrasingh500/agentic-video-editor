from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from openai import OpenAI
from sqlalchemy.orm import Session

from database.models import AgentRun, EditSession, Timeline

from .prompts import SYSTEM_PROMPT
from .session_ops import SessionClosedError, SessionNotFoundError
from .tools import TOOLS, execute_tool
from .types import (
    AgentFinalResponse,
    EditAgentResult,
    EditAgentType,
    EditMessage,
    EditOperation,
    EditPatch,
    EditRequest,
    PendingPatch,
)

logger = logging.getLogger(__name__)

MODEL = "google/gemini-3-pro-preview"
MAX_ITERATIONS = int(os.getenv("EDIT_AGENT_MAX_ITERATIONS", "0"))
LOG_PAYLOADS = os.getenv("EDIT_AGENT_LOG_PAYLOADS", "").lower() in {"1", "true", "yes"}
LOG_MAX_CHARS = int(os.getenv("EDIT_AGENT_LOG_MAX_CHARS", "2000"))

# JSON Schema for structured output - enforces the final response format
FINAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_final_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Summary of changes and outcomes"
                },
                "applied": {
                    "type": "boolean",
                    "description": "Whether changes were applied to the timeline"
                },
                "new_version": {
                    "type": ["integer", "null"],
                    "description": "New timeline version after edits, or null if no changes"
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Any warnings encountered during editing"
                },
                "next_actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional suggested follow-up actions"
                },
                "verification": {
                    "type": ["object", "null"],
                    "description": "Verification status - REQUIRED if edits were applied",
                    "properties": {
                        "render_viewed": {
                            "type": "boolean",
                            "description": "Did you call view_render_output to watch the result?"
                        },
                        "render_job_id": {
                            "type": ["string", "null"],
                            "description": "Job ID of the render you verified"
                        },
                        "observations": {
                            "type": ["string", "null"],
                            "description": "What did you see and hear in the render?"
                        },
                        "issues_found": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Any issues observed"
                        }
                    },
                    "required": ["render_viewed"]
                }
            },
            "required": ["message", "applied", "new_version", "warnings", "next_actions", "verification"],
            "additionalProperties": False
        }
    }
}

# Verification enforcement prompt - injected if edits were made but not verified
VERIFICATION_ENFORCEMENT_PROMPT = """
IMPORTANT: You made edits to the timeline but have NOT verified them.

Before you can complete this task, you MUST:
1. Call render_timeline to render the current timeline
2. Call view_render_output to watch the result
3. Report what you observed in your final response

This is a mandatory step. Please verify your edits now.
"""


def _check_verification_needed(trace: list[dict], applied: bool) -> bool:
    """Check if verification is needed based on trace and applied status.
    
    Returns True if:
    - Edits were applied (applied=True)
    - view_render_output was NOT called after the last edit
    """
    if not applied:
        return False
    
    # Find the last edit operation and check if view_render_output was called after
    last_edit_index = -1
    last_view_index = -1
    
    for i, entry in enumerate(trace):
        tool_name = entry.get("tool", "")
        if tool_name == "apply_timeline_patch":
            result = entry.get("result", {})
            if result.get("success") or result.get("applied"):
                last_edit_index = i
        elif tool_name == "view_render_output":
            last_view_index = i
    
    # Verification needed if there was an edit but no view after it
    if last_edit_index >= 0:
        return last_view_index < last_edit_index
    
    return False


def _build_progress_context(
    iteration: int,
    trace: list[dict],
    applied: bool,
    max_iterations: int,
) -> str | None:
    """Build a progress context message for injection at each iteration.
    
    Returns None for the first iteration (no progress to report).
    """
    if iteration == 0:
        return None
    
    # Collect tools used
    tools_used = [entry.get("tool", "unknown") for entry in trace]
    unique_tools = list(dict.fromkeys(tools_used))  # preserve order, remove duplicates
    
    # Check verification status
    has_edits = any(
        entry.get("tool") == "apply_timeline_patch" and 
        (entry.get("result", {}).get("success") or entry.get("result", {}).get("applied"))
        for entry in trace
    )
    has_verification = any(entry.get("tool") == "view_render_output" for entry in trace)
    
    # Build context message
    remaining = f"{max_iterations - iteration} remaining" if max_iterations > 0 else "unlimited"
    
    parts = [
        f"[PROGRESS UPDATE - Iteration {iteration + 1}, {remaining}]",
        f"Tools used so far: {', '.join(unique_tools) if unique_tools else 'none'}",
    ]
    
    if has_edits and not has_verification:
        parts.append("REMINDER: Edits applied but NOT verified. Call render_timeline + view_render_output before completing.")
    elif has_edits and has_verification:
        parts.append("✓ Edits verified.")
    
    return "\n".join(parts)


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


def orchestrate_edit(
    project_id: UUID | str,
    user_id: UUID | str,
    request: EditRequest,
    db: Session,
) -> EditAgentResult:
    try:
        project_uuid = (
            project_id if isinstance(project_id, UUID) else UUID(str(project_id))
        )
    except ValueError as exc:
        raise SessionNotFoundError(f"Invalid project ID: {project_id}") from exc

    try:
        user_uuid = user_id if isinstance(user_id, UUID) else UUID(str(user_id))
    except ValueError as exc:
        raise SessionNotFoundError("Invalid user ID") from exc

    timeline = (
        db.query(Timeline).filter(Timeline.project_id == project_uuid).first()
    )
    if not timeline:
        raise SessionNotFoundError("Timeline not found for project")

    session_record = None
    if request.session_id:
        session_record = (
            db.query(EditSession)
            .filter(EditSession.session_id == request.session_id)
            .first()
        )
        if not session_record:
            raise SessionNotFoundError(request.session_id)
        if session_record.project_id != project_uuid:
            raise SessionNotFoundError(request.session_id)
        if session_record.status != "active":
            raise SessionClosedError(request.session_id)
    else:
        session_record = EditSession(
            session_id=uuid4(),
            project_id=project_uuid,
            timeline_id=timeline.timeline_id,
            created_by=user_uuid,
            title=request.message[:80],
            messages=[],
            pending_patches=[],
            status="active",
        )
        db.add(session_record)
        db.commit()
        db.refresh(session_record)

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    history = list(session_record.messages or [])
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": request.message})
    _log_payload("user_message", request.message)

    client = _get_client()
    trace: list[dict] = []
    warnings: list[str] = []
    pending_patch_entries: list[dict] = []
    applied = False
    new_version = None
    final_content = ""

    iteration = 0
    while True:
        if MAX_ITERATIONS > 0 and iteration >= MAX_ITERATIONS:
            logger.warning("Edit agent max iterations reached")
            break
        logger.debug("Edit agent iteration %s", iteration + 1)
        
        # Inject progress context for iterations after the first
        progress_context = _build_progress_context(iteration, trace, applied, MAX_ITERATIONS)
        if progress_context:
            messages.append({
                "role": "user",
                "content": progress_context,
            })
        
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as exc:
            logger.error(f"OpenRouter API error: {exc}")
            break

        message = response.choices[0].message
        final_content = message.content or ""
        _log_payload("assistant_message", final_content)

        reasoning = getattr(message, "reasoning", None)
        if not reasoning:
            model_extra = getattr(message, "model_extra", None)
            if isinstance(model_extra, dict):
                reasoning = model_extra.get("reasoning")
        if reasoning:
            _log_payload("assistant_reasoning", reasoning)

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": message.content}
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

        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                _log_payload(
                    "tool_call",
                    {"name": tool_name, "arguments": tool_args},
                )

                trace_entry = {
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": tool_args,
                }

                result = execute_tool(
                    tool_name=tool_name,
                    arguments=tool_args,
                    project_id=str(project_uuid),
                    user_id=str(user_uuid),
                    timeline_id=str(session_record.timeline_id),
                    db=db,
                )

                trace_entry["result"] = result
                trace.append(trace_entry)

                _log_payload(
                    "tool_result",
                    {"name": tool_name, "result": result},
                )

                if tool_name == "edit_timeline":
                    applied = result.get("applied", applied)
                    new_version = result.get("new_version", new_version)
                    warnings.extend(result.get("warnings", []))
                    if result.get("errors"):
                        warnings.extend(result["errors"])
                elif result.get("error"):
                    warnings.append(f"{tool_name}: {result['error']}")

                # Handle multimodal content in tool results
                multimodal = result.pop("_multimodal", None)
                
                # Always append the tool result as text first
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })
                
                # If there's multimodal content, inject it as a user message
                if multimodal:
                    mm_type = multimodal.get("type", "video")
                    content_type = multimodal.get("content_type", "video/mp4")
                    b64_data = multimodal.get("data", "")

                    if mm_type == "image":
                        content_block = {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{content_type};base64,{b64_data}",
                            },
                        }
                    elif mm_type == "audio":
                        content_block = {
                            "type": "audio_url",
                            "audio_url": {
                                "url": f"data:{content_type};base64,{b64_data}",
                            },
                        }
                    else:
                        # Video content
                        content_block = {
                            "type": "video_url",
                            "video_url": {
                                "url": f"data:{content_type};base64,{b64_data}",
                            },
                        }

                    messages.append({
                        "role": "user",
                        "content": [
                            content_block,
                            {
                                "type": "text",
                                "text": f"Here is the visual content from {tool_name}. Please examine it carefully.",
                            },
                        ],
                    })

        if response.choices[0].finish_reason == "stop" and not message.tool_calls:
            break

        iteration += 1

    # Verification enforcement: if edits were made but not verified, give agent one more chance
    if _check_verification_needed(trace, applied):
        if MAX_ITERATIONS <= 0 or iteration < MAX_ITERATIONS:
            logger.info("Verification needed - injecting enforcement prompt")
            messages.append({
                "role": "user",
                "content": VERIFICATION_ENFORCEMENT_PROMPT,
            })
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
                message = response.choices[0].message
                
                # Process any tool calls from verification iteration
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            tool_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            tool_args = {}
                        
                        result = execute_tool(
                            tool_name,
                            tool_args,
                            str(project_uuid),
                            str(user_uuid),
                            str(timeline.timeline_id),
                            db,
                        )
                        trace.append({
                            "tool": tool_name,
                            "args": tool_args,
                            "result": result,
                        })
            except Exception as exc:
                logger.error(f"Verification iteration error: {exc}")
        else:
            # Max iterations reached, add warning
            warnings.append(
                "Edits were applied but verification was skipped due to iteration limit. "
                "Consider using view_render_output to verify the changes."
            )

    # Make a final call with structured output to ensure clean response format
    final_payload = _get_structured_final_response(
        client, messages, applied, new_version, warnings
    )
    final_message = final_payload.get("message", "Edit completed.")
    applied = final_payload.get("applied", applied)
    new_version = final_payload.get("new_version", new_version)
    
    _log_payload(
        "final_response",
        {
            "message": final_message,
            "applied": applied,
            "new_version": new_version,
            "warnings": warnings,
        },
    )

    existing_messages = list(session_record.messages or [])
    session_record.messages = existing_messages + _serialize_messages(
        [
            EditMessage(
                role="user",
                content=request.message,
                created_at=datetime.now(timezone.utc),
            ),
            EditMessage(
                role="assistant",
                content=final_message,
                created_at=datetime.now(timezone.utc),
            ),
        ]
    )
    if pending_patch_entries:
        existing_patches = list(session_record.pending_patches or [])
        session_record.pending_patches = existing_patches + pending_patch_entries
    session_record.updated_at = datetime.now(timezone.utc)
    db.commit()

    _log_run(db, project_uuid, trace, pending_patch_entries, final_message)

    pending_patches = [
        PendingPatch(
            patch_id=p["patch_id"],
            agent_type=EditAgentType.EDIT_AGENT,
            patch=EditPatch(
                description=p.get("patch", {}).get("description", ""),
                operations=[
                    EditOperation.model_validate(op)
                    for op in p.get("patch", {}).get("operations", [])
                ],
            ),
            created_at=_parse_iso(p.get("created_at")) or datetime.now(timezone.utc),
        )
        for p in pending_patch_entries
    ]

    return EditAgentResult(
        session_id=str(session_record.session_id),
        message=final_message,
        pending_patches=pending_patches,
        warnings=warnings,
        applied=applied,
        new_version=new_version,
    )


def _history_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    history = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content")
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    return history


def _serialize_messages(messages: list[EditMessage]) -> list[dict[str, Any]]:
    return [
        {
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
        }
        for msg in messages
    ]


def _get_structured_final_response(
    client: OpenAI,
    messages: list[dict[str, Any]],
    applied: bool,
    new_version: int | None,
    warnings: list[str],
) -> dict[str, Any]:
    """
    Make a final API call with structured output to ensure clean response format.
    
    This uses the OpenAI response_format parameter to enforce JSON schema compliance,
    guaranteeing the response matches our expected structure without prose or markdown.
    """
    # Add a summary prompt to guide the final structured response
    summary_prompt = (
        "Provide your final response summarizing what was done. "
        f"The current state is: applied={applied}, new_version={new_version}, "
        f"warnings={warnings}. "
        "Be concise and focus on what changes were made to the timeline."
    )
    
    final_messages = messages + [{"role": "user", "content": summary_prompt}]
    
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=final_messages,
            response_format=FINAL_RESPONSE_SCHEMA,
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        
        # Validate and return the structured response
        final_response = AgentFinalResponse.model_validate(payload)
        return final_response.model_dump()
        
    except Exception as exc:
        logger.warning(f"Structured output failed, using fallback: {exc}")
        # Fallback: try to parse from the last message content
        last_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_content = msg["content"]
                break
        
        parsed = _parse_final_json(last_content)
        return {
            "message": _extract_final_message(parsed, last_content),
            "applied": parsed.get("applied", applied),
            "new_version": parsed.get("new_version", new_version),
            "warnings": warnings,
            "next_actions": parsed.get("next_actions", []),
        }


def _parse_final_json(content: str) -> dict[str, Any]:
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if not json_match:
            return {}
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


def _extract_final_message(final_payload: dict[str, Any], final_content: str) -> str:
    # Prefer the message from the parsed JSON payload
    payload_message = final_payload.get("message")
    if isinstance(payload_message, str) and payload_message.strip():
        return payload_message.strip()
    
    # If no valid message in payload, try to extract just the message from raw content
    # This handles cases where the agent outputs prose around the JSON
    if final_content.strip():
        # If the content looks like it contains JSON, don't return all the prose
        if "{" in final_content and "}" in final_content:
            # Try to extract just the message field from any JSON in the content
            message_match = re.search(r'"message"\s*:\s*"([^"]*)"', final_content)
            if message_match:
                return message_match.group(1).strip()
        # Fall back to the raw content only if it doesn't look like messy JSON output
        if not re.search(r'```|"applied"|"new_version"|"warnings"', final_content):
            return final_content.strip()
    
    return "Edit completed."


def _log_run(
    db: Session,
    project_id: UUID,
    trace: list[dict],
    pending_patches: list[dict],
    final_message: str,
) -> None:
    try:
        run = AgentRun(
            run_id=uuid4(),
            project_id=project_id,
            trace={
                "agent": "edit_agent",
                "iterations": len(
                    set(t.get("iteration", 0) for t in trace if "iteration" in t)
                ),
                "tool_calls": trace,
                "final_message": final_message,
            },
            analysis_segments=pending_patches,
        )
        db.add(run)
        db.commit()
    except Exception as exc:
        logger.error(f"Failed to log agent run: {exc}")
        db.rollback()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _log_payload(label: str, payload: Any) -> None:
    if not LOG_PAYLOADS:
        return
    if isinstance(payload, str):
        message = payload
    else:
        try:
            message = json.dumps(payload, default=str, ensure_ascii=True)
        except TypeError:
            message = str(payload)
    if LOG_MAX_CHARS > 0 and len(message) > LOG_MAX_CHARS:
        message = f"{message[:LOG_MAX_CHARS]}... [truncated]"
    logger.info("Edit agent %s: %s", label, message)
