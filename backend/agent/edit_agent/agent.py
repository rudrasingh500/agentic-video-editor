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
MAX_ITERATIONS = 20
LOG_PAYLOADS = os.getenv("EDIT_AGENT_LOG_PAYLOADS", "").lower() in {"1", "true", "yes"}
LOG_MAX_CHARS = int(os.getenv("EDIT_AGENT_LOG_MAX_CHARS", "2000"))


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

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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

    for iteration in range(MAX_ITERATIONS):
        logger.debug(f"Edit agent iteration {iteration + 1}/{MAX_ITERATIONS}")
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

                if tool_name == "execute_edit":
                    applied = result.get("applied", applied)
                    new_version = result.get("new_version", new_version)
                    warnings.extend(result.get("warnings", []))
                    if result.get("pending_patch"):
                        pending_patch_entries.append(result["pending_patch"])

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    }
                )

            remaining = MAX_ITERATIONS - iteration - 1
            messages.append(
                {
                    "role": "user",
                    "content": _iteration_notice(iteration + 1, remaining),
                }
            )

        if response.choices[0].finish_reason == "stop" and not message.tool_calls:
            break

    final_payload = _parse_final_json(final_content)
    final_message = final_payload.get("message", final_content or "")
    applied = final_payload.get("applied", applied)
    new_version = final_payload.get("new_version", new_version)
    warnings.extend(final_payload.get("warnings", []))
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


def _iteration_notice(iteration: int, remaining: int) -> str:
    notice = (
        f"[System: Iteration {iteration}/{MAX_ITERATIONS} complete. "
        f"{remaining} iterations remaining. "
    )
    if remaining <= 2:
        notice += "URGENT: You must return your final JSON response now."
    elif remaining <= 5:
        notice += "You are running low on iterations."
    notice += "]"
    return notice


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
