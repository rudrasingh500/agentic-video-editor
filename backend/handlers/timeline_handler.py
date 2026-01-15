"""
Timeline Handler - REST API endpoints for timeline operations.

All mutating endpoints require the X-Expected-Version header for optimistic locking.
This prevents concurrent modification conflicts.

Header format:
    X-Expected-Version: <int>

On version conflict, returns 409 Conflict with:
{
    "detail": {
        "error": "version_conflict",
        "expected_version": <int>,
        "current_version": <int>,
        "message": "Timeline was modified. Please refresh and retry."
    }
}
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import Project
from dependencies.auth import SessionData, get_session
from dependencies.project import require_project
from models.timeline_models import (
    # Core types
    Timeline,
    TimelineSettings,
    RationalTime,
    TimeRange,
    TrackKind,
    TransitionType,
    MarkerColor,
    Effect,
    LinearTimeWarp,
    # Request models
    CreateTimelineRequest,
    AddTrackRequest,
    AddClipRequest,
    TrimClipRequest,
    MoveClipRequest,
    SlipClipRequest,
    AddGapRequest,
    AddTransitionRequest,
    ModifyTransitionRequest,
    NestClipsRequest,
    AddMarkerRequest,
    AddEffectRequest,
    # Response models
    TimelineResponse,
    TimelineMutationResponse,
    CheckpointListResponse,
    TimelineDiffResponse,
    CheckpointSummary,
)
from operators.timeline_operator import (
    create_timeline,
    get_timeline_by_project,
    get_timeline_snapshot_by_project,
    list_checkpoints,
    rollback_to_version,
    diff_versions,
    approve_checkpoint,
    TimelineNotFoundError,
    CheckpointNotFoundError,
    VersionConflictError,
    InvalidOperationError,
)
from operators.timeline_editor import (
    add_track,
    remove_track,
    rename_track,
    reorder_tracks,
    add_clip,
    remove_clip,
    trim_clip,
    slip_clip,
    move_clip,
    replace_clip_media,
    add_gap,
    remove_gap,
    adjust_gap_duration,
    add_transition,
    remove_transition,
    modify_transition,
    nest_clips_as_stack,
    flatten_nested_stack,
    add_marker,
    remove_marker,
    add_effect,
    remove_effect,
    replace_timeline,
    clear_track,
)


router = APIRouter(prefix="/projects/{project_id}/timeline", tags=["timeline"])


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_expected_version(
    x_expected_version: Annotated[int | None, Header()] = None
) -> int | None:
    """Extract expected version from header."""
    return x_expected_version


def require_expected_version(
    x_expected_version: Annotated[int | None, Header()] = None
) -> int:
    """Require expected version header for mutating operations."""
    if x_expected_version is None:
        raise HTTPException(
            status_code=400,
            detail="X-Expected-Version header is required for this operation"
        )
    return x_expected_version


def get_actor(session: SessionData) -> str:
    """Get actor identifier from session."""
    return f"user:{session.user_id}"


def handle_timeline_error(e: Exception):
    """Convert timeline exceptions to HTTP exceptions."""
    if isinstance(e, TimelineNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    elif isinstance(e, CheckpointNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    elif isinstance(e, VersionConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "version_conflict",
                "expected_version": e.expected_version,
                "current_version": e.current_version,
                "message": "Timeline was modified. Please refresh and retry."
            }
        )
    elif isinstance(e, InvalidOperationError):
        raise HTTPException(status_code=400, detail=str(e))
    else:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


def checkpoint_to_summary(checkpoint) -> CheckpointSummary:
    """Convert checkpoint model to summary."""
    return CheckpointSummary(
        checkpoint_id=checkpoint.checkpoint_id,
        version=checkpoint.version,
        parent_version=checkpoint.parent_version,
        description=checkpoint.description,
        created_by=checkpoint.created_by,
        created_at=checkpoint.created_at.isoformat(),
        is_approved=checkpoint.is_approved,
    )


# =============================================================================
# TIMELINE CRUD
# =============================================================================


@router.post("", response_model=TimelineResponse)
async def timeline_create(
    request: CreateTimelineRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
):
    """
    Create a timeline for the project.
    
    A project can only have one timeline. Returns 400 if timeline already exists.
    """
    try:
        timeline_model = create_timeline(
            db=db,
            project_id=project.project_id,
            name=request.name,
            settings=request.settings,
            metadata=request.metadata,
            created_by=get_actor(session),
        )
        
        # Get the snapshot
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineResponse(
            ok=True,
            timeline=result.timeline,
            version=result.version,
            checkpoint_id=result.checkpoint_id,
        )
    except Exception as e:
        if "already exists" in str(e):
            raise HTTPException(status_code=400, detail=str(e))
        handle_timeline_error(e)


@router.get("", response_model=TimelineResponse)
async def timeline_get(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    version: int | None = Query(default=None, description="Specific version to retrieve"),
):
    """
    Get the current timeline (or a specific version).
    
    Query params:
        version: Optional version number to retrieve a historical snapshot
    """
    try:
        result = get_timeline_snapshot_by_project(db, project.project_id, version)
        return TimelineResponse(
            ok=True,
            timeline=result.timeline,
            version=result.version,
            checkpoint_id=result.checkpoint_id,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.get("/version/{version}", response_model=TimelineResponse)
async def timeline_get_version(
    version: int = Path(..., description="Version number to retrieve"),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """Get a specific version of the timeline."""
    try:
        result = get_timeline_snapshot_by_project(db, project.project_id, version)
        return TimelineResponse(
            ok=True,
            timeline=result.timeline,
            version=result.version,
            checkpoint_id=result.checkpoint_id,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.put("", response_model=TimelineMutationResponse)
async def timeline_replace(
    new_timeline: Timeline,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """
    Replace the entire timeline with a new snapshot.
    
    Use this for imports or major restructures.
    Requires X-Expected-Version header.
    """
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = replace_timeline(
            db=db,
            timeline_id=timeline_model.timeline_id,
            new_snapshot=new_timeline,
            description="Replaced entire timeline",
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        # Get updated timeline
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# HISTORY
# =============================================================================


@router.get("/history", response_model=CheckpointListResponse)
async def timeline_history(
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List checkpoint history for the timeline."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoints, total = list_checkpoints(
            db=db,
            timeline_id=timeline_model.timeline_id,
            limit=limit,
            offset=offset,
        )
        
        return CheckpointListResponse(
            ok=True,
            checkpoints=checkpoints,
            total=total,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/rollback/{version}", response_model=TimelineMutationResponse)
async def timeline_rollback(
    version: int = Path(..., description="Version to rollback to"),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """
    Rollback to a previous version.
    
    Creates a new checkpoint with the content from the target version.
    Requires X-Expected-Version header.
    """
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = rollback_to_version(
            db=db,
            timeline_id=timeline_model.timeline_id,
            target_version=version,
            rollback_by=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.get("/diff", response_model=TimelineDiffResponse)
async def timeline_diff(
    from_version: int = Query(..., alias="from", description="Starting version"),
    to_version: int = Query(..., alias="to", description="Ending version"),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
):
    """
    Compare two versions and return a diff.
    
    Query params:
        from: Starting version number
        to: Ending version number
    """
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        diff = diff_versions(
            db=db,
            timeline_id=timeline_model.timeline_id,
            from_version=from_version,
            to_version=to_version,
        )
        
        return TimelineDiffResponse(ok=True, diff=diff)
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# TRACK OPERATIONS
# =============================================================================


@router.post("/tracks", response_model=TimelineMutationResponse)
async def track_add(
    request: AddTrackRequest,
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add a new track to the timeline."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_track(
            db=db,
            timeline_id=timeline_model.timeline_id,
            name=request.name,
            kind=request.kind,
            index=request.index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}", response_model=TimelineMutationResponse)
async def track_remove(
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove a track from the timeline."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_track(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.patch("/tracks/{track_index}", response_model=TimelineMutationResponse)
async def track_rename(
    new_name: str = Query(..., description="New track name"),
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Rename a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = rename_track(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            new_name=new_name,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/reorder", response_model=TimelineMutationResponse)
async def tracks_reorder(
    new_order: list[int],
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """
    Reorder tracks.
    
    new_order[new_index] = old_index
    Example: [2, 0, 1] moves track 2 to position 0, track 0 to position 1, etc.
    """
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = reorder_tracks(
            db=db,
            timeline_id=timeline_model.timeline_id,
            new_order=new_order,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/{track_index}/clear", response_model=TimelineMutationResponse)
async def track_clear(
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Clear all items from a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = clear_track(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# CLIP OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/clips", response_model=TimelineMutationResponse)
async def clip_add(
    request: AddClipRequest,
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add a clip to a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_clip(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            asset_id=request.asset_id,
            source_range=request.source_range,
            insert_index=request.insert_index,
            name=request.name,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}/clips/{clip_index}", response_model=TimelineMutationResponse)
async def clip_remove(
    track_index: int = Path(..., ge=0),
    clip_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove a clip from a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_clip(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            clip_index=clip_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.patch("/tracks/{track_index}/clips/{clip_index}", response_model=TimelineMutationResponse)
async def clip_trim(
    request: TrimClipRequest,
    track_index: int = Path(..., ge=0),
    clip_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Trim a clip by changing its source_range."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = trim_clip(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            clip_index=clip_index,
            new_source_range=request.new_source_range,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/{track_index}/clips/{clip_index}/move", response_model=TimelineMutationResponse)
async def clip_move(
    request: MoveClipRequest,
    track_index: int = Path(..., ge=0),
    clip_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Move a clip to a different position or track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = move_clip(
            db=db,
            timeline_id=timeline_model.timeline_id,
            from_track=track_index,
            from_index=clip_index,
            to_track=request.to_track_index,
            to_index=request.to_clip_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/{track_index}/clips/{clip_index}/slip", response_model=TimelineMutationResponse)
async def clip_slip(
    request: SlipClipRequest,
    track_index: int = Path(..., ge=0),
    clip_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Slip a clip (change source while keeping duration)."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = slip_clip(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            clip_index=clip_index,
            offset=request.offset,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/{track_index}/clips/{clip_index}/replace-media", response_model=TimelineMutationResponse)
async def clip_replace_media(
    new_asset_id: UUID = Query(..., description="New asset UUID"),
    track_index: int = Path(..., ge=0),
    clip_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Replace a clip's media reference."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = replace_clip_media(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            clip_index=clip_index,
            new_asset_id=new_asset_id,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# GAP OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/gaps", response_model=TimelineMutationResponse)
async def gap_add(
    request: AddGapRequest,
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add a gap to a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_gap(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            duration=request.duration,
            insert_index=request.insert_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}/gaps/{gap_index}", response_model=TimelineMutationResponse)
async def gap_remove(
    track_index: int = Path(..., ge=0),
    gap_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove a gap from a track."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_gap(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            gap_index=gap_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# TRANSITION OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/transitions", response_model=TimelineMutationResponse)
async def transition_add(
    request: AddTransitionRequest,
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add a transition between two items."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_transition(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            position=request.position,
            transition_type=request.transition_type,
            in_offset=request.in_offset,
            out_offset=request.out_offset,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}/transitions/{transition_index}", response_model=TimelineMutationResponse)
async def transition_remove(
    track_index: int = Path(..., ge=0),
    transition_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove a transition."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_transition(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            transition_index=transition_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.patch("/tracks/{track_index}/transitions/{transition_index}", response_model=TimelineMutationResponse)
async def transition_modify(
    request: ModifyTransitionRequest,
    track_index: int = Path(..., ge=0),
    transition_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Modify a transition."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = modify_transition(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            transition_index=transition_index,
            transition_type=request.transition_type,
            in_offset=request.in_offset,
            out_offset=request.out_offset,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# NESTED COMPOSITION OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/nest", response_model=TimelineMutationResponse)
async def nest_items(
    request: NestClipsRequest,
    track_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Nest a range of items into a Stack (compound clip)."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = nest_clips_as_stack(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            start_index=request.start_index,
            end_index=request.end_index,
            stack_name=request.stack_name,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.post("/tracks/{track_index}/flatten/{stack_index}", response_model=TimelineMutationResponse)
async def flatten_stack(
    track_index: int = Path(..., ge=0),
    stack_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Flatten a nested Stack back into individual items."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = flatten_nested_stack(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            stack_index=stack_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# MARKER OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/items/{item_index}/markers", response_model=TimelineMutationResponse)
async def marker_add(
    request: AddMarkerRequest,
    track_index: int = Path(..., ge=0),
    item_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add a marker to an item."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_marker(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            item_index=item_index,
            marked_range=request.marked_range,
            name=request.name,
            color=request.color,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}/items/{item_index}/markers/{marker_index}", response_model=TimelineMutationResponse)
async def marker_remove(
    track_index: int = Path(..., ge=0),
    item_index: int = Path(..., ge=0),
    marker_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove a marker from an item."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_marker(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            item_index=item_index,
            marker_index=marker_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


# =============================================================================
# EFFECT OPERATIONS
# =============================================================================


@router.post("/tracks/{track_index}/items/{item_index}/effects", response_model=TimelineMutationResponse)
async def effect_add(
    request: AddEffectRequest,
    track_index: int = Path(..., ge=0),
    item_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Add an effect to an item."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = add_effect(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            item_index=item_index,
            effect=request.effect,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)


@router.delete("/tracks/{track_index}/items/{item_index}/effects/{effect_index}", response_model=TimelineMutationResponse)
async def effect_remove(
    track_index: int = Path(..., ge=0),
    item_index: int = Path(..., ge=0),
    effect_index: int = Path(..., ge=0),
    project: Project = Depends(require_project),
    db: Session = Depends(get_db),
    session: SessionData = Depends(get_session),
    expected_version: int = Depends(require_expected_version),
):
    """Remove an effect from an item."""
    try:
        timeline_model = get_timeline_by_project(db, project.project_id)
        if not timeline_model:
            raise TimelineNotFoundError(project_id=project.project_id)
        
        checkpoint = remove_effect(
            db=db,
            timeline_id=timeline_model.timeline_id,
            track_index=track_index,
            item_index=item_index,
            effect_index=effect_index,
            actor=get_actor(session),
            expected_version=expected_version,
        )
        
        result = get_timeline_snapshot_by_project(db, project.project_id)
        
        return TimelineMutationResponse(
            ok=True,
            checkpoint=checkpoint_to_summary(checkpoint),
            timeline=result.timeline,
        )
    except Exception as e:
        handle_timeline_error(e)
