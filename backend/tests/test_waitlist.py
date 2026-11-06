import pytest
from sqlalchemy import text

from app.api import auth as auth_api
from app.models.tenant import Tenant
from app.models.user import ActivationToken, WaitlistEntry


@pytest.fixture(autouse=True)
def _hosted_deployment_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")


@pytest.fixture(autouse=True)
def clean_waitlist(seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM activation_tokens WHERE email LIKE 'waitlist-%@example.com'"))
    db.execute(text("DELETE FROM waitlist_entries WHERE email LIKE 'waitlist-%@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug LIKE 'contract-company%'"))
    db.execute(text("DELETE FROM login_rate_limit_attempts"))
    db.commit()
    yield
    db.execute(text("DELETE FROM activation_tokens WHERE email LIKE 'waitlist-%@example.com'"))
    db.execute(text("DELETE FROM waitlist_entries WHERE email LIKE 'waitlist-%@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug LIKE 'contract-company%'"))
    db.commit()


@pytest.fixture(autouse=True)
def forbid_unmocked_email_sends(monkeypatch):
    calls: list[str] = []

    def blocked_activation_email(*, to_email: str, **_kwargs) -> bool:
        calls.append(f"activation:{to_email}")
        return False

    def blocked_waitlist_admin_notification_email(*, entry: WaitlistEntry) -> bool:
        calls.append(f"waitlist-admin:{entry.email}")
        return False

    monkeypatch.setattr(auth_api, "send_activation_email", blocked_activation_email, raising=False)
    monkeypatch.setattr(
        auth_api,
        "send_waitlist_admin_notification_email",
        blocked_waitlist_admin_notification_email,
        raising=False,
    )
    yield
    assert not calls, "Tests must mock outbound email explicitly; unmocked calls: " + ", ".join(calls)


def _payload(email: str) -> dict:
    return {
        "email": email,
        "company": "Contract Company",
        "phone": "+48123123123",
        "monthly_orders": "100-1000",
        "message": "Chcemy przetestować ProfitOS.pl.",
        "privacy_accepted": True,
    }


def _headers() -> dict:
    return {"X-Requested-With": "XMLHttpRequest"}


def _disable_outbound_email(monkeypatch) -> None:
    monkeypatch.setattr(auth_api, "send_activation_email", lambda **_kwargs: False, raising=False)
    monkeypatch.setattr(auth_api, "send_waitlist_admin_notification_email", lambda **_kwargs: False, raising=False)


@pytest.mark.contract
def test_waitlist_signup_creates_entry(monkeypatch, app_client, seeded_db):
    _disable_outbound_email(monkeypatch)
    response = app_client.post(
        "/api/v1/auth/waitlist",
        json=_payload("waitlist-one@example.com"),
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    entry = seeded_db["db"].query(WaitlistEntry).filter_by(email="waitlist-one@example.com").one()
    assert entry.company == "Contract Company"
    assert entry.approved_at is not None
    assert entry.privacy_accepted_at is not None
    activation = seeded_db["db"].query(ActivationToken).filter_by(email="waitlist-one@example.com").one()
    tenant = seeded_db["db"].get(Tenant, activation.tenant_id)
    assert tenant is not None
    assert tenant.slug.startswith("contract-company")


@pytest.mark.contract
def test_waitlist_signup_sends_activation_and_admin_notification(monkeypatch, app_client):
    sent_user: list[dict] = []
    sent_admin: list[dict] = []

    def fake_send_activation_email(*, to_email: str, activation_url: str, tenant_name: str, expires_at) -> bool:
        sent_user.append({
            "to_email": to_email,
            "activation_url": activation_url,
            "tenant_name": tenant_name,
        })
        return True

    def fake_send_waitlist_admin_notification_email(*, entry: WaitlistEntry) -> bool:
        sent_admin.append({
            "email": entry.email,
            "company": entry.company,
            "phone": entry.phone,
            "monthly_orders": entry.monthly_orders,
            "message": entry.message,
        })
        return True

    monkeypatch.setattr(auth_api, "send_activation_email", fake_send_activation_email, raising=False)
    monkeypatch.setattr(auth_api, "send_waitlist_admin_notification_email", fake_send_waitlist_admin_notification_email, raising=False)

    response = app_client.post(
        "/api/v1/auth/waitlist",
        json=_payload("waitlist-mail@example.com"),
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["activation_email_sent"] is True
    assert sent_user == [{
        "to_email": "waitlist-mail@example.com",
        "activation_url": sent_user[0]["activation_url"],
        "tenant_name": "Contract Company",
    }]
    assert sent_user[0]["activation_url"].startswith("http")
    assert sent_admin == [{
        "email": "waitlist-mail@example.com",
        "company": "Contract Company",
        "phone": "+48123123123",
        "monthly_orders": "100-1000",
        "message": "Chcemy przetestować ProfitOS.pl.",
    }]


@pytest.mark.contract
def test_privacy_required_waitlist(app_client):
    payload = _payload("waitlist-privacy@example.com")
    payload["privacy_accepted"] = False
    response = app_client.post(
        "/api/v1/auth/waitlist",
        json=payload,
        headers=_headers(),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Privacy policy acceptance required"


@pytest.mark.contract
def test_waitlist_duplicate_email_returns_200_and_resends_notifications(monkeypatch, app_client, seeded_db):
    sent_user: list[str] = []
    sent_admin: list[str] = []

    def fake_send_activation_email(*, to_email: str, **_kwargs) -> bool:
        sent_user.append(to_email)
        return True

    def fake_send_waitlist_admin_notification_email(*, entry: WaitlistEntry) -> bool:
        sent_admin.append(entry.email)
        return True

    monkeypatch.setattr(auth_api, "send_activation_email", fake_send_activation_email, raising=False)
    monkeypatch.setattr(auth_api, "send_waitlist_admin_notification_email", fake_send_waitlist_admin_notification_email, raising=False)

    first = app_client.post("/api/v1/auth/waitlist", json=_payload("waitlist-dupe@example.com"), headers=_headers())
    second = app_client.post("/api/v1/auth/waitlist", json=_payload("waitlist-dupe@example.com"), headers=_headers())
    assert first.status_code == 200
    assert second.status_code == 200
    count = seeded_db["db"].query(WaitlistEntry).filter_by(email="waitlist-dupe@example.com").count()
    assert count == 1
    assert sent_user == ["waitlist-dupe@example.com", "waitlist-dupe@example.com"]
    assert sent_admin == ["waitlist-dupe@example.com", "waitlist-dupe@example.com"]
    tokens = seeded_db["db"].query(ActivationToken).filter_by(email="waitlist-dupe@example.com").all()
    assert len(tokens) == 2
    assert sum(1 for token in tokens if token.revoked_at is None) == 1


@pytest.mark.contract
def test_waitlist_honeypot_drops_silently(app_client, seeded_db):
    payload = _payload("waitlist-bot@example.com")
    payload["website"] = "https://spam.example"
    response = app_client.post("/api/v1/auth/waitlist", json=payload, headers=_headers())
    assert response.status_code == 200
    count = seeded_db["db"].query(WaitlistEntry).filter_by(email="waitlist-bot@example.com").count()
    assert count == 0


@pytest.mark.contract
def test_waitlist_rate_limit_after_3_per_24h_returns_429(monkeypatch, app_client):
    _disable_outbound_email(monkeypatch)
    for index in range(3):
        response = app_client.post(
            "/api/v1/auth/waitlist",
            json=_payload(f"waitlist-rate-{index}@example.com"),
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
    limited = app_client.post(
        "/api/v1/auth/waitlist",
        json=_payload("waitlist-rate-4@example.com"),
        headers=_headers(),
    )
    assert limited.status_code == 429
