import httpx

from app.core.config import settings
from app.models.account import Account
from app.services.allegro import ALLEGRO_TOKEN_URL, AllegroService, allegro_user_agent


def test_headers_include_user_agent(monkeypatch):
    monkeypatch.setattr(settings, "ALLEGRO_USER_AGENT", None)
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://example.com")
    service = AllegroService(db=None)  # type: ignore[arg-type]
    account = Account(access_token="access-token")

    headers = service._headers(account)

    assert headers["User-Agent"] == "ProfitOS/0.1.0 (+https://example.com)"
    assert headers["Authorization"] == "Bearer access-token"


def test_headers_include_configured_user_agent(monkeypatch):
    monkeypatch.setattr(settings, "ALLEGRO_USER_AGENT", "Custom agent/1.0")
    service = AllegroService(db=None)  # type: ignore[arg-type]

    assert service._headers(Account(access_token="access-token"))["User-Agent"] == "Custom agent/1.0"


def test_refresh_token_post_sends_user_agent(monkeypatch):
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_ID", "global-client", raising=False)
    monkeypatch.setattr(settings, "ALLEGRO_CLIENT_SECRET", "global-secret", raising=False)

    account = Account(refresh_token="refresh-token", token_expires_at=None)

    class FakeDb:
        def get(self, model, pk):
            return account

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    service = AllegroService(db=FakeDb())  # type: ignore[arg-type]

    captured = {}

    def fake_post(url, *, data, auth, headers, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        captured["headers"] = headers
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"access_token": "new-access-token", "expires_in": 43200},
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    service.refresh_token_if_needed(account_id=1)

    assert captured["url"] == ALLEGRO_TOKEN_URL
    assert captured["data"]["grant_type"] == "refresh_token"
    assert captured["data"]["refresh_token"] == "refresh-token"
    assert captured["headers"]["User-Agent"] == allegro_user_agent()
    assert account.access_token == "new-access-token"
