import os
from uuid import UUID
from fastapi import APIRouter, Cookie, Depends, Header, Response
from sqlalchemy.orm import Session

from database.base import get_db
from dependencies.auth import (
    parse_session_cookie,
    resolve_session_token,
    validate_session_token,
)
from models.api_models import SessionCreateResponse, SessionValidateResponse
from operators.auth_operator import (
    create_session,
    invalidate_session,
    SESSION_TTL_SECONDS,
)


router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"


def build_session_cookie(session_id: UUID, session_secret: str) -> str:
    return f"{session_id}.{session_secret}"


@router.post("/session", response_model=SessionCreateResponse)
async def session_create(
    response: Response,
    db: Session = Depends(get_db),
):
    session_id, session_secret, expires_at, user_id = create_session(db)

    cookie_value = build_session_cookie(session_id, session_secret)
    response.set_cookie(
        key="sid",
        value=cookie_value,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )

    return SessionCreateResponse(
        ok=True,
        session_id=str(session_id),
        user_id=str(user_id),
        expires_at=expires_at,
        session_token=cookie_value,
        webhook_token=cookie_value,
    )


@router.get("/session/validate", response_model=SessionValidateResponse)
async def session_validate(
    sid: str | None = Cookie(default=None),
    x_session_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    session_token = resolve_session_token(sid, x_session_token)
    session = validate_session_token(session_token, db)
    if not session:
        return SessionValidateResponse(valid=False)

    return SessionValidateResponse(
        valid=True,
        user_id=str(session.user_id) if session.user_id else None,
        scopes=session.scopes,
        webhook_token=session_token,
    )


@router.delete("/session")
async def session_delete(
    response: Response,
    sid: str | None = Cookie(default=None),
    x_session_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    session_token = resolve_session_token(sid, x_session_token)
    if session_token:
        parsed = parse_session_cookie(session_token)
        if parsed:
            session_id, _ = parsed
            invalidate_session(session_id, db)

    response.delete_cookie(key="sid", path="/")
    return {"ok": True}
