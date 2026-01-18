"""Session management for edit orchestrator.

Handles CRUD operations for EditSession records in the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from database.models import EditSession

from .types import (
    EditSessionDetail,
    EditSessionStatus,
    EditSessionSummary,
    MessageRole,
    PendingPatch,
    SessionMessage,
)

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """Raised when an edit session is not found."""

    pass


class SessionClosedError(Exception):
    """Raised when trying to modify a closed session."""

    pass


def create_session(
    db: Session,
    project_id: str,
    timeline_id: str,
    user_id: str,
    title: str | None = None,
) -> EditSessionDetail:
    """Create a new edit session.

    Args:
        db: Database session
        project_id: Project UUID
        timeline_id: Timeline UUID
        user_id: User who is creating the session

    Returns:
        EditSessionDetail with the new session
    """
    session_id = uuid4()
    now = datetime.now(timezone.utc)

    edit_session = EditSession(
        session_id=session_id,
        project_id=project_id,
        timeline_id=timeline_id,
        created_by=user_id,
        title=title,
        messages=[],
        pending_patches=[],
        status="active",
        created_at=now,
        updated_at=now,
    )

    db.add(edit_session)
    db.commit()
    db.refresh(edit_session)

    logger.info(f"Created edit session {session_id} for project {project_id}")

    return _to_detail(edit_session)


def get_session(
    db: Session,
    session_id: str,
) -> EditSessionDetail:
    """Get an edit session by ID.

    Args:
        db: Database session
        session_id: Session UUID

    Returns:
        EditSessionDetail

    Raises:
        SessionNotFoundError: If session doesn't exist
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    return _to_detail(edit_session)


def get_session_by_project(
    db: Session,
    project_id: str,
    status: EditSessionStatus | None = None,
) -> EditSessionDetail | None:
    """Get the most recent active session for a project.

    Args:
        db: Database session
        project_id: Project UUID
        status: Filter by status (default: active)

    Returns:
        EditSessionDetail or None if no active session
    """
    query = db.query(EditSession).filter(EditSession.project_id == project_id)

    if status:
        query = query.filter(EditSession.status == status.value)

    edit_session = query.order_by(EditSession.updated_at.desc()).first()

    if not edit_session:
        return None

    return _to_detail(edit_session)


def list_sessions(
    db: Session,
    project_id: str,
    limit: int = 20,
    offset: int = 0,
    status: EditSessionStatus | None = None,
) -> tuple[list[EditSessionSummary], int]:
    """List edit sessions for a project.

    Args:
        db: Database session
        project_id: Project UUID
        limit: Max number of sessions to return
        offset: Pagination offset
        status: Filter by status

    Returns:
        Tuple of (sessions, total_count)
    """
    query = db.query(EditSession).filter(EditSession.project_id == project_id)

    if status:
        query = query.filter(EditSession.status == status.value)

    total = query.count()

    sessions = (
        query.order_by(EditSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    summaries = [_to_summary(s) for s in sessions]
    return summaries, total


def add_message(
    db: Session,
    session_id: str,
    role: MessageRole,
    content: str,
    tool_calls: list[dict] | None = None,
    agent_responses: list[dict] | None = None,
) -> SessionMessage:
    """Add a message to the session conversation.

    Args:
        db: Database session
        session_id: Session UUID
        role: Message role (user/assistant/system)
        content: Message content
        tool_calls: Optional tool calls from assistant
        agent_responses: Optional agent responses

    Returns:
        The new SessionMessage

    Raises:
        SessionNotFoundError: If session doesn't exist
        SessionClosedError: If session is not active
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    if edit_session.status != "active":
        raise SessionClosedError(f"Edit session {session_id} is {edit_session.status}")

    now = datetime.now(timezone.utc)
    message = SessionMessage(
        role=role,
        content=content,
        timestamp=now,
        tool_calls=tool_calls,
        agent_responses=agent_responses,
    )

    # Append to messages list
    messages = list(edit_session.messages or [])
    messages.append(message.model_dump(mode="json"))
    edit_session.messages = messages
    edit_session.updated_at = now

    db.commit()

    return message


def add_pending_patches(
    db: Session,
    session_id: str,
    patches: list[PendingPatch],
) -> None:
    """Add pending patches to a session.

    Args:
        db: Database session
        session_id: Session UUID
        patches: Patches to add

    Raises:
        SessionNotFoundError: If session doesn't exist
        SessionClosedError: If session is not active
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    if edit_session.status != "active":
        raise SessionClosedError(f"Edit session {session_id} is {edit_session.status}")

    # Append to pending patches
    existing = list(edit_session.pending_patches or [])
    for patch in patches:
        existing.append(patch.model_dump(mode="json"))

    edit_session.pending_patches = existing
    edit_session.updated_at = datetime.now(timezone.utc)

    db.commit()


def clear_pending_patches(
    db: Session,
    session_id: str,
    patch_ids: list[str] | None = None,
) -> int:
    """Clear pending patches from a session.

    Args:
        db: Database session
        session_id: Session UUID
        patch_ids: Specific patches to clear (None = all)

    Returns:
        Number of patches cleared

    Raises:
        SessionNotFoundError: If session doesn't exist
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    existing = list(edit_session.pending_patches or [])
    cleared = 0

    if patch_ids is None:
        cleared = len(existing)
        edit_session.pending_patches = []
    else:
        new_patches = []
        for patch in existing:
            if patch.get("patch_id") in patch_ids:
                cleared += 1
            else:
                new_patches.append(patch)
        edit_session.pending_patches = new_patches

    edit_session.updated_at = datetime.now(timezone.utc)
    db.commit()

    return cleared


def update_session_status(
    db: Session,
    session_id: str,
    status: EditSessionStatus,
) -> None:
    """Update session status.

    Args:
        db: Database session
        session_id: Session UUID
        status: New status

    Raises:
        SessionNotFoundError: If session doesn't exist
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    edit_session.status = status.value
    edit_session.updated_at = datetime.now(timezone.utc)
    db.commit()


def update_session_title(
    db: Session,
    session_id: str,
    title: str,
) -> None:
    """Update session title.

    Args:
        db: Database session
        session_id: Session UUID
        title: New title

    Raises:
        SessionNotFoundError: If session doesn't exist
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        raise SessionNotFoundError(f"Edit session {session_id} not found")

    edit_session.title = title
    edit_session.updated_at = datetime.now(timezone.utc)
    db.commit()


def delete_session(
    db: Session,
    session_id: str,
) -> bool:
    """Delete an edit session.

    Args:
        db: Database session
        session_id: Session UUID

    Returns:
        True if deleted, False if not found
    """
    edit_session = (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )

    if not edit_session:
        return False

    db.delete(edit_session)
    db.commit()
    return True


def _to_summary(edit_session: EditSession) -> EditSessionSummary:
    """Convert DB model to summary."""
    messages = edit_session.messages or []
    patches = edit_session.pending_patches or []

    return EditSessionSummary(
        session_id=str(edit_session.session_id),
        title=edit_session.title,
        status=EditSessionStatus(edit_session.status),
        message_count=len(messages),
        pending_patch_count=len(patches),
        created_at=edit_session.created_at,
        updated_at=edit_session.updated_at,
    )


def _to_detail(edit_session: EditSession) -> EditSessionDetail:
    """Convert DB model to detail."""
    raw_messages = edit_session.messages or []
    raw_patches = edit_session.pending_patches or []

    messages = []
    for m in raw_messages:
        messages.append(SessionMessage(**m))

    patches = []
    for p in raw_patches:
        patches.append(PendingPatch(**p))

    return EditSessionDetail(
        session_id=str(edit_session.session_id),
        project_id=str(edit_session.project_id),
        timeline_id=str(edit_session.timeline_id),
        created_by=str(edit_session.created_by),
        title=edit_session.title,
        status=EditSessionStatus(edit_session.status),
        messages=messages,
        pending_patches=patches,
        created_at=edit_session.created_at,
        updated_at=edit_session.updated_at,
    )
