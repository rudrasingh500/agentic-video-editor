"""REST API endpoints for the Edit Orchestrator.

Provides endpoints for:
- Sending edit requests
- Managing edit sessions
- Listing and applying pending patches
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project, Timeline
from dependencies.auth import SessionData, get_session as get_auth_session
from dependencies.project import require_project
from agent.edit_agent import (
    EditRequest,
    EditSessionStatus,
    SessionNotFoundError,
    SessionClosedError,
    clear_pending_patches,
    delete_session,
    execute_patch,
    get_session as get_edit_session_data,
    list_sessions,
    orchestrate_edit,
    update_session_status,
)
from models.api_models import (
    ApplyPatchesRequestBody,
    ApplyPatchesResponse,
    EditPatchSummary,
    EditRequestBody,
    EditResponse,
    EditSessionCloseResponse,
    EditSessionDetailResponse,
    EditSessionListResponse,
    EditSessionResponse,
)
from operators.timeline_operator import (
    TimelineAlreadyExistsError,
    create_timeline,
    get_timeline_by_project,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_user_id(session: SessionData) -> UUID:
    if session.user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session.user_id


def _ensure_timeline(db: Session, project: Project, actor: str) -> Timeline:
    existing = get_timeline_by_project(db, project.project_id)
    if existing:
        return existing
    try:
        return create_timeline(
            db=db,
            project_id=project.project_id,
            name=project.project_name,
            created_by=actor,
        )
    except TimelineAlreadyExistsError:
        existing = get_timeline_by_project(db, project.project_id)
        if existing:
            return existing
        raise


@router.post("", response_model=EditResponse)
async def send_edit_request(
    project_id: UUID,
    body: EditRequestBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditResponse:
    """Send an edit request to the edit agent.

    This processes the user's natural language request and returns
    proposed edit patches for review.
    """
    user_id = _require_user_id(session)
    try:
        _ensure_timeline(db, project, f"user:{user_id}")
    except Exception:
        db.rollback()
        logger.exception("Failed to initialize timeline for project %s", project.project_id)
        raise HTTPException(status_code=500, detail="Failed to initialize timeline")

    request = EditRequest(
        message=body.message,
        session_id=body.session_id,
    )

    extra_warnings: list[str] = []

    try:
        result = orchestrate_edit(
            project_id=project.project_id,
            user_id=user_id,
            request=request,
            db=db,
        )
    except SessionNotFoundError:
        if not request.session_id:
            raise HTTPException(status_code=404, detail="Session not found")
        logger.warning(
            "Edit session %s not found for project %s. Starting new session.",
            request.session_id,
            project.project_id,
        )
        fallback_request = EditRequest(message=body.message, session_id=None)
        try:
            result = orchestrate_edit(
                project_id=project.project_id,
                user_id=user_id,
                request=fallback_request,
                db=db,
            )
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="Session not found")
        except SessionClosedError:
            raise HTTPException(status_code=400, detail="Session is closed")
        extra_warnings.append(
            "Previous edit session was not found. Started a new session."
        )
    except SessionClosedError:
        raise HTTPException(status_code=400, detail="Session is closed")

    # Convert pending patches to summaries
    patch_summaries = [
        EditPatchSummary(
            patch_id=p.patch_id,
            agent_type=p.agent_type.value,
            operation_count=len(p.patch.operations) if p.patch else 0,
            description=p.patch.description if p.patch else "",
            created_at=p.created_at,
        )
        for p in result.pending_patches
    ]

    return EditResponse(
        ok=True,
        session_id=result.session_id,
        message=result.message,
        pending_patches=patch_summaries,
        warnings=extra_warnings + result.warnings,
        applied=result.applied,
        new_version=result.new_version,
    )


@router.get("/sessions", response_model=EditSessionListResponse)
async def list_edit_sessions(
    project_id: UUID,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditSessionListResponse:
    """List edit sessions for a project."""
    _require_user_id(session)

    status_filter = None
    if status:
        try:
            status_filter = EditSessionStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Must be one of: active, completed, cancelled"
            )

    sessions, total = list_sessions(
        db=db,
        project_id=str(project.project_id),
        limit=limit,
        offset=offset,
        status=status_filter,
    )

    return EditSessionListResponse(
        ok=True,
        sessions=[
            EditSessionResponse(
                ok=True,
                session_id=s.session_id,
                project_id=str(project.project_id),
                timeline_id="",  # Summary doesn't include this
                title=s.title,
                status=s.status.value,
                message_count=s.message_count,
                pending_patch_count=s.pending_patch_count,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=EditSessionDetailResponse)
async def get_edit_session(
    project_id: UUID,
    session_id: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditSessionDetailResponse:
    """Get full details of an edit session including messages and patches."""
    _require_user_id(session)

    try:
        session = get_edit_session_data(db, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Verify session belongs to project
    if session.project_id != str(project.project_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return EditSessionDetailResponse(
        ok=True,
        session_id=session.session_id,
        project_id=session.project_id,
        timeline_id=session.timeline_id,
        title=session.title,
        status=session.status.value,
        messages=[m.model_dump(mode="json") for m in session.messages],
        pending_patches=[p.model_dump(mode="json") for p in session.pending_patches],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.post("/sessions/{session_id}/apply", response_model=ApplyPatchesResponse)
async def apply_session_patches(
    project_id: UUID,
    session_id: str,
    body: ApplyPatchesRequestBody,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> ApplyPatchesResponse:
    """Apply pending patches from a session to the timeline.

    This creates a new timeline checkpoint with the applied changes.
    """
    _require_user_id(session)

    try:
        session = get_edit_session_data(db, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.project_id != str(project.project_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.status != EditSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Session is {session.status.value}, cannot apply patches"
        )

    # Get timeline for this project
    timeline = (
        db.query(Timeline)
        .filter(Timeline.project_id == project.project_id)
        .first()
    )
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found for project")

    # Filter patches if specific IDs provided
    patches_to_apply = session.pending_patches
    if body.patch_ids:
        patches_to_apply = [
            p for p in session.pending_patches
            if p.patch_id in body.patch_ids
        ]

    if not patches_to_apply:
        return ApplyPatchesResponse(
            ok=True,
            new_version=None,
            operations_applied=0,
            errors=["No patches to apply"],
        )

    # Apply each patch's operations to the timeline
    total_operations = 0
    errors: list[str] = []
    current_version = int(str(getattr(timeline, "current_version", 0)))
    applied_patch_ids: list[str] = []

    for pending_patch in patches_to_apply:
        if pending_patch.patch is None:
            errors.append(f"Patch {pending_patch.patch_id}: No patch data")
            continue

        if not pending_patch.patch.operations:
            # No operations, nothing to apply but mark as applied
            applied_patch_ids.append(pending_patch.patch_id)
            continue

        # Execute the patch
        result = execute_patch(
            db=db,
            timeline_id=UUID(session.timeline_id),
            patch=pending_patch.patch,
            actor=f"agent:{pending_patch.agent_type.value}",
            starting_version=int(current_version),
            stop_on_error=True,
        )

        total_operations += result.successful_operations

        if result.errors:
            errors.extend([
                f"Patch {pending_patch.patch_id}: {e}"
                for e in result.errors
            ])

        if result.success:
            applied_patch_ids.append(pending_patch.patch_id)
            if result.final_version is not None:
                current_version = result.final_version
        else:
            # Stop on first failed patch
            logger.warning(
                f"Stopping patch application due to errors in patch {pending_patch.patch_id}"
            )
            break

    # Clear only the successfully applied patches
    if applied_patch_ids:
        clear_pending_patches(db, session_id, applied_patch_ids)

    # Refresh timeline to get updated version
    db.refresh(timeline)

    return ApplyPatchesResponse(
        ok=len(errors) == 0,
        new_version=(
            int(str(getattr(timeline, "current_version", 0))) if applied_patch_ids else None
        ),
        operations_applied=total_operations,
        errors=errors if errors else [],
    )


@router.post("/sessions/{session_id}/complete", response_model=EditSessionCloseResponse)
async def complete_session(
    project_id: UUID,
    session_id: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditSessionCloseResponse:
    """Mark an edit session as completed."""
    _require_user_id(session)

    try:
        session = get_edit_session_data(db, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.project_id != str(project.project_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    update_session_status(db, session_id, EditSessionStatus.COMPLETED)

    return EditSessionCloseResponse(ok=True)


@router.post("/sessions/{session_id}/cancel", response_model=EditSessionCloseResponse)
async def cancel_session(
    project_id: UUID,
    session_id: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditSessionCloseResponse:
    """Cancel an edit session and discard pending patches."""
    _require_user_id(session)

    try:
        session = get_edit_session_data(db, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.project_id != str(project.project_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # Clear all pending patches
    clear_pending_patches(db, session_id)

    # Update status
    update_session_status(db, session_id, EditSessionStatus.CANCELLED)

    return EditSessionCloseResponse(ok=True)


@router.delete("/sessions/{session_id}", response_model=EditSessionCloseResponse)
async def delete_edit_session(
    project_id: UUID,
    session_id: str,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_auth_session),
) -> EditSessionCloseResponse:
    """Delete an edit session permanently."""
    _require_user_id(session)

    try:
        session = get_edit_session_data(db, session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    if session.project_id != str(project.project_id):
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    delete_session(db, session_id)

    return EditSessionCloseResponse(ok=True)
