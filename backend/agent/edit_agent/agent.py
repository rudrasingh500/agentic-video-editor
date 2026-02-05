from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from openai import OpenAI
from sqlalchemy.orm import Session

from database.base import SessionLocal
from database.models import AgentRun, EditSession, Timeline

from .prompts import REFLECTION_PROMPT, SYSTEM_PROMPT, INTENT_CLASSIFICATION_PROMPT
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
MAX_CONTEXT_TOKENS = int(os.getenv("EDIT_AGENT_MAX_CONTEXT_TOKENS", "80000"))
PARALLEL_WORKERS = int(os.getenv("EDIT_AGENT_PARALLEL_WORKERS", "4"))
LOG_PAYLOADS = os.getenv("EDIT_AGENT_LOG_PAYLOADS", "").lower() in {"1", "true", "yes"}
LOG_MAX_CHARS = int(os.getenv("EDIT_AGENT_LOG_MAX_CHARS", "2000"))

PARALLEL_SAFE_TOOLS = {
    "list_assets_summaries",
    "get_asset_details",
    "search_by_tags",
    "search_transcript",
    "search_faces_speakers",
    "search_events_scenes",
    "search_objects",
    "semantic_search",
    "list_entities",
    "get_entity_details",
    "find_entity_appearances",
    "skills_registry",
    "get_timeline_snapshot",
    "compare_timeline_versions",
}

_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, PARALLEL_WORKERS))

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
                        },
                        "confidence_score": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Confidence that the edits achieved the intended goal"
                        },
                        "verification_method": {
                            "type": "string",
                            "enum": ["visual", "audio", "metadata", "automated", "combined"],
                            "description": "Primary verification method used"
                        },
                        "audio_verified": {
                            "type": "boolean",
                            "description": "Whether audio was explicitly checked"
                        },
                        "timeline_version_verified": {
                            "type": ["integer", "null"],
                            "description": "Timeline version that was verified"
                        },
                        "quality_metrics": {
                            "type": ["object", "null"],
                            "description": "Automated quality check results if available"
                        }
                    },
                    "required": ["render_viewed", "confidence_score", "verification_method"]
                }
            },
            "required": ["message", "applied", "new_version", "warnings", "next_actions", "verification"],
            "additionalProperties": False
        }
    }
}

INTENT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "edit_intent_classification",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "simple_edit",
                        "complex_sequence",
                        "search_first",
                        "info_only",
                    ],
                },
                "estimated_operations": {"type": "integer", "minimum": 0},
                "requires_search": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["intent", "estimated_operations", "requires_search", "confidence"],
            "additionalProperties": False,
        },
    },
}

# Verification enforcement prompt - injected if edits were made but not verified
VERIFICATION_ENFORCEMENT_PROMPT = """
IMPORTANT: You made edits to the timeline but have NOT verified them.

Before you can complete this task, you MUST:
1. Call render_output to render the current timeline
2. Call view_render_output to watch the result
3. (Optional) Call run_quality_checks for automated checks
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
        result = entry.get("result", {})
        if tool_name == "edit_timeline" and result.get("applied"):
            last_edit_index = i
        elif tool_name == "undo_to_version" and result.get("success"):
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
        (entry.get("tool") == "edit_timeline" and entry.get("result", {}).get("applied"))
        or (entry.get("tool") == "undo_to_version" and entry.get("result", {}).get("success"))
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
        parts.append(
            "REMINDER: Edits applied but NOT verified. Call render_output + view_render_output before completing."
        )
    elif has_edits and has_verification:
        parts.append("✓ Edits verified.")
    
    return "\n".join(parts)


def _get_client() -> OpenAI:
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


def _classify_intent(client: OpenAI, message: str) -> dict[str, Any]:
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format=INTENT_SCHEMA,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception as exc:
        logger.warning("Intent classification failed: %s", exc)
        return {
            "intent": "complex_sequence",
            "estimated_operations": 4,
            "requires_search": True,
            "confidence": 0.3,
        }


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    total_chars = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    total_chars += len(block.get("text", ""))
                else:
                    total_chars += 400
    return max(1, total_chars // 4)


def _truncate_messages(
    messages: list[dict[str, Any]],
    max_tokens: int,
    preserve_recent: int = 14,
) -> list[dict[str, Any]]:
    if max_tokens <= 0:
        return messages
    if _estimate_tokens(messages) <= max_tokens:
        return messages

    system_messages = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    tail = non_system[-preserve_recent:] if preserve_recent > 0 else []

    truncated = system_messages + tail
    return truncated


def _should_reflect(iteration: int, trace: list[dict]) -> bool:
    if iteration == 0:
        return False
    if trace:
        last_tool = trace[-1].get("tool")
        if last_tool in {"edit_timeline", "undo_to_version"}:
            return True
    return iteration % 3 == 0


def _build_reflection_context(trace: list[dict]) -> str:
    tools_used = [entry.get("tool", "unknown") for entry in trace]
    unique_tools = list(dict.fromkeys(tools_used))
    edits_applied = sum(
        1
        for entry in trace
        if entry.get("tool") in {"edit_timeline", "undo_to_version"}
    )
    return (
        f"{REFLECTION_PROMPT}\n"
        f"Tools used so far: {', '.join(unique_tools) if unique_tools else 'none'}\n"
        f"Edits applied so far: {edits_applied}"
    )


def _execute_tool_in_new_session(
    tool_name: str,
    tool_args: dict[str, Any],
    project_id: str,
    user_id: str,
    timeline_id: str,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return execute_tool(
            tool_name=tool_name,
            arguments=tool_args,
            project_id=project_id,
            user_id=user_id,
            timeline_id=timeline_id,
            db=db,
        )
    finally:
        db.close()


def _execute_tool_calls(
    tool_calls: list[tuple[Any, dict[str, Any]]],
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
) -> list[tuple[Any, dict[str, Any], dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}

    parallel_calls = [
        (tool_call, args)
        for tool_call, args in tool_calls
        if tool_call.function.name in PARALLEL_SAFE_TOOLS
    ]
    if parallel_calls:
        futures = {}
        for tool_call, args in parallel_calls:
            futures[
                _TOOL_EXECUTOR.submit(
                    _execute_tool_in_new_session,
                    tool_call.function.name,
                    args,
                    project_id,
                    user_id,
                    timeline_id,
                )
            ] = tool_call.id

        for future in as_completed(futures):
            tool_call_id = futures[future]
            try:
                results[tool_call_id] = future.result()
            except Exception as exc:
                results[tool_call_id] = {"error": str(exc)}

    for tool_call, args in tool_calls:
        if tool_call.id in results:
            continue
        results[tool_call.id] = execute_tool(
            tool_name=tool_call.function.name,
            arguments=args,
            project_id=project_id,
            user_id=user_id,
            timeline_id=timeline_id,
            db=db,
        )

    ordered = []
    for tool_call, args in tool_calls:
        ordered.append((tool_call, args, results.get(tool_call.id, {"error": "No result"})))
    return ordered


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
    intent = _classify_intent(client, request.message)
    max_iterations = MAX_ITERATIONS
    if intent.get("intent") == "simple_edit":
        max_iterations = 5 if MAX_ITERATIONS <= 0 else min(MAX_ITERATIONS, 5)
    elif intent.get("intent") == "info_only":
        max_iterations = 3 if MAX_ITERATIONS <= 0 else min(MAX_ITERATIONS, 3)
    trace: list[dict] = []
    warnings: list[str] = []
    pending_patch_entries: list[dict] = []
    applied = False
    new_version = None
    final_content = ""

    iteration = 0
    while True:
        if max_iterations > 0 and iteration >= max_iterations:
            logger.warning("Edit agent max iterations reached")
            break
        logger.debug("Edit agent iteration %s", iteration + 1)
        
        # Inject progress context for iterations after the first
        progress_context = _build_progress_context(iteration, trace, applied, max_iterations)
        if progress_context:
            messages.append({
                "role": "user",
                "content": progress_context,
            })

        if _should_reflect(iteration, trace):
            messages.append({
                "role": "user",
                "content": _build_reflection_context(trace),
            })

        messages = _truncate_messages(messages, MAX_CONTEXT_TOKENS)
        
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
            parsed_calls: list[tuple[Any, dict[str, Any]]] = []
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                parsed_calls.append((tool_call, tool_args))
                _log_payload(
                    "tool_call",
                    {"name": tool_name, "arguments": tool_args},
                )

            tool_results = _execute_tool_calls(
                parsed_calls,
                project_id=str(project_uuid),
                user_id=str(user_uuid),
                timeline_id=str(session_record.timeline_id),
                db=db,
            )

            for tool_call, tool_args, result in tool_results:
                tool_name = tool_call.function.name
                trace_entry = {
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": tool_args,
                }

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
                    if result.get("rolled_back"):
                        rollback_target = result.get("rollback_target_version")
                        if rollback_target is not None:
                            warnings.append(
                                f"Patch rolled back to version {rollback_target}."
                            )
                elif tool_name == "undo_to_version" and result.get("success"):
                    applied = True
                    new_version = result.get("new_version", new_version)
                elif tool_name == "run_quality_checks":
                    issues = result.get("issues_detected") if isinstance(result, dict) else None
                    if issues:
                        warnings.extend([f"quality_check: {issue}" for issue in issues])
                elif result.get("error"):
                    warnings.append(f"{tool_name}: {result['error']}")

                # Handle multimodal content in tool results
                result_payload = dict(result)
                multimodal = result_payload.pop("_multimodal", None)

                # Always append the tool result as text first
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result_payload),
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
        if max_iterations <= 0 or iteration < max_iterations:
            logger.info("Verification needed - injecting enforcement prompt")
            messages.append({
                "role": "user",
                "content": VERIFICATION_ENFORCEMENT_PROMPT,
            })
            try:
                messages = _truncate_messages(messages, MAX_CONTEXT_TOKENS)
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
        client,
        _truncate_messages(messages, MAX_CONTEXT_TOKENS),
        applied,
        new_version,
        warnings,
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
    final_messages = _truncate_messages(final_messages, MAX_CONTEXT_TOKENS)
    
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
