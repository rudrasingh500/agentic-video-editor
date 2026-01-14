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


# Asset models
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
