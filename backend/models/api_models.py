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
