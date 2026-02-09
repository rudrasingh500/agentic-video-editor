from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import SessionData, get_session
from dependencies.project import require_project
from models.api_models import (
    AssetResponse,
    GenerationCreateRequest,
    GenerationCreateResponse,
    GenerationDecisionRequest,
    GenerationDecisionResponse,
    GenerationDetailResponse,
    GenerationResponse,
)
from operators.generation_operator import (
    create_generation,
    decide_generation,
    get_asset_preview_url,
    get_generation,
    get_generation_assets,
)


router = APIRouter(prefix="/projects/{project_id}/generations", tags=["generations"])


def _coerce_frame_repeat_count(parameters: dict | None) -> int | None:
    if not parameters:
        return None
    value = parameters.get("frame_repeat_count")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _asset_to_response(asset) -> AssetResponse:
    return AssetResponse(
        asset_id=str(asset.asset_id),
        asset_name=asset.asset_name,
        asset_type=asset.asset_type,
        asset_url=asset.asset_url,
        uploaded_at=asset.uploaded_at,
        indexing_status=asset.indexing_status or "pending",
        indexing_error=asset.indexing_error,
        indexing_attempts=asset.indexing_attempts or 0,
    )


def _generation_to_response(db: Session, generation) -> GenerationResponse:
    generated_asset, applied_asset = get_generation_assets(db, generation)
    return GenerationResponse(
        generation_id=str(generation.generation_id),
        project_id=str(generation.project_id),
        timeline_id=str(generation.timeline_id) if generation.timeline_id else None,
        request_origin=generation.request_origin,
        requestor=generation.requestor,
        provider=generation.provider,
        model=generation.model,
        mode=generation.mode,
        status=generation.status,
        prompt=generation.prompt,
        parameters=generation.parameters or {},
        reference_asset_id=(
            str(generation.reference_asset_id) if generation.reference_asset_id else None
        ),
        reference_snippet_id=(
            str(generation.reference_snippet_id) if generation.reference_snippet_id else None
        ),
        reference_identity_id=(
            str(generation.reference_identity_id) if generation.reference_identity_id else None
        ),
        reference_character_model_id=(
            str(generation.reference_character_model_id)
            if generation.reference_character_model_id
            else None
        ),
        target_asset_id=str(generation.target_asset_id) if generation.target_asset_id else None,
        frame_range=generation.frame_range,
        frame_indices=generation.frame_indices,
        frame_repeat_count=_coerce_frame_repeat_count(generation.parameters),
        generated_asset=_asset_to_response(generated_asset) if generated_asset else None,
        generated_preview_url=get_asset_preview_url(generated_asset),
        applied_asset=_asset_to_response(applied_asset) if applied_asset else None,
        applied_preview_url=get_asset_preview_url(applied_asset),
        request_context=generation.request_context or {},
        decision_reason=generation.decision_reason,
        error_message=generation.error_message,
        created_at=generation.created_at,
        updated_at=generation.updated_at,
        decided_at=generation.decided_at,
        applied_at=generation.applied_at,
    )


def _requestor(session: SessionData) -> str:
    if session.user_id:
        return f"user:{session.user_id}"
    return "user:anonymous"


@router.post("", response_model=GenerationCreateResponse)
async def create_generation_endpoint(
    body: GenerationCreateRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        generation = create_generation(
            db=db,
            project_id=project.project_id,
            prompt=body.prompt,
            mode=body.mode,
            requestor=_requestor(session),
            request_origin="user",
            timeline_id=UUID(body.timeline_id) if body.timeline_id else None,
            target_asset_id=UUID(body.target_asset_id) if body.target_asset_id else None,
            frame_range=body.frame_range.model_dump() if body.frame_range else None,
            frame_indices=body.frame_indices,
            frame_repeat_count=body.frame_repeat_count,
            reference_asset_id=(
                UUID(body.reference_asset_id) if body.reference_asset_id else None
            ),
            reference_snippet_id=(
                UUID(body.reference_snippet_id) if body.reference_snippet_id else None
            ),
            reference_identity_id=(
                UUID(body.reference_identity_id) if body.reference_identity_id else None
            ),
            reference_character_model_id=(
                UUID(body.reference_character_model_id)
                if body.reference_character_model_id
                else None
            ),
            model=body.model,
            parameters=body.parameters,
            request_context=body.request_context,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return GenerationCreateResponse(
        ok=True,
        generation=_generation_to_response(db, generation),
    )


@router.post("/{generation_id}/decision", response_model=GenerationDecisionResponse)
async def decide_generation_endpoint(
    generation_id: UUID,
    body: GenerationDecisionRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    try:
        generation = decide_generation(
            db=db,
            project_id=project.project_id,
            generation_id=generation_id,
            decision=body.decision,
            decided_by=_requestor(session),
            reason=body.reason,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return GenerationDecisionResponse(
        ok=True,
        generation=_generation_to_response(db, generation),
    )


@router.get("/{generation_id}", response_model=GenerationDetailResponse)
async def get_generation_endpoint(
    generation_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    generation = get_generation(db, project.project_id, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return GenerationDetailResponse(
        ok=True,
        generation=_generation_to_response(db, generation),
    )
