from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models import (
    Snippet,
    SnippetIdentity,
    SnippetIdentityLink,
    SnippetMergeSuggestion,
)


logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r. Using default %.3f", name, raw, default)
        return default


STRICT_AUTO_ATTACH_MIN_SIM = _env_float("SNIPPET_AUTO_ATTACH_MIN_SIM", 0.955)
STRICT_AUTO_ATTACH_MIN_MARGIN = _env_float("SNIPPET_AUTO_ATTACH_MIN_MARGIN", 0.01)
STRICT_SUGGEST_MIN_SIM = _env_float("SNIPPET_SUGGEST_MIN_SIM", 0.95)

AUTO_LINKABLE_SNIPPET_TYPES = {"face", "item"}


def strict_auto_link_snippet(
    db: Session,
    snippet: Snippet,
    actor: str = "system:auto-linker",
) -> dict[str, Any]:
    if snippet.snippet_type not in AUTO_LINKABLE_SNIPPET_TYPES:
        return {
            "decision": "skipped",
            "reason": f"snippet_type_not_auto_linked:{snippet.snippet_type}",
        }

    if not snippet.embedding:
        return {"decision": "new_identity", "reason": "missing_embedding"}

    top_matches = _find_identity_candidates(
        db=db,
        project_id=str(snippet.project_id),
        identity_type="person" if snippet.snippet_type == "face" else "item",
        embedding=snippet.embedding,
    )

    top1 = top_matches[0] if top_matches else None
    top2 = top_matches[1] if len(top_matches) > 1 else None

    score1 = float(top1["similarity"]) if top1 else 0.0
    score2 = float(top2["similarity"]) if top2 else 0.0
    margin = score1 - score2

    if (
        top1
        and score1 >= STRICT_AUTO_ATTACH_MIN_SIM
        and margin >= STRICT_AUTO_ATTACH_MIN_MARGIN
    ):
        identity = db.query(SnippetIdentity).filter(
            SnippetIdentity.identity_id == top1["identity_id"],
            SnippetIdentity.project_id == snippet.project_id,
            SnippetIdentity.merged_into_id.is_(None),
        ).first()
        if not identity:
            return {"decision": "new_identity", "reason": "candidate_not_found"}

        _attach_snippet_to_identity(
            db=db,
            snippet=snippet,
            identity=identity,
            confidence=score1,
            link_source=actor,
            metadata_json={"policy": "strict_auto", "margin": margin},
        )
        return {
            "decision": "auto_attached",
            "identity_id": str(identity.identity_id),
            "similarity": score1,
            "margin": margin,
        }

    if top1 and score1 >= STRICT_SUGGEST_MIN_SIM:
        suggestion = SnippetMergeSuggestion(
            suggestion_id=uuid4(),
            project_id=snippet.project_id,
            snippet_id=snippet.snippet_id,
            candidate_identity_id=top1["identity_id"],
            similarity_score=score1,
            decision="pending",
            metadata_json={"policy": "strict_auto", "margin": margin},
        )
        db.add(suggestion)
        db.flush()
        return {
            "decision": "suggested",
            "suggestion_id": str(suggestion.suggestion_id),
            "identity_id": str(top1["identity_id"]),
            "similarity": score1,
            "margin": margin,
        }

    identity = _create_identity_for_snippet(db, snippet)
    _attach_snippet_to_identity(
        db=db,
        snippet=snippet,
        identity=identity,
        confidence=1.0,
        link_source=actor,
        metadata_json={"policy": "strict_auto", "reason": "new_identity"},
    )
    return {
        "decision": "new_identity",
        "identity_id": str(identity.identity_id),
        "similarity": score1,
        "margin": margin,
    }


def _find_identity_candidates(
    db: Session,
    project_id: str,
    identity_type: str,
    embedding: list[float],
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT
                identity_id,
                1 - (prototype_embedding <=> :query_embedding) AS similarity
            FROM snippet_identities
            WHERE project_id = :project_id
              AND identity_type = :identity_type
              AND merged_into_id IS NULL
              AND prototype_embedding IS NOT NULL
            ORDER BY prototype_embedding <=> :query_embedding
            LIMIT 5
            """
        ),
        {
            "query_embedding": str(embedding),
            "project_id": project_id,
            "identity_type": identity_type,
        },
    ).fetchall()
    return [
        {"identity_id": row.identity_id, "similarity": float(row.similarity)}
        for row in rows
    ]


def _create_identity_for_snippet(db: Session, snippet: Snippet) -> SnippetIdentity:
    identity_type = "person" if snippet.snippet_type == "face" else "item"
    identity = SnippetIdentity(
        identity_id=uuid4(),
        project_id=snippet.project_id,
        identity_type=identity_type,
        name=f"{identity_type.title()} {str(snippet.snippet_id)[:8]}",
        canonical_snippet_id=snippet.snippet_id,
        prototype_embedding=snippet.embedding,
        created_by="system:auto-linker",
    )
    db.add(identity)
    db.flush()
    return identity


def _attach_snippet_to_identity(
    db: Session,
    snippet: Snippet,
    identity: SnippetIdentity,
    confidence: float,
    link_source: str,
    metadata_json: dict[str, Any],
) -> None:
    existing = db.query(SnippetIdentityLink).filter(
        SnippetIdentityLink.snippet_id == snippet.snippet_id,
        SnippetIdentityLink.identity_id == identity.identity_id,
        SnippetIdentityLink.status == "active",
    ).first()
    if not existing:
        link = SnippetIdentityLink(
            link_id=uuid4(),
            project_id=snippet.project_id,
            snippet_id=snippet.snippet_id,
            identity_id=identity.identity_id,
            confidence=confidence,
            is_primary=True,
            link_source=link_source,
            status="active",
            metadata_json=metadata_json,
        )
        db.add(link)

    if snippet.embedding:
        identity.prototype_embedding = snippet.embedding
    if identity.canonical_snippet_id is None:
        identity.canonical_snippet_id = snippet.snippet_id
    identity.updated_at = datetime.now(timezone.utc)
