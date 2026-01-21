from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from agent.asset_retrieval.agent import find_assets
from database.models import Assets
from models.render_models import RenderJobStatus, RenderJobType, RenderPreset, RenderRequest
from operators.render_operator import create_render_job, dispatch_render_job, poll_job_status
from utils.gcs_utils import generate_signed_url, parse_gcs_url

from .skill_executor import SkillExecutionError, execute_skill


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_assets",
            "description": "Find relevant assets for the edit request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
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
            "name": "execute_edit",
            "description": "Execute a specific edit skill using JSON arguments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string"},
                    "arguments": {"type": "object"},
                    "apply": {"type": "boolean", "default": True},
                },
                "required": ["skill_id", "arguments"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_asset",
            "description": "Get a signed URL to view an asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {"type": "string"},
                    "t0_ms": {"type": "number"},
                    "t1_ms": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_output",
            "description": "Render a preview output and return a signed URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timeline_version": {"type": "integer"},
                    "preset": {"type": "object"},
                    "wait": {"type": "boolean", "default": True},
                },
                "required": [],
            },
        },
    },
]


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
) -> dict[str, Any]:
    tool_map = {
        "retrieve_assets": _retrieve_assets,
        "skills_registry": _skills_registry,
        "execute_edit": _execute_edit,
        "view_asset": _view_asset,
        "render_output": _render_output,
    }
    tool_fn = tool_map.get(tool_name)
    if not tool_fn:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return tool_fn(
            project_id=project_id,
            user_id=user_id,
            timeline_id=timeline_id,
            db=db,
            **arguments,
        )
    except Exception as exc:
        return {"error": str(exc)}


def _retrieve_assets(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    query: str,
) -> dict[str, Any]:
    result = find_assets(project_id=project_id, query=query, db=db)
    return {
        "candidates": [c.model_dump() for c in result.candidates],
        "trace": result.trace,
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
            "skills": [
                {
                    "id": s.id,
                    "title": s.title,
                    "summary": s.summary,
                    "subskills": [
                        {
                            "id": sub.id,
                            "title": sub.title,
                            "summary": sub.summary,
                        }
                        for sub in s.subskills
                    ],
                }
                for s in skills
            ]
        }
    if action == "read":
        if not skill_id:
            return {"error": "skill_id required for read"}
        skill = read_skill(skill_id.split(".")[0])
        if not skill:
            return {"error": f"Skill not found: {skill_id}"}
        sub = next((s for s in skill.subskills if s.id == skill_id), None)
        return {
            "id": skill.id,
            "title": skill.title,
            "summary": skill.summary,
            "subskill": sub.__dict__ if sub else None,
        }
    return {"error": f"Unknown action: {action}"}


def _execute_edit(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    skill_id: str,
    arguments: dict[str, Any],
    apply: bool = True,
) -> dict[str, Any]:
    try:
        result = execute_skill(
            skill_id=skill_id,
            arguments=arguments,
            db=db,
            timeline_id=UUID(timeline_id),
            actor="agent:edit_agent",
            apply=apply,
        )
    except SkillExecutionError as exc:
        return {"error": str(exc)}

    patch = {
        "patch_id": str(uuid4()),
        "agent_type": "edit_agent",
        "patch": {
            "description": result.description,
            "operations": [op.model_dump() for op in result.operations],
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    response = {
        "description": result.description,
        "operations": [op.model_dump() for op in result.operations],
        "warnings": result.warnings,
        "applied": apply,
        "new_version": result.new_version,
    }
    if not apply:
        response["pending_patch"] = patch
    return response


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
    asset = (
        db.query(Assets)
        .filter(Assets.project_id == project_id, Assets.asset_id == asset_id)
        .first()
    )
    if not asset:
        return {"error": f"Asset not found: {asset_id}"}

    asset_url_value = getattr(asset, "asset_url", None)
    asset_url = str(asset_url_value) if asset_url_value is not None else ""
    signed_url = _maybe_sign_url(asset_url)

    return {
        "asset_id": str(asset.asset_id),
        "asset_name": asset.asset_name,
        "asset_type": asset.asset_type,
        "asset_url": asset_url,
        "signed_url": signed_url,
        "t0_ms": t0_ms,
        "t1_ms": t1_ms,
        "reason": reason,
    }


def _render_output(
    project_id: str,
    user_id: str,
    timeline_id: str,
    db: Session,
    timeline_version: int | None = None,
    preset: dict[str, Any] | None = None,
    wait: bool = True,
) -> dict[str, Any]:
    request = RenderRequest(
        job_type=RenderJobType.PREVIEW,
        timeline_version=timeline_version,
        preset=RenderPreset.model_validate(preset) if preset else None,
        metadata={},
    )
    job = create_render_job(db, UUID(project_id), request, created_by=f"agent:{user_id}")
    job_id = UUID(str(job.job_id))
    job = dispatch_render_job(db, job_id)

    if wait:
        for _ in range(20):
            job = poll_job_status(db, job_id) or job
            if job.status in (
                RenderJobStatus.COMPLETED.value,
                RenderJobStatus.FAILED.value,
                RenderJobStatus.CANCELLED.value,
            ):
                break
            time.sleep(3)

    output_url = None
    output_url_value = getattr(job, "output_url", None)
    if output_url_value is not None:
        output_url = str(output_url_value)
    if output_url is None:
        output_filename_value = getattr(job, "output_filename", None)
        output_filename = (
            str(output_filename_value) if output_filename_value is not None else None
        )
        output_url = _default_render_url(project_id, output_filename)
    signed_url = _maybe_sign_url(output_url) if output_url else None

    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "output_url": output_url,
        "signed_url": signed_url,
    }


def _default_render_url(project_id: str, output_filename: str | None) -> str | None:
    if not output_filename:
        return None
    bucket = os.getenv("GCS_RENDER_BUCKET", "video-editor-renders")
    return f"gs://{bucket}/{project_id}/renders/{output_filename}"


def _maybe_sign_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = parse_gcs_url(url)
    if not parsed:
        return url
    bucket, blob = parsed
    return generate_signed_url(bucket, blob, expiration=timedelta(hours=1))
