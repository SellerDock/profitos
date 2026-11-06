"""Isolated, synthetic finance data for dashboard tests."""
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.tenant import TenantScope
from app.models.account import Account
from app.models.raw_data import (
    BillingRaw, CustomerReturnItemRaw, CustomerReturnRaw, OrderRaw,
    PaymentRefundLineItemRaw, PaymentRefundRaw,
)
from app.models.tenant import Tenant
from app.models.user import User


@contextmanager
def finance_data(db):
    tenant = Tenant(name="Finance test", slug=f"finance-{uuid4().hex}")
    db.add(tenant)
    db.flush()
    tenant_id = tenant.id
    try:
        account = Account(tenant_id=tenant_id, name="Test account", allegro_client_id="test", allegro_client_secret="test")
        db.add(account)
        db.flush()
        scope = TenantScope(db, User(id=-1, email="finance@example.test", password_hash="", tenant_id=tenant_id, is_active=True))
        yield scope, account
    finally:
        # Roll back a failed transaction before attempting FK-ordered cleanup.
        db.rollback()
        for model in (CustomerReturnItemRaw, PaymentRefundLineItemRaw, CustomerReturnRaw,
                      PaymentRefundRaw, BillingRaw, OrderRaw, Account):
            db.execute(delete(model).where(model.tenant_id == tenant_id))
        db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        db.commit()


@pytest.fixture
def finance_scope(db_session):
    with finance_data(db_session) as data:
        yield data


def add_order(scope, account, *, price, quantity=1, currency="PLN", bought_at=datetime(2026, 4, 12, 10), status="READY_FOR_PROCESSING", delivery_amount=0):
    order = OrderRaw(tenant_id=scope.tenant_id, account_id=account.id, line_item_id=uuid4().hex,
                     order_id=uuid4().hex, offer_id=uuid4().hex, quantity=quantity, unit_price=price,
                     delivery_amount=delivery_amount, currency=currency, bought_at=bought_at, status=status)
    scope.db.add(order)
    scope.db.flush()
    return order


def add_billing(scope, account, order, *, type, amount, occurred_at=datetime(2026, 4, 12, 10), currency="PLN", shipping_is_smart=None, shipping_order_is_smart=None):
    row = BillingRaw(tenant_id=scope.tenant_id, account_id=account.id, entry_id=uuid4().hex,
                     order_id=order.order_id if order is not None else None, type=type, amount=amount, currency=currency, occurred_at=occurred_at,
                     shipping_is_smart=shipping_is_smart, shipping_order_is_smart=shipping_order_is_smart)
    scope.db.add(row)
    scope.db.flush()
    return row


def add_customer_return(scope, account, order, *, status, with_item=False):
    row = CustomerReturnRaw(customer_return_id=uuid4().hex, tenant_id=scope.tenant_id,
                            account_id=account.id, order_id=order.order_id, status=status)
    scope.db.add(row)
    scope.db.flush()
    if with_item:
        scope.db.add(CustomerReturnItemRaw(tenant_id=scope.tenant_id, customer_return_id=row.customer_return_id,
                                          item_index=0, offer_id=order.offer_id, quantity=order.quantity,
                                          unit_price=order.unit_price, currency=order.currency))
        scope.db.flush()
    return row


def add_payment_refund(scope, account, order, *, amount, status="SUCCESS"):
    row = PaymentRefundRaw(refund_id=uuid4().hex, tenant_id=scope.tenant_id, account_id=account.id,
                           order_id=order.order_id, total_amount=amount, currency="PLN", status=status)
    scope.db.add(row)
    scope.db.flush()
    return row
