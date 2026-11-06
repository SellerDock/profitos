import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.services.allegro import AllegroService

router = APIRouter(prefix="/allegro", tags=["allegro"])
accounts_callback_router = APIRouter(prefix="/accounts/allegro", tags=["allegro"])


@router.get("/auth")
def allegro_auth_new(scope: TenantScope = Depends(get_scope)):
    """Redirect the user to Allegro OAuth consent screen for a new account."""
    service = AllegroService(scope.db)
    state = _encode_oauth_state({"tenant_id": scope.tenant_id})
    try:
        url = service.get_auth_url(settings.ALLEGRO_REDIRECT_URI, state)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return RedirectResponse(url)


@router.get("/auth/{account_id}")
def allegro_auth(account_id: int, scope: TenantScope = Depends(get_scope)):
    """Redirect the user to Allegro OAuth consent screen."""
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    service = AllegroService(scope.db)
    state = _encode_oauth_state({"tenant_id": scope.tenant_id, "account_id": account_id})
    try:
        url = service.get_auth_url(settings.ALLEGRO_REDIRECT_URI, state, account)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return RedirectResponse(url)


@router.get("/callback")
def allegro_callback(
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
        return RedirectResponse(f"{settings.APP_BASE_URL}/settings?{urlencode(params)}")
    if not code:
        raise HTTPException(status_code=400, detail="Allegro authorization failed: missing code")

    service = AllegroService(db)
    try:
        state_data = _decode_oauth_state(state)
        tenant_id = int(state_data["tenant_id"])
        account_id = state_data.get("account_id")
        account = db.get(Account, int(account_id)) if account_id is not None else None
        if account is not None and account.tenant_id != tenant_id:
            raise ValueError("OAuth state account does not belong to tenant")
        token_data = service.exchange_code_for_tokens(code, settings.ALLEGRO_REDIRECT_URI, account)
        profile = service.get_current_user_profile(token_data["access_token"])
        connected_account = service.upsert_account_from_profile(tenant_id, profile, token_data, account)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Allegro authorization failed: {e}")

    return RedirectResponse(f"{settings.APP_BASE_URL}/settings?connected={connected_account.id}")


@accounts_callback_router.get("/callback")
def allegro_accounts_callback(
    code: str | None = Query(None),
    state: str = Query(...),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Compatibility callback for Allegro apps configured under /accounts/allegro."""
    return allegro_callback(code=code, state=state, error=error, error_description=error_description, db=db)


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
