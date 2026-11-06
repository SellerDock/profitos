from datetime import datetime, timedelta

import pyotp
import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import ActivationToken, User, UserSession, WaitlistEntry


@pytest.fixture(autouse=True)
def _hosted_deployment_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")


TENANT_TABLES = [
    "encrypted_sku_cost_history",
    "encrypted_sku_costs",
    "financial_vaults",
    "sku_aliases",
    "sku_masters",
    "allegro_ads_imports",
    "sync_log",
    "account_import_state",
    "customer_return_items_raw",
    "customer_returns_raw",
    "payment_refund_line_items_raw",
    "payment_refunds_raw",
    "order_events_raw",
    "orders_raw",
    "billing_raw",
    "offers_cache",
    "stock_levels",
    "stock_settings",
    "accounts",
]


def _xrw(headers: dict | None = None) -> dict:
    merged = {"X-Requested-With": "XMLHttpRequest"}
    if headers:
        merged.update(headers)
    return merged


@pytest.fixture(autouse=True)
def clean_rodo(seeded_db):
    db = seeded_db["db"]
    db.rollback()
    _cleanup_rodo_rows(db)
    yield
    db.rollback()
    _cleanup_rodo_rows(db)


def _cleanup_rodo_rows(db) -> None:
    db.execute(text("DELETE FROM activation_tokens WHERE email LIKE 'rodo-%@example.com'"))
    db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'rodo-%'"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'rodo-%@example.com'"))
    db.execute(text("DELETE FROM waitlist_entries WHERE email LIKE 'rodo-%@example.com'"))
    for table in TENANT_TABLES:
        db.execute(text(f"DELETE FROM {table} WHERE tenant_id IN (SELECT id FROM tenants WHERE slug LIKE 'rodo-%')"))
    db.execute(text("DELETE FROM tenants WHERE slug LIKE 'rodo-%'"))
    db.commit()


def _create_operator_session(app_client, db, email: str = "rodo-operator@example.com") -> User:
    operator = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_operator=True,
        is_active=True,
        totp_secret=pyotp.random_base32(),
        totp_enrolled_at=datetime.utcnow(),
    )
    db.add(operator)
    db.flush()
    session = UserSession(
        id=f"rodo-operator-session-{operator.id}",
        user_id=operator.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db.add(session)
    db.commit()
    app_client.cookies.set("apos_session", session.id)
    return operator


def _create_tenant_user_session(
    app_client,
    db,
    *,
    slug: str = "rodo-self-delete",
    email: str = "rodo-user@example.com",
    password: str = "CorrectHorseBatteryStaple1!",
    totp_secret: str | None = None,
) -> tuple[Tenant, User]:
    tenant = Tenant(name=slug.replace("-", " ").title(), slug=slug, is_active=True)
    db.add(tenant)
    db.flush()
    user = User(
        email=email,
        password_hash=hash_password(password),
        tenant_id=tenant.id,
        is_operator=False,
        is_active=True,
        totp_secret=totp_secret,
        totp_enrolled_at=datetime.utcnow() if totp_secret else None,
        privacy_accepted_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    db.add(UserSession(id=f"rodo-user-session-{user.id}", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db.commit()
    app_client.cookies.set("apos_session", f"rodo-user-session-{user.id}")
    return tenant, user


@pytest.mark.contract
def test_self_delete_requires_password(app_client, seeded_db):
    _create_tenant_user_session(app_client, seeded_db["db"])
    response = app_client.post(
        "/api/v1/auth/me/delete",
        json={"confirm": True},
        headers=_xrw(),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.contract
def test_self_delete_with_totp(app_client, seeded_db):
    secret = pyotp.random_base32()
    tenant, user = _create_tenant_user_session(
        app_client,
        seeded_db["db"],
        slug="rodo-self-delete-totp",
        email="rodo-totp@example.com",
        totp_secret=secret,
    )
    tenant_id = tenant.id
    user_id = user.id
    missing_totp = app_client.post(
        "/api/v1/auth/me/delete",
        json={"password": "CorrectHorseBatteryStaple1!", "confirm": True},
        headers=_xrw(),
    )
    assert missing_totp.status_code == 401
    assert missing_totp.json()["detail"] == "Invalid TOTP code"

    response = app_client.post(
        "/api/v1/auth/me/delete",
        json={"password": "CorrectHorseBatteryStaple1!", "totp": pyotp.TOTP(secret).now(), "confirm": True},
        headers=_xrw(),
    )
    assert response.status_code == 204
    seeded_db["db"].expire_all()
    assert seeded_db["db"].get(User, user_id) is None
    assert seeded_db["db"].get(Tenant, tenant_id) is None


@pytest.mark.contract
def test_self_delete_last_user_deletes_tenant(app_client, seeded_db):
    tenant, user = _create_tenant_user_session(app_client, seeded_db["db"])
    tenant_id = tenant.id
    user_id = user.id
    session_id = f"rodo-user-session-{user_id}"
    response = app_client.post(
        "/api/v1/auth/me/delete",
        json={"password": "CorrectHorseBatteryStaple1!", "confirm": True},
        headers=_xrw(),
    )
    assert response.status_code == 204
    seeded_db["db"].expire_all()
    assert seeded_db["db"].get(User, user_id) is None
    assert seeded_db["db"].get(Tenant, tenant_id) is None
    assert seeded_db["db"].get(UserSession, session_id) is None


@pytest.mark.contract
def test_operator_cannot_self_delete(app_client, seeded_db):
    _create_operator_session(app_client, seeded_db["db"])
    response = app_client.post(
        "/api/v1/auth/me/delete",
        json={"password": "CorrectHorseBatteryStaple1!", "confirm": True},
        headers=_xrw(),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Operators cannot self-delete via API. Use scripts/delete_operator.py"


def _seed_tenant_operational_rows(db, operator: User, slug: str = "rodo-hard-delete") -> Tenant:
    tenant = Tenant(name="RODO Hard Delete", slug=slug, is_active=True)
    db.add(tenant)
    db.flush()
    user = User(
        email="rodo-hard-delete@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=tenant.id,
        is_operator=False,
        is_active=True,
        privacy_accepted_at=datetime.utcnow(),
    )
    db.add(user)
    db.flush()
    db.add(UserSession(id="rodo-hard-delete-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    waitlist = WaitlistEntry(email="rodo-hard-delete@example.com", privacy_accepted_at=datetime.utcnow())
    db.add(waitlist)
    db.flush()
    db.add(ActivationToken(
        token_hash=f"rodo{tenant.id:060d}"[-64:],
        waitlist_entry_id=waitlist.id,
        tenant_id=tenant.id,
        email=waitlist.email,
        created_by_user_id=operator.id,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    account_id = db.execute(text("""
        INSERT INTO accounts (tenant_id, name, allegro_client_id, allegro_client_secret, color)
        VALUES (:tid, 'RODO Account', :client_id, 'secret', '#334155')
        RETURNING id
    """), {"tid": tenant.id, "client_id": f"rodo-client-{tenant.id}"}).scalar_one()
    sku_id = db.execute(text("""
        INSERT INTO sku_masters (tenant_id, sku_key, name, vat_rate, target_margin_pct)
        VALUES (:tid, :sku, 'RODO SKU', 23, 20)
        RETURNING id
    """), {"tid": tenant.id, "sku": f"RODO-{tenant.id}"}).scalar_one()
    vault_id = db.execute(text("""
        INSERT INTO financial_vaults
            (tenant_id, scope, kdf, salt, memory_cost, time_cost, parallelism, verify_nonce, verify_ciphertext, key_version)
        VALUES (:tid, 'global', 'argon2id', 'salt', 65536, 3, 1, 'nonce', 'ciphertext', 1)
        RETURNING id
    """), {"tid": tenant.id}).scalar_one()
    db.execute(text("""
        INSERT INTO sku_aliases (tenant_id, sku_master_id, account_id, raw_name, multiplier)
        VALUES (:tid, :sku_id, :account_id, 'raw', 1)
    """), {"tid": tenant.id, "sku_id": sku_id, "account_id": account_id})
    db.execute(text("""
        INSERT INTO encrypted_sku_costs (tenant_id, sku_master_id, vault_id, ciphertext, nonce, key_version, aad_context)
        VALUES (:tid, :sku_id, :vault_id, 'ct', 'nonce', 1, 'aad')
    """), {"tid": tenant.id, "sku_id": sku_id, "vault_id": vault_id})
    db.execute(text("""
        INSERT INTO encrypted_sku_cost_history
            (tenant_id, sku_master_id, vault_id, ciphertext, nonce, key_version, aad_context, valid_from)
        VALUES (:tid, :sku_id, :vault_id, 'ct', 'nonce', 1, 'aad', CURRENT_DATE)
    """), {"tid": tenant.id, "sku_id": sku_id, "vault_id": vault_id})
    db.execute(text("INSERT INTO stock_levels (tenant_id, sku_id, quantity, updated_by) VALUES (:tid, :sku_id, 3, 'manual')"), {"tid": tenant.id, "sku_id": sku_id})
    db.execute(text("INSERT INTO stock_settings (tenant_id, key, value) VALUES (:tid, 'threshold_warning', 5)"), {"tid": tenant.id})
    db.execute(text("""
        INSERT INTO offers_cache (tenant_id, offer_id, account_id, sku, name, price, currency)
        VALUES (:tid, :offer_id, :account_id, 'RODO', 'Offer', 100, 'PLN')
    """), {"tid": tenant.id, "offer_id": f"rodo-offer-{tenant.id}", "account_id": account_id})
    db.execute(text("""
        INSERT INTO billing_raw (tenant_id, entry_id, account_id, offer_id, order_id, type, amount, currency)
        VALUES (:tid, :entry_id, :account_id, :offer_id, :order_id, 'SUC', -2, 'PLN')
    """), {"tid": tenant.id, "entry_id": f"rodo-billing-{tenant.id}", "account_id": account_id, "offer_id": f"rodo-offer-{tenant.id}", "order_id": f"rodo-order-{tenant.id}"})
    db.execute(text("""
        INSERT INTO orders_raw (tenant_id, line_item_id, order_id, account_id, offer_id, sku, quantity, unit_price, delivery_amount, currency)
        VALUES (:tid, :line_id, :order_id, :account_id, :offer_id, 'RODO', 1, 100, 0, 'PLN')
    """), {"tid": tenant.id, "line_id": f"rodo-line-{tenant.id}", "order_id": f"rodo-order-{tenant.id}", "account_id": account_id, "offer_id": f"rodo-offer-{tenant.id}"})
    db.execute(text("""
        INSERT INTO order_events_raw (tenant_id, event_id, account_id, order_id, event_type)
        VALUES (:tid, :event_id, :account_id, :order_id, 'READY_FOR_PROCESSING')
    """), {"tid": tenant.id, "event_id": f"rodo-event-{tenant.id}", "account_id": account_id, "order_id": f"rodo-order-{tenant.id}"})
    db.execute(text("""
        INSERT INTO customer_returns_raw (tenant_id, customer_return_id, account_id, order_id, is_fulfillment)
        VALUES (:tid, :return_id, :account_id, :order_id, false)
    """), {"tid": tenant.id, "return_id": f"rodo-return-{tenant.id}", "account_id": account_id, "order_id": f"rodo-order-{tenant.id}"})
    db.execute(text("""
        INSERT INTO customer_return_items_raw (tenant_id, customer_return_id, item_index, quantity)
        VALUES (:tid, :return_id, 0, 1)
    """), {"tid": tenant.id, "return_id": f"rodo-return-{tenant.id}"})
    db.execute(text("""
        INSERT INTO payment_refunds_raw
            (tenant_id, refund_id, account_id, order_id, total_amount, currency, delivery_amount, overpaid_amount, additional_services_amount)
        VALUES (:tid, :refund_id, :account_id, :order_id, 100, 'PLN', 0, 0, 0)
    """), {"tid": tenant.id, "refund_id": f"rodo-refund-{tenant.id}", "account_id": account_id, "order_id": f"rodo-order-{tenant.id}"})
    db.execute(text("""
        INSERT INTO payment_refund_line_items_raw (tenant_id, refund_id, item_index, quantity)
        VALUES (:tid, :refund_id, 0, 1)
    """), {"tid": tenant.id, "refund_id": f"rodo-refund-{tenant.id}"})
    db.execute(text("""
        INSERT INTO account_import_state (tenant_id, account_id)
        VALUES (:tid, :account_id)
    """), {"tid": tenant.id, "account_id": account_id})
    db.execute(text("""
        INSERT INTO sync_log (tenant_id, account_id, days_fetched, orders_count, billing_count, offers_count)
        VALUES (:tid, :account_id, 1, 0, 0, 0)
    """), {"tid": tenant.id, "account_id": account_id})
    db.execute(text("""
        INSERT INTO allegro_ads_imports
            (tenant_id, account_id, offer_id, campaign_name, ad_date, impressions, clicks, interest, cpc, ctr, cost, roas, units_sold_via_ad, sales_value)
        VALUES (:tid, :account_id, :offer_id, 'RODO Campaign', CURRENT_DATE, 0, 0, 0, 0, 0, 1, 0, 0, 0)
    """), {"tid": tenant.id, "account_id": account_id, "offer_id": f"rodo-offer-{tenant.id}"})
    db.commit()
    return tenant


@pytest.mark.contract
def test_admin_hard_delete_tenant_requires_slug_match(app_client, seeded_db):
    operator = _create_operator_session(app_client, seeded_db["db"])
    tenant = _seed_tenant_operational_rows(seeded_db["db"], operator, slug="rodo-slug-mismatch")
    response = app_client.delete(
        f"/api/v1/admin/tenants/{tenant.id}?confirm=true&slug=wrong",
        headers=_xrw(),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "slug confirmation does not match"


@pytest.mark.contract
def test_admin_hard_delete_tenant_cascade(app_client, seeded_db):
    operator = _create_operator_session(app_client, seeded_db["db"])
    tenant = _seed_tenant_operational_rows(seeded_db["db"], operator)
    tenant_id = tenant.id
    tenant_slug = tenant.slug
    response = app_client.delete(
        f"/api/v1/admin/tenants/{tenant_id}?confirm=true&slug={tenant_slug}",
        headers=_xrw(),
    )
    assert response.status_code == 204, response.text
    seeded_db["db"].expire_all()
    assert seeded_db["db"].get(Tenant, tenant_id) is None
    for table in TENANT_TABLES:
        count = seeded_db["db"].execute(text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id}).scalar_one()
        assert count == 0, table


@pytest.mark.contract
def test_admin_hard_delete_operator_tenant(app_client, seeded_db):
    _create_operator_session(app_client, seeded_db["db"])
    response = app_client.delete(
        "/api/v1/admin/tenants/1?confirm=true&slug=operator",
        headers=_xrw(),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Operator tenant cannot be deleted"


@pytest.mark.contract
def test_system_health_reports_metrics(app_client, seeded_db):
    _create_operator_session(app_client, seeded_db["db"])
    response = app_client.get("/api/v1/admin/system-health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "status",
        "db_ok",
        "tenants_count",
        "users_count",
        "active_sessions",
        "pending_activations",
        "pending_waitlist",
        "last_sync_at",
        "checked_at",
    }
    assert body["db_ok"] is True
    assert body["status"] == "ok"
    assert body["users_count"] >= 1
    assert body["active_sessions"] >= 1


@pytest.mark.contract
def test_system_health_requires_operator(app_client, seeded_db):
    _create_tenant_user_session(
        app_client,
        seeded_db["db"],
        slug="rodo-health-normal",
        email="rodo-health-normal@example.com",
    )
    response = app_client.get("/api/v1/admin/system-health")
    assert response.status_code == 403
