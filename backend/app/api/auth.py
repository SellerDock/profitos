from __future__ import annotations

import logging
import io
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pyotp
import segno
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import EmailStr, Field
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_dep import get_current_user
from app.core.config import settings
from app.core.deployment import require_hosted
from app.core.database import SessionLocal, get_db
from app.core.device_session import (
    REFRESH_SLIDING_TTL,
    RefreshError,
    create_device_session,
    find_device_session_by_token,
    is_app_user_agent,
    revoke_family,
    rotate_refresh_token,
)
from app.core.security import hash_password, needs_rehash, new_session_token, verify_password
from app.core.session import SESSION_TTL
from app.core.tenant import TenantScope, get_scope
from app.models.tenant import Tenant
from app.models.user import ActivationToken, DeviceSession, User, UserSession, WaitlistEntry
from app.schemas.strict import StrictMutationModel
from app.services.email import send_activation_email, send_waitlist_admin_notification_email

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("app.security")

SESSION_COOKIE = "apos_session"
REFRESH_COOKIE = "apos_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"
ENROLL_COOKIE = "apos_totp_enroll"
ENROLL_TTL = timedelta(minutes=5)
_DUMMY_HASH: str | None = None

# Rate limit attempt counters persist in the `login_rate_limit_attempts` table
# (PostgreSQL) instead of in-process memory, so they survive backend restarts
# and stay correct if more than one backend process is ever run.
_RATE_LIMIT_MAX_WINDOW = timedelta(hours=24)


def _send_registration_admin_notification(*, entry: WaitlistEntry) -> None:
    try:
        send_waitlist_admin_notification_email(entry=entry)
    except Exception as exc:
        logger.warning("auth registration_admin_email_failed email=%s error=%s", entry.email, exc)


@dataclass
class EnrollmentState:
    user_id: int
    secret: str
    expires_at: datetime


_enrollments: dict[str, EnrollmentState] = {}


class LoginRequest(StrictMutationModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=512)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$")
    remember_device: bool = False


class TotpEnrollRequest(StrictMutationModel):
    totp: str = Field(pattern=r"^\d{6}$")


class TotpDisableRequest(StrictMutationModel):
    password: str = Field(min_length=8, max_length=512)


class WaitlistRequest(StrictMutationModel):
    email: EmailStr
    company: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    monthly_orders: str | None = Field(default=None, max_length=32)
    message: str | None = Field(default=None, max_length=2000)
    website: str | None = Field(default=None, max_length=255)
    privacy_accepted: bool = False


class ActivateRequest(StrictMutationModel):
    token: str = Field(min_length=16, max_length=256)
    password: str = Field(min_length=8, max_length=512)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$")
    privacy_accepted: bool = False


class DeleteSelfRequest(StrictMutationModel):
    password: str | None = Field(default=None, max_length=512)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$")
    confirm: bool


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-constant-time-login")
    return _DUMMY_HASH


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56] or "tenant"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    counter = 2
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        suffix = f"-{counter}"
        slug = f"{base[:64 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def _activation_url(raw_token: str) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}/activate?token={raw_token}"


def _tenant_name_for_registration(data: WaitlistRequest, email: str) -> str:
    company = (data.company or "").strip()
    if len(company) >= 2:
        return company[:255]
    return email.split("@", 1)[0][:255] or "ProfitOS"


def _latest_activation(db: Session, *, email: str) -> ActivationToken | None:
    return (
        db.query(ActivationToken)
        .filter(ActivationToken.email == email)
        .order_by(ActivationToken.created_at.desc())
        .first()
    )


def _create_activation_for_tenant(
    db: Session,
    *,
    entry: WaitlistEntry,
    tenant_id: int,
) -> tuple[ActivationToken, str]:
    raw_token = secrets.token_urlsafe(32)
    activation = ActivationToken(
        token_hash=_token_hash(raw_token),
        waitlist_entry_id=entry.id,
        tenant_id=tenant_id,
        email=entry.email.lower(),
        created_by_user_id=None,
        expires_at=_now() + timedelta(days=7),
    )
    entry.approved_at = entry.approved_at or _now()
    db.add(activation)
    return activation, raw_token


def _create_activation_for_entry(
    db: Session,
    *,
    entry: WaitlistEntry,
    tenant_name: str,
) -> tuple[ActivationToken, str]:
    tenant = Tenant(name=tenant_name, slug=_unique_slug(db, tenant_name), is_active=True)
    db.add(tenant)
    db.flush()
    return _create_activation_for_tenant(db, entry=entry, tenant_id=tenant.id)


def _create_fresh_activation_for_existing_entry(
    db: Session,
    *,
    entry: WaitlistEntry,
    tenant_name: str,
) -> tuple[ActivationToken, str]:
    latest = _latest_activation(db, email=entry.email.lower())
    if latest and latest.used_at is None and latest.revoked_at is None:
        latest.revoked_at = _now()
    if latest and latest.tenant_id:
        return _create_activation_for_tenant(db, entry=entry, tenant_id=latest.tenant_id)
    return _create_activation_for_entry(db, entry=entry, tenant_name=tenant_name)


def _send_activation_for_registration(
    *,
    activation: ActivationToken,
    raw_token: str,
    tenant_name: str,
) -> tuple[bool, str | None]:
    try:
        return (
            send_activation_email(
                to_email=activation.email,
                activation_url=_activation_url(raw_token),
                tenant_name=tenant_name,
                expires_at=activation.expires_at,
            ),
            None,
        )
    except Exception as exc:
        logger.warning("auth registration_activation_email_failed email=%s error=%s", activation.email, exc)
        return False, str(exc)


def _user_agent(request: Request) -> str | None:
    value = request.headers.get("user-agent")
    return value[:512] if value else None


def _login_bucket_key(email: str, ip: str) -> str:
    return f"login:{email}:{ip}"


def _waitlist_bucket_key(ip: str) -> str:
    return f"waitlist:{ip}"


def _refresh_bucket_key(ip: str) -> str:
    return f"refresh:{ip}"


def _rl_sweep_stale(session: Session) -> None:
    # Global janitor pass, independent of any single bucket_key: bounds table
    # growth for keys that are never retried (and thus never pruned by their
    # own count query below).
    session.execute(
        text("DELETE FROM login_rate_limit_attempts WHERE created_at <= :cutoff"),
        {"cutoff": _now() - _RATE_LIMIT_MAX_WINDOW},
    )


def _rl_count(session: Session, bucket_key: str, window: timedelta) -> int:
    return session.execute(
        text(
            "SELECT count(*) FROM login_rate_limit_attempts "
            "WHERE bucket_key = :key AND created_at > :cutoff"
        ),
        {"key": bucket_key, "cutoff": _now() - window},
    ).scalar_one()


def _rl_insert(session: Session, bucket_key: str) -> None:
    session.execute(
        text("INSERT INTO login_rate_limit_attempts (bucket_key, created_at) VALUES (:key, :created_at)"),
        {"key": bucket_key, "created_at": _now()},
    )


def _rate_limited(bucket_key: str, limit: int, window: timedelta) -> bool:
    """Check-then-record limiter: only accepted attempts consume a slot."""
    with SessionLocal() as session:
        if _rl_count(session, bucket_key, window) >= limit:
            session.commit()
            return True
        _rl_insert(session, bucket_key)
        _rl_sweep_stale(session)
        session.commit()
        return False


def _login_rate_limited(bucket_key: str, limit: int, window: timedelta) -> bool:
    """Peek-only check, used before verifying credentials."""
    with SessionLocal() as session:
        count = _rl_count(session, bucket_key, window)
        session.commit()
        return count >= limit


def _record_failed_login(bucket_key: str, limit: int, window: timedelta) -> bool:
    """Record a failed attempt and report whether the limit is now reached."""
    with SessionLocal() as session:
        _rl_insert(session, bucket_key)
        count = _rl_count(session, bucket_key, window)
        _rl_sweep_stale(session)
        session.commit()
        return count >= limit


def _create_session(db: Session, user: User, request: Request) -> str:
    token = new_session_token()
    session = UserSession(
        id=token,
        user_id=user.id,
        expires_at=_now() + SESSION_TTL,
        user_agent=_user_agent(request),
        ip=_client_ip(request),
    )
    db.add(session)
    user.last_login_at = _now()
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    logger.info("auth session_created email=%s ip=%s", user.email, _client_ip(request))
    return token


def _get_valid_activation(db: Session, raw_token: str) -> ActivationToken:
    activation = db.query(ActivationToken).filter(ActivationToken.token_hash == _token_hash(raw_token)).first()
    if (
        not activation
        or activation.used_at is not None
        or activation.revoked_at is not None
        or activation.expires_at <= _now()
    ):
        raise HTTPException(400, {"code": "invalid_token", "message": "Invalid or expired activation token"})
    tenant = db.get(Tenant, activation.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(400, {"code": "invalid_token", "message": "Invalid or expired activation token"})
    return activation


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(REFRESH_SLIDING_TTL.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )


def _set_enroll_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        ENROLL_COOKIE,
        token,
        max_age=int(ENROLL_TTL.total_seconds()),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )


def _clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=settings.session_cookie_secure, samesite="strict")


def render_provisioning_qr(uri: str) -> str:
    qr = segno.make(uri, error="m")
    buf = io.BytesIO()
    qr.save(
        buf,
        kind="svg",
        xmldecl=False,
        svgns=True,
        scale=4,
        dark="#0f172a",
        light="#ffffff",
        border=2,
    )
    svg = buf.getvalue().decode("utf-8")
    if "<script" in svg.lower():
        raise RuntimeError("Unsafe QR SVG generated")
    return svg


@router.post("/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    email = data.email.lower()
    ip = _client_ip(request)
    user = db.query(User).filter(User.email == email).first()

    if user and user.locked_until and user.locked_until > _now():
        logger.warning("auth login_locked email=%s ip=%s until=%s", email, ip, user.locked_until)
        raise HTTPException(429, "Too many login attempts", headers={"Retry-After": "900"})

    bucket_key = _login_bucket_key(email, ip)
    login_window = timedelta(minutes=15)
    if _login_rate_limited(bucket_key, 5, login_window):
        if user:
            user.locked_until = _now() + login_window
            db.commit()
        logger.warning("auth login_rate_limited email=%s ip=%s", email, ip)
        raise HTTPException(429, "Too many login attempts", headers={"Retry-After": "900"})

    password_ok = verify_password(user.password_hash if user else _dummy_hash(), data.password)
    if not user or not user.is_active or not password_ok:
        if user:
            user.failed_login_attempts += 1
            if _record_failed_login(bucket_key, 5, login_window):
                user.locked_until = _now() + login_window
            db.commit()
        else:
            _record_failed_login(bucket_key, 5, login_window)
        logger.warning("auth login_fail email=%s ip=%s reason=credentials", email, ip)
        raise HTTPException(401, "Invalid credentials")

    tenant = db.get(Tenant, user.tenant_id)
    if not tenant or not tenant.is_active:
        logger.warning("auth login_fail email=%s ip=%s reason=tenant_inactive", email, ip)
        raise HTTPException(401, "Invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
        db.commit()

    if user.is_operator:
        if user.totp_secret is None:
            secret = pyotp.random_base32()
            enroll_token = new_session_token()
            _enrollments[enroll_token] = EnrollmentState(
                user_id=user.id,
                secret=secret,
                expires_at=_now() + ENROLL_TTL,
            )
            provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
                name=user.email,
                issuer_name=settings.BRAND_PRODUCT_NAME,
            )
            _set_enroll_cookie(response, enroll_token)
            logger.info("auth totp_enroll_required email=%s ip=%s", user.email, ip)
            return {
                "status": "totp_enroll_required",
                "provisioning_uri": provisioning_uri,
                "secret": secret,
                "qr_svg": render_provisioning_qr(provisioning_uri),
                "issuer": settings.BRAND_PRODUCT_NAME,
                "account_name": user.email,
            }
        if not data.totp:
            return {"status": "totp_required"}
        if not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
            user.failed_login_attempts += 1
            if _record_failed_login(bucket_key, 5, login_window):
                user.locked_until = _now() + login_window
            db.commit()
            logger.warning("auth login_fail email=%s ip=%s reason=totp", email, ip)
            raise HTTPException(401, "Invalid TOTP code")
    elif user.totp_secret:
        if not data.totp:
            return {"status": "totp_required"}
        if not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
            user.failed_login_attempts += 1
            if _record_failed_login(bucket_key, 5, login_window):
                user.locked_until = _now() + login_window
            db.commit()
            logger.warning("auth login_fail email=%s ip=%s reason=totp", email, ip)
            raise HTTPException(401, "Invalid TOTP code")

    token = _create_session(db, user, request)
    _set_session_cookie(response, token)

    user_agent = _user_agent(request)
    if data.remember_device or is_app_user_agent(user_agent):
        issued = create_device_session(
            db,
            user_id=user.id,
            tenant_id=user.tenant_id,
            user_agent=user_agent,
            ip=ip,
        )
        db.commit()
        _set_refresh_cookie(response, issued.raw_token)
        logger.info("auth device_session_created user_id=%s ip=%s", user.id, ip)

    logger.info("auth login_success email=%s ip=%s", user.email, ip)
    return {
        "status": "ok",
        "user": {
            "email": user.email,
            "is_operator": user.is_operator,
            "tenant_id": user.tenant_id,
            "totp_enrolled": bool(user.totp_secret),
        },
    }


@router.post("/refresh")
def refresh(
    request: Request,
    response: Response,
    apos_refresh: str | None = Cookie(default=None),
    x_refresh_token: str | None = Header(default=None, alias="X-Refresh-Token"),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    if _rate_limited(_refresh_bucket_key(ip), 20, timedelta(minutes=15)):
        logger.warning("auth refresh_rate_limited ip=%s", ip)
        raise HTTPException(429, "Too many refresh attempts", headers={"Retry-After": "900"})

    raw_token = apos_refresh or x_refresh_token
    if not raw_token:
        raise HTTPException(401, "Authentication required")

    try:
        issued = rotate_refresh_token(db, raw_token=raw_token, user_agent=_user_agent(request), ip=ip)
    except RefreshError as exc:
        logger.warning("auth refresh_rejected ip=%s reason=%s", ip, exc.reason)
        raise HTTPException(401, "Authentication required") from exc

    user = db.get(User, issued.device_session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Authentication required")
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(401, "Authentication required")

    token = _create_session(db, user, request)
    _set_session_cookie(response, token)
    _set_refresh_cookie(response, issued.raw_token)
    logger.info("auth refresh_rotated user_id=%s ip=%s", user.id, ip)
    return {
        "status": "ok",
        "user": {
            "email": user.email,
            "is_operator": user.is_operator,
            "tenant_id": user.tenant_id,
            "totp_enrolled": bool(user.totp_secret),
        },
    }


@router.post("/totp/enroll")
def enroll_totp(
    data: TotpEnrollRequest,
    request: Request,
    response: Response,
    apos_totp_enroll: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    state = _enrollments.get(apos_totp_enroll or "")
    if not state or state.expires_at <= _now():
        raise HTTPException(401, "TOTP enrollment expired")
    user = db.get(User, state.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "TOTP enrollment expired")
    if not pyotp.TOTP(state.secret).verify(data.totp, valid_window=1):
        raise HTTPException(401, "Invalid TOTP code")

    user.totp_secret = state.secret
    user.totp_enrolled_at = _now()
    token = _create_session(db, user, request)
    _set_session_cookie(response, token)
    _clear_cookie(response, ENROLL_COOKIE)
    _enrollments.pop(apos_totp_enroll or "", None)
    logger.info("auth totp_enrolled email=%s ip=%s", user.email, _client_ip(request))
    return {
        "status": "ok",
        "user": {
            "email": user.email,
            "is_operator": user.is_operator,
            "tenant_id": user.tenant_id,
            "totp_enrolled": bool(user.totp_secret),
        },
    }


@router.post("/totp/setup")
def setup_totp(
    response: Response,
    user: User = Depends(get_current_user),
):
    if user.totp_secret:
        raise HTTPException(409, "TOTP is already enabled")
    secret = pyotp.random_base32()
    enroll_token = new_session_token()
    _enrollments[enroll_token] = EnrollmentState(
        user_id=user.id,
        secret=secret,
        expires_at=_now() + ENROLL_TTL,
    )
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=settings.BRAND_PRODUCT_NAME,
    )
    _set_enroll_cookie(response, enroll_token)
    return {
        "status": "totp_enroll_required",
        "provisioning_uri": provisioning_uri,
        "secret": secret,
        "qr_svg": render_provisioning_qr(provisioning_uri),
        "issuer": settings.BRAND_PRODUCT_NAME,
        "account_name": user.email,
    }


@router.post("/totp/disable")
def disable_totp(
    data: TotpDisableRequest,
    apos_session: str | None = Cookie(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.is_operator:
        raise HTTPException(403, "Operator TOTP cannot be disabled")
    if not data.password or not verify_password(user.password_hash, data.password):
        raise HTTPException(401, "Invalid credentials")
    db_user = db.get(User, user.id)
    if not db_user:
        raise HTTPException(401, "Authentication required")
    db_user.totp_secret = None
    db_user.totp_enrolled_at = None
    db.execute(
        text("""
            UPDATE user_sessions
            SET revoked_at = now()
            WHERE user_id = :uid
              AND revoked_at IS NULL
              AND id <> :current_session
        """),
        {"uid": user.id, "current_session": apos_session or ""},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/logout", status_code=204)
def logout(response: Response, apos_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if apos_session:
        session = db.get(UserSession, apos_session)
        if session and session.revoked_at is None:
            session.revoked_at = _now()
            db.commit()
            logger.info("auth session_revoked user_id=%s", session.user_id)
    _clear_cookie(response, SESSION_COOKIE)


@router.post("/device/logout", status_code=204)
def device_logout(
    response: Response,
    apos_session: str | None = Cookie(default=None),
    apos_refresh: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if apos_session:
        session = db.get(UserSession, apos_session)
        if session and session.revoked_at is None:
            session.revoked_at = _now()
            db.commit()
            logger.info("auth session_revoked user_id=%s", session.user_id)
    if apos_refresh:
        device_session = find_device_session_by_token(db, apos_refresh)
        if device_session is not None:
            revoke_family(db, device_session.family_id, reason="logout")
            logger.info("auth device_session_revoked user_id=%s reason=logout", device_session.user_id)
    _clear_cookie(response, SESSION_COOKIE)
    _clear_refresh_cookie(response)


@router.get("/devices")
def list_devices(scope: TenantScope = Depends(get_scope)):
    subquery = (
        scope.db.query(DeviceSession.family_id, func.max(DeviceSession.id).label("latest_id"))
        .filter(DeviceSession.user_id == scope.user.id, DeviceSession.tenant_id == scope.tenant_id)
        .group_by(DeviceSession.family_id)
        .subquery()
    )
    rows = (
        scope.db.query(DeviceSession)
        .join(subquery, DeviceSession.id == subquery.c.latest_id)
        .order_by(DeviceSession.created_at.desc())
        .all()
    )
    return {
        "devices": [
            {
                "id": row.id,
                "device_label": row.device_label,
                "user_agent": row.user_agent,
                "app_version": row.app_version,
                "ip_created": row.ip_created,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "status": "revoked" if row.revoked_at else "active",
            }
            for row in rows
        ]
    }


@router.delete("/devices/{device_id}", status_code=204)
def revoke_device(device_id: int, scope: TenantScope = Depends(get_scope)):
    row = (
        scope.db.query(DeviceSession)
        .filter(
            DeviceSession.id == device_id,
            DeviceSession.user_id == scope.user.id,
            DeviceSession.tenant_id == scope.tenant_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "not found")
    revoke_family(scope.db, row.family_id, reason="user_revoked")
    logger.info("auth device_session_revoked user_id=%s reason=user_revoked", scope.user.id)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "email": user.email,
        "is_operator": user.is_operator,
        "tenant_id": user.tenant_id,
        "totp_enrolled": bool(user.totp_secret),
    }


@router.get("/activate/{token}", dependencies=[Depends(require_hosted)])
def activation_status(token: str, db: Session = Depends(get_db)):
    activation = _get_valid_activation(db, token)
    tenant = db.get(Tenant, activation.tenant_id)
    if not activation.totp_secret:
        activation.totp_secret = pyotp.random_base32()
        db.commit()
        db.refresh(activation)
    provisioning_uri = pyotp.totp.TOTP(activation.totp_secret).provisioning_uri(
        name=activation.email,
        issuer_name=settings.BRAND_PRODUCT_NAME,
    )
    return {
        "status": "valid",
        "email": activation.email,
        "tenant_name": tenant.name if tenant else "",
        "provisioning_uri": provisioning_uri,
        "secret": activation.totp_secret,
        "qr_svg": render_provisioning_qr(provisioning_uri),
        "expires_at": activation.expires_at.isoformat(),
    }


@router.post("/activate", dependencies=[Depends(require_hosted)])
def activate_account(data: ActivateRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    if not data.privacy_accepted:
        raise HTTPException(422, "Privacy policy acceptance required")
    activation = _get_valid_activation(db, data.token)
    if db.query(User).filter(User.email == activation.email.lower()).first():
        raise HTTPException(400, {"code": "invalid_token", "message": "Activation email already has an account"})
    if data.totp:
        if not activation.totp_secret:
            raise HTTPException(400, {"code": "invalid_token", "message": "Activation not prepared"})
        if not pyotp.TOTP(activation.totp_secret).verify(data.totp, valid_window=1):
            raise HTTPException(401, "Invalid TOTP code")
    now = _now()
    user = User(
        email=activation.email.lower(),
        password_hash=hash_password(data.password),
        tenant_id=activation.tenant_id,
        is_operator=False,
        is_active=True,
        totp_secret=activation.totp_secret if data.totp else None,
        totp_enrolled_at=now if data.totp else None,
        privacy_accepted_at=now,
    )
    activation.used_at = now
    db.add(user)
    db.flush()
    token = _create_session(db, user, request)
    _set_session_cookie(response, token)
    logger.info("auth activation_success email=%s ip=%s", user.email, _client_ip(request))
    return {"status": "ok"}


@router.post("/waitlist", dependencies=[Depends(require_hosted)])
def waitlist(data: WaitlistRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if not data.privacy_accepted:
        raise HTTPException(422, "Privacy policy acceptance required")
    if data.website:
        return {"status": "ok"}
    if _rate_limited(_waitlist_bucket_key(ip), 3, timedelta(hours=24)):
        response.headers["Retry-After"] = "3600"
        raise HTTPException(429, "Too many waitlist submissions", headers={"Retry-After": "3600"})
    email = data.email.lower()

    if db.query(User).filter(User.email == email).first():
        logger.info("auth registration_existing_user email=%s ip=%s", email, ip)
        return {"status": "ok", "activation_email_sent": False}

    tenant_name = _tenant_name_for_registration(data, email)
    existing_entry = db.query(WaitlistEntry).filter(WaitlistEntry.email == email).first()
    if existing_entry:
        existing_entry.company = data.company or existing_entry.company
        existing_entry.phone = data.phone or existing_entry.phone
        existing_entry.monthly_orders = data.monthly_orders or existing_entry.monthly_orders
        existing_entry.message = data.message or existing_entry.message
        existing_entry.privacy_accepted_at = existing_entry.privacy_accepted_at or _now()
        activation, raw_token = _create_fresh_activation_for_existing_entry(
            db,
            entry=existing_entry,
            tenant_name=tenant_name,
        )
        db.commit()
        _send_registration_admin_notification(entry=existing_entry)
        activation_email_sent, activation_email_error = _send_activation_for_registration(
            activation=activation,
            raw_token=raw_token,
            tenant_name=tenant_name,
        )
        logger.info("auth registration_duplicate email=%s ip=%s activation_email_sent=%s", email, ip, activation_email_sent)
        response_data = {"status": "ok", "activation_email_sent": activation_email_sent}
        if activation_email_error:
            response_data["activation_email_error"] = activation_email_error
        return response_data

    entry = WaitlistEntry(
        email=email,
        company=data.company,
        phone=data.phone,
        monthly_orders=data.monthly_orders,
        message=data.message,
        ip=ip,
        user_agent=_user_agent(request),
        privacy_accepted_at=_now(),
    )
    db.add(entry)
    try:
        db.flush()
        activation, raw_token = _create_activation_for_entry(db, entry=entry, tenant_name=tenant_name)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_entry = db.query(WaitlistEntry).filter(WaitlistEntry.email == email).first()
        logger.info("auth registration duplicate_after_integrity email=%s ip=%s", email, ip)
        if not existing_entry:
            return {"status": "ok", "activation_email_sent": False}
        activation, raw_token = _create_fresh_activation_for_existing_entry(
            db,
            entry=existing_entry,
            tenant_name=tenant_name,
        )
        db.commit()
        _send_registration_admin_notification(entry=existing_entry)
        activation_email_sent, activation_email_error = _send_activation_for_registration(
            activation=activation,
            raw_token=raw_token,
            tenant_name=tenant_name,
        )
        response_data = {"status": "ok", "activation_email_sent": activation_email_sent}
        if activation_email_error:
            response_data["activation_email_error"] = activation_email_error
        return response_data
    _send_registration_admin_notification(entry=entry)
    activation_email_sent, activation_email_error = _send_activation_for_registration(
        activation=activation,
        raw_token=raw_token,
        tenant_name=tenant_name,
    )
    logger.info("auth registration_created email=%s ip=%s activation_email_sent=%s", email, ip, activation_email_sent)
    response_data = {"status": "ok", "activation_email_sent": activation_email_sent}
    if activation_email_error:
        response_data["activation_email_error"] = activation_email_error
    return response_data


@router.post("/me/delete", status_code=204)
def delete_self(
    data: DeleteSelfRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.is_operator:
        raise HTTPException(403, "Operators cannot self-delete via API. Use scripts/delete_operator.py")
    if not data.confirm:
        raise HTTPException(422, "Confirmation required")
    if not data.password or not verify_password(user.password_hash, data.password):
        raise HTTPException(401, "Invalid credentials")
    if user.totp_secret:
        if not data.totp or not pyotp.TOTP(user.totp_secret).verify(data.totp, valid_window=1):
            raise HTTPException(401, "Invalid TOTP code")

    tenant_id = user.tenant_id
    db_user = db.get(User, user.id)
    if not db_user:
        raise HTTPException(401, "Authentication required")
    sibling_count = db.query(User).filter(User.tenant_id == tenant_id, User.id != user.id).count()

    from app.services.cleanup import _hard_delete_user

    _hard_delete_user(db, db_user, also_delete_tenant=(sibling_count == 0 and tenant_id != 1))
    _clear_cookie(response, SESSION_COOKIE)
    logger.info("auth user_self_deleted email=%s tenant_id=%s", user.email, tenant_id)
