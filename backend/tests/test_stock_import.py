from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.security import hash_password
from app.models.account import Account
from app.models.raw_data import OfferCache, StockLevel
from app.models.sku import SkuMaster
from app.models.user import User, UserSession
from app.services.allegro import AllegroService
from app.services.import_service import ImportService


def _xrw() -> dict:
    return {"X-Requested-With": "XMLHttpRequest"}


@pytest.fixture
def stock_import_fixture(app_client, seeded_db):
    db = seeded_db["db"]
    db.execute(text("DELETE FROM stock_levels WHERE sku_id IN (SELECT id FROM sku_masters WHERE sku_key LIKE 'stock-import-%')"))
    db.execute(text("DELETE FROM offers_cache WHERE offer_id LIKE 'stock-import-%'"))
    db.execute(text("DELETE FROM sku_masters WHERE sku_key LIKE 'stock-import-%'"))
    db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'stock-import-%'"))
    db.execute(text("DELETE FROM users WHERE email LIKE 'stock-import-%@example.com'"))
    db.execute(text("DELETE FROM accounts WHERE allegro_client_id LIKE 'stock-import-%'"))
    db.commit()

    account = Account(
        tenant_id=1,
        name="Stock Import Account",
        allegro_client_id="stock-import-client",
        allegro_client_secret="secret",
        access_token="access",
        refresh_token="refresh",
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(account)
    sku = SkuMaster(
        tenant_id=1,
        sku_key="stock-import-sku",
        name="Stock Import SKU",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("0"),
    )
    db.add(sku)
    user = User(
        email="stock-import-user@example.com",
        password_hash=hash_password("CorrectHorseBatteryStaple1!"),
        tenant_id=1,
        is_operator=True,
        is_active=True,
    )
    db.add(user)
    db.flush()
    session = UserSession(id="stock-import-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1))
    db.add(session)
    db.commit()
    app_client.cookies.set("apos_session", session.id)

    try:
        yield {"db": db, "account": account, "sku": sku, "client": app_client}
    finally:
        app_client.cookies.clear()
        db.execute(text("DELETE FROM stock_levels WHERE sku_id IN (SELECT id FROM sku_masters WHERE sku_key LIKE 'stock-import-%')"))
        db.execute(text("DELETE FROM offers_cache WHERE offer_id LIKE 'stock-import-%'"))
        db.execute(text("DELETE FROM sku_masters WHERE sku_key LIKE 'stock-import-%'"))
        db.execute(text("DELETE FROM user_sessions WHERE id LIKE 'stock-import-%'"))
        db.execute(text("DELETE FROM users WHERE email LIKE 'stock-import-%@example.com'"))
        db.execute(text("DELETE FROM accounts WHERE allegro_client_id LIKE 'stock-import-%'"))
        db.commit()


@pytest.mark.contract
def test_allegro_offers_extract_stock_available(monkeypatch, seeded_db):
    account = seeded_db["db"].get(Account, seeded_db["account_id"])
    service = AllegroService(seeded_db["db"])
    monkeypatch.setattr(service, "refresh_token_if_needed", lambda _account_id: account)
    monkeypatch.setattr(service, "_paginate_offset", lambda *_args, **_kwargs: [
        {
            "id": "stock-import-offer-raw",
            "external": {"id": "stock-import-sku"},
            "name": "Stock Import SKU",
            "sellingMode": {"price": {"amount": "19.99", "currency": "PLN"}},
            "stock": {"available": 17, "sold": 3},
        }
    ])
    monkeypatch.setattr(service, "_get_offer_detail_metadata", lambda *_args: (None, None))

    rows = service.get_all_offers(account.id)

    assert rows[0]["stock_available"] == 17


@pytest.mark.contract
def test_sync_offers_imports_stock_levels(monkeypatch, stock_import_fixture):
    db = stock_import_fixture["db"]
    account = stock_import_fixture["account"]
    sku = stock_import_fixture["sku"]
    service = ImportService(db)
    monkeypatch.setattr(service.allegro, "get_all_offers", lambda _account_id: [
        {
            "offer_id": "stock-import-offer-1",
            "sku": sku.sku_key,
            "name": sku.name,
            "price": "10.00",
            "vat_rate": "23",
            "currency": "PLN",
            "ean": None,
            "stock_available": 4,
        },
        {
            "offer_id": "stock-import-offer-2",
            "sku": sku.sku_key,
            "name": sku.name,
            "price": "12.00",
            "vat_rate": "23",
            "currency": "PLN",
            "ean": None,
            "stock_available": 6,
        },
    ])

    count = service._sync_offers(account.id, 1)

    assert count == 2
    offer = db.query(OfferCache).filter_by(offer_id="stock-import-offer-1").one()
    assert offer.stock_available == 4
    level = db.query(StockLevel).filter_by(tenant_id=1, sku_id=sku.id).one()
    assert level.quantity == 10
    assert level.updated_by == "allegro"


@pytest.mark.contract
def test_sync_offers_preserves_ean_when_detail_fetch_temporarily_fails(monkeypatch, stock_import_fixture):
    db = stock_import_fixture["db"]
    account = stock_import_fixture["account"]
    sku = stock_import_fixture["sku"]
    service = ImportService(db)
    row = {
        "offer_id": "stock-import-ean-preserve",
        "sku": sku.sku_key,
        "name": sku.name,
        "price": "10.00",
        "vat_rate": "23",
        "currency": "PLN",
        "ean": "5900000000000",
        "stock_available": 4,
    }
    monkeypatch.setattr(service.allegro, "get_all_offers", lambda _account_id: [row])

    service._sync_offers(account.id, 1)
    row["ean"] = None
    service._sync_offers(account.id, 1)

    db.expire_all()
    offer = db.query(OfferCache).filter_by(offer_id=row["offer_id"]).one()
    assert offer.ean == "5900000000000"


@pytest.mark.contract
def test_stock_auto_import_fetches_allegro_stock(monkeypatch, stock_import_fixture):
    db = stock_import_fixture["db"]
    account = stock_import_fixture["account"]
    sku = stock_import_fixture["sku"]

    def fake_get_all_offers(self, account_id: int):
        if account_id != account.id:
            return []
        return [
            {
                "offer_id": "stock-import-auto-offer",
                "sku": sku.sku_key,
                "name": sku.name,
                "price": "10.00",
                "vat_rate": "23",
                "currency": "PLN",
                "ean": None,
                "stock_available": 9,
            }
        ]

    monkeypatch.setattr("app.services.allegro.AllegroService.get_all_offers", fake_get_all_offers)

    response = stock_import_fixture["client"].post("/api/v1/stock/auto-import", headers=_xrw())

    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1
    db.expire_all()
    level = db.query(StockLevel).filter_by(tenant_id=1, sku_id=sku.id).one()
    assert level.quantity == 9
    assert level.updated_by == "allegro"


@pytest.mark.contract
def test_sync_offers_respects_manual_stock_override(monkeypatch, stock_import_fixture):
    db = stock_import_fixture["db"]
    account = stock_import_fixture["account"]
    sku = stock_import_fixture["sku"]
    db.add(StockLevel(
        tenant_id=1,
        sku_id=sku.id,
        quantity=99,
        updated_by="manual",
        sync_from_allegro=False,
    ))
    db.commit()
    service = ImportService(db)
    monkeypatch.setattr(service.allegro, "get_all_offers", lambda _account_id: [
        {
            "offer_id": "stock-import-manual-offer",
            "sku": sku.sku_key,
            "name": sku.name,
            "price": "10.00",
            "vat_rate": "23",
            "currency": "PLN",
            "ean": None,
            "stock_available": 4,
        },
    ])

    service._sync_offers(account.id, 1)

    db.expire_all()
    level = db.query(StockLevel).filter_by(tenant_id=1, sku_id=sku.id).one()
    assert level.quantity == 99
    assert level.updated_by == "manual"
    assert level.sync_from_allegro is False


@pytest.mark.contract
def test_stock_update_can_disable_allegro_stock_sync(stock_import_fixture):
    db = stock_import_fixture["db"]
    sku = stock_import_fixture["sku"]

    response = stock_import_fixture["client"].put(
        f"/api/v1/stock/{sku.id}",
        json={"quantity": 12, "sync_from_allegro": False},
        headers=_xrw(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["sync_from_allegro"] is False
    db.expire_all()
    level = db.query(StockLevel).filter_by(tenant_id=1, sku_id=sku.id).one()
    assert level.quantity == 12
    assert level.sync_from_allegro is False

    listed = stock_import_fixture["client"].get("/api/v1/stock/", headers=_xrw()).json()
    row = next(item for item in listed if item["sku_id"] == sku.id)
    assert row["sync_from_allegro"] is False
