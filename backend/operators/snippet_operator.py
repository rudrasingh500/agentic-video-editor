from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import (
    CharacterModel,
    CharacterModelIdentityLink,
    CharacterModelMergeEvent,
    CharacterModelSnippetLink,
    GenerationReferenceAnchor,
    IdentityMergeEvent,
    Snippet,
    SnippetIdentity,
    SnippetIdentityLink,
    SnippetMergeSuggestion,
)
from utils.gcs_utils import generate_signed_url, upload_file


ASSET_BUCKET = os.getenv("GCS_BUCKET", "video-editor")


def create_snippet(
    db: Session,
    project_id: UUID,
    snippet_type: str,
    source_type: str,
    source_ref: dict,
    asset_id: UUID | None = None,
    frame_index: int | None = None,
    timestamp_ms: int | None = None,
    bbox: dict | None = None,
    descriptor: str | None = None,
    embedding: list[float] | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    quality_score: float | None = None,
    crop_bytes: bytes | None = None,
    preview_bytes: bytes | None = None,
    created_by: str = "system",
) -> Snippet:
    snippet_id = uuid4()
    crop_blob_path = None
    preview_blob_path = None

    if crop_bytes:
        crop_blob_path = f"{project_id}/snippets/{snippet_id}/crop.jpg"
        upload_file(
            bucket_name=ASSET_BUCKET,
            contents=crop_bytes,
            destination_blob_name=crop_blob_path,
            content_type="image/jpeg",
        )

    if preview_bytes:
        preview_blob_path = f"{project_id}/snippets/{snippet_id}/preview.jpg"
        upload_file(
            bucket_name=ASSET_BUCKET,
            contents=preview_bytes,
            destination_blob_name=preview_blob_path,
            content_type="image/jpeg",
        )
    elif crop_bytes:
        preview_blob_path = crop_blob_path

    snippet = Snippet(
        snippet_id=snippet_id,
        project_id=project_id,
        asset_id=asset_id,
        snippet_type=snippet_type,
        source_type=source_type,
        source_ref=source_ref or {},
        frame_index=frame_index,
        timestamp_ms=timestamp_ms,
        bbox=bbox,
        crop_blob_path=crop_blob_path,
        preview_blob_path=preview_blob_path,
        descriptor=descriptor,
        embedding=embedding,
        tags=tags,
        notes=notes,
        quality_score=quality_score,
        created_by=created_by,
    )
    db.add(snippet)
    db.flush()
    return snippet


def list_snippets(
    db: Session,
    project_id: UUID,
    snippet_type: str | None = None,
    asset_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Snippet]:
    query = db.query(Snippet).filter(Snippet.project_id == project_id)
    if snippet_type:
        query = query.filter(Snippet.snippet_type == snippet_type)
    if asset_id:
        query = query.filter(Snippet.asset_id == asset_id)
    return query.order_by(Snippet.created_at.desc()).offset(offset).limit(limit).all()


def get_snippet(db: Session, project_id: UUID, snippet_id: UUID) -> Snippet | None:
    return db.query(Snippet).filter(
        Snippet.project_id == project_id,
        Snippet.snippet_id == snippet_id,
    ).first()


def get_snippet_preview_url(snippet: Snippet, expires_seconds: int = 3600) -> str | None:
    if not snippet.preview_blob_path:
        return None
    return generate_signed_url(
        bucket_name=ASSET_BUCKET,
        blob_name=snippet.preview_blob_path,
        expiration=None,
    )


def create_identity(
    db: Session,
    project_id: UUID,
    name: str,
    identity_type: str,
    description: str | None = None,
    snippet_ids: list[UUID] | None = None,
    created_by: str = "user",
) -> SnippetIdentity:
    identity = SnippetIdentity(
        identity_id=uuid4(),
        project_id=project_id,
        identity_type=identity_type,
        name=name,
        description=description,
        created_by=created_by,
    )
    db.add(identity)
    db.flush()

    if snippet_ids:
        snippets = db.query(Snippet).filter(
            Snippet.project_id == project_id,
            Snippet.snippet_id.in_(snippet_ids),
        ).all()
        for idx, snippet in enumerate(snippets):
            link = SnippetIdentityLink(
                link_id=uuid4(),
                project_id=project_id,
                snippet_id=snippet.snippet_id,
                identity_id=identity.identity_id,
                confidence=1.0,
                is_primary=(idx == 0),
                link_source=created_by,
                status="active",
                metadata_json={},
            )
            db.add(link)
            if idx == 0:
                identity.canonical_snippet_id = snippet.snippet_id
                identity.prototype_embedding = snippet.embedding

    db.flush()
    return identity


def list_identities(
    db: Session,
    project_id: UUID,
    identity_type: str | None = None,
    include_merged: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[SnippetIdentity]:
    query = db.query(SnippetIdentity).filter(SnippetIdentity.project_id == project_id)
    if identity_type:
        query = query.filter(SnippetIdentity.identity_type == identity_type)
    if not include_merged:
        query = query.filter(SnippetIdentity.merged_into_id.is_(None))
    return query.order_by(SnippetIdentity.updated_at.desc()).offset(offset).limit(limit).all()


def merge_identities(
    db: Session,
    project_id: UUID,
    source_identity_ids: list[UUID],
    target_identity_id: UUID,
    actor: str,
    reason: str | None = None,
) -> SnippetIdentity | None:
    target = db.query(SnippetIdentity).filter(
        SnippetIdentity.project_id == project_id,
        SnippetIdentity.identity_id == target_identity_id,
    ).first()
    if not target:
        return None

    for source_id in source_identity_ids:
        if source_id == target_identity_id:
            continue

        source = db.query(SnippetIdentity).filter(
            SnippetIdentity.project_id == project_id,
            SnippetIdentity.identity_id == source_id,
        ).first()
        if not source:
            continue

        source.merged_into_id = target.identity_id
        source.status = "merged"

        source_links = db.query(SnippetIdentityLink).filter(
            SnippetIdentityLink.identity_id == source.identity_id,
            SnippetIdentityLink.status == "active",
        ).all()
        for link in source_links:
            exists = db.query(SnippetIdentityLink).filter(
                SnippetIdentityLink.snippet_id == link.snippet_id,
                SnippetIdentityLink.identity_id == target.identity_id,
                SnippetIdentityLink.status == "active",
            ).first()
            if exists:
                continue
            db.add(
                SnippetIdentityLink(
                    link_id=uuid4(),
                    project_id=project_id,
                    snippet_id=link.snippet_id,
                    identity_id=target.identity_id,
                    confidence=link.confidence,
                    is_primary=False,
                    link_source=actor,
                    status="active",
                    metadata_json={"merged_from": str(source.identity_id)},
                )
            )

        db.add(
            IdentityMergeEvent(
                event_id=uuid4(),
                project_id=project_id,
                source_identity_id=source.identity_id,
                target_identity_id=target.identity_id,
                reason=reason,
                actor=actor,
                metadata_json={},
            )
        )

    target.updated_at = datetime.now(timezone.utc)
    db.flush()
    return target


def create_character_model(
    db: Session,
    project_id: UUID,
    name: str,
    model_type: str,
    description: str | None = None,
    canonical_prompt: str | None = None,
    identity_ids: list[UUID] | None = None,
    snippet_ids: list[UUID] | None = None,
    created_by: str = "user",
) -> CharacterModel:
    model = CharacterModel(
        character_model_id=uuid4(),
        project_id=project_id,
        model_type=model_type,
        name=name,
        description=description,
        canonical_prompt=canonical_prompt,
        created_by=created_by,
    )
    db.add(model)
    db.flush()

    if identity_ids:
        for identity_id in identity_ids:
            db.add(
                CharacterModelIdentityLink(
                    link_id=uuid4(),
                    character_model_id=model.character_model_id,
                    identity_id=identity_id,
                    role="primary",
                    metadata_json={},
                )
            )

    if snippet_ids:
        for idx, snippet_id in enumerate(snippet_ids):
            db.add(
                CharacterModelSnippetLink(
                    link_id=uuid4(),
                    character_model_id=model.character_model_id,
                    snippet_id=snippet_id,
                    role="reference",
                    metadata_json={},
                )
            )
            if idx == 0:
                model.canonical_snippet_id = snippet_id

    db.flush()
    return model


def list_character_models(
    db: Session,
    project_id: UUID,
    model_type: str | None = None,
    include_merged: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[CharacterModel]:
    query = db.query(CharacterModel).filter(CharacterModel.project_id == project_id)
    if model_type:
        query = query.filter(CharacterModel.model_type == model_type)
    if not include_merged:
        query = query.filter(CharacterModel.merged_into_id.is_(None))
    return query.order_by(CharacterModel.updated_at.desc()).offset(offset).limit(limit).all()


def merge_character_models(
    db: Session,
    project_id: UUID,
    source_model_ids: list[UUID],
    target_model_id: UUID,
    actor: str,
    reason: str | None = None,
) -> CharacterModel | None:
    target = db.query(CharacterModel).filter(
        CharacterModel.project_id == project_id,
        CharacterModel.character_model_id == target_model_id,
    ).first()
    if not target:
        return None

    for source_model_id in source_model_ids:
        if source_model_id == target_model_id:
            continue
        source = db.query(CharacterModel).filter(
            CharacterModel.project_id == project_id,
            CharacterModel.character_model_id == source_model_id,
        ).first()
        if not source:
            continue

        source.merged_into_id = target.character_model_id
        source.status = "merged"

        source_identity_links = db.query(CharacterModelIdentityLink).filter(
            CharacterModelIdentityLink.character_model_id == source.character_model_id
        ).all()
        for link in source_identity_links:
            exists = db.query(CharacterModelIdentityLink).filter(
                CharacterModelIdentityLink.character_model_id == target.character_model_id,
                CharacterModelIdentityLink.identity_id == link.identity_id,
            ).first()
            if not exists:
                db.add(
                    CharacterModelIdentityLink(
                        link_id=uuid4(),
                        character_model_id=target.character_model_id,
                        identity_id=link.identity_id,
                        role=link.role,
                        metadata_json={"merged_from": str(source.character_model_id)},
                    )
                )

        source_snippet_links = db.query(CharacterModelSnippetLink).filter(
            CharacterModelSnippetLink.character_model_id == source.character_model_id
        ).all()
        for link in source_snippet_links:
            exists = db.query(CharacterModelSnippetLink).filter(
                CharacterModelSnippetLink.character_model_id == target.character_model_id,
                CharacterModelSnippetLink.snippet_id == link.snippet_id,
            ).first()
            if not exists:
                db.add(
                    CharacterModelSnippetLink(
                        link_id=uuid4(),
                        character_model_id=target.character_model_id,
                        snippet_id=link.snippet_id,
                        role=link.role,
                        metadata_json={"merged_from": str(source.character_model_id)},
                    )
                )

        db.add(
            CharacterModelMergeEvent(
                event_id=uuid4(),
                project_id=project_id,
                source_model_id=source.character_model_id,
                target_model_id=target.character_model_id,
                reason=reason,
                actor=actor,
                metadata_json={},
            )
        )

    target.updated_at = datetime.now(timezone.utc)
    db.flush()
    return target


def attach_generation_anchor(
    db: Session,
    project_id: UUID,
    timeline_id: UUID | None,
    anchor_type: str,
    snippet_id: UUID | None,
    identity_id: UUID | None,
    character_model_id: UUID | None,
    request_context: dict,
    created_by: str,
) -> GenerationReferenceAnchor:
    anchor = GenerationReferenceAnchor(
        anchor_id=uuid4(),
        project_id=project_id,
        timeline_id=timeline_id,
        anchor_type=anchor_type,
        snippet_id=snippet_id,
        identity_id=identity_id,
        character_model_id=character_model_id,
        request_context=request_context or {},
        created_by=created_by,
    )
    db.add(anchor)
    db.flush()
    return anchor


def list_merge_suggestions(
    db: Session,
    project_id: UUID,
    decision: str = "pending",
    limit: int = 50,
) -> list[SnippetMergeSuggestion]:
    return db.query(SnippetMergeSuggestion).filter(
        SnippetMergeSuggestion.project_id == project_id,
        SnippetMergeSuggestion.decision == decision,
    ).order_by(SnippetMergeSuggestion.created_at.desc()).limit(limit).all()


def decide_merge_suggestion(
    db: Session,
    project_id: UUID,
    suggestion_id: UUID,
    decision: str,
    actor: str,
) -> SnippetMergeSuggestion | None:
    suggestion = db.query(SnippetMergeSuggestion).filter(
        SnippetMergeSuggestion.project_id == project_id,
        SnippetMergeSuggestion.suggestion_id == suggestion_id,
    ).first()
    if not suggestion:
        return None

    suggestion.decision = decision
    suggestion.decided_by = actor
    suggestion.decided_at = datetime.now(timezone.utc)

    if decision == "accepted":
        snippet = db.query(Snippet).filter(Snippet.snippet_id == suggestion.snippet_id).first()
        if snippet:
            exists = db.query(SnippetIdentityLink).filter(
                SnippetIdentityLink.snippet_id == snippet.snippet_id,
                SnippetIdentityLink.identity_id == suggestion.candidate_identity_id,
                SnippetIdentityLink.status == "active",
            ).first()
            if not exists:
                db.add(
                    SnippetIdentityLink(
                        link_id=uuid4(),
                        project_id=project_id,
                        snippet_id=snippet.snippet_id,
                        identity_id=suggestion.candidate_identity_id,
                        confidence=suggestion.similarity_score,
                        is_primary=True,
                        link_source=actor,
                        status="active",
                        metadata_json={"from_suggestion": str(suggestion.suggestion_id)},
                    )
                )

    db.flush()
    return suggestion


def best_identity_candidates(
    db: Session,
    project_id: UUID,
    snippet_id: UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    snippet = None
    if snippet_id:
        snippet = db.query(Snippet).filter(
            Snippet.project_id == project_id,
            Snippet.snippet_id == snippet_id,
        ).first()

    if not snippet or not snippet.embedding:
        identities = db.query(SnippetIdentity).filter(
            SnippetIdentity.project_id == project_id,
            SnippetIdentity.merged_into_id.is_(None),
        ).order_by(SnippetIdentity.updated_at.desc()).limit(limit).all()
        return [
            {
                "identity_id": str(identity.identity_id),
                "name": identity.name,
                "identity_type": identity.identity_type,
                "similarity": None,
            }
            for identity in identities
        ]

    rows = db.execute(
        text(
            """
            SELECT identity_id, name, identity_type,
                   1 - (prototype_embedding <=> :query_embedding) AS similarity
            FROM snippet_identities
            WHERE project_id = :project_id
              AND merged_into_id IS NULL
              AND prototype_embedding IS NOT NULL
            ORDER BY prototype_embedding <=> :query_embedding
            LIMIT :limit
            """
        ),
        {
            "query_embedding": str(snippet.embedding),
            "project_id": str(project_id),
            "limit": limit,
        },
    ).fetchall()

    return [
        {
            "identity_id": str(row.identity_id),
            "name": row.name,
            "identity_type": row.identity_type,
            "similarity": float(row.similarity),
        }
        for row in rows
    ]
