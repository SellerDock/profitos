from datetime import datetime, timedelta

import pyotp
import pytest
from sqlalchemy import text

from app.api.auth import _enrollments
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User, UserSession


PASSWORD = "CorrectHorseBatteryStaple1!"


def _xrw(headers: dict | None = None) -> dict:
    merged = {"X-Requested-With": "XMLHttpRequest"}
    if headers:
        merged.update(headers)
    return merged


@pytest.fixture
def totp_users(db_session):
    db_session.execute(text("DELETE FROM user_sessions"))
    db_session.execute(text("DELETE FROM users WHERE email LIKE 'totp-%@example.com'"))
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    db_session.execute(text("DELETE FROM login_rate_limit_attempts"))
    _enrollments.clear()

    def make_user(email: str, *, is_operator: bool, secret: str | None = None) -> User:
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            tenant_id=1,
            is_operator=is_operator,
            is_active=True,
            totp_secret=secret,
            totp_enrolled_at=datetime.utcnow() if secret else None,
        )
        db_session.add(user)
        db_session.flush()
        return user

    users = {
        "operator_plain": make_user("totp-operator-plain@example.com", is_operator=True),
        "operator_totp": make_user("totp-operator-enrolled@example.com", is_operator=True, secret=pyotp.random_base32()),
        "user_plain": make_user("totp-user-plain@example.com", is_operator=False),
        "user_totp": make_user("totp-user-enrolled@example.com", is_operator=False, secret=pyotp.random_base32()),
    }
    db_session.commit()
    try:
        yield users
    finally:
        db_session.execute(text("DELETE FROM user_sessions"))
        db_session.execute(text("DELETE FROM users WHERE email LIKE 'totp-%@example.com'"))
        db_session.commit()
        _enrollments.clear()


@pytest.mark.contract
def test_operator_login_without_enrollment_returns_enroll_required(app_client, totp_users):
    user = totp_users["operator_plain"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "totp_enroll_required"
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["secret"]
    assert body["qr_svg"].startswith("<svg")
    assert body["issuer"] == "ProfitOS"
    assert body["account_name"] == user.email
    assert "apos_totp_enroll" in response.cookies
    assert "apos_session" not in response.cookies


@pytest.mark.contract
def test_operator_login_with_enrolled_secret_requires_totp_code(app_client, totp_users):
    user = totp_users["operator_totp"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "totp_required"}
    assert "apos_session" not in response.cookies


@pytest.mark.contract
def test_operator_login_with_wrong_totp_returns_401(app_client, totp_users):
    user = totp_users["operator_totp"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "totp": "000000"},
        headers=_xrw(),
    )
    assert response.status_code == 401


@pytest.mark.contract
def test_operator_login_with_correct_totp_returns_ok(app_client, totp_users, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "selfhosted")
    user = totp_users["operator_totp"]
    code = pyotp.TOTP(user.totp_secret).now()
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "totp": code},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert response.json()["user"]["is_operator"] is True
    assert "apos_session" in response.cookies


@pytest.mark.contract
def test_user_login_without_totp_secret_no_code_required(app_client, totp_users):
    user = totp_users["user_plain"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert response.json()["user"]["is_operator"] is False
    assert "apos_session" in response.cookies


@pytest.mark.contract
def test_successful_user_logins_do_not_consume_rate_limit(app_client, totp_users):
    user = totp_users["user_plain"]
    for _ in range(5):
        response = app_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": PASSWORD},
            headers=_xrw(),
        )
        assert response.status_code == 200, response.text

    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password"},
        headers=_xrw(),
    )
    assert response.status_code == 401


@pytest.mark.contract
def test_user_login_with_totp_secret_requires_code(app_client, totp_users):
    user = totp_users["user_totp"]
    first = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"status": "totp_required"}

    code = pyotp.TOTP(user.totp_secret).now()
    second = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "totp": code},
        headers=_xrw(),
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "ok"
    assert "apos_session" in second.cookies


@pytest.mark.contract
def test_user_can_enable_and_disable_optional_totp_in_settings(app_client, totp_users, db_session):
    user = totp_users["user_plain"]
    db_session.add(UserSession(
        id="totp-user-settings-session",
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    db_session.commit()
    app_client.cookies.set("apos_session", "totp-user-settings-session")

    setup = app_client.post("/api/v1/auth/totp/setup", headers=_xrw())
    assert setup.status_code == 200, setup.text
    assert setup.json()["status"] == "totp_enroll_required"
    assert setup.json()["qr_svg"].startswith("<svg")

    code = pyotp.TOTP(setup.json()["secret"]).now()
    enroll = app_client.post("/api/v1/auth/totp/enroll", json={"totp": code}, headers=_xrw())
    assert enroll.status_code == 200, enroll.text
    db_session.expire_all()
    assert db_session.get(User, user.id).totp_secret == setup.json()["secret"]

    disable = app_client.post(
        "/api/v1/auth/totp/disable",
        json={"password": PASSWORD},
        headers=_xrw(),
    )
    assert disable.status_code == 200, disable.text
    db_session.expire_all()
    assert db_session.get(User, user.id).totp_secret is None


@pytest.mark.contract
def test_operator_cannot_disable_totp(app_client, totp_users, db_session):
    user = totp_users["operator_totp"]
    db_session.add(UserSession(
        id="totp-operator-settings-session",
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    db_session.commit()
    app_client.cookies.set("apos_session", "totp-operator-settings-session")

    response = app_client.post(
        "/api/v1/auth/totp/disable",
        json={"password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 403
