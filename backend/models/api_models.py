from datetime import datetime
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