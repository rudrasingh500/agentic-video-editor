from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionCreateResponse(BaseModel):
    ok: bool
    session_id: str
    user_id: str
    expires_at: datetime


class SessionValidateResponse(BaseModel):
    valid: bool
    user_id: str | None = None
    scopes: list[str] = Field(default_factory=list)


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


class AssetDownloadResponse(BaseModel):
    ok: bool
    url: str
    expires_in: int | None = None


class AssetDeleteResponse(BaseModel):
    ok: bool


class AssetReindexResponse(BaseModel):
    ok: bool
    asset: AssetResponse


class GenerationFrameRange(BaseModel):
    start_frame: int
    end_frame: int


class GenerationCreateRequest(BaseModel):
    prompt: str
    mode: str = "image"
    target_asset_id: str | None = None
    frame_range: GenerationFrameRange | None = None
    frame_indices: list[int] | None = None
    frame_repeat_count: int | None = None
    reference_asset_id: str | None = None
    reference_snippet_id: str | None = None
    reference_identity_id: str | None = None
    reference_character_model_id: str | None = None
    model: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    timeline_id: str | None = None
    request_context: dict[str, Any] = Field(default_factory=dict)


class GenerationDecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    reason: str | None = None


class GenerationResponse(BaseModel):
    generation_id: str
    project_id: str
    timeline_id: str | None = None
    request_origin: str
    requestor: str
    provider: str
    model: str
    mode: str
    status: str
    prompt: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    reference_asset_id: str | None = None
    reference_snippet_id: str | None = None
    reference_identity_id: str | None = None
    reference_character_model_id: str | None = None
    target_asset_id: str | None = None
    frame_range: dict[str, Any] | None = None
    frame_indices: list[int] | None = None
    frame_repeat_count: int | None = None
    generated_asset: AssetResponse | None = None
    generated_preview_url: str | None = None
    applied_asset: AssetResponse | None = None
    applied_preview_url: str | None = None
    request_context: dict[str, Any] = Field(default_factory=dict)
    decision_reason: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None
    applied_at: datetime | None = None


class GenerationCreateResponse(BaseModel):
    ok: bool
    generation: GenerationResponse


class GenerationDecisionResponse(BaseModel):
    ok: bool
    generation: GenerationResponse


class GenerationDetailResponse(BaseModel):
    ok: bool
    generation: GenerationResponse


class OutputUploadUrlRequest(BaseModel):
    filename: str
    content_type: str | None = None


class OutputUploadUrlResponse(BaseModel):
    ok: bool
    upload_url: str
    gcs_path: str
    expires_in: int | None = None


class OutputShareRequest(BaseModel):
    gcs_path: str
    changes: dict[str, Any] | None = None


class OutputShareResponse(BaseModel):
    ok: bool
    video_id: str
    video_url: str
    version: int
    created_at: datetime


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
    pending_patches: list[EditPatchSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
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
    errors: list[str] = Field(default_factory=list)


class EditSessionCloseResponse(BaseModel):
    """Response from closing/cancelling a session."""

    ok: bool


class SnippetCreateRequest(BaseModel):
    snippet_type: str
    source_type: str
    source_ref: dict[str, Any] = Field(default_factory=dict)
    asset_id: str | None = None
    frame_index: int | None = None
    timestamp_ms: int | None = None
    bbox: dict[str, Any] | None = None
    descriptor: str | None = None
    embedding: list[float] | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    quality_score: float | None = None
    created_by: str = "user"


class SnippetResponse(BaseModel):
    snippet_id: str
    project_id: str
    asset_id: str | None = None
    snippet_type: str
    source_type: str
    source_ref: dict[str, Any] = Field(default_factory=dict)
    frame_index: int | None = None
    timestamp_ms: int | None = None
    bbox: dict[str, Any] | None = None
    descriptor: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    quality_score: float | None = None
    created_by: str
    created_at: datetime


class SnippetDetailResponse(BaseModel):
    ok: bool
    snippet: SnippetResponse
    preview_url: str | None = None


class SnippetListResponse(BaseModel):
    ok: bool
    snippets: list[SnippetResponse]


class IdentityCreateRequest(BaseModel):
    name: str
    identity_type: str
    description: str | None = None
    snippet_ids: list[str] = Field(default_factory=list)
    created_by: str = "user"


class IdentityResponse(BaseModel):
    identity_id: str
    project_id: str
    identity_type: str
    name: str
    description: str | None = None
    status: str
    canonical_snippet_id: str | None = None
    merged_into_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class IdentityDetailResponse(BaseModel):
    ok: bool
    identity: IdentityResponse


class IdentityListResponse(BaseModel):
    ok: bool
    identities: list[IdentityResponse]


class IdentityMergeRequest(BaseModel):
    source_identity_ids: list[str]
    target_identity_id: str
    actor: str = "agent"
    reason: str | None = None


class IdentityMergeResponse(BaseModel):
    ok: bool
    identity: IdentityResponse


class CharacterModelCreateRequest(BaseModel):
    name: str
    model_type: str = "character"
    description: str | None = None
    canonical_prompt: str | None = None
    identity_ids: list[str] = Field(default_factory=list)
    snippet_ids: list[str] = Field(default_factory=list)
    created_by: str = "user"


class CharacterModelResponse(BaseModel):
    character_model_id: str
    project_id: str
    model_type: str
    name: str
    description: str | None = None
    canonical_prompt: str | None = None
    status: str
    canonical_snippet_id: str | None = None
    merged_into_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class CharacterModelDetailResponse(BaseModel):
    ok: bool
    character_model: CharacterModelResponse


class CharacterModelListResponse(BaseModel):
    ok: bool
    character_models: list[CharacterModelResponse]


class CharacterModelMergeRequest(BaseModel):
    source_model_ids: list[str]
    target_model_id: str
    actor: str = "agent"
    reason: str | None = None


class CharacterModelMergeResponse(BaseModel):
    ok: bool
    character_model: CharacterModelResponse


class SnippetMergeSuggestionResponse(BaseModel):
    ok: bool
    suggestions: list[dict[str, Any]]


class SnippetMergeDecisionRequest(BaseModel):
    decision: str
    actor: str = "agent"


class SnippetMergeDecisionResponse(BaseModel):
    ok: bool
    suggestion_id: str
    decision: str


class AttachGenerationAnchorRequest(BaseModel):
    anchor_type: str
    timeline_id: str | None = None
    snippet_id: str | None = None
    identity_id: str | None = None
    character_model_id: str | None = None
    request_context: dict[str, Any] = Field(default_factory=dict)
    created_by: str = "agent"


class AttachGenerationAnchorResponse(BaseModel):
    ok: bool
    anchor_id: str


class BestIdentityCandidatesResponse(BaseModel):
    ok: bool
    candidates: list[dict[str, Any]]
