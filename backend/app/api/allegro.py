import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import TenantScope, get_scope
from app.models.account import Account, AllegroOAuthTransaction
from app.services.allegro import AllegroService

router = APIRouter(prefix="/allegro", tags=["allegro"])
accounts_callback_router = APIRouter(prefix="/accounts/allegro", tags=["allegro"])


@router.get("/auth")
def allegro_auth_new(scope: TenantScope = Depends(get_scope)):
    """Redirect the user to Allegro OAuth consent screen for a new account."""
    service = AllegroService(scope.db)
    nonce = _start_oauth_transaction(scope, None)
    state = _encode_oauth_state({"tenant_id": scope.tenant_id, "nonce": nonce})
    try:
        url = service.get_auth_url(settings.ALLEGRO_REDIRECT_URI, state)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return _redirect_with_oauth_cookie(url, nonce)


@router.get("/auth/{account_id}")
def allegro_auth(account_id: int, scope: TenantScope = Depends(get_scope)):
    """Redirect the user to Allegro OAuth consent screen."""
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    service = AllegroService(scope.db)
    nonce = _start_oauth_transaction(scope, account_id)
    state = _encode_oauth_state({"tenant_id": scope.tenant_id, "account_id": account_id, "nonce": nonce})
    try:
        url = service.get_auth_url(settings.ALLEGRO_REDIRECT_URI, state, account)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return _redirect_with_oauth_cookie(url, nonce)


@router.get("/callback")
def allegro_callback(
    request: Request,
    code: str | None = Query(None),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Allegro redirects here after user grants access."""
    if error:
        params = {"allegro_error": error}
        if error_description:
            params["allegro_error_description"] = error_description
        return _clear_oauth_cookie(RedirectResponse(f"{settings.APP_BASE_URL}/settings?{urlencode(params)}"))
    if not code:
        raise HTTPException(status_code=400, detail="Allegro authorization failed: missing code")

    try:
        state_data = _decode_oauth_state(state)
        transaction = _consume_oauth_transaction(db, state_data, request.cookies.get(OAUTH_COOKIE))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Allegro authorization failed: {e}")

    service = AllegroService(db)
    try:
        tenant_id = transaction["tenant_id"]
        account_id = transaction["account_id"]
        account = db.get(Account, account_id) if account_id is not None else None
        if account is not None and account.tenant_id != tenant_id:
            raise ValueError("OAuth state account does not belong to tenant")
        token_data = service.exchange_code_for_tokens(code, settings.ALLEGRO_REDIRECT_URI, account)
        profile = service.get_current_user_profile(token_data["access_token"])
        connected_account = service.upsert_account_from_profile(tenant_id, profile, token_data, account)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Allegro authorization failed: {e}")

    return _clear_oauth_cookie(RedirectResponse(f"{settings.APP_BASE_URL}/settings?connected={connected_account.id}"))


@accounts_callback_router.get("/callback")
def allegro_accounts_callback(
    request: Request,
    code: str | None = Query(None),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Compatibility callback for Allegro apps configured under /accounts/allegro."""
    return allegro_callback(request=request, code=code, state=state, error=error,
                            error_description=error_description, db=db)


# ── One-time OAuth transactions ────────────────────────────────────────────────
#
# The signed state alone does not prove that the callback comes back to the
# browser that started the flow (login CSRF: an attacker could send a victim
# the callback URL for the attacker's own Allegro account). Each flow therefore
# gets a random nonce stored hashed in the DB, put into the signed state and
# into an httponly cookie. The callback requires the cookie to match the state
# and consumes the transaction atomically, so it cannot be replayed.

OAUTH_COOKIE = "apos_oauth"
OAUTH_COOKIE_PATH = "/api/v1"
OAUTH_TTL = timedelta(minutes=15)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def _start_oauth_transaction(scope: TenantScope, account_id: int | None) -> str:
    now = _utcnow()
    scope.db.execute(delete(AllegroOAuthTransaction).where(
        AllegroOAuthTransaction.expires_at < now - timedelta(days=1)))
    nonce = secrets.token_urlsafe(32)
    user_id = scope.user.id if scope.user is not None and scope.user.id else None
    scope.db.add(AllegroOAuthTransaction(
        nonce_hash=_hash_nonce(nonce), tenant_id=scope.tenant_id, user_id=user_id,
        account_id=account_id, created_at=now, expires_at=now + OAUTH_TTL,
    ))
    scope.db.commit()
    return nonce


def _consume_oauth_transaction(db: Session, state_data: dict, cookie_nonce: str | None) -> dict:
    state_nonce = state_data.get("nonce")
    if not isinstance(state_nonce, str) or not state_nonce:
        raise ValueError("OAuth state missing transaction")
    if not cookie_nonce or not hmac.compare_digest(cookie_nonce, state_nonce):
        raise ValueError("OAuth transaction does not belong to this browser session")
    now = _utcnow()
    row = db.execute(
        update(AllegroOAuthTransaction)
        .where(
            AllegroOAuthTransaction.nonce_hash == _hash_nonce(state_nonce),
            AllegroOAuthTransaction.used_at.is_(None),
            AllegroOAuthTransaction.expires_at > now,
        )
        .values(used_at=now)
        .returning(AllegroOAuthTransaction.tenant_id, AllegroOAuthTransaction.account_id)
    ).first()
    db.commit()
    if row is None:
        raise ValueError("OAuth transaction expired or already used")
    if int(state_data["tenant_id"]) != row.tenant_id or state_data.get("account_id") != row.account_id:
        raise ValueError("OAuth state does not match transaction")
    return {"tenant_id": row.tenant_id, "account_id": row.account_id}


def _redirect_with_oauth_cookie(url: str, nonce: str) -> RedirectResponse:
    response = RedirectResponse(url)
    # SameSite=Lax: the cookie must be sent on the top-level redirect back from allegro.pl.
    response.set_cookie(OAUTH_COOKIE, nonce, max_age=int(OAUTH_TTL.total_seconds()), httponly=True,
                        secure=settings.session_cookie_secure, samesite="lax", path=OAUTH_COOKIE_PATH)
    return response


def _clear_oauth_cookie(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(OAUTH_COOKIE, path=OAUTH_COOKIE_PATH, httponly=True,
                           secure=settings.session_cookie_secure, samesite="lax")
    return response


def _encode_oauth_state(payload: dict) -> str:
    data = {**payload, "iat": int(time.time())}
    body = _b64url(json.dumps(data, separators=(",", ":")).encode())
    signature = _b64url(hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def _decode_oauth_state(state: str) -> dict:
    try:
        body, signature = state.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid OAuth state") from exc
    expected = _b64url(hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid OAuth state signature")
    data = json.loads(_b64url_decode(body))
    if int(data.get("iat", 0)) < int(time.time()) - 900:
        raise ValueError("Expired OAuth state")
    if "tenant_id" not in data:
        raise ValueError("OAuth state missing tenant")
    return data


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())


@router.get("/orders/{account_id}")
def get_orders(
    account_id: int,
    date_from: str = Query(..., description="ISO 8601, e.g. 2024-01-01T00:00:00Z"),
    date_to: str = Query(..., description="ISO 8601, e.g. 2024-01-31T23:59:59Z"),
    scope: TenantScope = Depends(get_scope),
):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    service = AllegroService(scope.db)
    try:
        return service.get_orders(account_id, date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Allegro API error: {e}")


@router.get("/billing/{account_id}")
def get_billing(
    account_id: int,
    date_from: str = Query(...),
    date_to: str = Query(...),
    scope: TenantScope = Depends(get_scope),
):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    service = AllegroService(scope.db)
    try:
        return service.get_billing(account_id, date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Allegro API error: {e}")


@router.get("/offers/{account_id}")
def get_offers(account_id: int, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    service = AllegroService(scope.db)
    try:
        return service.get_offers(account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Allegro API error: {e}")
