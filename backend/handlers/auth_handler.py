from uuid import UUID
from fastapi import APIRouter, Depends, Response, Cookie
from sqlalchemy.orm import Session

from database.base import get_db
from models.api_models import SessionCreateResponse, SessionValidateResponse
from operators.auth_operator import (
    create_session,
    validate_session,
    invalidate_session,
    SESSION_TTL_SECONDS,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def build_session_cookie(session_id: UUID, session_secret: str) -> str:
    return f"{session_id}.{session_secret}"


def parse_session_cookie(cookie: str) -> tuple[UUID, str] | None:
    try:
        parts = cookie.split(".", 1)
        if len(parts) != 2:
            return None
        return UUID(parts[0]), parts[1]
    except (ValueError, IndexError):
        return None


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
        secure=True,
        samesite="lax",
        max_age=SESSION_TTL_SECONDS,
        path="/",
    )

    return SessionCreateResponse(
        ok=True,
        session_id=str(session_id),
        user_id=str(user_id),
        expires_at=expires_at,
    )


@router.get("/session/validate", response_model=SessionValidateResponse)
async def session_validate(
    sid: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not sid:
        return SessionValidateResponse(valid=False)

    parsed = parse_session_cookie(sid)
    if not parsed:
        return SessionValidateResponse(valid=False)

    session_id, secret = parsed
    session_data = validate_session(session_id, secret, db)

    if not session_data:
        return SessionValidateResponse(valid=False)

    return SessionValidateResponse(
        valid=True,
        user_id=session_data.get("user_id"),
        scopes=session_data.get("scopes", []),
    )


@router.delete("/session")
async def session_delete(
    response: Response,
    sid: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if sid:
        parsed = parse_session_cookie(sid)
        if parsed:
            session_id, _ = parsed
            invalidate_session(session_id, db)

    response.delete_cookie(key="sid", path="/")
    return {"ok": True}
