from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.models.account import Account
from app.models.raw_data import OfferCache, OrderRaw, StockLevel
from app.models.sku import SkuMaster
from app.models.tenant import Tenant


def _cleanup(db):
    db.execute(text("DELETE FROM stock_levels WHERE sku_id IN (SELECT id FROM sku_masters WHERE sku_key LIKE 'filter-view-%')"))
    db.execute(text("DELETE FROM offers_cache WHERE offer_id LIKE 'filter-view-%'"))
    db.execute(text("DELETE FROM orders_raw WHERE line_item_id LIKE 'filter-view-%'"))
    db.execute(text("DELETE FROM sku_masters WHERE sku_key LIKE 'filter-view-%'"))
    db.execute(text("DELETE FROM accounts WHERE allegro_client_id LIKE 'filter-view-%'"))
    db.commit()


def _seed(db):
    _cleanup(db)
    if db.get(Tenant, 1) is None:
        db.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db.flush()

    account_a = Account(
        tenant_id=1,
        name="Filter Account A",
        allegro_client_id="filter-view-a",
        allegro_client_secret="secret",
        access_token="set",
    )
    account_b = Account(
        tenant_id=1,
        name="Filter Account B",
        allegro_client_id="filter-view-b",
        allegro_client_secret="secret",
        access_token="set",
    )
    db.add_all([account_a, account_b])
    db.flush()

    sku_a = SkuMaster(
        tenant_id=1,
        sku_key="filter-view-a",
        name="Filter Product A",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("20"),
    )
    sku_b = SkuMaster(
        tenant_id=1,
        sku_key="filter-view-b",
        name="Filter Product B",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("20"),
    )
    db.add_all([sku_a, sku_b])
    db.flush()

    now = datetime.utcnow().replace(microsecond=0)
    db.add_all([
        OfferCache(
            tenant_id=1,
            account_id=account_a.id,
            offer_id="filter-view-offer-a",
            sku=sku_a.sku_key,
            name=sku_a.name,
            price=Decimal("10.00"),
            stock_available=20,
            currency="PLN",
            synced_at=now,
        ),
        OfferCache(
            tenant_id=1,
            account_id=account_b.id,
            offer_id="filter-view-offer-b",
            sku=sku_b.sku_key,
            name=sku_b.name,
            price=Decimal("10.00"),
            stock_available=30,
            currency="PLN",
            synced_at=now,
        ),
        OrderRaw(
            tenant_id=1,
            account_id=account_a.id,
            line_item_id="filter-view-line-a",
            order_id="filter-view-order-a",
            offer_id="filter-view-offer-a",
            sku=sku_a.sku_key,
            buyer_login="buyer-a",
            quantity=2,
            unit_price=Decimal("10.00"),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="READY_FOR_PROCESSING",
            bought_at=now - timedelta(days=1),
        ),
        OrderRaw(
            tenant_id=1,
            account_id=account_b.id,
            line_item_id="filter-view-line-b",
            order_id="filter-view-order-b",
            offer_id="filter-view-offer-b",
            sku=sku_b.sku_key,
            buyer_login="buyer-b",
            quantity=5,
            unit_price=Decimal("10.00"),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="READY_FOR_PROCESSING",
            bought_at=now - timedelta(days=1),
        ),
        StockLevel(
            tenant_id=1,
            sku_id=sku_a.id,
            quantity=20,
            updated_by="auto",
            updated_at=now,
            sync_from_allegro=True,
        ),
        StockLevel(
            tenant_id=1,
            sku_id=sku_b.id,
            quantity=30,
            updated_by="auto",
            updated_at=now,
            sync_from_allegro=True,
        ),
    ])
    db.commit()
    return account_a, account_b


def test_products_can_be_filtered_by_account(authed_client, db_session):
    account_a, account_b = _seed(db_session)
    try:
        all_response = authed_client.get("/api/v1/products/")
        account_response = authed_client.get(f"/api/v1/products/?account_id={account_a.id}")
        other_response = authed_client.get(f"/api/v1/products/?account_id={account_b.id}")

        assert all_response.status_code == 200
        assert account_response.status_code == 200
        assert other_response.status_code == 200
        assert {"filter-view-a", "filter-view-b"}.issubset({row["sku_key"] for row in all_response.json()})
        assert [row["sku_key"] for row in account_response.json()] == ["filter-view-a"]
        assert [row["sku_key"] for row in other_response.json()] == ["filter-view-b"]
    finally:
        _cleanup(db_session)


def test_stock_sales_can_be_filtered_by_account(authed_client, db_session):
    account_a, account_b = _seed(db_session)
    try:
        account_response = authed_client.get(f"/api/v1/stock/?account_id={account_a.id}")
        other_response = authed_client.get(f"/api/v1/stock/?account_id={account_b.id}")

        assert account_response.status_code == 200
        assert other_response.status_code == 200
        account_rows = {row["sku_key"]: row for row in account_response.json()}
        other_rows = {row["sku_key"]: row for row in other_response.json()}
        assert set(account_rows) == {"filter-view-a"}
        assert account_rows["filter-view-a"]["sold_15d"] == 2
        assert set(other_rows) == {"filter-view-b"}
        assert other_rows["filter-view-b"]["sold_15d"] == 5
    finally:
        _cleanup(db_session)
