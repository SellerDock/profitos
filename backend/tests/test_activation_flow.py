from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pyotp
import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.api import admin as admin_api
from app.models.tenant import Tenant
from app.models.user import ActivationToken, User, UserSession, WaitlistEntry


@pytest.fixture(autouse=True)
def _hosted_deployment_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")


def _xrw(headers: dict | None = None) -> dict:
    merged = {"X-Requested-With": "XMLHttpRequest"}
    if headers:
        merged.update(headers)
    return merged


@pytest.fixture
def admin_fixture(app_client, seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM activation_tokens WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'activation-%'"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM waitlist_entries WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug LIKE 'activation-%'"))
    if db.get(Tenant, 1) is None:
        db.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db.flush()
    operator = User(
        email="activation-operator@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_operator=True,
        is_active=True,
        totp_secret=pyotp.random_base32(),
        totp_enrolled_at=datetime.utcnow(),
    )
    db.add(operator)
    db.flush()
    session = UserSession(id="activation-operator-session", user_id=operator.id, expires_at=datetime.utcnow() + timedelta(days=1))
    db.add(session)
    db.commit()
    app_client.cookies.set("apos_session", session.id)
    yield {"db": db, "operator": operator, "client": app_client}
    app_client.cookies.clear()
    db.execute(text("DELETE FROM activation_tokens WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'activation-%'"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM waitlist_entries WHERE email LIKE 'activation-%@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug LIKE 'activation-%'"))
    db.commit()


def _create_waitlist(db, email: str = "activation-customer@example.com") -> WaitlistEntry:
    entry = WaitlistEntry(email=email, company="Activation Co", monthly_orders="100-1000")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _approve(client, entry_id: int, name: str = "Activation Customer"):
    return client.post(
        f"/api/v1/admin/waitlist/{entry_id}/approve",
        json={"tenant_name": name},
        headers=_xrw(),
    )


def _token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def _activation_payload(raw_token: str, **extra) -> dict:
    payload = {
        "token": raw_token,
        "password": "CorrectHorseBatteryStaple2!",
        "privacy_accepted": True,
    }
    payload.update(extra)
    return payload


@pytest.mark.contract
def test_admin_waitlist_requires_operator(app_client, seeded_db):
    db = seeded_db["db"]
    user = User(
        email="activation-normal@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_operator=False,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(UserSession(id="activation-normal-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db.commit()
    app_client.cookies.set("apos_session", "activation-normal-session")
    response = app_client.get("/api/v1/admin/waitlist")
    assert response.status_code == 403


@pytest.mark.contract
def test_approve_waitlist_creates_tenant_and_returns_one_time_url(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db)
    response = _approve(admin_fixture["client"], entry.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activation_email_sent"] is False
    raw_token = _token_from_url(body["activation_url"])
    activation = db.query(ActivationToken).filter_by(email=entry.email).one()
    assert raw_token not in activation.token_hash
    assert len(activation.token_hash) == 64
    assert db.get(Tenant, body["tenant_id"]).slug.startswith("activation-customer")


@pytest.mark.contract
def test_approve_waitlist_sends_activation_email(monkeypatch, admin_fixture):
    sent: list[dict] = []

    def fake_send_activation_email(*, to_email: str, activation_url: str, tenant_name: str, expires_at: datetime) -> bool:
        sent.append({
            "to_email": to_email,
            "activation_url": activation_url,
            "tenant_name": tenant_name,
            "expires_at": expires_at,
        })
        return True

    monkeypatch.setattr(admin_api, "send_activation_email", fake_send_activation_email, raising=False)
    entry = _create_waitlist(admin_fixture["db"], "activation-email@example.com")

    response = _approve(admin_fixture["client"], entry.id, "Activation Mail Tenant")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activation_email_sent"] is True
    assert sent == [{
        "to_email": entry.email,
        "activation_url": body["activation_url"],
        "tenant_name": "Activation Mail Tenant",
        "expires_at": datetime.fromisoformat(body["expires_at"]),
    }]


@pytest.mark.contract
def test_approve_waitlist_keeps_manual_url_when_activation_email_fails(monkeypatch, admin_fixture):
    def fake_send_activation_email(**_kwargs) -> bool:
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr(admin_api, "send_activation_email", fake_send_activation_email, raising=False)
    entry = _create_waitlist(admin_fixture["db"], "activation-email-fail@example.com")

    response = _approve(admin_fixture["client"], entry.id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activation_email_sent"] is False
    assert body["activation_email_error"] == "smtp unavailable"
    assert body["activation_url"].startswith("http")


@pytest.mark.contract
def test_approve_waitlist_twice_returns_409(admin_fixture):
    entry = _create_waitlist(admin_fixture["db"], "activation-dupe@example.com")
    assert _approve(admin_fixture["client"], entry.id).status_code == 200
    assert _approve(admin_fixture["client"], entry.id).status_code == 409


@pytest.mark.contract
def test_reject_waitlist_marks_notes(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db, "activation-reject@example.com")
    response = admin_fixture["client"].post(
        f"/api/v1/admin/waitlist/{entry.id}/reject",
        json={"reason": "not now"},
        headers=_xrw(),
    )
    assert response.status_code == 200
    db.refresh(entry)
    assert entry.notes == "#rejected:not now"


@pytest.mark.contract
def test_activation_status_returns_activation_metadata_with_optional_totp(admin_fixture):
    entry = _create_waitlist(admin_fixture["db"], "activation-status@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    response = admin_fixture["client"].get(f"/api/v1/auth/activate/{raw_token}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "valid"
    assert body["email"] == entry.email
    assert body["tenant_name"]
    assert body["qr_svg"].startswith("<svg")
    assert "<script" not in body["qr_svg"].lower()
    assert body["secret"]
    assert body["provisioning_uri"].startswith("otpauth://totp/")


@pytest.mark.contract
def test_activation_post_creates_user_session_and_consumes_token(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db, "activation-complete@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    response = admin_fixture["client"].post(
        "/api/v1/auth/activate",
        json=_activation_payload(raw_token),
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert "apos_session" in response.cookies
    user = db.query(User).filter_by(email=entry.email).one()
    activation = db.query(ActivationToken).filter_by(email=entry.email).one()
    assert user.tenant_id == activation.tenant_id
    assert user.totp_secret is None
    assert user.privacy_accepted_at is not None
    assert activation.used_at is not None


@pytest.mark.contract
def test_privacy_required_activate(admin_fixture):
    entry = _create_waitlist(admin_fixture["db"], "activation-privacy@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    response = admin_fixture["client"].post(
        "/api/v1/auth/activate",
        json=_activation_payload(raw_token, privacy_accepted=False),
        headers=_xrw(),
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Privacy policy acceptance required"


@pytest.mark.contract
def test_activation_post_with_totp_enrolls_optional_user_totp(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db, "activation-totp@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    status = admin_fixture["client"].get(f"/api/v1/auth/activate/{raw_token}").json()
    code = pyotp.TOTP(status["secret"]).now()
    response = admin_fixture["client"].post(
        "/api/v1/auth/activate",
        json=_activation_payload(raw_token, totp=code),
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    user = db.query(User).filter_by(email=entry.email).one()
    assert user.totp_secret == status["secret"]
    assert user.totp_enrolled_at is not None


@pytest.mark.contract
def test_activation_link_is_single_use(admin_fixture):
    entry = _create_waitlist(admin_fixture["db"], "activation-once@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    first = admin_fixture["client"].post(
        "/api/v1/auth/activate",
        json=_activation_payload(raw_token),
        headers=_xrw(),
    )
    second = admin_fixture["client"].post(
        "/api/v1/auth/activate",
        json=_activation_payload(raw_token),
        headers=_xrw(),
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"]["code"] == "invalid_token"


@pytest.mark.contract
def test_expired_activation_token_returns_invalid_token(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db, "activation-expired@example.com")
    raw_token = _token_from_url(_approve(admin_fixture["client"], entry.id).json()["activation_url"])
    activation = db.query(ActivationToken).filter_by(email=entry.email).one()
    activation.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    response = admin_fixture["client"].get(f"/api/v1/auth/activate/{raw_token}")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_token"


@pytest.mark.contract
def test_tenant_deactivate_revokes_sessions(admin_fixture):
    db = admin_fixture["db"]
    entry = _create_waitlist(db, "activation-deactivate@example.com")
    approve = _approve(admin_fixture["client"], entry.id)
    tenant_id = approve.json()["tenant_id"]
    user = User(
        email=entry.email,
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=tenant_id,
        is_operator=False,
        is_active=True,
        totp_secret=pyotp.random_base32(),
    )
    db.add(user)
    db.flush()
    db.add(UserSession(id="activation-user-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db.commit()
    response = admin_fixture["client"].post(f"/api/v1/admin/tenants/{tenant_id}/deactivate", headers=_xrw())
    assert response.status_code == 200
    db.expire_all()
    assert db.get(Tenant, tenant_id).is_active is False
    assert db.get(UserSession, "activation-user-session").revoked_at is not None


@pytest.mark.contract
def test_admin_tenants_lists_counts(admin_fixture):
    entry = _create_waitlist(admin_fixture["db"], "activation-list@example.com")
    tenant_id = _approve(admin_fixture["client"], entry.id).json()["tenant_id"]
    response = admin_fixture["client"].get("/api/v1/admin/tenants")
    assert response.status_code == 200, response.text
    tenant = next(item for item in response.json()["items"] if item["id"] == tenant_id)
    assert tenant["accounts_count"] == 0
    assert tenant["users_count"] == 0


@pytest.mark.contract
def test_admin_tenants_includes_operator_tenant(admin_fixture):
    response = admin_fixture["client"].get("/api/v1/admin/tenants")
    assert response.status_code == 200, response.text
    tenant_ids = {item["id"] for item in response.json()["items"]}
    assert 1 in tenant_ids
