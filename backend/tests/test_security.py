import os

from fastapi.testclient import TestClient

os.environ["API_BEARER_TOKEN"] = "test-token"
os.environ["BACKEND_CORS_ORIGINS"] = "http://localhost:3001"

from app.core.tenant import get_scope
from app.main import app
from tests.tenant_helpers import operator_scope


client = TestClient(app)


def test_health_is_public():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_rejects_missing_bearer_token():
    response = client.get("/api/v1/not-a-real-route")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Cookie, Bearer"


def test_api_rejects_invalid_bearer_token():
    response = client.get(
        "/api/v1/not-a-real-route",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Cookie, Bearer"


def test_api_accepts_valid_bearer_token_before_routing():
    response = client.get(
        "/api/v1/not-a-real-route",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404


def test_cors_allows_configured_origin():
    response = client.options(
        "/api/v1/accounts/",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"


def test_cors_rejects_unconfigured_origin():
    response = client.options(
        "/api/v1/accounts/",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_allegro_oauth_routes_are_public():
    class _Db:
        def get(self, *_):
            return None

    app.dependency_overrides[get_scope] = lambda: operator_scope(_Db())
    try:
        auth_response = client.get("/api/v1/allegro/auth/999", follow_redirects=False)
        callback_response = client.get("/api/v1/allegro/callback", follow_redirects=False)
        accounts_callback_response = client.get("/api/v1/accounts/allegro/callback", follow_redirects=False)
    finally:
        app.dependency_overrides.clear()

    assert auth_response.status_code != 401
    assert callback_response.status_code != 401
    assert accounts_callback_response.status_code != 401
