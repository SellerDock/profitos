from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.models.raw_data import BillingRaw


@pytest.mark.contract
def test_recent_orders_smart_only_filters_before_limit(authed_client, seeded_db):
    db = seeded_db["db"]
    account_id = seeded_db["account_id"]
    now = datetime.utcnow().replace(microsecond=0)

    db.add_all([
        BillingRaw(
            tenant_id=1,
            entry_id="contract-billing-smart-2",
            account_id=account_id,
            offer_id="contract-offer-a",
            order_id="contract-order-2",
            type="DPB",
            amount=Decimal("-8.00"),
            currency="PLN",
            occurred_at=now - timedelta(hours=2),
            shipping_is_smart=True,
        ),
        BillingRaw(
            tenant_id=1,
            entry_id="contract-billing-smart-4",
            account_id=account_id,
            offer_id="contract-offer-b",
            order_id="contract-order-4",
            type="HB4",
            amount=Decimal("-6.00"),
            currency="PLN",
            occurred_at=now - timedelta(hours=4),
            shipping_is_smart=True,
        ),
    ])
    db.commit()

    plain_response = authed_client.get("/api/v1/orders/recent?limit=2")
    assert plain_response.status_code == 200, plain_response.text
    assert [order["order_id"] for order in plain_response.json()] == [
        "contract-order-0",
        "contract-order-1",
    ]

    smart_response = authed_client.get("/api/v1/orders/recent?limit=2&smart_only=true")
    assert smart_response.status_code == 200, smart_response.text
    assert [order["order_id"] for order in smart_response.json()] == [
        "contract-order-2",
        "contract-order-4",
    ]
    assert [order["smart_cost"] for order in smart_response.json()] == ["8.00", "6.00"]
