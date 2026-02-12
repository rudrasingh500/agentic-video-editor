from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from database.models import EditSession
from operators import timeline_editor
from operators.timeline_operator import rollback_to_version
from models.timeline_models import (
    Effect,
    FreezeFrame,
    LinearTimeWarp,
    RationalTime,
    TimeRange,
    TrackKind,
    TransitionType,
)

from .types import (
    EditAgentType,
    EditSessionActivityEvent,
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


class PatchTransaction:
    """Execute patch operations with optional rollback on error."""

    def __init__(
        self,
        db: Session,
        timeline_id: UUID,
        starting_version: int,
    ) -> None:
        self.db = db
        self.timeline_id = timeline_id
        self.starting_version = starting_version
        self.expected_version = starting_version
        self.applied_operations: int = 0
        self._logger = logging.getLogger(__name__)

    def execute(
        self,
        patch: EditPatch,
        actor: str,
        stop_on_error: bool = True,
        rollback_on_error: bool = True,
    ) -> PatchExecutionResult:
        errors: list[str] = []
        rolled_back = False
        rollback_version: int | None = None
        rollback_target_version: int | None = None

        for operation in patch.operations:
            try:
                self.expected_version = _apply_operation(
                    self.db, self.timeline_id, operation, actor, self.expected_version
                )
                self.applied_operations += 1
            except Exception as exc:
                errors.append(str(exc))
                if stop_on_error and rollback_on_error and self.applied_operations > 0:
                    rollback_checkpoint = self._rollback(actor)
                    if rollback_checkpoint is not None:
                        rolled_back = True
                        rollback_version = int(rollback_checkpoint.version)
                        rollback_target_version = self.starting_version
                        self.expected_version = rollback_version
                    else:
                        errors.append("Rollback failed; timeline may be partially updated.")
                if stop_on_error:
                    break

        final_version = self.expected_version if self.applied_operations > 0 else None

        if rolled_back and rollback_version is not None:
            final_version = rollback_version

        return PatchExecutionResult(
            success=len(errors) == 0,
            successful_operations=self.applied_operations,
            errors=errors,
            final_version=final_version,
            rolled_back=rolled_back,
            rollback_version=rollback_version,
            rollback_target_version=rollback_target_version,
        )

    def _rollback(self, actor: str):
        try:
            return rollback_to_version(
                db=self.db,
                timeline_id=self.timeline_id,
                target_version=self.starting_version,
                rollback_by=f"{actor}:rollback",
                expected_version=self.expected_version,
            )
        except Exception as exc:
            self._logger.error("Rollback failed: %s", exc)
            return None


def execute_patch(
    db: Session,
    timeline_id: UUID,
    patch: EditPatch,
    actor: str,
    starting_version: int,
    stop_on_error: bool = True,
    rollback_on_error: bool = True,
) -> PatchExecutionResult:
    transaction = PatchTransaction(db, timeline_id, starting_version)
    return transaction.execute(
        patch=patch,
        actor=actor,
        stop_on_error=stop_on_error,
        rollback_on_error=rollback_on_error,
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
    activity_events_raw = record.activity_events or []

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

    activity_events = [
        EditSessionActivityEvent(
            event_id=str(event.get("event_id") or uuid4()),
            event_type=str(event.get("event_type") or "info"),
            status=str(event.get("status") or "completed"),
            label=str(event.get("label") or ""),
            created_at=_parse_dt(event.get("created_at")) or record.created_at,
            iteration=event.get("iteration"),
            tool_name=event.get("tool_name"),
            summary=event.get("summary"),
            meta=event.get("meta") if isinstance(event.get("meta"), dict) else {},
        )
        for event in activity_events_raw
        if isinstance(event, dict)
    ]

    return EditSessionData(
        session_id=str(record.session_id),
        project_id=str(record.project_id),
        timeline_id=str(record.timeline_id),
        title=record.title,
        status=EditSessionStatus(record.status),
        messages=messages,
        pending_patches=pending,
        activity_events=activity_events,
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


# Safety fallback: map skill IDs to operation types if agent uses wrong format.
# This allows recovery when the agent mistakenly uses a skill ID (e.g., "cuts.insert")
# as an operation_type instead of the correct low-level operation (e.g., "add_clip").
_SKILL_ID_TO_OPERATION: dict[str, str] = {
    "cuts.trim": "trim_clip",
    "cuts.split": "split_clip",
    "cuts.insert": "add_clip",
    "cuts.overwrite": "replace_clip_media",
    "cuts.move": "move_clip",
    "cuts.slip": "slip_clip",
    "cuts.slide": "move_clip",
    "cuts.pacing": "adjust_gap_duration",
    "silences.remove": "remove_clip",
    "brolls.add": "add_clip",
    "captions.add": "add_generator_clip",
    "mix.crossfade": "add_transition",
    "fx.transition": "add_transition",
}

_logger = logging.getLogger(__name__)


def _apply_operation(
    db: Session,
    timeline_id: UUID,
    operation: EditOperation,
    actor: str,
    expected_version: int,
) -> int:
    data = operation.operation_data
    op_type = operation.operation_type

    # Safety fallback: map skill IDs to operation types if agent used wrong format
    if op_type in _SKILL_ID_TO_OPERATION:
        corrected = _SKILL_ID_TO_OPERATION[op_type]
        _logger.warning(
            "Agent used skill ID '%s' as operation_type, mapping to '%s'. "
            "This indicates the agent prompt/workflow should be reviewed.",
            op_type,
            corrected,
        )
        op_type = corrected

    if op_type == "add_track":
        kind_value = data.get("kind")
        kind = TrackKind(kind_value) if kind_value else TrackKind.VIDEO
        checkpoint = timeline_editor.add_track(
            db,
            timeline_id,
            name=data["name"],
            kind=kind,
            index=data.get("index"),
            actor=actor,
            expected_version=expected_version,
        )
    elif op_type == "trim_clip":
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
