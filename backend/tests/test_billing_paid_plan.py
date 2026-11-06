from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.models.billing_profile import TenantPaidPlanAcceptance
from app.models.tenant import Tenant
from app.models.user import User, UserSession


@pytest.fixture(autouse=True)
def _hosted_deployment_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")


def _xrw() -> dict:
    return {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def paid_plan_fixture(app_client, seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM tenant_paid_plan_acceptances WHERE terms_version LIKE 'test-%'"))
    db.execute(text("DELETE FROM user_sessions WHERE id = 'paid-plan-session'"))
    db.execute(text("DELETE FROM users WHERE email = 'paid-plan@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug = 'paid-plan-tenant'"))
    tenant = Tenant(
        name="Paid Plan Tenant",
        slug="paid-plan-tenant",
        is_active=True,
        created_at=datetime.utcnow() - timedelta(days=31),
    )
    db.add(tenant)
    db.flush()
    user = User(
        email="paid-plan@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=tenant.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    session = UserSession(id="paid-plan-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1))
    db.add(session)
    db.commit()
    app_client.cookies.set("apos_session", session.id)
    yield {"db": db, "client": app_client, "tenant": tenant, "user": user}
    app_client.cookies.clear()
    db.execute(text("DELETE FROM tenant_paid_plan_acceptances WHERE tenant_id = :tenant_id"), {"tenant_id": tenant.id})
    db.execute(text("DELETE FROM user_sessions WHERE id = 'paid-plan-session'"))
    db.execute(text("DELETE FROM users WHERE email = 'paid-plan@example.com'"))
    db.execute(text("DELETE FROM tenants WHERE slug = 'paid-plan-tenant'"))
    db.commit()


@pytest.mark.contract
def test_paid_plan_acceptance_updates_subscription_status(paid_plan_fixture):
    client = paid_plan_fixture["client"]

    before = client.get("/api/v1/billing/subscription")
    assert before.status_code == 200, before.text
    assert before.json()["paid_plan_accepted"] is False
    assert before.json()["imports_paused"] is True

    response = client.post(
        "/api/v1/billing/paid-plan/accept",
        json={"terms_accepted": True, "terms_version": "test-terms"},
        headers={**_xrw(), "User-Agent": "pytest"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["paid_plan_accepted"] is True
    assert body["terms_version"] == "test-terms"

    after = client.get("/api/v1/billing/subscription")
    assert after.status_code == 200, after.text
    assert after.json()["paid_plan_accepted"] is True
    assert after.json()["imports_paused"] is False
    acceptance = paid_plan_fixture["db"].query(TenantPaidPlanAcceptance).filter_by(
        tenant_id=paid_plan_fixture["tenant"].id,
        terms_version="test-terms",
    ).one()
    assert acceptance.user_id == paid_plan_fixture["user"].id


@pytest.mark.contract
def test_paid_plan_acceptance_requires_terms_checkbox(paid_plan_fixture):
    response = paid_plan_fixture["client"].post(
        "/api/v1/billing/paid-plan/accept",
        json={"terms_accepted": False, "terms_version": "test-terms"},
        headers=_xrw(),
    )

    assert response.status_code == 422
