from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import CharacterModel, Project, Snippet, SnippetIdentity, SnippetIdentityLink
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
    IdentityUpdateRequest,
    IdentityWithSnippetsResponse,
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
    list_identity_snippets_map,
    list_character_models,
    list_identities,
    list_merge_suggestions,
    list_snippets,
    merge_character_models,
    merge_identities,
    update_identity,
)


router = APIRouter(prefix="/projects/{project_id}/snippets", tags=["snippets"])


def _snippet_to_response(
    snippet,
    preview_url: str | None = None,
    identity_name: str | None = None,
    is_identity_poster: bool = False,
) -> SnippetResponse:
    display_label = None
    if identity_name:
        display_label = f"{identity_name} (Poster)" if is_identity_poster else identity_name

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
        identity_name=identity_name,
        is_identity_poster=is_identity_poster,
        display_label=display_label,
        preview_url=preview_url,
        created_by=snippet.created_by,
        created_at=snippet.created_at,
    )


def _snippet_identity_display_map(
    db: Session,
    project_id: UUID,
    snippet_ids: list[UUID],
) -> dict[UUID, tuple[str, bool]]:
    if not snippet_ids:
        return {}

    links = db.query(SnippetIdentityLink).filter(
        SnippetIdentityLink.project_id == project_id,
        SnippetIdentityLink.snippet_id.in_(snippet_ids),
        SnippetIdentityLink.status == "active",
    ).all()
    if not links:
        return {}

    identity_ids = list({link.identity_id for link in links})
    identities = db.query(SnippetIdentity).filter(
        SnippetIdentity.project_id == project_id,
        SnippetIdentity.identity_id.in_(identity_ids),
    ).all()
    identity_by_id = {identity.identity_id: identity for identity in identities}

    best_link_by_snippet: dict[UUID, SnippetIdentityLink] = {}
    for link in links:
        current = best_link_by_snippet.get(link.snippet_id)
        if current is None:
            best_link_by_snippet[link.snippet_id] = link
            continue
        current_rank = (1 if current.is_primary else 0, float(current.confidence or 0.0))
        link_rank = (1 if link.is_primary else 0, float(link.confidence or 0.0))
        if link_rank > current_rank:
            best_link_by_snippet[link.snippet_id] = link

    result: dict[UUID, tuple[str, bool]] = {}
    for snippet_id, link in best_link_by_snippet.items():
        identity = identity_by_id.get(link.identity_id)
        if not identity:
            continue
        is_poster = identity.canonical_snippet_id == snippet_id
        result[snippet_id] = (identity.name, bool(is_poster))
    return result


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
    preview_url = get_snippet_preview_url(snippet)
    return SnippetDetailResponse(
        ok=True,
        snippet=_snippet_to_response(snippet, preview_url=preview_url),
        preview_url=preview_url,
    )


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
    identity_map = _snippet_identity_display_map(
        db,
        project.project_id,
        [snippet.snippet_id for snippet in snippets],
    )
    return SnippetListResponse(
        ok=True,
        snippets=[
            _snippet_to_response(
                s,
                preview_url=get_snippet_preview_url(s),
                identity_name=(identity_map.get(s.snippet_id) or (None, False))[0],
                is_identity_poster=(identity_map.get(s.snippet_id) or (None, False))[1],
            )
            for s in snippets
        ],
    )


@router.get("/items/{snippet_id}", response_model=SnippetDetailResponse)
async def get_snippet_endpoint(
    snippet_id: UUID,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    snippet = get_snippet(db, project.project_id, snippet_id)
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    identity_map = _snippet_identity_display_map(db, project.project_id, [snippet.snippet_id])
    identity_name, is_poster = identity_map.get(snippet.snippet_id, (None, False))
    preview_url = get_snippet_preview_url(snippet)
    return SnippetDetailResponse(
        ok=True,
        snippet=_snippet_to_response(
            snippet,
            preview_url=preview_url,
            identity_name=identity_name,
            is_identity_poster=is_poster,
        ),
        preview_url=preview_url,
    )


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
    include_snippets: bool = False,
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
    if not include_snippets:
        return IdentityListResponse(ok=True, identities=[_identity_to_response(i) for i in identities])

    snippets_map = list_identity_snippets_map(
        db,
        project.project_id,
        [identity.identity_id for identity in identities],
    )
    response_items: list[IdentityResponse | IdentityWithSnippetsResponse] = []
    for identity in identities:
        identity_base = _identity_to_response(identity)
        linked_snippets = snippets_map.get(identity.identity_id, [])
        response_items.append(
            IdentityWithSnippetsResponse(
                **identity_base.model_dump(),
                snippets=[
                    _snippet_to_response(snippet, preview_url=get_snippet_preview_url(snippet))
                    for snippet in linked_snippets
                ],
            )
        )
    return IdentityListResponse(ok=True, identities=response_items)


@router.patch("/identities/{identity_id}", response_model=IdentityDetailResponse)
async def update_identity_endpoint(
    identity_id: UUID,
    body: IdentityUpdateRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    if body.name is None and body.description is None:
        raise HTTPException(status_code=400, detail="No identity updates provided")

    updated = update_identity(
        db=db,
        project_id=project.project_id,
        identity_id=identity_id,
        name=body.name,
        description=body.description,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Identity not found")

    db.commit()
    db.refresh(updated)
    return IdentityDetailResponse(ok=True, identity=_identity_to_response(updated))


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
    snippet_ids = [item.snippet_id for item in suggestions]
    candidate_ids = [item.candidate_identity_id for item in suggestions]

    snippets = db.query(Snippet).filter(
        Snippet.project_id == project.project_id,
        Snippet.snippet_id.in_(snippet_ids),
    ).all() if snippet_ids else []
    snippets_by_id = {snippet.snippet_id: snippet for snippet in snippets}

    identities = db.query(SnippetIdentity).filter(
        SnippetIdentity.project_id == project.project_id,
        SnippetIdentity.identity_id.in_(candidate_ids),
    ).all() if candidate_ids else []
    identities_by_id = {identity.identity_id: identity for identity in identities}

    canonical_snippet_ids = [
        identity.canonical_snippet_id
        for identity in identities
        if identity.canonical_snippet_id is not None
    ]
    canonical_snippets = db.query(Snippet).filter(
        Snippet.project_id == project.project_id,
        Snippet.snippet_id.in_(canonical_snippet_ids),
    ).all() if canonical_snippet_ids else []
    canonical_by_id = {snippet.snippet_id: snippet for snippet in canonical_snippets}

    return SnippetMergeSuggestionResponse(
        ok=True,
        suggestions=[
            {
                **{
                    "suggestion_id": str(item.suggestion_id),
                    "snippet_id": str(item.snippet_id),
                    "candidate_identity_id": str(item.candidate_identity_id),
                    "similarity_score": item.similarity_score,
                    "decision": item.decision,
                    "metadata": item.metadata_json or {},
                    "created_at": item.created_at,
                },
                **{
                    "snippet_preview_url": get_snippet_preview_url(snippets_by_id[item.snippet_id])
                    if item.snippet_id in snippets_by_id
                    else None,
                    "candidate_identity_name": (
                        identities_by_id[item.candidate_identity_id].name
                        if item.candidate_identity_id in identities_by_id
                        else None
                    ),
                    "candidate_identity_canonical_snippet_id": (
                        str(identities_by_id[item.candidate_identity_id].canonical_snippet_id)
                        if (
                            item.candidate_identity_id in identities_by_id
                            and identities_by_id[item.candidate_identity_id].canonical_snippet_id
                        )
                        else None
                    ),
                    "candidate_identity_preview_url": (
                        get_snippet_preview_url(
                            canonical_by_id[
                                identities_by_id[item.candidate_identity_id].canonical_snippet_id
                            ]
                        )
                        if (
                            item.candidate_identity_id in identities_by_id
                            and identities_by_id[item.candidate_identity_id].canonical_snippet_id
                            in canonical_by_id
                        )
                        else None
                    ),
                },
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
