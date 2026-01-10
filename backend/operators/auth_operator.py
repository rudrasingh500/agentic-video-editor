import secrets
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session as DBSession

from database.models import Session, User
from redis_client import redis_auth


SESSION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days


def generate_session_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_session(
    db: DBSession,
    user_id: UUID | None = None,
    scopes: list[str] | None = None,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> tuple[UUID, str, datetime, UUID]:
    now = datetime.now(timezone.utc)
    
    if user_id is None:
        user = User(
            session_id=uuid4(),
            last_activity=now,
            created_at=now,
        )
        db.add(user)
        db.flush()
        user_id = user.session_id

    session_id = uuid4()
    session_secret = generate_session_secret()
    secret_hash = hash_secret(session_secret)
    expires_at = now + timedelta(seconds=ttl_seconds)

    session = Session(
        id=session_id,
        secret_hash=secret_hash,
        user_id=user_id,
        scopes=scopes or [],
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()

    cache_session(session_id, secret_hash, user_id, scopes or [], ttl_seconds)

    return session_id, session_secret, expires_at, user_id


def cache_session(
    session_id: UUID,
    secret_hash: str,
    user_id: UUID | None,
    scopes: list[str],
    ttl_seconds: int,
) -> None:
    cache_key = f"sess:{session_id}"
    cache_data = {
        "secret_hash": secret_hash,
        "user_id": str(user_id) if user_id else None,
        "scopes": scopes,
    }
    redis_auth.setex(cache_key, ttl_seconds, json.dumps(cache_data))


def get_cached_session(session_id: UUID) -> dict | None:
    cache_key = f"sess:{session_id}"
    data = redis_auth.get(cache_key)
    if data:
        return json.loads(data)
    return None


def validate_session(session_id: UUID, secret: str, db: DBSession) -> dict | None:
    secret_hash = hash_secret(secret)
    
    cached = get_cached_session(session_id)
    if cached:
        if secrets.compare_digest(cached["secret_hash"], secret_hash):
            return cached
        return None

    session = db.query(Session).filter(
        Session.id == session_id,
        Session.expires_at > datetime.now(timezone.utc),
    ).first()
    
    if not session:
        return None
    
    if not secrets.compare_digest(session.secret_hash, secret_hash):
        return None

    remaining_ttl = int((session.expires_at - datetime.now(timezone.utc)).total_seconds())
    if remaining_ttl > 0:
        cache_session(session_id, session.secret_hash, session.user_id, session.scopes, remaining_ttl)

    return {
        "secret_hash": session.secret_hash,
        "user_id": str(session.user_id) if session.user_id else None,
        "scopes": session.scopes,
    }


def invalidate_session(session_id: UUID, db: DBSession) -> None:
    redis_auth.delete(f"sess:{session_id}")
    db.query(Session).filter(Session.id == session_id).delete()
    db.commit()

