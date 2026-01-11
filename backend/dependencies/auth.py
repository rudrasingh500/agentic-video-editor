from uuid import UUID
from dataclasses import dataclass
from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database.base import get_db
from operators.auth_operator import validate_session


@dataclass
class SessionData:
    session_id: UUID
    user_id: UUID | None
    scopes: list[str]


def parse_session_cookie(cookie: str) -> tuple[UUID, str] | None:
    try:
        parts = cookie.split(".", 1)
        if len(parts) != 2:
            return None
        return UUID(parts[0]), parts[1]
    except (ValueError, IndexError):
        return None


def get_session(
    sid: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> SessionData:
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
    db: Session = Depends(get_db),
) -> SessionData | None:
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
