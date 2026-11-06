from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.models.user import User, UserSession
from app.services import email as email_service


def _xrw() -> dict:
    return {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def support_user(app_client, seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'support-report-%'"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'support-report-%@example.com'"))
    db.commit()

    user = User(
        email="support-report-user@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_active=True,
    )
    db.add(user)
    db.flush()
    session = UserSession(
        id="support-report-session",
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(session)
    db.commit()
    app_client.cookies.set("apos_session", session.id)

    try:
        yield {"client": app_client, "user": user}
    finally:
        app_client.cookies.clear()
        db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'support-report-%'"))
        db.execute(text("DELETE FROM users WHERE email LIKE 'support-report-%@example.com'"))
        db.commit()


@pytest.mark.contract
def test_support_report_requires_login(app_client):
    response = app_client.post(
        "/api/v1/support/ticket",
        data={"message": "Nie działa import."},
        headers=_xrw(),
    )

    assert response.status_code == 401


@pytest.mark.contract
def test_support_report_sends_message_with_attachment(monkeypatch, support_user):
    sent: list[dict] = []

    def fake_send_support_report_email(**kwargs) -> bool:
        sent.append(kwargs)
        return True

    monkeypatch.setattr(email_service, "send_support_report_email", fake_send_support_report_email, raising=False)

    response = support_user["client"].post(
        "/api/v1/support/ticket",
        data={"message": "Na ekranie importu coś się wysypało."},
        files={"attachment": ("blad.txt", b"stack trace", "text/plain")},
        headers=_xrw(),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}
    assert sent == [{
        "from_user_email": "support-report-user@example.com",
        "tenant_id": 1,
        "message": "Na ekranie importu coś się wysypało.",
        "attachment_filename": "blad.txt",
        "attachment_content_type": "text/plain",
        "attachment_bytes": b"stack trace",
    }]


@pytest.mark.contract
def test_support_report_rejects_attachment_over_5mb(support_user):
    response = support_user["client"].post(
        "/api/v1/support/ticket",
        data={"message": "Duży plik."},
        files={"attachment": ("too-big.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain")},
        headers=_xrw(),
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Attachment max size is 5 MB"
