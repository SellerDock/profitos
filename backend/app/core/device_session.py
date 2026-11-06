"""Refresh-token device sessions: issuance, sliding rotation with reuse
detection, and revocation.

Two lifetimes govern a refresh token family (see device-session-design.md
section 6): ``refresh_expires_at`` slides forward by REFRESH_SLIDING_TTL on
every successful rotation, while ``absolute_expires_at`` is fixed at
REFRESH_ABSOLUTE_TTL from the *original* login and never moves — after 90
days the user must fully re-authenticate regardless of activity.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import new_session_token
from app.models.user import DeviceSession, UserSession

REFRESH_SLIDING_TTL = timedelta(days=30)
REFRESH_ABSOLUTE_TTL = timedelta(days=90)

# Grace window distinguishing a concurrent/replayed rotation of the directly
# previous token (benign race: two parallel refreshes of the same token) from
# a genuine reuse attack (a stolen token replayed long after it was rotated
# away). Within the window we reject with 401 but do NOT revoke the family.
ROTATION_GRACE_PERIOD = timedelta(seconds=30)

APP_UA_MARKER = "pl.profitos.app"
_APP_VERSION_RE = re.compile(r"pl\.profitos\.app(?:/(\S+))?")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def is_app_user_agent(user_agent: str | None) -> bool:
    return bool(user_agent) and APP_UA_MARKER in user_agent


def _extract_app_version(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    match = _APP_VERSION_RE.search(user_agent)
    return match.group(0) if match else None


def _device_label(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    if APP_UA_MARKER in user_agent:
        return "Aplikacja ProfitOS"
    if "iPhone" in user_agent or "iPad" in user_agent:
        return "iOS — przeglądarka"
    if "Android" in user_agent:
        return "Android — przeglądarka"
    if "Macintosh" in user_agent:
        return "macOS — przeglądarka"
    if "Windows" in user_agent:
        return "Windows — przeglądarka"
    if "Linux" in user_agent:
        return "Linux — przeglądarka"
    return "Nieznane urządzenie"


@dataclass
class IssuedRefreshToken:
    device_session: DeviceSession
    raw_token: str


class RefreshError(Exception):
    """A refresh token could not be exchanged for a new session.

    Callers must map every variant to the same generic 401 response so a
    caller can never learn whether a presented token ever existed.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def create_device_session(
    db: Session,
    *,
    user_id: int,
    tenant_id: int,
    user_agent: str | None,
    ip: str | None,
) -> IssuedRefreshToken:
    now = _now()
    raw_token = new_session_token()
    device_session = DeviceSession(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=uuid.uuid4().hex,
        refresh_token_hash=hash_refresh_token(raw_token),
        device_label=_device_label(user_agent),
        user_agent=user_agent[:512] if user_agent else None,
        app_version=_extract_app_version(user_agent),
        ip_created=ip,
        created_at=now,
        last_used_at=now,
        refresh_expires_at=now + REFRESH_SLIDING_TTL,
        absolute_expires_at=now + REFRESH_ABSOLUTE_TTL,
    )
    db.add(device_session)
    db.flush()
    return IssuedRefreshToken(device_session=device_session, raw_token=raw_token)


def revoke_family(db: Session, family_id: str, *, reason: str) -> None:
    """Revoke every not-yet-revoked token in a rotation chain (one device).

    Used both for reuse-detection and for explicit user/device revocation —
    a "device" in the /devices panel is a family_id, not a single row.
    """
    db.query(DeviceSession).filter(
        DeviceSession.family_id == family_id,
        DeviceSession.revoked_at.is_(None),
    ).update({"revoked_at": _now(), "revoked_reason": reason}, synchronize_session=False)
    db.commit()


def revoke_user_sessions(db: Session, user_id: int, *, reason: str) -> None:
    now = _now()
    db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)).update(
        {"revoked_at": now}, synchronize_session=False
    )
    db.query(DeviceSession).filter(DeviceSession.user_id == user_id, DeviceSession.revoked_at.is_(None)).update(
        {"revoked_at": now, "revoked_reason": reason}, synchronize_session=False
    )


def find_device_session_by_token(db: Session, raw_token: str) -> DeviceSession | None:
    token_hash = hash_refresh_token(raw_token)
    return db.query(DeviceSession).filter(DeviceSession.refresh_token_hash == token_hash).first()


def rotate_refresh_token(
    db: Session,
    *,
    raw_token: str,
    user_agent: str | None,
    ip: str | None,
) -> IssuedRefreshToken:
    """Validate and rotate a refresh token, detecting reuse of a token that
    was already rotated away (theft signal) by revoking its whole family.

    Raises RefreshError on any invalid/expired/revoked/reused token.
    """
    now = _now()
    token_hash = hash_refresh_token(raw_token)
    # Lock the row for the whole rotation so a concurrent refresh of the same
    # token blocks until this transaction commits and then sees the rotated
    # state instead of rotating a second time.
    existing = (
        db.query(DeviceSession)
        .filter(DeviceSession.refresh_token_hash == token_hash)
        .with_for_update()
        .first()
    )
    if existing is None:
        raise RefreshError("not_found")

    if existing.rotated_at is not None:
        if existing.rotated_at >= now - ROTATION_GRACE_PERIOD:
            # Just-rotated predecessor presented again within the grace
            # window — a concurrent refresh or client retry, not theft.
            # Reject without revoking the family.
            raise RefreshError("rotated_recently")
        revoke_family(db, existing.family_id, reason="reuse_detected")
        raise RefreshError("reuse_detected")

    if existing.revoked_at is not None:
        raise RefreshError("revoked")

    if existing.absolute_expires_at <= now or existing.refresh_expires_at <= now:
        existing.revoked_at = now
        existing.revoked_reason = "expired"
        db.commit()
        raise RefreshError("expired")

    existing.rotated_at = now
    existing.last_used_at = now

    raw_new_token = new_session_token()
    rotated = DeviceSession(
        user_id=existing.user_id,
        tenant_id=existing.tenant_id,
        family_id=existing.family_id,
        refresh_token_hash=hash_refresh_token(raw_new_token),
        device_label=existing.device_label or _device_label(user_agent),
        user_agent=(user_agent[:512] if user_agent else existing.user_agent),
        app_version=_extract_app_version(user_agent) or existing.app_version,
        ip_created=ip or existing.ip_created,
        created_at=now,
        last_used_at=now,
        refresh_expires_at=min(now + REFRESH_SLIDING_TTL, existing.absolute_expires_at),
        absolute_expires_at=existing.absolute_expires_at,
    )
    db.add(rotated)
    db.commit()
    db.refresh(rotated)
    return IssuedRefreshToken(device_session=rotated, raw_token=raw_new_token)
