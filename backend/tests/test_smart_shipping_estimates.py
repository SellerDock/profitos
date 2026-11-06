from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.account import Account
from app.models.raw_data import BillingRaw
from app.models.tenant import Tenant
from app.services.import_service import (
    ImportService,
    _SMART_ESTIMATE_PREFIX,
    _smart_estimate_rate,
)


@pytest.mark.parametrize(("total", "expected"), [
    ("29.99", None),
    ("30.00", "1.59"),
    ("44.99", "1.59"),
    ("45.00", "3.19"),
    ("64.99", "3.19"),
    ("65.00", "5.19"),
    ("99.99", "5.19"),
    ("100.00", "7.89"),
    ("149.99", "7.89"),
    ("150.00", "9.99"),
])
def test_smart_rate_boundaries(total, expected):
    rate = _smart_estimate_rate(Decimal(total))
    if expected is None:
        assert rate is None
    else:
        assert rate == Decimal(expected)


def _cleanup(db):
    db.rollback()
    db.execute(text("DELETE FROM billing_raw WHERE order_id LIKE 'smart-estimate-test-%' OR entry_id = 'smart-real-test'"))
    db.execute(text("DELETE FROM accounts WHERE allegro_client_id = 'smart-estimate-test-client'"))
    db.commit()


def _row(order_id, amount, bought_at, *, smart=True, method="Allegro Paczkomaty InPost"):
    return {
        "order_id": order_id,
        "line_item_id": f"line-{order_id}-{amount}",
        "unit_price": amount,
        "quantity": 1,
        "currency": "PLN",
        "bought_at": bought_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "delivery_is_smart": smart,
        "delivery_method_name": method,
    }


def test_estimate_is_per_order_idempotent_and_replaced_by_real_smart_fee(db_session):
    _cleanup(db_session)
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    account = Account(
        tenant_id=1,
        name="Smart estimate test",
        allegro_client_id="smart-estimate-test-client",
        allegro_client_secret="test-secret",
    )
    db_session.add(account)
    db_session.commit()
    service = ImportService(db_session)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    order_id = "smart-estimate-test-order"

    try:
        rows = [_row(order_id, "45.00", now), _row(order_id, "19.99", now)]
        assert service._upsert_smart_shipping_estimates(account.id, 1, rows) == 1
        assert service._upsert_smart_shipping_estimates(account.id, 1, rows) == 1
        estimate = db_session.execute(text("""
            SELECT amount, type, shipping_is_smart
            FROM billing_raw WHERE entry_id = :entry_id
        """), {"entry_id": f"{_SMART_ESTIMATE_PREFIX}{account.id}:{order_id}"}).one()
        assert estimate.amount == Decimal("-3.19")
        assert estimate.type == "SMART"
        assert estimate.shipping_is_smart is True

        db_session.add(BillingRaw(
            tenant_id=1,
            entry_id="smart-real-test",
            account_id=account.id,
            order_id=order_id,
            type="HB4",
            amount=Decimal("-3.69"),
            currency="PLN",
            occurred_at=now,
            shipping_is_smart=True,
            shipping_order_is_smart=True,
        ))
        db_session.commit()
        assert service._remove_replaced_smart_estimates(account.id, 1) == 1
        assert db_session.execute(text("""
            SELECT count(*) FROM billing_raw
            WHERE entry_id = :entry_id
        """), {"entry_id": f"{_SMART_ESTIMATE_PREFIX}{account.id}:{order_id}"}).scalar() == 0
    finally:
        _cleanup(db_session)


def test_does_not_estimate_below_30_non_smart_or_old_order(db_session):
    _cleanup(db_session)
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    account = Account(
        tenant_id=1,
        name="Smart estimate test",
        allegro_client_id="smart-estimate-test-client",
        allegro_client_secret="test-secret",
    )
    db_session.add(account)
    db_session.commit()
    service = ImportService(db_session)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    try:
        rows = [
            _row("smart-estimate-test-under-30", "29.99", now),
            _row("smart-estimate-test-not-smart", "45.00", now, smart=False),
            _row("smart-estimate-test-old", "45.00", now - timedelta(days=2)),
        ]
        assert service._upsert_smart_shipping_estimates(account.id, 1, rows) == 0
        assert db_session.execute(text("""
            SELECT count(*) FROM billing_raw
            WHERE entry_id LIKE 'smart-estimate:%' AND account_id = :account_id
        """), {"account_id": account.id}).scalar() == 0
    finally:
        _cleanup(db_session)


def test_estimates_smart_for_any_delivery_method(db_session):
    _cleanup(db_session)
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    account = Account(
        tenant_id=1,
        name="Smart estimate test",
        allegro_client_id="smart-estimate-test-client",
        allegro_client_secret="test-secret",
    )
    db_session.add(account)
    db_session.commit()
    service = ImportService(db_session)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)

    try:
        rows = [
            _row("smart-estimate-test-one", "45.00", now, method="Allegro One Kurier"),
            _row("smart-estimate-test-dpd", "65.00", now, method="Allegro DPD Kurier"),
            _row("smart-estimate-test-no-name", "100.00", now, method=""),
        ]
        assert service._upsert_smart_shipping_estimates(account.id, 1, rows) == 3
        estimates = dict(db_session.execute(text("""
            SELECT order_id, amount
            FROM billing_raw
            WHERE entry_id LIKE 'smart-estimate:%' AND account_id = :account_id
        """), {"account_id": account.id}).all())
        assert estimates == {
            "smart-estimate-test-one": Decimal("-3.19"),
            "smart-estimate-test-dpd": Decimal("-5.19"),
            "smart-estimate-test-no-name": Decimal("-7.89"),
        }
    finally:
        _cleanup(db_session)


def test_forecast_expires_after_seven_days(db_session):
    _cleanup(db_session)
    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()
    account = Account(
        tenant_id=1,
        name="Smart estimate test",
        allegro_client_id="smart-estimate-test-client",
        allegro_client_secret="test-secret",
    )
    db_session.add(account)
    db_session.commit()
    service = ImportService(db_session)
    as_of = datetime(2026, 7, 21, 12, 0, 0)

    try:
        expired_order_id = "smart-estimate-test-expired"
        fresh_order_id = "smart-estimate-test-fresh"
        db_session.add_all([
            BillingRaw(
                tenant_id=1,
                entry_id=f"{_SMART_ESTIMATE_PREFIX}{account.id}:{expired_order_id}",
                account_id=account.id,
                order_id=expired_order_id,
                type="SMART",
                amount=Decimal("-5.19"),
                currency="PLN",
                occurred_at=as_of - timedelta(days=7),
                shipping_is_smart=True,
                shipping_order_is_smart=True,
            ),
            BillingRaw(
                tenant_id=1,
                entry_id=f"{_SMART_ESTIMATE_PREFIX}{account.id}:{fresh_order_id}",
                account_id=account.id,
                order_id=fresh_order_id,
                type="SMART",
                amount=Decimal("-5.19"),
                currency="PLN",
                occurred_at=as_of - timedelta(days=7) + timedelta(seconds=1),
                shipping_is_smart=True,
                shipping_order_is_smart=True,
            ),
        ])
        db_session.commit()

        assert service._remove_expired_smart_estimates(account.id, 1, as_of=as_of) == 1
        remaining = db_session.execute(text("""
            SELECT order_id
            FROM billing_raw
            WHERE account_id = :account_id AND type = 'SMART'
        """), {"account_id": account.id}).scalars().all()
        assert remaining == [fresh_order_id]
    finally:
        _cleanup(db_session)
