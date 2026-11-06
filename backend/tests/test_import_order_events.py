from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from app.models.account import Account
from app.models.raw_data import AccountImportState, CustomerReturnItemRaw, OrderRaw
from app.models.tenant import Tenant
from app.services.import_service import ImportService


def _cleanup(db):
    db.rollback()
    db.execute(text("DELETE FROM customer_return_items_raw WHERE customer_return_id LIKE 'return-sync-test-%'"))
    db.execute(text("DELETE FROM customer_returns_raw WHERE customer_return_id LIKE 'return-sync-test-%'"))
    db.execute(text("DELETE FROM order_events_raw WHERE event_id LIKE 'event-sync-test-%'"))
    db.execute(text("DELETE FROM account_import_state WHERE account_id IN (SELECT id FROM accounts WHERE allegro_client_id = 'event-sync-test-client')"))
    db.execute(text("DELETE FROM orders_raw WHERE line_item_id LIKE 'event-sync-test-%'"))
    db.execute(text("DELETE FROM accounts WHERE allegro_client_id = 'event-sync-test-client'"))
    db.commit()


def _ensure_tenant(db):
    if db.get(Tenant, 1) is None:
        db.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db.flush()


class _FakeAllegro:
    def __init__(self, events=None, customer_returns=None):
        self._events = events
        self._customer_returns = customer_returns

    def get_order_events(self, account_id, latest_event_id):
        return self._events

    def get_all_customer_returns(self, account_id, date_from, date_to):
        return self._customer_returns


def test_order_events_update_existing_order_statuses(db_session):
    _cleanup(db_session)
    _ensure_tenant(db_session)
    account = Account(
        tenant_id=1,
        name="Order Event Sync",
        allegro_client_id="event-sync-test-client",
        allegro_client_secret="event-sync-test-secret",
        access_token="set",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(AccountImportState(
        account_id=account.id,
        tenant_id=1,
        latest_order_event_id="event-sync-test-cursor",
        latest_order_event_at=datetime.utcnow(),
    ))
    db_session.add_all([
        OrderRaw(
            tenant_id=1,
            line_item_id="event-sync-test-line-1",
            order_id="event-sync-test-order-cancelled",
            account_id=account.id,
            offer_id="event-sync-test-offer-1",
            sku="EVENT-SYNC-1",
            quantity=1,
            unit_price=Decimal("100.00"),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="READY_FOR_PROCESSING",
            bought_at=datetime.utcnow(),
        ),
        OrderRaw(
            tenant_id=1,
            line_item_id="event-sync-test-line-2",
            order_id="event-sync-test-order-ready",
            account_id=account.id,
            offer_id="event-sync-test-offer-2",
            sku="EVENT-SYNC-2",
            quantity=1,
            unit_price=Decimal("50.00"),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="FILLED_IN",
            bought_at=datetime.utcnow(),
        ),
    ])
    db_session.commit()

    events = [
        {
            "id": "event-sync-test-1",
            "type": "BUYER_CANCELLED",
            "occurredAt": "2026-05-08T10:00:00Z",
            "order": {"checkoutForm": {"id": "event-sync-test-order-cancelled", "revision": "1"}},
        },
        {
            "id": "event-sync-test-2",
            "type": "READY_FOR_PROCESSING",
            "occurredAt": "2026-05-08T10:01:00Z",
            "order": {"checkoutForm": {"id": "event-sync-test-order-ready", "revision": "2"}},
        },
    ]
    service = ImportService(db_session)
    service.allegro = _FakeAllegro(events)

    try:
        assert service._sync_order_events(account.id, 1) == 2
        statuses = dict(db_session.execute(
            text("SELECT order_id, status FROM orders_raw WHERE line_item_id LIKE 'event-sync-test-%'")
        ).fetchall())
        assert statuses["event-sync-test-order-cancelled"] == "CANCELLED"
        assert statuses["event-sync-test-order-ready"] == "READY_FOR_PROCESSING"
    finally:
        _cleanup(db_session)


def test_customer_returns_ignore_duplicate_rows_in_same_batch(db_session):
    _cleanup(db_session)
    _ensure_tenant(db_session)
    account = Account(
        tenant_id=1,
        name="Customer Return Sync",
        allegro_client_id="event-sync-test-client",
        allegro_client_secret="event-sync-test-secret",
        access_token="set",
    )
    db_session.add(account)
    db_session.commit()

    duplicate_return = {
        "id": "return-sync-test-1",
        "orderId": "return-sync-test-order",
        "referenceNumber": "RMA-1",
        "buyer": {"login": "buyer", "email": "buyer@example.com"},
        "status": "NEW",
        "marketplaceId": "allegro-pl",
        "isFulfillment": False,
        "createdAt": "2026-05-14T10:00:00Z",
        "items": [
            {
                "offerId": "return-sync-test-offer",
                "name": "Return item",
                "quantity": 1,
                "price": {"amount": "45.00", "currency": "PLN"},
                "reason": {"type": "MISTAKE", "userComment": ""},
            }
        ],
    }
    service = ImportService(db_session)
    service.allegro = _FakeAllegro(customer_returns=[duplicate_return, duplicate_return])

    try:
        assert service._sync_customer_returns(account.id, 1, "2026-05-01T00:00:00Z", "2026-05-14T00:00:00Z") == 1
        items = (
            db_session.query(CustomerReturnItemRaw)
            .filter(CustomerReturnItemRaw.customer_return_id == "return-sync-test-1")
            .all()
        )
        assert len(items) == 1
        assert items[0].offer_id == "return-sync-test-offer"
    finally:
        _cleanup(db_session)
