"""Types for the Edit Orchestrator agent.

This module defines the input/output contracts for the orchestrator,
including edit requests, plans, and results.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .sub_agents.types import EDLPatch, SubAgentType


class EditSessionStatus(str, Enum):
    """Status of an edit session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MessageRole(str, Enum):
    """Role of a message in the conversation."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SessionMessage(BaseModel):
    """A single message in the edit session conversation."""

    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: list[dict[str, Any]] | None = None
    agent_responses: list[dict[str, Any]] | None = None


class EditRequest(BaseModel):
    """Input from user for an edit operation."""

    message: str = Field(description="User's edit request in natural language")
    session_id: str | None = Field(
        default=None,
        description="Continue existing session, or None to create new session",
    )


class SubAgentCall(BaseModel):
    """A planned call to a sub-agent."""

    agent_type: SubAgentType = Field(description="Type of sub-agent to invoke")
    intent: str = Field(description="What this agent should accomplish")
    focus_track_indices: list[int] | None = Field(
        default=None,
        description="Suggested track indices to focus on",
    )
    focus_time_range_ms: tuple[int, int] | None = Field(
        default=None,
        description="Suggested time range in milliseconds (start, end)",
    )
    asset_ids: list[str] = Field(
        default_factory=list,
        description="Asset IDs relevant to this sub-agent call",
    )
    priority: int = Field(
        default=1,
        description="Execution priority (1 = highest)",
    )


class EditPlan(BaseModel):
    """Orchestrator's plan before executing sub-agents."""

    summary: str = Field(description="Human-readable summary of what will be done")
    sub_agent_calls: list[SubAgentCall] = Field(
        default_factory=list,
        description="Ordered list of sub-agent calls to make",
    )
    estimated_changes: int = Field(
        default=0,
        description="Estimated number of EDL operations",
    )
    requires_assets: bool = Field(
        default=False,
        description="Whether asset retrieval is needed",
    )
    analysis_needed: list[str] = Field(
        default_factory=list,
        description="Types of analysis needed before executing",
    )


class PendingPatch(BaseModel):
    """A patch that is pending user approval."""

    patch_id: str = Field(description="Unique identifier for this patch")
    agent_type: SubAgentType = Field(description="Agent that generated this patch")
    patch: EDLPatch = Field(description="The actual patch to apply")
    reasoning: str = Field(description="Agent's reasoning for this patch")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrchestratorResult(BaseModel):
    """Final output of the orchestrator after processing a request."""

    session_id: str = Field(description="Edit session ID")
    plan: EditPlan | None = Field(
        default=None,
        description="The execution plan (if planning was performed)",
    )
    pending_patches: list[PendingPatch] = Field(
        default_factory=list,
        description="Patches awaiting user approval",
    )
    applied: bool = Field(
        default=False,
        description="Whether patches were applied (always False for now)",
    )
    new_version: int | None = Field(
        default=None,
        description="New timeline version after applying (if applied)",
    )
    message: str = Field(
        description="Response message to show user",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal warnings from processing",
    )
    trace: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full execution trace for debugging",
    )


class ApplyPatchesRequest(BaseModel):
    """Request to apply pending patches from a session."""

    patch_ids: list[str] | None = Field(
        default=None,
        description="Specific patches to apply (None = all pending)",
    )
    description: str = Field(
        default="Applied AI-suggested edits",
        description="Description for the timeline checkpoint",
    )


class ApplyPatchesResult(BaseModel):
    """Result of applying patches to the timeline."""

    success: bool
    new_version: int | None = None
    operations_applied: int = 0
    errors: list[str] = Field(default_factory=list)


class EditSessionSummary(BaseModel):
    """Summary of an edit session for listing."""

    session_id: str
    title: str | None
    status: EditSessionStatus
    message_count: int
    pending_patch_count: int
    created_at: datetime
    updated_at: datetime


class EditSessionDetail(BaseModel):
    """Full details of an edit session."""

    session_id: str
    project_id: str
    timeline_id: str
    created_by: str
    title: str | None
    status: EditSessionStatus
    messages: list[SessionMessage]
    pending_patches: list[PendingPatch]
    created_at: datetime
    updated_at: datetime
