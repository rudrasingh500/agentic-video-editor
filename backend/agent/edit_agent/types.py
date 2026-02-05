from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EditSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EditAgentType(str, Enum):
    EDIT_AGENT = "edit_agent"


class EditRequest(BaseModel):
    message: str = Field(description="User edit request")
    session_id: str | None = Field(default=None, description="Existing session ID")


class EditOperation(BaseModel):
    operation_type: str
    operation_data: dict[str, Any]


class EditPatch(BaseModel):
    description: str
    operations: list[EditOperation] = Field(default_factory=list)


class PendingPatch(BaseModel):
    patch_id: str
    agent_type: EditAgentType
    patch: EditPatch | None = None
    created_at: datetime


class EditMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class EditSessionData(BaseModel):
    session_id: str
    project_id: str
    timeline_id: str
    title: str | None
    status: EditSessionStatus
    messages: list[EditMessage] = Field(default_factory=list)
    pending_patches: list[PendingPatch] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EditSessionSummary(BaseModel):
    session_id: str
    project_id: str
    title: str | None
    status: EditSessionStatus
    message_count: int
    pending_patch_count: int
    created_at: datetime
    updated_at: datetime


class PatchExecutionResult(BaseModel):
    success: bool
    successful_operations: int = 0
    errors: list[str] = Field(default_factory=list)
    final_version: int | None = None


class EditAgentResult(BaseModel):
    session_id: str
    message: str
    pending_patches: list[PendingPatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    applied: bool = False
    new_version: int | None = None


class VerificationStatus(BaseModel):
    """Verification status for edit operations."""
    render_viewed: bool = Field(description="Whether view_render_output was called")
    render_job_id: str | None = Field(default=None, description="Job ID of the verified render")
    observations: str | None = Field(
        default=None,
        description="What was observed in the render (visual/audio)"
    )
    issues_found: list[str] = Field(
        default_factory=list,
        description="Any issues observed during verification"
    )


class AgentFinalResponse(BaseModel):
    """Structured output schema for the agent's final response."""
    message: str = Field(description="Summary of changes and outcomes")
    applied: bool = Field(description="Whether changes were applied to the timeline")
    new_version: int | None = Field(default=None, description="New timeline version after edits")
    warnings: list[str] = Field(default_factory=list, description="Any warnings encountered")
    next_actions: list[str] = Field(default_factory=list, description="Optional suggested follow-up actions")
    verification: VerificationStatus | None = Field(
        default=None,
        description="Verification status - required if edits were applied"
    )
