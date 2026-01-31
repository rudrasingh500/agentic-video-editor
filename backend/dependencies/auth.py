import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database.base import get_db
from database.models import User
from operators.auth_operator import validate_session


@dataclass
class SessionData:
    session_id: UUID
    user_id: UUID | None
    scopes: list[str]


DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEV_SESSION_ID = UUID("00000000-0000-0000-0000-000000000002")
DEV_SCOPES = ["dev"]


def parse_session_cookie(cookie: str) -> tuple[UUID, str] | None:
    try:
        parts = cookie.split(".", 1)
        if len(parts) != 2:
            return None
        return UUID(parts[0]), parts[1]
    except (ValueError, IndexError):
        return None


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def _resolve_dev_session(token: str | None) -> SessionData | None | bool:
    if not token:
        return None
    dev_token = os.getenv("DEV_API_TOKEN")
    if not dev_token:
        return None
    if not secrets.compare_digest(token, dev_token):
        return False
    return SessionData(
        session_id=DEV_SESSION_ID,
        user_id=DEV_USER_ID,
        scopes=DEV_SCOPES,
    )


def get_session(
    sid: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SessionData:
    token = _parse_bearer_token(authorization)
    dev_session = _resolve_dev_session(token)
    if dev_session is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )
    if dev_session:
        _ensure_dev_user(db, dev_session.user_id)
        return dev_session
    if not sid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    parsed = parse_session_cookie(sid)
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session cookie",
        )

    session_id, secret = parsed
    session_data = validate_session(session_id, secret, db)

    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )

    return SessionData(
        session_id=session_id,
        user_id=UUID(session_data["user_id"]) if session_data["user_id"] else None,
        scopes=session_data.get("scopes", []),
    )


def get_optional_session(
    sid: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> SessionData | None:
    token = _parse_bearer_token(authorization)
    dev_session = _resolve_dev_session(token)
    if dev_session is False:
        return None
    if dev_session:
        _ensure_dev_user(db, dev_session.user_id)
        return dev_session
    if not sid:
        return None

    parsed = parse_session_cookie(sid)
    if not parsed:
        return None

    session_id, secret = parsed
    session_data = validate_session(session_id, secret, db)

    if not session_data:
        return None

    return SessionData(
        session_id=session_id,
        user_id=UUID(session_data["user_id"]) if session_data["user_id"] else None,
        scopes=session_data.get("scopes", []),
    )


def require_scope(required_scope: str):
    def checker(session: SessionData = Depends(get_session)) -> SessionData:
        if required_scope not in session.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {required_scope}",
            )
        return session

    return checker


def _ensure_dev_user(db: Session, user_id: UUID | None) -> None:
    if user_id is None:
        return
    existing = db.query(User).filter(User.session_id == user_id).first()
    if existing:
        return
    now = datetime.now(timezone.utc)
    user = User(session_id=user_id, last_activity=now, created_at=now)
    try:
        db.add(user)
        db.commit()
    except Exception:
        db.rollback()
