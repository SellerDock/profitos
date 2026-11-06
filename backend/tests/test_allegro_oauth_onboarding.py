from urllib.parse import parse_qs, quote, urlparse

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.models.account import Account, AllegroAccountClaim
from app.services.allegro import allegro_user_agent


def test_one_click_oauth_creates_account_from_allegro_profile(authed_client, db_session, monkeypatch):
    db_session.execute(text("DELETE FROM allegro_account_claims WHERE allegro_user_id = '12345678'"))
    db_session.execute(text("DELETE FROM accounts WHERE allegro_client_id = 'global-client' OR name = 'test_account'"))
    db_session.commit()

    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_ID", "global-client", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_SECRET", "global-secret", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_SCOPES", "allegro:api:profile:read", raising=False)

    def fake_post(url, *, data, auth, headers, timeout):
        assert url == "https://allegro.pl/auth/oauth/token"
        assert data == {
            "grant_type": "authorization_code",
            "code": "auth-code",
            "redirect_uri": settings.ALLEGRO_REDIRECT_URI,
        }
        assert auth == ("global-client", "global-secret")
        assert headers["User-Agent"] == allegro_user_agent()
        assert timeout == 15
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 43199,
            },
        )

    def fake_get(url, *, headers, timeout):
        assert url == "https://api.allegro.pl/me"
        assert headers["Authorization"] == "Bearer access-token"
        assert headers["User-Agent"] == allegro_user_agent()
        assert timeout == 15
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "id": "12345678",
                "login": "test_account",
                "email": "test_account@allegro.pl",
                "company": {"name": "Test Company"},
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    auth_response = authed_client.get("/api/v1/allegro/auth", follow_redirects=False)

    assert auth_response.status_code == 307
    auth_url = urlparse(auth_response.headers["location"])
    auth_query = parse_qs(auth_url.query)
    assert auth_url.scheme == "https"
    assert auth_url.netloc == "allegro.pl"
    assert auth_url.path == "/auth/oauth/authorize"
    assert auth_query["client_id"] == ["global-client"]
    assert auth_query["scope"] == ["allegro:api:profile:read"]

    state = auth_query["state"][0]
    callback_response = authed_client.get(
        f"/api/v1/allegro/callback?code=auth-code&state={quote(state)}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 307, callback_response.text
    account = (
        db_session.query(Account)
        .filter(Account.tenant_id == 1, Account.allegro_user_id == "12345678")
        .one()
    )
    assert account.name == "test_account"
    assert account.allegro_client_id == "global-client"
    assert account.allegro_client_secret == "global-secret"
    assert account.access_token == "access-token"
    assert account.refresh_token == "refresh-token"
    claim = (
        db_session.query(AllegroAccountClaim)
        .filter(AllegroAccountClaim.allegro_user_id == "12345678")
        .one()
    )
    assert claim.tenant_id == 1
    assert claim.account_id == account.id
    assert claim.account_name == "test_account"
    db_session.delete(claim)
    db_session.delete(account)
    db_session.commit()


def test_auth_url_normalizes_comma_separated_scopes(authed_client, monkeypatch):
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_ID", "global-client", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_SECRET", "global-secret", raising=False)
    monkeypatch.setattr(
        settings,
        "ALLEGRO_SCOPES",
        "allegro:api:profile:read, allegro:api:orders:read,allegro:api:sale:offers:read",
        raising=False,
    )

    response = authed_client.get("/api/v1/allegro/auth", follow_redirects=False)

    assert response.status_code == 307
    auth_query = parse_qs(urlparse(response.headers["location"]).query)
    assert auth_query["scope"] == [
        "allegro:api:profile:read allegro:api:orders:read allegro:api:sale:offers:read"
    ]


def test_allegro_oauth_error_redirects_to_settings(authed_client, monkeypatch):
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_ID", "global-client", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_SECRET", "global-secret", raising=False)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://app.profitos.pl", raising=False)

    auth_response = authed_client.get("/api/v1/allegro/auth", follow_redirects=False)
    state = parse_qs(urlparse(auth_response.headers["location"]).query)["state"][0]

    callback_response = authed_client.get(
        "/api/v1/accounts/allegro/callback"
        f"?error=invalid_scope&error_description=OAuth%202.0%20Parameter%3A%20scope&state={quote(state)}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 307
    redirect = urlparse(callback_response.headers["location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == "https://app.profitos.pl/settings"
    query = parse_qs(redirect.query)
    assert query["allegro_error"] == ["invalid_scope"]
    assert query["allegro_error_description"] == ["OAuth 2.0 Parameter: scope"]
