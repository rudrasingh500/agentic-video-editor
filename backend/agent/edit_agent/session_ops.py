from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from database.models import EditSession
from operators import timeline_editor
from models.timeline_models import (
    Effect,
    FreezeFrame,
    LinearTimeWarp,
    RationalTime,
    TimeRange,
    TransitionType,
)

from .types import (
    EditAgentType,
    EditMessage,
    EditOperation,
    EditPatch,
    EditSessionData,
    EditSessionStatus,
    EditSessionSummary,
    PatchExecutionResult,
    PendingPatch,
)


class SessionNotFoundError(Exception):
    pass


class SessionClosedError(Exception):
    pass


def get_session(db: Session, session_id: str) -> EditSessionData:
    record = _get_session_record(db, session_id)
    if not record:
        raise SessionNotFoundError(session_id)

    return _record_to_session(record)


def list_sessions(
    db: Session,
    project_id: str,
    limit: int = 20,
    offset: int = 0,
    status: EditSessionStatus | None = None,
) -> tuple[list[EditSessionSummary], int]:
    query = db.query(EditSession).filter(EditSession.project_id == project_id)
    if status:
        query = query.filter(EditSession.status == status.value)

    total = query.count()
    records = (
        query.order_by(EditSession.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    sessions: list[EditSessionSummary] = []
    for record in records:
        messages = record.messages or []
        pending = record.pending_patches or []
        sessions.append(
            EditSessionSummary(
                session_id=str(record.session_id),
                project_id=str(record.project_id),
                title=record.title,
                status=EditSessionStatus(record.status),
                message_count=len(messages),
                pending_patch_count=len(pending),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )

    return sessions, total


def update_session_status(db: Session, session_id: str, status: EditSessionStatus) -> None:
    record = _get_session_record(db, session_id)
    if not record:
        raise SessionNotFoundError(session_id)
    record.status = status.value
    record.updated_at = datetime.now(timezone.utc)
    db.commit()


def delete_session(db: Session, session_id: str) -> None:
    record = _get_session_record(db, session_id)
    if not record:
        raise SessionNotFoundError(session_id)
    db.delete(record)
    db.commit()


def clear_pending_patches(
    db: Session, session_id: str, patch_ids: list[str] | None = None
) -> None:
    record = _get_session_record(db, session_id)
    if not record:
        raise SessionNotFoundError(session_id)
    patches = record.pending_patches or []
    if patch_ids:
        patches = [p for p in patches if p.get("patch_id") not in patch_ids]
    else:
        patches = []
    record.pending_patches = patches
    record.updated_at = datetime.now(timezone.utc)
    db.commit()


def execute_patch(
    db: Session,
    timeline_id: UUID,
    patch: EditPatch,
    actor: str,
    starting_version: int,
    stop_on_error: bool = True,
) -> PatchExecutionResult:
    errors: list[str] = []
    expected_version = starting_version
    successful = 0

    for operation in patch.operations:
        try:
            expected_version = _apply_operation(
                db, timeline_id, operation, actor, expected_version
            )
            successful += 1
        except Exception as exc:
            errors.append(str(exc))
            if stop_on_error:
                break

    return PatchExecutionResult(
        success=len(errors) == 0,
        successful_operations=successful,
        errors=errors,
        final_version=expected_version if successful > 0 else None,
    )


def _get_session_record(db: Session, session_id: str) -> EditSession | None:
    return (
        db.query(EditSession)
        .filter(EditSession.session_id == session_id)
        .first()
    )


def _record_to_session(record: EditSession) -> EditSessionData:
    messages_raw = record.messages or []
    patches_raw = record.pending_patches or []

    messages = [
        EditMessage(
            role=m.get("role", "user"),
            content=m.get("content", ""),
            created_at=_parse_dt(m.get("created_at")) or record.created_at,
        )
        for m in messages_raw
    ]

    pending: list[PendingPatch] = []
    for p in patches_raw:
        patch_data = p.get("patch")
        patch = EditPatch.model_validate(patch_data) if patch_data else None
        pending.append(
            PendingPatch(
                patch_id=p.get("patch_id", str(uuid4())),
                agent_type=EditAgentType.EDIT_AGENT,
                patch=patch,
                created_at=_parse_dt(p.get("created_at")) or record.created_at,
            )
        )

    return EditSessionData(
        session_id=str(record.session_id),
        project_id=str(record.project_id),
        timeline_id=str(record.timeline_id),
        title=record.title,
        status=EditSessionStatus(record.status),
        messages=messages,
        pending_patches=pending,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _apply_operation(
    db: Session,
    timeline_id: UUID,
    operation: EditOperation,
    actor: str,
    expected_version: int,
) -> int:
    data = operation.operation_data
    op_type = operation.operation_type

    if op_type == "trim_clip":
        new_range = TimeRange.model_validate(data["new_source_range"])
        checkpoint = timeline_editor.trim_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            new_range,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "split_clip":
        split_offset = RationalTime.model_validate(data["split_offset"])
        checkpoint = timeline_editor.split_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            split_offset,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "remove_clip":
        checkpoint = timeline_editor.remove_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_clip":
        source_range = TimeRange.model_validate(data["source_range"])
        checkpoint = timeline_editor.add_clip(
            db,
            timeline_id,
            data["track_index"],
            UUID(data["asset_id"]),
            source_range,
            insert_index=data.get("insert_index"),
            name=data.get("name"),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "replace_clip_media":
        checkpoint = timeline_editor.replace_clip_media(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            UUID(data["new_asset_id"]),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "move_clip":
        checkpoint = timeline_editor.move_clip(
            db,
            timeline_id,
            data["from_track"],
            data["from_index"],
            data["to_track"],
            data["to_index"],
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "slip_clip":
        offset = RationalTime.model_validate(data["offset"])
        checkpoint = timeline_editor.slip_clip(
            db,
            timeline_id,
            data["track_index"],
            data["clip_index"],
            offset,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_transition":
        transition_value = data.get("transition_type")
        transition = (
            TransitionType(transition_value)
            if transition_value
            else TransitionType.SMPTE_DISSOLVE
        )
        checkpoint = timeline_editor.add_transition(
            db,
            timeline_id,
            data["track_index"],
            data["position"],
            transition_type=transition,
            in_offset=RationalTime.model_validate(data["in_offset"]),
            out_offset=RationalTime.model_validate(data["out_offset"]),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_effect":
        effect_data = data["effect"]
        schema = effect_data.get("OTIO_SCHEMA")
        if schema == "LinearTimeWarp.1":
            effect = LinearTimeWarp.model_validate(effect_data)
        elif schema == "FreezeFrame.1":
            effect = FreezeFrame.model_validate(effect_data)
        else:
            effect = Effect.model_validate(effect_data)
        checkpoint = timeline_editor.add_effect(
            db,
            timeline_id,
            data["track_index"],
            data["item_index"],
            effect,
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "add_generator_clip":
        source_range = TimeRange.model_validate(data["source_range"])
        checkpoint = timeline_editor.add_generator_clip(
            db,
            timeline_id,
            data["track_index"],
            data["generator_kind"],
            data.get("parameters", {}),
            source_range,
            insert_index=data.get("insert_index"),
            name=data.get("name"),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "adjust_gap_duration":
        new_duration = RationalTime.model_validate(data["new_duration"])
        checkpoint = timeline_editor.adjust_gap_duration(
            db,
            timeline_id,
            data["track_index"],
            data["gap_index"],
            new_duration,
            actor=actor,
            expected_version=expected_version,
        )
    else:
        raise ValueError(f"Unsupported operation: {op_type}")

    return int(checkpoint.version)
