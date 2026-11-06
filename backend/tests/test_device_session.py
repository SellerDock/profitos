from datetime import datetime, timedelta
import threading

import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.device_session import (
    REFRESH_ABSOLUTE_TTL,
    REFRESH_SLIDING_TTL,
    ROTATION_GRACE_PERIOD,
    RefreshError,
    hash_refresh_token,
    rotate_refresh_token,
)
from app.core.security import hash_password, new_session_token
from app.models.tenant import Tenant
from app.models.user import DeviceSession, User, UserSession


PASSWORD = "CorrectHorseBatteryStaple1!"


def _xrw(headers: dict | None = None) -> dict:
    merged = {"X-Requested-With": "XMLHttpRequest"}
    if headers:
        merged.update(headers)
    return merged


def _seed_device_session(
    db,
    *,
    user: User,
    family_id: str = "fam-default",
    rotated: bool = False,
    revoked: bool = False,
    revoked_reason: str | None = None,
    refresh_expires_at: datetime | None = None,
    absolute_expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> tuple[str, DeviceSession]:
    raw_token = new_session_token()
    now = datetime.utcnow()
    device_session = DeviceSession(
        user_id=user.id,
        tenant_id=user.tenant_id,
        family_id=family_id,
        refresh_token_hash=hash_refresh_token(raw_token),
        created_at=created_at or now,
        last_used_at=now,
        refresh_expires_at=refresh_expires_at or (now + REFRESH_SLIDING_TTL),
        absolute_expires_at=absolute_expires_at or (now + REFRESH_ABSOLUTE_TTL),
        rotated_at=now if rotated else None,
        revoked_at=now if revoked else None,
        revoked_reason=revoked_reason,
    )
    db.add(device_session)
    db.commit()
    db.refresh(device_session)
    return raw_token, device_session


@pytest.fixture
def device_users(db_session):
    db_session.execute(text("DELETE FROM device_sessions"))
    db_session.execute(text("DELETE FROM user_sessions"))
    db_session.execute(text("DELETE FROM users WHERE email LIKE 'device-%@example.com'"))
    db_session.execute(text("DELETE FROM login_rate_limit_attempts"))
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    tenant_b = db_session.query(Tenant).filter(Tenant.slug == "device-tenant-b").first()
    if tenant_b is None:
        tenant_b = Tenant(name="Device Tenant B", slug="device-tenant-b", is_active=True)
        db_session.add(tenant_b)
        db_session.flush()

    def make_user(email: str, *, tenant_id: int = 1, secret: str | None = None) -> User:
        user = User(
            email=email,
            password_hash=hash_password(PASSWORD),
            tenant_id=tenant_id,
            is_operator=False,
            is_active=True,
            totp_secret=secret,
            totp_enrolled_at=datetime.utcnow() if secret else None,
        )
        db_session.add(user)
        db_session.flush()
        return user

    users = {
        "a": make_user("device-user-a@example.com"),
        "b": make_user("device-user-b@example.com", tenant_id=tenant_b.id),
        "totp": make_user("device-user-totp@example.com", secret=pyotp.random_base32()),
    }
    db_session.commit()
    try:
        yield users
    finally:
        db_session.execute(text("DELETE FROM device_sessions"))
        db_session.execute(text("DELETE FROM user_sessions"))
        db_session.execute(text("DELETE FROM users WHERE email LIKE 'device-%@example.com'"))
        db_session.execute(text("DELETE FROM tenants WHERE slug = 'device-tenant-b'"))
        db_session.execute(text("DELETE FROM login_rate_limit_attempts"))
        db_session.commit()


# --- refresh happy path / rotation -----------------------------------------


@pytest.mark.contract
def test_refresh_happy_path_rotates_and_issues_new_session(app_client, device_users, db_session):
    user = device_users["a"]
    raw_token, seeded = _seed_device_session(db_session, user=user)
    app_client.cookies.set("apos_refresh", raw_token)

    response = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert "apos_session" in response.cookies
    assert "apos_refresh" in response.cookies
    assert response.cookies["apos_refresh"] != raw_token

    db_session.expire_all()
    old = db_session.get(DeviceSession, seeded.id)
    assert old.rotated_at is not None
    assert old.revoked_at is None

    rows = db_session.query(DeviceSession).filter(DeviceSession.family_id == seeded.family_id).all()
    assert len(rows) == 2


@pytest.mark.contract
def test_old_token_after_rotation_returns_401(app_client, device_users, db_session):
    user = device_users["a"]
    raw_token, _seeded = _seed_device_session(db_session, user=user)
    app_client.cookies.set("apos_refresh", raw_token)
    first = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert first.status_code == 200, first.text

    app_client.cookies.set("apos_refresh", raw_token)
    second = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert second.status_code == 401


@pytest.mark.contract
def test_reuse_of_rotated_token_revokes_entire_family(app_client, device_users, db_session):
    user = device_users["a"]
    raw_token, seeded = _seed_device_session(db_session, user=user)
    app_client.cookies.set("apos_refresh", raw_token)
    first = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert first.status_code == 200, first.text
    new_raw = first.cookies["apos_refresh"]

    # Simulate a stolen token replayed well after the rotation (outside the
    # concurrency grace window) — this is the theft signal that must still
    # revoke the whole family.
    db_session.expire_all()
    old = db_session.get(DeviceSession, seeded.id)
    old.rotated_at = datetime.utcnow() - ROTATION_GRACE_PERIOD - timedelta(seconds=60)
    db_session.commit()

    app_client.cookies.set("apos_refresh", raw_token)
    reused = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert reused.status_code == 401

    db_session.expire_all()
    rows = db_session.query(DeviceSession).filter(DeviceSession.family_id == seeded.family_id).all()
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)
    assert all(row.revoked_reason == "reuse_detected" for row in rows)

    app_client.cookies.set("apos_refresh", new_raw)
    blocked = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert blocked.status_code == 401


# --- concurrent rotation (race) ----------------------------------------------


@pytest.mark.contract
def test_concurrent_rotation_one_wins_and_family_survives(device_users, db_session):
    user = device_users["a"]
    raw_token, seeded = _seed_device_session(db_session, user=user, family_id="fam-race")

    engine = db_session.get_bind()
    results: dict[str, tuple[str, str]] = {}

    def attempt(name: str) -> None:
        db = Session(engine)
        try:
            issued = rotate_refresh_token(db, raw_token=raw_token, user_agent=None, ip=None)
            results[name] = ("ok", issued.raw_token)
        except RefreshError as exc:
            results[name] = ("error", exc.reason)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [outcome for outcome in results.values() if outcome[0] == "ok"]
    losers = [outcome for outcome in results.values() if outcome[0] == "error"]
    assert len(winners) == 1, results
    assert len(losers) == 1, results
    # The loser raced a just-rotated token — rejected with 401, but this is a
    # race, not a reuse attack, so the family must NOT be revoked.
    assert losers[0][1] == "rotated_recently"

    db_session.expire_all()
    rows = db_session.query(DeviceSession).filter(DeviceSession.family_id == seeded.family_id).all()
    assert len(rows) == 2
    assert all(row.revoked_at is None for row in rows)

    # The family still works: the winning token rotates normally afterwards.
    follow_up = rotate_refresh_token(db_session, raw_token=winners[0][1], user_agent=None, ip=None)
    assert follow_up.device_session.family_id == seeded.family_id


# --- lifetimes ---------------------------------------------------------------


@pytest.mark.contract
def test_absolute_cap_expired_returns_401(app_client, device_users, db_session):
    user = device_users["a"]
    now = datetime.utcnow()
    raw_token, _seeded = _seed_device_session(
        db_session,
        user=user,
        created_at=now - timedelta(days=95),
        absolute_expires_at=now - timedelta(days=5),
        refresh_expires_at=now + timedelta(days=10),
    )
    app_client.cookies.set("apos_refresh", raw_token)
    response = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert response.status_code == 401


@pytest.mark.contract
def test_sliding_expiry_expired_returns_401(app_client, device_users, db_session):
    user = device_users["a"]
    now = datetime.utcnow()
    raw_token, _seeded = _seed_device_session(
        db_session,
        user=user,
        refresh_expires_at=now - timedelta(minutes=1),
        absolute_expires_at=now + timedelta(days=60),
    )
    app_client.cookies.set("apos_refresh", raw_token)
    response = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert response.status_code == 401


# --- TOTP interaction ----------------------------------------------------


@pytest.mark.contract
def test_refresh_does_not_require_totp(app_client, device_users, db_session):
    user = device_users["totp"]
    raw_token, _seeded = _seed_device_session(db_session, user=user)
    app_client.cookies.set("apos_refresh", raw_token)
    response = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"


@pytest.mark.contract
def test_login_for_totp_user_still_requires_totp(app_client, device_users):
    user = device_users["totp"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "totp_required"}
    assert "apos_session" not in response.cookies
    assert "apos_refresh" not in response.cookies


@pytest.mark.contract
def test_login_with_totp_and_remember_device_sets_refresh_cookie(app_client, device_users):
    user = device_users["totp"]
    code = pyotp.TOTP(user.totp_secret).now()
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "totp": code, "remember_device": True},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert "apos_refresh" in response.cookies


# --- remember_device / app UA marker ----------------------------------------


@pytest.mark.contract
def test_login_without_remember_device_does_not_set_refresh_cookie(app_client, device_users):
    user = device_users["a"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert "apos_session" in response.cookies
    assert "apos_refresh" not in response.cookies


@pytest.mark.contract
def test_login_with_remember_device_sets_refresh_cookie(app_client, device_users, db_session):
    user = device_users["a"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD, "remember_device": True},
        headers=_xrw(),
    )
    assert response.status_code == 200, response.text
    assert "apos_refresh" in response.cookies

    db_session.expire_all()
    rows = db_session.query(DeviceSession).filter(DeviceSession.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None


@pytest.mark.contract
def test_login_with_app_user_agent_marker_sets_refresh_cookie(app_client, device_users):
    user = device_users["a"]
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
        headers=_xrw({"User-Agent": "ProfitOSAndroid/1.0 pl.profitos.app/0.1.0"}),
    )
    assert response.status_code == 200, response.text
    assert "apos_refresh" in response.cookies


# --- devices panel -----------------------------------------------------------


@pytest.mark.contract
def test_list_devices_hides_token_hash_and_is_isolated_per_user(app_client, device_users, db_session):
    user_a = device_users["a"]
    user_b = device_users["b"]
    session_token = "device-list-session"
    db_session.add(UserSession(id=session_token, user_id=user_a.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    _seed_device_session(db_session, user=user_a, family_id="fam-a")
    _seed_device_session(db_session, user=user_b, family_id="fam-b")
    db_session.commit()
    app_client.cookies.set("apos_session", session_token)

    response = app_client.get("/api/v1/auth/devices")
    assert response.status_code == 200, response.text
    devices = response.json()["devices"]
    assert len(devices) == 1
    device = devices[0]
    assert device["status"] == "active"
    assert set(device.keys()) == {
        "id",
        "device_label",
        "user_agent",
        "app_version",
        "ip_created",
        "created_at",
        "last_used_at",
        "status",
    }


@pytest.mark.contract
def test_list_devices_shows_one_row_per_family_not_per_rotation(app_client, device_users, db_session):
    user = device_users["a"]
    session_token = "device-list-rotation-session"
    db_session.add(UserSession(id=session_token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db_session.commit()
    app_client.cookies.set("apos_session", session_token)

    raw_token, _seeded = _seed_device_session(db_session, user=user, family_id="fam-rotate")
    app_client.cookies.set("apos_refresh", raw_token)
    refreshed = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert refreshed.status_code == 200, refreshed.text
    app_client.cookies.set("apos_session", session_token)

    response = app_client.get("/api/v1/auth/devices")
    assert response.status_code == 200, response.text
    assert len(response.json()["devices"]) == 1


@pytest.mark.contract
def test_delete_device_revokes_family_and_dependent_refresh(app_client, device_users, db_session):
    user = device_users["a"]
    session_token = "device-delete-session"
    db_session.add(UserSession(id=session_token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    raw_token, seeded = _seed_device_session(db_session, user=user)
    db_session.commit()
    app_client.cookies.set("apos_session", session_token)

    delete_resp = app_client.delete(f"/api/v1/auth/devices/{seeded.id}", headers=_xrw())
    assert delete_resp.status_code == 204

    db_session.expire_all()
    revoked = db_session.get(DeviceSession, seeded.id)
    assert revoked.revoked_at is not None
    assert revoked.revoked_reason == "user_revoked"

    app_client.cookies.set("apos_refresh", raw_token)
    refreshed = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert refreshed.status_code == 401


@pytest.mark.contract
def test_delete_device_for_other_user_returns_404(app_client, device_users, db_session):
    user_a = device_users["a"]
    user_b = device_users["b"]
    _raw_token_b, seeded_b = _seed_device_session(db_session, user=user_b)

    session_token = "device-delete-other-session"
    db_session.add(UserSession(id=session_token, user_id=user_a.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db_session.commit()
    app_client.cookies.set("apos_session", session_token)

    response = app_client.delete(f"/api/v1/auth/devices/{seeded_b.id}", headers=_xrw())
    assert response.status_code == 404

    db_session.expire_all()
    assert db_session.get(DeviceSession, seeded_b.id).revoked_at is None


@pytest.mark.contract
def test_device_logout_revokes_family_and_clears_cookies(app_client, device_users, db_session):
    user = device_users["a"]
    session_token = "device-logout-session"
    db_session.add(UserSession(id=session_token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    raw_token, seeded = _seed_device_session(db_session, user=user)
    db_session.commit()
    app_client.cookies.set("apos_session", session_token)
    app_client.cookies.set("apos_refresh", raw_token)

    response = app_client.post("/api/v1/auth/device/logout", headers=_xrw())
    assert response.status_code == 204

    db_session.expire_all()
    assert db_session.get(DeviceSession, seeded.id).revoked_at is not None
    assert db_session.get(UserSession, session_token).revoked_at is not None


# --- rate limiting -------------------------------------------------------


@pytest.mark.contract
def test_refresh_is_rate_limited_per_ip(app_client, device_users):
    app_client.cookies.set("apos_refresh", "not-a-real-token")
    for _ in range(20):
        response = app_client.post("/api/v1/auth/refresh", headers=_xrw())
        assert response.status_code == 401
    limited = app_client.post("/api/v1/auth/refresh", headers=_xrw())
    assert limited.status_code == 429


@pytest.mark.contract
@pytest.mark.parametrize("via_header", [False, True])
def test_logout_revokes_refresh_family(app_client, device_users, db_session, via_header):
    raw, row = _seed_device_session(db_session, user=device_users["a"])
    headers = _xrw({"X-Refresh-Token": raw} if via_header else None)
    if not via_header:
        app_client.cookies.set("apos_refresh", raw, path="/api/v1/auth")
    response = app_client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 204
    cookies = response.headers.get_list("set-cookie")
    assert any("Path=/api/v1/auth;" in cookie for cookie in cookies)
    assert any("Path=/api/v1/auth/refresh;" in cookie for cookie in cookies)
    db_session.expire_all()
    assert db_session.get(DeviceSession, row.id).revoked_reason == "logout"
    response = app_client.post("/api/v1/auth/refresh", headers=_xrw({"X-Refresh-Token": raw}))
    assert response.status_code == 401


@pytest.mark.contract
def test_refresh_sets_new_cookie_path_and_removes_legacy(app_client, device_users, db_session):
    raw, _ = _seed_device_session(db_session, user=device_users["a"])
    response = app_client.post("/api/v1/auth/refresh", headers=_xrw({"X-Refresh-Token": raw}))
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any("apos_refresh=" in c and "Path=/api/v1/auth;" in c and "Max-Age=0" not in c for c in cookies)
    assert any("apos_refresh=" in c and "Path=/api/v1/auth/refresh;" in c and "Max-Age=0" in c for c in cookies)


@pytest.mark.contract
@pytest.mark.parametrize("script", ["reset_password", "reset_totp"])
def test_reset_revokes_all_sessions(device_users, db_session, script):
    from scripts import reset_password, reset_totp

    user = device_users["a"]
    _, device = _seed_device_session(db_session, user=user)
    session = UserSession(id=new_session_token(), user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1))
    db_session.add(session)
    db_session.commit()
    if script == "reset_password":
        reset_password.reset(db_session, user, "NewCorrectHorseBattery1!")
    else:
        reset_totp.reset(db_session, user)
    db_session.expire_all()
    assert db_session.get(UserSession, session.id).revoked_at is not None
    assert db_session.get(DeviceSession, device.id).revoked_reason == script
