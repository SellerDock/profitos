"""Issue #1: Allegro OAuth state is a one-time transaction bound to the browser."""
from datetime import timedelta
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import allegro
from app.core.config import settings
from app.main import app
from app.models.account import AllegroOAuthTransaction


@pytest.fixture
def oauth(monkeypatch, db_session):
    """Fake the Allegro token/profile calls and count successful exchanges."""
    db_session.execute(text("DELETE FROM allegro_oauth_transactions"))
    db_session.commit()
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_ID", "global-client", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_SECRET", "global-secret", raising=False)
    calls = []

    def exchange(self, code, redirect_uri, account=None):
        calls.append(code)
        raise RuntimeError("stop after exchange")  # reaching here = transaction accepted

    monkeypatch.setattr(allegro.AllegroService, "exchange_code_for_tokens", exchange)
    yield calls
    db_session.execute(text("DELETE FROM allegro_oauth_transactions"))
    db_session.commit()


def _start(client: TestClient) -> str:
    response = client.get("/api/v1/allegro/auth", follow_redirects=False)
    assert response.status_code == 307
    assert allegro.OAUTH_COOKIE in response.cookies
    return parse_qs(urlparse(response.headers["location"]).query)["state"][0]


def _callback(client: TestClient, state: str, path: str = "/api/v1/allegro/callback"):
    return client.get(f"{path}?code=auth-code&state={quote(state)}", follow_redirects=False)


def test_transaction_stored_hashed_and_cookie_flags(authed_client, oauth, db_session):
    response = authed_client.get("/api/v1/allegro/auth", follow_redirects=False)
    nonce = response.cookies[allegro.OAUTH_COOKIE]
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/api/v1" in header
    row = db_session.query(AllegroOAuthTransaction).one()
    assert row.nonce_hash == allegro._hash_nonce(nonce) and nonce not in row.nonce_hash
    assert row.used_at is None and row.tenant_id == 1 and row.account_id is None
    assert row.expires_at - row.created_at == allegro.OAUTH_TTL


def test_same_browser_callback_is_accepted(authed_client, oauth):
    state = _start(authed_client)
    assert _callback(authed_client, state).status_code == 400  # fake exchange stops the flow
    assert oauth == ["auth-code"]


def test_compat_callback_path_receives_cookie(authed_client, oauth):
    state = _start(authed_client)
    _callback(authed_client, state, "/api/v1/accounts/allegro/callback")
    assert oauth == ["auth-code"]


def test_callback_replay_is_rejected(authed_client, oauth):
    state = _start(authed_client)
    _callback(authed_client, state)
    response = _callback(authed_client, state)
    assert response.status_code == 400
    assert "already used" in response.json()["detail"]
    assert oauth == ["auth-code"]


def test_callback_from_other_browser_is_rejected(authed_client, oauth):
    """Login CSRF: the attacker's state + code opened in the victim's browser."""
    state = _start(authed_client)
    with TestClient(app) as victim:
        response = _callback(victim, state)
    assert response.status_code == 400
    assert "browser session" in response.json()["detail"]
    assert oauth == []


def test_cookie_of_other_transaction_is_rejected(authed_client, oauth):
    state_a = _start(authed_client)
    _start(authed_client)  # overwrites the cookie with transaction B
    response = _callback(authed_client, state_a)
    assert response.status_code == 400
    assert oauth == []


def test_signed_state_without_transaction_is_rejected(authed_client, oauth):
    """Old-style state (signed, no nonce) no longer works."""
    state = allegro._encode_oauth_state({"tenant_id": 1})
    response = _callback(authed_client, state)
    assert response.status_code == 400
    assert oauth == []


def test_expired_transaction_is_rejected(authed_client, oauth, db_session):
    state = _start(authed_client)
    row = db_session.query(AllegroOAuthTransaction).one()
    row.expires_at = row.created_at - timedelta(seconds=1)
    db_session.commit()
    response = _callback(authed_client, state)
    assert response.status_code == 400
    assert oauth == []


def test_state_tampered_tenant_is_rejected(authed_client, oauth):
    state = _start(authed_client)
    data = allegro._decode_oauth_state(state)
    forged = allegro._encode_oauth_state({**data, "tenant_id": 999})  # needs SECRET_KEY anyway
    response = _callback(authed_client, forged)
    assert response.status_code == 400
    assert oauth == []


def test_error_callback_clears_cookie(authed_client, oauth):
    state = _start(authed_client)
    response = authed_client.get(f"/api/v1/allegro/callback?error=access_denied&state={quote(state)}",
                                 follow_redirects=False)
    assert response.status_code == 307
    assert allegro.OAUTH_COOKIE in response.headers["set-cookie"]
    assert 'max-age=0' in response.headers["set-cookie"].lower()
