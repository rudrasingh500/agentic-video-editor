from datetime import datetime
from typing import Any
from pydantic import BaseModel


class SessionCreateResponse(BaseModel):
    ok: bool
    session_id: str
    user_id: str
    expires_at: datetime


class SessionValidateResponse(BaseModel):
    valid: bool
    user_id: str | None = None
    scopes: list[str] = []


class ProjectCreateRequest(BaseModel):
    name: str


class ProjectCreateResponse(BaseModel):
    ok: bool
    project_id: str
    project_name: str


class ProjectListResponse(BaseModel):
    ok: bool
    projects: list[dict[str, Any]]


class ProjectGetResponse(BaseModel):
    ok: bool
    project_id: str
    project_name: str


class ProjectDeleteResponse(BaseModel):
    ok: bool


class AssetResponse(BaseModel):
    asset_id: str
    asset_name: str
    asset_type: str
    asset_url: str
    uploaded_at: datetime
    indexing_status: str
    indexing_error: str | None = None
    indexing_attempts: int = 0


class AssetListResponse(BaseModel):
    ok: bool
    assets: list[AssetResponse]


class AssetUploadResponse(BaseModel):
    ok: bool
    asset: AssetResponse


class AssetDeleteResponse(BaseModel):
    ok: bool


class AssetReindexResponse(BaseModel):
    ok: bool
    asset: AssetResponse


# Edit Agent API Models


class EditRequestBody(BaseModel):
    """Request body for sending an edit request."""

    message: str
    session_id: str | None = None


class EditPatchSummary(BaseModel):
    """Summary of a pending patch."""

    patch_id: str
    agent_type: str
    operation_count: int
    description: str
    created_at: datetime


class EditResponse(BaseModel):
    """Response from the edit agent."""

    ok: bool
    session_id: str
    message: str
    pending_patches: list[EditPatchSummary] = []
    warnings: list[str] = []
    applied: bool = False
    new_version: int | None = None


class EditSessionResponse(BaseModel):
    """Response containing edit session details."""

    ok: bool
    session_id: str
    project_id: str
    timeline_id: str
    title: str | None
    status: str
    message_count: int
    pending_patch_count: int
    created_at: datetime
    updated_at: datetime


class EditSessionListResponse(BaseModel):
    """Response containing list of edit sessions."""

    ok: bool
    sessions: list[EditSessionResponse]
    total: int


class EditSessionDetailResponse(BaseModel):
    """Response containing full edit session with messages."""

    ok: bool
    session_id: str
    project_id: str
    timeline_id: str
    title: str | None
    status: str
    messages: list[dict[str, Any]]
    pending_patches: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ApplyPatchesRequestBody(BaseModel):
    """Request body for applying patches."""

    patch_ids: list[str] | None = None
    description: str = "Applied AI-suggested edits"


class ApplyPatchesResponse(BaseModel):
    """Response from applying patches."""

    ok: bool
    new_version: int | None = None
    operations_applied: int = 0
    errors: list[str] = []


class EditSessionCloseResponse(BaseModel):
    """Response from closing/cancelling a session."""

    ok: bool
