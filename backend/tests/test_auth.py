from datetime import datetime, timedelta

import pyotp
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.security import hash_password
from app.api.auth import render_provisioning_qr
from app.models.user import User, UserSession


@pytest.fixture
def operator_user(seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM user_sessions"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'auth-%@example.com'"))
    db.execute(text("DELETE FROM login_rate_limit_attempts"))
    db.commit()

    user = User(
        email="auth-operator@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_operator=True,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    try:
        yield user
    finally:
        db.execute(text("DELETE FROM user_sessions WHERE user_id = :uid"), {"uid": user.id})
        db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user.id})
        db.commit()


def _xrw(headers: dict | None = None) -> dict:
    merged = {"X-Requested-With": "XMLHttpRequest"}
    if headers:
        merged.update(headers)
    return merged


@pytest.mark.contract
def test_login_with_invalid_credentials_returns_401(app_client, operator_user):
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "wrong-password"},
        headers=_xrw(),
    )
    assert response.status_code == 401


@pytest.mark.contract
def test_unknown_email_failed_logins_are_rate_limited(app_client, operator_user):
    for _ in range(5):
        response = app_client.post(
            "/api/v1/auth/login",
            json={"email": "auth-missing@example.com", "password": "wrong-password"},
            headers=_xrw(),
        )
        assert response.status_code == 401

    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": "auth-missing@example.com", "password": "wrong-password"},
        headers=_xrw(),
    )
    assert response.status_code == 429


@pytest.mark.contract
def test_provisioning_qr_rejects_script_svg(monkeypatch):
    class ScriptQr:
        def save(self, buf, **_kwargs):
            buf.write(b'<svg><script>alert("x")</script></svg>')

    monkeypatch.setattr("app.api.auth.segno.make", lambda *_args, **_kwargs: ScriptQr())

    with pytest.raises(RuntimeError, match="Unsafe QR SVG"):
        render_provisioning_qr("otpauth://totp/ProfitOS:test@example.com")


@pytest.mark.contract
def test_login_with_correct_password_no_totp_returns_enroll_required(app_client, operator_user):
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "CorrectHorseBatteryStaple1!"},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "totp_enroll_required"
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert "apos_totp_enroll" in response.cookies
    assert "apos_session" not in response.cookies


@pytest.mark.contract
def test_totp_enroll_response_contains_qr_svg(app_client, operator_user):
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "CorrectHorseBatteryStaple1!"},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "totp_enroll_required"
    assert body["qr_svg"].startswith("<svg")
    assert "<script" not in body["qr_svg"].lower()
    assert "otpauth://totp/" in body["provisioning_uri"]
    assert body["issuer"] == "ProfitOS"
    assert pyotp.parse_uri(body["provisioning_uri"]).issuer == "ProfitOS"
    assert body["account_name"] == operator_user.email
    assert len(body["secret"]) >= 16


@pytest.mark.contract
def test_totp_enroll_uses_current_brand(app_client, operator_user, monkeypatch):
    monkeypatch.setattr(settings, "BRAND_PRODUCT_NAME", "TestBrand")
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "CorrectHorseBatteryStaple1!"},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["issuer"] == "TestBrand"
    assert pyotp.parse_uri(body["provisioning_uri"]).issuer == "TestBrand"


@pytest.mark.contract
def test_login_after_totp_enrollment_returns_session_cookie(app_client, operator_user):
    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "CorrectHorseBatteryStaple1!"},
        headers=_xrw(),
    )
    secret = login.json()["secret"]
    code = pyotp.TOTP(secret).now()

    enroll = app_client.post("/api/v1/auth/totp/enroll", json={"totp": code}, headers=_xrw())
    assert enroll.status_code == 200, enroll.text
    assert enroll.json()["status"] == "ok"
    assert "apos_session" in enroll.cookies

    me = app_client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == operator_user.email


@pytest.mark.contract
def test_login_with_existing_totp_secret_requires_totp(app_client, operator_user, seeded_db):
    operator_user.totp_secret = "JBSWY3DPEHPK3PXP"
    operator_user.totp_enrolled_at = datetime.utcnow()
    seeded_db["db"].commit()

    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "CorrectHorseBatteryStaple1!"},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "totp_required"}
    assert "apos_session" not in response.cookies

    response = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": operator_user.email,
            "password": "CorrectHorseBatteryStaple1!",
            "totp": pyotp.TOTP(operator_user.totp_secret).now(),
        },
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


@pytest.mark.contract
def test_protected_endpoint_without_session_returns_401(app_client):
    response = app_client.get("/api/v1/dashboard/summary?period=today")
    assert response.status_code == 401


@pytest.mark.contract
def test_protected_endpoint_without_session_returns_401_when_bearer_disabled(app_client, monkeypatch):
    monkeypatch.setattr(settings, "API_BEARER_TOKEN", None)
    response = app_client.get("/api/v1/dashboard/summary?period=today")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.contract
def test_protected_endpoint_with_session_returns_200(app_client, operator_user, seeded_db):
    token = "test-session-token"
    seeded_db["db"].add(UserSession(
        id=token,
        user_id=operator_user.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    seeded_db["db"].commit()
    app_client.cookies.set("apos_session", token)

    response = app_client.get("/api/v1/dashboard/summary?period=today")
    assert response.status_code == 200, response.text


@pytest.mark.contract
def test_protected_endpoint_with_legacy_bearer_returns_200(app_client):
    response = app_client.get(
        "/api/v1/dashboard/summary?period=today",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.contract
def test_logout_revokes_session(app_client, operator_user, seeded_db):
    token = "logout-session-token"
    seeded_db["db"].add(UserSession(
        id=token,
        user_id=operator_user.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    seeded_db["db"].commit()
    app_client.cookies.set("apos_session", token)

    response = app_client.post("/api/v1/auth/logout", headers=_xrw())
    assert response.status_code == 204
    seeded_db["db"].expire_all()
    assert seeded_db["db"].get(UserSession, token).revoked_at is not None


@pytest.mark.contract
def test_session_after_expiry_returns_401(app_client, operator_user, seeded_db):
    token = "expired-session-token"
    seeded_db["db"].add(UserSession(
        id=token,
        user_id=operator_user.id,
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    ))
    seeded_db["db"].commit()
    app_client.cookies.set("apos_session", token)

    response = app_client.get("/api/v1/dashboard/summary?period=today")
    assert response.status_code == 401


@pytest.mark.contract
def test_locked_account_returns_429(app_client, operator_user):
    for _ in range(5):
        app_client.post(
            "/api/v1/auth/login",
            json={"email": operator_user.email, "password": "wrong-password"},
            headers=_xrw(),
        )
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": operator_user.email, "password": "wrong-password"},
        headers=_xrw(),
    )
    assert response.status_code == 429


@pytest.mark.contract
def test_csrf_post_without_xrw_header_returns_403(app_client, operator_user, seeded_db):
    token = "csrf-session-token"
    seeded_db["db"].add(UserSession(
        id=token,
        user_id=operator_user.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    seeded_db["db"].commit()
    app_client.cookies.set("apos_session", token)

    response = app_client.post("/api/v1/products/import-costs", json={"rows": []})
    assert response.status_code == 403
