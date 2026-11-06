from datetime import UTC, datetime

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import extract_bearer_token, is_valid_api_token
from app.core.session import SESSION_TTL
from app.models.tenant import Tenant
from app.models.user import User, UserSession


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def get_current_user(
    request: Request,
    apos_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if apos_session:
        session = db.get(UserSession, apos_session)
        now = _now()
        if session and session.revoked_at is None and session.expires_at > now:
            if session.last_seen_at and now - session.last_seen_at > SESSION_TTL:
                session.revoked_at = now
                db.commit()
                raise HTTPException(401, "Authentication required")
            user = db.get(User, session.user_id)
            if user and user.is_active:
                tenant = db.get(Tenant, user.tenant_id)
                if not tenant or not tenant.is_active:
                    raise HTTPException(401, "Authentication required")
                session.last_seen_at = now
                session.expires_at = now + SESSION_TTL
                db.commit()
                return user

    token = extract_bearer_token(authorization)
    if is_valid_api_token(token):
        return User(
            id=0,
            email="legacy@bearer",
            password_hash="",
            is_operator=True,
            tenant_id=None,
            is_active=True,
        )

    raise HTTPException(
        401,
        "Authentication required",
        headers={"WWW-Authenticate": "Cookie, Bearer"},
    )


async def require_operator(user: User = Depends(get_current_user)) -> User:
    if not user.is_operator:
        raise HTTPException(403, "Operator access required")
    return user
