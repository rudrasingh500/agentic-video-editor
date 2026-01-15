"""
Timeline Operator - Core CRUD operations with versioning and optimistic locking.

This module provides the foundation for timeline management:
- Create/read/update timelines
- Checkpoint-based versioning with optimistic locking
- Rollback to previous versions
- Diff between versions
- Approval workflow for agent integration

All mutating operations use optimistic locking via expected_version parameter
to handle concurrent modifications safely.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session as DBSession

from database.models import (
    Timeline as TimelineModel,
    TimelineCheckpoint as TimelineCheckpointModel,
    TimelineOperation as TimelineOperationModel,
)
from models.timeline_models import (
    Timeline,
    TimelineSettings,
    RationalTime,
    Stack,
    Track,
    Clip,
    Gap,
    Transition,
    CheckpointSummary,
    TimelineDiff,
    TimelineWithVersion,
)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class TimelineError(Exception):
    """Base exception for timeline operations."""
    pass


class TimelineNotFoundError(TimelineError):
    """Raised when timeline is not found."""
    def __init__(self, timeline_id: UUID | None = None, project_id: UUID | None = None):
        self.timeline_id = timeline_id
        self.project_id = project_id
        if timeline_id:
            super().__init__(f"Timeline not found: {timeline_id}")
        elif project_id:
            super().__init__(f"No timeline found for project: {project_id}")
        else:
            super().__init__("Timeline not found")


class CheckpointNotFoundError(TimelineError):
    """Raised when checkpoint is not found."""
    def __init__(self, checkpoint_id: UUID | None = None, version: int | None = None):
        self.checkpoint_id = checkpoint_id
        self.version = version
        if checkpoint_id:
            super().__init__(f"Checkpoint not found: {checkpoint_id}")
        elif version is not None:
            super().__init__(f"Checkpoint version not found: {version}")
        else:
            super().__init__("Checkpoint not found")


class VersionConflictError(TimelineError):
    """
    Raised when optimistic locking fails.
    
    This occurs when the expected_version doesn't match the current_version,
    indicating that another process modified the timeline concurrently.
    """
    def __init__(self, expected_version: int, current_version: int):
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Version conflict: expected {expected_version}, "
            f"but current version is {current_version}. "
            f"Please refresh and retry."
        )


class InvalidOperationError(TimelineError):
    """Raised when an operation is invalid."""
    pass


# =============================================================================
# CREATE OPERATIONS
# =============================================================================


def create_timeline(
    db: DBSession,
    project_id: UUID,
    name: str,
    settings: TimelineSettings | None = None,
    metadata: dict[str, Any] | None = None,
    created_by: str = "system",
) -> TimelineModel:
    """
    Create a new timeline for a project with an initial empty checkpoint.
    
    Args:
        db: Database session
        project_id: Project UUID (must be unique per timeline)
        name: Display name for the timeline
        settings: Timeline settings (framerate, resolution, etc.)
        metadata: Additional metadata
        created_by: Actor identifier (e.g., "user:uuid", "system")
    
    Returns:
        The created Timeline database model
    
    Raises:
        TimelineError: If a timeline already exists for this project
    """
    # Check if timeline already exists for this project
    existing = db.query(TimelineModel).filter(
        TimelineModel.project_id == project_id
    ).first()
    if existing:
        raise TimelineError(f"Timeline already exists for project {project_id}")
    
    # Use defaults if not provided
    if settings is None:
        settings = TimelineSettings()
    if metadata is None:
        metadata = {}
    
    # Create the timeline record
    timeline = TimelineModel(
        project_id=project_id,
        name=name,
        global_start_time=None,
        settings=settings.model_dump(),
        timeline_metadata=metadata,
        current_version=0,
    )
    db.add(timeline)
    db.flush()  # Get the timeline_id
    
    # Create initial empty timeline snapshot
    empty_timeline = Timeline.create_empty(
        name=name,
        rate=settings.default_framerate,
    )
    empty_timeline.metadata = metadata
    
    # Create version 0 checkpoint
    checkpoint = TimelineCheckpointModel(
        timeline_id=timeline.timeline_id,
        version=0,
        parent_version=None,
        snapshot=empty_timeline.model_dump(),
        description="Initial empty timeline",
        created_by=created_by,
        is_approved=True,
    )
    db.add(checkpoint)
    
    # Log the operation
    operation = TimelineOperationModel(
        checkpoint_id=checkpoint.checkpoint_id,
        operation_type="create_timeline",
        operation_data={
            "name": name,
            "settings": settings.model_dump(),
            "metadata": metadata,
        },
    )
    db.add(operation)
    
    db.commit()
    db.refresh(timeline)
    
    return timeline


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_timeline(db: DBSession, timeline_id: UUID) -> TimelineModel | None:
    """
    Get timeline metadata by ID.
    
    Note: This returns the database model, not the full snapshot.
    Use get_timeline_snapshot() to get the actual timeline content.
    """
    return db.query(TimelineModel).filter(
        TimelineModel.timeline_id == timeline_id
    ).first()


def get_timeline_by_project(db: DBSession, project_id: UUID) -> TimelineModel | None:
    """Get timeline for a project."""
    return db.query(TimelineModel).filter(
        TimelineModel.project_id == project_id
    ).first()


def get_timeline_snapshot(
    db: DBSession,
    timeline_id: UUID,
    version: int | None = None,
) -> TimelineWithVersion:
    """
    Get the timeline snapshot at a specific version (or latest).
    
    Args:
        db: Database session
        timeline_id: Timeline UUID
        version: Specific version to retrieve (None = latest)
    
    Returns:
        TimelineWithVersion containing the Timeline, version number, and checkpoint_id
    
    Raises:
        TimelineNotFoundError: If timeline doesn't exist
        CheckpointNotFoundError: If specified version doesn't exist
    """
    timeline = get_timeline(db, timeline_id)
    if not timeline:
        raise TimelineNotFoundError(timeline_id=timeline_id)
    
    # Determine which version to fetch
    target_version = version if version is not None else timeline.current_version
    
    # Get the checkpoint
    checkpoint = db.query(TimelineCheckpointModel).filter(
        TimelineCheckpointModel.timeline_id == timeline_id,
        TimelineCheckpointModel.version == target_version,
    ).first()
    
    if not checkpoint:
        raise CheckpointNotFoundError(version=target_version)
    
    # Parse the snapshot into Pydantic model
    timeline_data = Timeline.model_validate(checkpoint.snapshot)
    
    return TimelineWithVersion(
        timeline=timeline_data,
        version=checkpoint.version,
        checkpoint_id=checkpoint.checkpoint_id,
    )


def get_timeline_snapshot_by_project(
    db: DBSession,
    project_id: UUID,
    version: int | None = None,
) -> TimelineWithVersion:
    """
    Get timeline snapshot for a project.
    
    Convenience method that finds the timeline by project_id first.
    """
    timeline = get_timeline_by_project(db, project_id)
    if not timeline:
        raise TimelineNotFoundError(project_id=project_id)
    
    return get_timeline_snapshot(db, timeline.timeline_id, version)


def get_checkpoint(
    db: DBSession,
    checkpoint_id: UUID,
) -> TimelineCheckpointModel | None:
    """Get a specific checkpoint by ID."""
    return db.query(TimelineCheckpointModel).filter(
        TimelineCheckpointModel.checkpoint_id == checkpoint_id
    ).first()


def get_checkpoint_by_version(
    db: DBSession,
    timeline_id: UUID,
    version: int,
) -> TimelineCheckpointModel | None:
    """Get a checkpoint by timeline and version number."""
    return db.query(TimelineCheckpointModel).filter(
        TimelineCheckpointModel.timeline_id == timeline_id,
        TimelineCheckpointModel.version == version,
    ).first()


def list_checkpoints(
    db: DBSession,
    timeline_id: UUID,
    limit: int = 50,
    offset: int = 0,
    include_unapproved: bool = True,
) -> tuple[list[CheckpointSummary], int]:
    """
    List checkpoint history for a timeline.
    
    Args:
        db: Database session
        timeline_id: Timeline UUID
        limit: Maximum number of checkpoints to return
        offset: Number of checkpoints to skip
        include_unapproved: Include unapproved checkpoints (default True)
    
    Returns:
        Tuple of (list of CheckpointSummary, total count)
    """
    query = db.query(TimelineCheckpointModel).filter(
        TimelineCheckpointModel.timeline_id == timeline_id
    )
    
    if not include_unapproved:
        query = query.filter(TimelineCheckpointModel.is_approved == True)
    
    # Get total count
    total = query.count()
    
    # Get paginated results, ordered by version descending (newest first)
    checkpoints = query.order_by(
        TimelineCheckpointModel.version.desc()
    ).offset(offset).limit(limit).all()
    
    # Convert to summaries
    summaries = [
        CheckpointSummary(
            checkpoint_id=cp.checkpoint_id,
            version=cp.version,
            parent_version=cp.parent_version,
            description=cp.description,
            created_by=cp.created_by,
            created_at=cp.created_at.isoformat(),
            is_approved=cp.is_approved,
        )
        for cp in checkpoints
    ]
    
    return summaries, total


# =============================================================================
# CHECKPOINT CREATION (with optimistic locking)
# =============================================================================


def create_checkpoint(
    db: DBSession,
    timeline_id: UUID,
    snapshot: Timeline,
    description: str,
    created_by: str,
    expected_version: int,
    operation_type: str,
    operation_data: dict[str, Any],
    is_approved: bool = True,
) -> TimelineCheckpointModel:
    """
    Create a new checkpoint with optimistic locking.
    
    This is the core function for all timeline mutations. It:
    1. Verifies expected_version matches current_version (optimistic lock)
    2. Creates a new checkpoint with version = current_version + 1
    3. Updates the timeline's current_version
    4. Logs the operation
    
    Args:
        db: Database session
        timeline_id: Timeline UUID
        snapshot: The new Timeline state (Pydantic model)
        description: Human-readable description of the change
        created_by: Actor identifier
        expected_version: The version the caller expects (for optimistic locking)
        operation_type: Type of operation (e.g., "add_clip", "trim_clip")
        operation_data: Full operation parameters for audit log
        is_approved: Whether this checkpoint is auto-approved (default True)
    
    Returns:
        The created TimelineCheckpoint model
    
    Raises:
        TimelineNotFoundError: If timeline doesn't exist
        VersionConflictError: If expected_version doesn't match current_version
    """
    # Get the timeline with a lock
    timeline = db.query(TimelineModel).filter(
        TimelineModel.timeline_id == timeline_id
    ).with_for_update().first()
    
    if not timeline:
        raise TimelineNotFoundError(timeline_id=timeline_id)
    
    # Optimistic locking check
    if timeline.current_version != expected_version:
        raise VersionConflictError(
            expected_version=expected_version,
            current_version=timeline.current_version,
        )
    
    # Calculate new version
    new_version = timeline.current_version + 1
    
    # Create the checkpoint
    checkpoint = TimelineCheckpointModel(
        timeline_id=timeline_id,
        version=new_version,
        parent_version=timeline.current_version,
        snapshot=snapshot.model_dump(),
        description=description,
        created_by=created_by,
        is_approved=is_approved,
    )
    db.add(checkpoint)
    db.flush()  # Get checkpoint_id
    
    # Log the operation
    operation = TimelineOperationModel(
        checkpoint_id=checkpoint.checkpoint_id,
        operation_type=operation_type,
        operation_data=operation_data,
    )
    db.add(operation)
    
    # Update timeline's current version
    timeline.current_version = new_version
    timeline.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(checkpoint)
    
    return checkpoint


# =============================================================================
# ROLLBACK
# =============================================================================


def rollback_to_version(
    db: DBSession,
    timeline_id: UUID,
    target_version: int,
    rollback_by: str,
    expected_version: int,
) -> TimelineCheckpointModel:
    """
    Rollback to a previous version by creating a new checkpoint.
    
    This doesn't delete history - it creates a new checkpoint that
    contains the snapshot from the target version.
    
    Args:
        db: Database session
        timeline_id: Timeline UUID
        target_version: Version to rollback to
        rollback_by: Actor performing the rollback
        expected_version: Current version for optimistic locking
    
    Returns:
        The new checkpoint (with the rolled-back content)
    
    Raises:
        TimelineNotFoundError: If timeline doesn't exist
        CheckpointNotFoundError: If target_version doesn't exist
        VersionConflictError: If expected_version doesn't match
    """
    # Get the target checkpoint
    target_checkpoint = get_checkpoint_by_version(db, timeline_id, target_version)
    if not target_checkpoint:
        raise CheckpointNotFoundError(version=target_version)
    
    # Parse the target snapshot
    target_snapshot = Timeline.model_validate(target_checkpoint.snapshot)
    
    # Create new checkpoint with the rolled-back content
    return create_checkpoint(
        db=db,
        timeline_id=timeline_id,
        snapshot=target_snapshot,
        description=f"Rolled back to version {target_version}",
        created_by=rollback_by,
        expected_version=expected_version,
        operation_type="rollback",
        operation_data={
            "target_version": target_version,
            "reason": f"Rollback requested by {rollback_by}",
        },
        is_approved=True,  # Rollbacks are always approved
    )


# =============================================================================
# DIFF
# =============================================================================


def diff_versions(
    db: DBSession,
    timeline_id: UUID,
    from_version: int,
    to_version: int,
) -> TimelineDiff:
    """
    Compare two versions and return a structured diff.
    
    Args:
        db: Database session
        timeline_id: Timeline UUID
        from_version: Starting version
        to_version: Ending version
    
    Returns:
        TimelineDiff with added/removed/modified tracks and clips
    
    Raises:
        CheckpointNotFoundError: If either version doesn't exist
    """
    # Get both checkpoints
    from_checkpoint = get_checkpoint_by_version(db, timeline_id, from_version)
    to_checkpoint = get_checkpoint_by_version(db, timeline_id, to_version)
    
    if not from_checkpoint:
        raise CheckpointNotFoundError(version=from_version)
    if not to_checkpoint:
        raise CheckpointNotFoundError(version=to_version)
    
    # Parse snapshots
    from_timeline = Timeline.model_validate(from_checkpoint.snapshot)
    to_timeline = Timeline.model_validate(to_checkpoint.snapshot)
    
    # Compare tracks
    from_track_names = {t.name for t in from_timeline.tracks.children if isinstance(t, Track)}
    to_track_names = {t.name for t in to_timeline.tracks.children if isinstance(t, Track)}
    
    tracks_added = list(to_track_names - from_track_names)
    tracks_removed = list(from_track_names - to_track_names)
    
    # Compare clips
    from_clips = _extract_clip_info(from_timeline)
    to_clips = _extract_clip_info(to_timeline)
    
    from_clip_ids = {c["id"] for c in from_clips}
    to_clip_ids = {c["id"] for c in to_clips}
    
    clips_added = [c for c in to_clips if c["id"] not in from_clip_ids]
    clips_removed = [c for c in from_clips if c["id"] not in to_clip_ids]
    
    # Find modified clips (same id but different content)
    clips_modified = []
    for to_clip in to_clips:
        if to_clip["id"] in from_clip_ids:
            from_clip = next(c for c in from_clips if c["id"] == to_clip["id"])
            if from_clip != to_clip:
                clips_modified.append({
                    "id": to_clip["id"],
                    "name": to_clip["name"],
                    "from": from_clip,
                    "to": to_clip,
                })
    
    # Generate summary
    changes = []
    if tracks_added:
        changes.append(f"Added {len(tracks_added)} track(s)")
    if tracks_removed:
        changes.append(f"Removed {len(tracks_removed)} track(s)")
    if clips_added:
        changes.append(f"Added {len(clips_added)} clip(s)")
    if clips_removed:
        changes.append(f"Removed {len(clips_removed)} clip(s)")
    if clips_modified:
        changes.append(f"Modified {len(clips_modified)} clip(s)")
    
    summary = "; ".join(changes) if changes else "No changes"
    
    return TimelineDiff(
        from_version=from_version,
        to_version=to_version,
        tracks_added=tracks_added,
        tracks_removed=tracks_removed,
        clips_added=clips_added,
        clips_removed=clips_removed,
        clips_modified=clips_modified,
        summary=summary,
    )


def _extract_clip_info(timeline: Timeline) -> list[dict[str, Any]]:
    """Extract clip information for diffing."""
    clips = []
    
    for track_idx, track in enumerate(timeline.tracks.children):
        if not isinstance(track, Track):
            continue
        
        for item_idx, item in enumerate(track.children):
            if isinstance(item, Clip):
                # Create a unique ID based on position and media reference
                clip_id = f"{track.name}:{item_idx}"
                if hasattr(item.media_reference, 'asset_id'):
                    clip_id = f"{track.name}:{item.media_reference.asset_id}:{item_idx}"
                
                clips.append({
                    "id": clip_id,
                    "name": item.name,
                    "track": track.name,
                    "track_index": track_idx,
                    "item_index": item_idx,
                    "source_range": item.source_range.model_dump(),
                    "media_reference": item.media_reference.model_dump(),
                })
    
    return clips


# =============================================================================
# APPROVAL WORKFLOW
# =============================================================================


def approve_checkpoint(
    db: DBSession,
    checkpoint_id: UUID,
    approved_by: str,
) -> TimelineCheckpointModel:
    """
    Mark a checkpoint as approved.
    
    Args:
        db: Database session
        checkpoint_id: Checkpoint UUID
        approved_by: Actor approving the checkpoint
    
    Returns:
        The updated checkpoint
    
    Raises:
        CheckpointNotFoundError: If checkpoint doesn't exist
    """
    checkpoint = get_checkpoint(db, checkpoint_id)
    if not checkpoint:
        raise CheckpointNotFoundError(checkpoint_id=checkpoint_id)
    
    checkpoint.is_approved = True
    checkpoint.approved_by = approved_by
    checkpoint.approved_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(checkpoint)
    
    return checkpoint


def reject_checkpoint(
    db: DBSession,
    checkpoint_id: UUID,
    rejected_by: str,
    rollback: bool = True,
    expected_version: int | None = None,
) -> tuple[TimelineCheckpointModel, TimelineCheckpointModel | None]:
    """
    Mark a checkpoint as rejected (set is_approved=False).
    
    Optionally rollback to the previous approved version.
    
    Args:
        db: Database session
        checkpoint_id: Checkpoint UUID to reject
        rejected_by: Actor rejecting the checkpoint
        rollback: Whether to rollback to previous approved version
        expected_version: Required if rollback=True
    
    Returns:
        Tuple of (rejected checkpoint, new rollback checkpoint or None)
    
    Raises:
        CheckpointNotFoundError: If checkpoint doesn't exist
        VersionConflictError: If expected_version doesn't match (when rolling back)
    """
    checkpoint = get_checkpoint(db, checkpoint_id)
    if not checkpoint:
        raise CheckpointNotFoundError(checkpoint_id=checkpoint_id)
    
    # Mark as rejected
    checkpoint.is_approved = False
    
    rollback_checkpoint = None
    
    if rollback and expected_version is not None:
        # Find the last approved version before this one
        last_approved = db.query(TimelineCheckpointModel).filter(
            TimelineCheckpointModel.timeline_id == checkpoint.timeline_id,
            TimelineCheckpointModel.version < checkpoint.version,
            TimelineCheckpointModel.is_approved == True,
        ).order_by(TimelineCheckpointModel.version.desc()).first()
        
        if last_approved:
            rollback_checkpoint = rollback_to_version(
                db=db,
                timeline_id=checkpoint.timeline_id,
                target_version=last_approved.version,
                rollback_by=rejected_by,
                expected_version=expected_version,
            )
    
    db.commit()
    db.refresh(checkpoint)
    
    return checkpoint, rollback_checkpoint


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_operations_for_checkpoint(
    db: DBSession,
    checkpoint_id: UUID,
) -> list[TimelineOperationModel]:
    """Get all operations associated with a checkpoint."""
    return db.query(TimelineOperationModel).filter(
        TimelineOperationModel.checkpoint_id == checkpoint_id
    ).order_by(TimelineOperationModel.created_at).all()


def get_timeline_operations(
    db: DBSession,
    timeline_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Get operation history for a timeline.
    
    Returns operations with their associated checkpoint info.
    """
    # Join operations with checkpoints
    results = db.query(
        TimelineOperationModel,
        TimelineCheckpointModel.version,
        TimelineCheckpointModel.description,
    ).join(
        TimelineCheckpointModel,
        TimelineOperationModel.checkpoint_id == TimelineCheckpointModel.checkpoint_id,
    ).filter(
        TimelineCheckpointModel.timeline_id == timeline_id
    ).order_by(
        TimelineCheckpointModel.version.desc()
    ).offset(offset).limit(limit).all()
    
    return [
        {
            "operation_id": str(op.operation_id),
            "operation_type": op.operation_type,
            "operation_data": op.operation_data,
            "created_at": op.created_at.isoformat(),
            "version": version,
            "checkpoint_description": description,
        }
        for op, version, description in results
    ]


def delete_timeline(db: DBSession, timeline_id: UUID) -> bool:
    """
    Delete a timeline and all its checkpoints/operations.
    
    Note: This is a destructive operation. Consider soft-delete for production.
    """
    timeline = get_timeline(db, timeline_id)
    if not timeline:
        return False
    
    db.delete(timeline)
    db.commit()
    return True
