from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import CharacterModel, Project, SnippetIdentity
from dependencies.project import require_project
from models.api_models import (
    AttachGenerationAnchorRequest,
    AttachGenerationAnchorResponse,
    BestIdentityCandidatesResponse,
    CharacterModelCreateRequest,
    CharacterModelDetailResponse,
    CharacterModelListResponse,
    CharacterModelMergeRequest,
    CharacterModelMergeResponse,
    CharacterModelResponse,
    IdentityCreateRequest,
    IdentityDetailResponse,
    IdentityListResponse,
    IdentityMergeRequest,
    IdentityMergeResponse,
    IdentityResponse,
    SnippetCreateRequest,
    SnippetDetailResponse,
    SnippetListResponse,
    SnippetMergeDecisionRequest,
    SnippetMergeDecisionResponse,
    SnippetMergeSuggestionResponse,
    SnippetResponse,
)
from operators.snippet_operator import (
    attach_generation_anchor,
    best_identity_candidates,
    create_character_model,
    create_identity,
    create_snippet,
    decide_merge_suggestion,
    get_snippet,
    get_snippet_preview_url,
    list_character_models,
    list_identities,
    list_merge_suggestions,
    list_snippets,
    merge_character_models,
    merge_identities,
)


router = APIRouter(prefix="/projects/{project_id}/snippets", tags=["snippets"])


def _snippet_to_response(snippet) -> SnippetResponse:
    return SnippetResponse(
        snippet_id=str(snippet.snippet_id),
        project_id=str(snippet.project_id),
        asset_id=str(snippet.asset_id) if snippet.asset_id else None,
        snippet_type=snippet.snippet_type,
        source_type=snippet.source_type,
        source_ref=snippet.source_ref or {},
        frame_index=snippet.frame_index,
        timestamp_ms=snippet.timestamp_ms,
        bbox=snippet.bbox,
        descriptor=snippet.descriptor,
        tags=snippet.tags or [],
        notes=snippet.notes,
        quality_score=snippet.quality_score,
        created_by=snippet.created_by,
        created_at=snippet.created_at,
    )


def _identity_to_response(identity: SnippetIdentity) -> IdentityResponse:
    return IdentityResponse(
        identity_id=str(identity.identity_id),
        project_id=str(identity.project_id),
        identity_type=identity.identity_type,
        name=identity.name,
        description=identity.description,
        status=identity.status,
        canonical_snippet_id=(str(identity.canonical_snippet_id) if identity.canonical_snippet_id else None),
        merged_into_id=str(identity.merged_into_id) if identity.merged_into_id else None,
        created_by=identity.created_by,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
    )


def _character_model_to_response(model: CharacterModel) -> CharacterModelResponse:
    return CharacterModelResponse(
        character_model_id=str(model.character_model_id),
        project_id=str(model.project_id),
        model_type=model.model_type,
        name=model.name,
        description=model.description,
        canonical_prompt=model.canonical_prompt,
        status=model.status,
        canonical_snippet_id=str(model.canonical_snippet_id) if model.canonical_snippet_id else None,
        merged_into_id=str(model.merged_into_id) if model.merged_into_id else None,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.post("", response_model=SnippetDetailResponse)
async def create_snippet_endpoint(
    body: SnippetCreateRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    snippet = create_snippet(
        db=db,
        project_id=project.project_id,
        snippet_type=body.snippet_type,
        source_type=body.source_type,
        source_ref=body.source_ref,
        asset_id=UUID(body.asset_id) if body.asset_id else None,
        frame_index=body.frame_index,
        timestamp_ms=body.timestamp_ms,
        bbox=body.bbox,
        descriptor=body.descriptor,
        embedding=body.embedding,
        tags=body.tags,
        notes=body.notes,
        quality_score=body.quality_score,
        created_by=body.created_by,
    )
    db.commit()
    db.refresh(snippet)
    return SnippetDetailResponse(ok=True, snippet=_snippet_to_response(snippet), preview_url=get_snippet_preview_url(snippet))


@router.get("", response_model=SnippetListResponse)
async def list_snippets_endpoint(
    snippet_type: str | None = None,
    asset_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    snippets = list_snippets(
        db=db,
        project_id=project.project_id,
        snippet_type=snippet_type,
        asset_id=asset_id,
        limit=limit,
        offset=offset,
    )
    return SnippetListResponse(ok=True, snippets=[_snippet_to_response(s) for s in snippets])


@router.get("/items/{snippet_id}", response_model=SnippetDetailResponse)
async def get_snippet_endpoint(
    snippet_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    snippet = get_snippet(db, project.project_id, snippet_id)
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return SnippetDetailResponse(ok=True, snippet=_snippet_to_response(snippet), preview_url=get_snippet_preview_url(snippet))


@router.post("/identities", response_model=IdentityDetailResponse)
async def create_identity_endpoint(
    body: IdentityCreateRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    identity = create_identity(
        db=db,
        project_id=project.project_id,
        name=body.name,
        identity_type=body.identity_type,
        description=body.description,
        snippet_ids=[UUID(sid) for sid in body.snippet_ids] if body.snippet_ids else None,
        created_by=body.created_by,
    )
    db.commit()
    db.refresh(identity)
    return IdentityDetailResponse(ok=True, identity=_identity_to_response(identity))


@router.get("/identities", response_model=IdentityListResponse)
async def list_identities_endpoint(
    identity_type: str | None = None,
    include_merged: bool = False,
    limit: int = 50,
    offset: int = 0,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    identities = list_identities(
        db=db,
        project_id=project.project_id,
        identity_type=identity_type,
        include_merged=include_merged,
        limit=limit,
        offset=offset,
    )
    return IdentityListResponse(ok=True, identities=[_identity_to_response(i) for i in identities])


@router.get("/identities/{identity_id}", response_model=IdentityDetailResponse)
async def get_identity_endpoint(
    identity_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    identity = db.query(SnippetIdentity).filter(
        SnippetIdentity.project_id == project.project_id,
        SnippetIdentity.identity_id == identity_id,
    ).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    return IdentityDetailResponse(ok=True, identity=_identity_to_response(identity))


@router.post("/identities/merge", response_model=IdentityMergeResponse)
async def merge_identities_endpoint(
    body: IdentityMergeRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    merged = merge_identities(
        db=db,
        project_id=project.project_id,
        source_identity_ids=[UUID(item) for item in body.source_identity_ids],
        target_identity_id=UUID(body.target_identity_id),
        actor=body.actor,
        reason=body.reason,
    )
    if not merged:
        raise HTTPException(status_code=404, detail="Target identity not found")
    db.commit()
    db.refresh(merged)
    return IdentityMergeResponse(ok=True, identity=_identity_to_response(merged))


@router.post("/character-models", response_model=CharacterModelDetailResponse)
async def create_character_model_endpoint(
    body: CharacterModelCreateRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    model = create_character_model(
        db=db,
        project_id=project.project_id,
        name=body.name,
        model_type=body.model_type,
        description=body.description,
        canonical_prompt=body.canonical_prompt,
        identity_ids=[UUID(iid) for iid in body.identity_ids] if body.identity_ids else None,
        snippet_ids=[UUID(sid) for sid in body.snippet_ids] if body.snippet_ids else None,
        created_by=body.created_by,
    )
    db.commit()
    db.refresh(model)
    return CharacterModelDetailResponse(ok=True, character_model=_character_model_to_response(model))


@router.get("/character-models", response_model=CharacterModelListResponse)
async def list_character_models_endpoint(
    model_type: str | None = None,
    include_merged: bool = False,
    limit: int = 50,
    offset: int = 0,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    models = list_character_models(
        db=db,
        project_id=project.project_id,
        model_type=model_type,
        include_merged=include_merged,
        limit=limit,
        offset=offset,
    )
    return CharacterModelListResponse(ok=True, character_models=[_character_model_to_response(m) for m in models])


@router.get("/character-models/{character_model_id}", response_model=CharacterModelDetailResponse)
async def get_character_model_endpoint(
    character_model_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    model = db.query(CharacterModel).filter(
        CharacterModel.project_id == project.project_id,
        CharacterModel.character_model_id == character_model_id,
    ).first()
    if not model:
        raise HTTPException(status_code=404, detail="Character model not found")
    return CharacterModelDetailResponse(ok=True, character_model=_character_model_to_response(model))


@router.post("/character-models/merge", response_model=CharacterModelMergeResponse)
async def merge_character_models_endpoint(
    body: CharacterModelMergeRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    merged = merge_character_models(
        db=db,
        project_id=project.project_id,
        source_model_ids=[UUID(item) for item in body.source_model_ids],
        target_model_id=UUID(body.target_model_id),
        actor=body.actor,
        reason=body.reason,
    )
    if not merged:
        raise HTTPException(status_code=404, detail="Target character model not found")
    db.commit()
    db.refresh(merged)
    return CharacterModelMergeResponse(ok=True, character_model=_character_model_to_response(merged))


@router.get("/merge-suggestions", response_model=SnippetMergeSuggestionResponse)
async def list_merge_suggestions_endpoint(
    decision: str = "pending",
    limit: int = 50,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    suggestions = list_merge_suggestions(db, project.project_id, decision=decision, limit=limit)
    return SnippetMergeSuggestionResponse(
        ok=True,
        suggestions=[
            {
                "suggestion_id": str(item.suggestion_id),
                "snippet_id": str(item.snippet_id),
                "candidate_identity_id": str(item.candidate_identity_id),
                "similarity_score": item.similarity_score,
                "decision": item.decision,
                "metadata": item.metadata_json or {},
                "created_at": item.created_at,
            }
            for item in suggestions
        ],
    )


@router.post("/merge-suggestions/{suggestion_id}/decision", response_model=SnippetMergeDecisionResponse)
async def decide_merge_suggestion_endpoint(
    suggestion_id: UUID,
    body: SnippetMergeDecisionRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    suggestion = decide_merge_suggestion(
        db=db,
        project_id=project.project_id,
        suggestion_id=suggestion_id,
        decision=body.decision,
        actor=body.actor,
    )
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    db.commit()
    return SnippetMergeDecisionResponse(ok=True, suggestion_id=str(suggestion.suggestion_id), decision=suggestion.decision)


@router.post("/generation-anchor", response_model=AttachGenerationAnchorResponse)
async def attach_generation_anchor_endpoint(
    body: AttachGenerationAnchorRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    anchor = attach_generation_anchor(
        db=db,
        project_id=project.project_id,
        timeline_id=UUID(body.timeline_id) if body.timeline_id else None,
        anchor_type=body.anchor_type,
        snippet_id=UUID(body.snippet_id) if body.snippet_id else None,
        identity_id=UUID(body.identity_id) if body.identity_id else None,
        character_model_id=UUID(body.character_model_id) if body.character_model_id else None,
        request_context=body.request_context,
        created_by=body.created_by,
    )
    db.commit()
    return AttachGenerationAnchorResponse(ok=True, anchor_id=str(anchor.anchor_id))


@router.get("/generation-candidates", response_model=BestIdentityCandidatesResponse)
async def generation_candidates_endpoint(
    snippet_id: UUID | None = None,
    limit: int = 5,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    candidates = best_identity_candidates(
        db=db,
        project_id=project.project_id,
        snippet_id=snippet_id,
        limit=limit,
    )
    return BestIdentityCandidatesResponse(ok=True, candidates=candidates)
