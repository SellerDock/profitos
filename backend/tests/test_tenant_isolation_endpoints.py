from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.main import app
from app.models.account import Account
from app.models.raw_data import AllegroAdsImport, BillingRaw, OfferCache, OrderRaw
from app.models.sku import EncryptedSkuCost, FinancialVault, SkuAlias, SkuMaster
from app.models.tenant import Tenant
from app.models.user import User, UserSession


@dataclass
class TenantIsolationFixture:
    client_t1: TestClient
    client_t2: TestClient
    db: object
    t1_account_id: int
    t2_account_id: int
    t1_sku_id: int
    t2_sku_id: int
    t1_sku_key: str
    t2_sku_key: str
    t1_alias_id: int
    t2_alias_id: int
    t1_order_ids: set[str]
    t2_order_ids: set[str]
    t1_revenue: Decimal
    t2_revenue: Decimal


@pytest.fixture
def two_tenants(db_session):
    suffix = uuid4().hex[:8]

    def cleanup() -> None:
        db_session.execute(text("DELETE FROM user_sessions WHERE id LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM allegro_ads_imports WHERE imported_filename LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM billing_raw WHERE entry_id LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM orders_raw WHERE line_item_id LIKE :p OR order_id LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM offers_cache WHERE offer_id LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM sku_aliases WHERE raw_name LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(
            text(
                "DELETE FROM encrypted_sku_costs WHERE sku_master_id IN "
                "(SELECT id FROM sku_masters WHERE sku_key LIKE :p)"
            ),
            {"p": f"tenant-iso-{suffix}-%"},
        )
        db_session.execute(
            text(
                "DELETE FROM encrypted_sku_cost_history WHERE sku_master_id IN "
                "(SELECT id FROM sku_masters WHERE sku_key LIKE :p)"
            ),
            {"p": f"tenant-iso-{suffix}-%"},
        )
        db_session.execute(text("DELETE FROM sku_masters WHERE sku_key LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM financial_vaults WHERE scope LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM accounts WHERE allegro_client_id LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.execute(text("DELETE FROM tenants WHERE slug LIKE :p"), {"p": f"tenant-iso-{suffix}-%"})
        db_session.commit()

    cleanup()

    if db_session.get(Tenant, 1) is None:
        db_session.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db_session.flush()

    t2 = Tenant(name="Customer A", slug=f"tenant-iso-{suffix}-customer-a", is_active=True)
    db_session.add(t2)
    db_session.flush()

    account1 = Account(
        tenant_id=1,
        name=f"Tenant 1 {suffix}",
        allegro_client_id=f"tenant-iso-{suffix}-client-1",
        allegro_client_secret="secret",
    )
    account2 = Account(
        tenant_id=t2.id,
        name=f"Tenant 2 {suffix}",
        allegro_client_id=f"tenant-iso-{suffix}-client-2",
        allegro_client_secret="secret",
    )
    db_session.add_all([account1, account2])
    db_session.flush()

    sku1 = SkuMaster(
        tenant_id=1,
        sku_key=f"tenant-iso-{suffix}-sku-1",
        name="Tenant 1 SKU",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("0"),
    )
    sku2 = SkuMaster(
        tenant_id=t2.id,
        sku_key=f"tenant-iso-{suffix}-sku-2",
        name="Tenant 2 SKU",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("0"),
    )
    db_session.add_all([sku1, sku2])
    db_session.flush()

    vault1 = FinancialVault(
        tenant_id=1,
        scope=f"tenant-iso-{suffix}-global-1",
        kdf="argon2id",
        salt="MDEyMzQ1Njc4OWFiY2RlZg==",
        memory_cost=131072,
        time_cost=4,
        parallelism=1,
        verify_nonce="MDEyMzQ1Njc4OWFi",
        verify_ciphertext="Y2lwaGVydGV4dC10YWc=",
        key_version=1,
    )
    vault2 = FinancialVault(
        tenant_id=t2.id,
        scope=f"tenant-iso-{suffix}-global-2",
        kdf="argon2id",
        salt="MDEyMzQ1Njc4OWFiY2RlZg==",
        memory_cost=131072,
        time_cost=4,
        parallelism=1,
        verify_nonce="MDEyMzQ1Njc4OWFi",
        verify_ciphertext="Y2lwaGVydGV4dC10YWc=",
        key_version=1,
    )
    db_session.add_all([vault1, vault2])
    db_session.flush()

    db_session.add_all([
        SkuAlias(
            tenant_id=1,
            sku_master_id=sku1.id,
            account_id=account1.id,
            raw_name=f"tenant-iso-{suffix}-alias-1",
            multiplier=Decimal("1.0"),
        ),
        SkuAlias(
            tenant_id=t2.id,
            sku_master_id=sku2.id,
            account_id=account2.id,
            raw_name=f"tenant-iso-{suffix}-alias-2",
            multiplier=Decimal("1.0"),
        ),
        EncryptedSkuCost(
            tenant_id=1,
            sku_master_id=sku1.id,
            vault_id=vault1.id,
            ciphertext="Y29zdDEtdGFn",
            nonce="MDEyMzQ1Njc4OWFi",
            key_version=1,
            aad_context=f"profitos:sku-cost:{sku1.id}:current:v1",
        ),
        EncryptedSkuCost(
            tenant_id=t2.id,
            sku_master_id=sku2.id,
            vault_id=vault2.id,
            ciphertext="Y29zdDItdGFn",
            nonce="MDEyMzQ1Njc4OWFi",
            key_version=1,
            aad_context=f"profitos:sku-cost:{sku2.id}:current:v1",
        ),
    ])
    db_session.flush()
    alias1 = (
        db_session.query(SkuAlias)
        .filter(SkuAlias.raw_name == f"tenant-iso-{suffix}-alias-1")
        .one()
    )
    alias2 = (
        db_session.query(SkuAlias)
        .filter(SkuAlias.raw_name == f"tenant-iso-{suffix}-alias-2")
        .one()
    )

    now = datetime.utcnow().replace(microsecond=0)
    t1_order_ids: set[str] = set()
    t2_order_ids: set[str] = set()
    t1_revenue = Decimal("0")
    t2_revenue = Decimal("0")
    for tenant_id, account, sku, amount, target_set in [
        (1, account1, sku1, Decimal("100.00"), t1_order_ids),
        (t2.id, account2, sku2, Decimal("999.00"), t2_order_ids),
    ]:
        offer_id = f"tenant-iso-{suffix}-offer-{tenant_id}"
        db_session.add(OfferCache(
            tenant_id=tenant_id,
            offer_id=offer_id,
            account_id=account.id,
            sku=sku.sku_key,
            name=f"Tenant {tenant_id} Offer",
            price=amount,
            currency="PLN",
            synced_at=now,
        ))
        for idx in range(5):
            order_id = f"tenant-iso-{suffix}-order-{tenant_id}-{idx}"
            target_set.add(order_id)
            db_session.add(OrderRaw(
                tenant_id=tenant_id,
                line_item_id=f"tenant-iso-{suffix}-line-{tenant_id}-{idx}",
                order_id=order_id,
                account_id=account.id,
                offer_id=offer_id,
                sku=sku.sku_key,
                buyer_login=f"buyer-{tenant_id}-{idx}",
                quantity=1,
                unit_price=amount,
                delivery_amount=Decimal("0.00"),
                currency="PLN",
                status="READY_FOR_PROCESSING",
                bought_at=now - timedelta(days=idx),
            ))
            db_session.add(BillingRaw(
                tenant_id=tenant_id,
                entry_id=f"tenant-iso-{suffix}-billing-{tenant_id}-{idx}",
                account_id=account.id,
                offer_id=offer_id,
                order_id=order_id,
                type="SUC",
                amount=Decimal("-5.00"),
                currency="PLN",
                occurred_at=now - timedelta(days=idx),
            ))
        if tenant_id == 1:
            t1_revenue += amount * 5
        else:
            t2_revenue += amount * 5
        db_session.add(AllegroAdsImport(
            tenant_id=tenant_id,
            account_id=account.id,
            offer_id=offer_id,
            campaign_name=f"Tenant {tenant_id} Campaign",
            ad_date=date.today(),
            impressions=10,
            clicks=2,
            interest=1,
            cpc=Decimal("1.0000"),
            ctr=Decimal("0.1000"),
            cost=Decimal("2.00"),
            roas=Decimal("10.00"),
            units_sold_via_ad=1,
            sales_value=amount,
            imported_filename=f"tenant-iso-{suffix}-{tenant_id}.csv",
        ))

    user1 = User(
        email=f"tenant-iso-{suffix}-1@example.com",
        password_hash="hash",
        tenant_id=1,
        is_operator=True,
        is_active=True,
    )
    user2 = User(
        email=f"tenant-iso-{suffix}-2@example.com",
        password_hash="hash",
        tenant_id=t2.id,
        is_operator=True,
        is_active=True,
    )
    db_session.add_all([user1, user2])
    db_session.flush()

    token1 = f"tenant-iso-{suffix}-session-1"
    token2 = f"tenant-iso-{suffix}-session-2"
    db_session.add_all([
        UserSession(id=token1, user_id=user1.id, expires_at=now + timedelta(days=1)),
        UserSession(id=token2, user_id=user2.id, expires_at=now + timedelta(days=1)),
    ])
    db_session.commit()

    client1 = TestClient(app)
    client2 = TestClient(app)
    # Mutating requests need the CSRF header (see require_api_auth in app/main.py).
    client1.headers.update({"X-Requested-With": "XMLHttpRequest"})
    client2.headers.update({"X-Requested-With": "XMLHttpRequest"})
    client1.cookies.set("apos_session", token1)
    client2.cookies.set("apos_session", token2)

    try:
        yield TenantIsolationFixture(
            client_t1=client1,
            client_t2=client2,
            db=db_session,
            t1_account_id=account1.id,
            t2_account_id=account2.id,
            t1_sku_id=sku1.id,
            t2_sku_id=sku2.id,
            t1_sku_key=sku1.sku_key,
            t2_sku_key=sku2.sku_key,
            t1_alias_id=alias1.id,
            t2_alias_id=alias2.id,
            t1_order_ids=t1_order_ids,
            t2_order_ids=t2_order_ids,
            t1_revenue=t1_revenue,
            t2_revenue=t2_revenue,
        )
    finally:
        client1.close()
        client2.close()
        cleanup()


@pytest.mark.contract
def test_accounts_list_only_returns_own_tenant(two_tenants):
    ids_1 = {a["id"] for a in two_tenants.client_t1.get("/api/v1/accounts/").json()}
    ids_2 = {a["id"] for a in two_tenants.client_t2.get("/api/v1/accounts/").json()}
    assert two_tenants.t1_account_id in ids_1
    assert two_tenants.t2_account_id in ids_2
    assert ids_1.isdisjoint(ids_2)


@pytest.mark.contract
def test_account_detail_404_for_foreign_tenant(two_tenants):
    response = two_tenants.client_t1.get(f"/api/v1/accounts/{two_tenants.t2_account_id}")
    assert response.status_code == 404


@pytest.mark.contract
def test_patch_foreign_account_returns_404_and_does_not_modify(two_tenants):
    response = two_tenants.client_t1.patch(
        f"/api/v1/accounts/{two_tenants.t2_account_id}",
        json={"name": "pwned"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404
    original = two_tenants.client_t2.get(f"/api/v1/accounts/{two_tenants.t2_account_id}")
    assert original.status_code == 200
    assert original.json()["name"] != "pwned"


@pytest.mark.contract
def test_sku_master_404_for_foreign_tenant(two_tenants):
    response = two_tenants.client_t1.get(f"/api/v1/sku-masters/{two_tenants.t2_sku_id}")
    assert response.status_code == 404


@pytest.mark.contract
def test_products_list_only_returns_own_tenant(two_tenants):
    rows = two_tenants.client_t1.get("/api/v1/products/").json()
    ids = {row["id"] for row in rows}
    assert two_tenants.t1_sku_id in ids
    assert two_tenants.t2_sku_id not in ids


@pytest.mark.contract
def test_orders_recent_only_own_tenant(two_tenants):
    response = two_tenants.client_t1.get("/api/v1/orders/recent")
    assert response.status_code == 200, response.text
    orders = response.json()
    returned = {o["order_id"] for o in orders if o["order_id"].startswith("tenant-iso-")}
    assert returned <= two_tenants.t1_order_ids
    assert returned.isdisjoint(two_tenants.t2_order_ids)


@pytest.mark.contract
def test_encrypted_cost_export_404_for_foreign_sku(two_tenants):
    response = two_tenants.client_t1.get(
        f"/api/v1/security/encrypted-cost-export/{two_tenants.t2_sku_id}"
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_dashboard_summary_does_not_aggregate_foreign_orders(two_tenants):
    response = two_tenants.client_t1.get(
        f"/api/v1/dashboard/summary?period=last_30d&account_id={two_tenants.t1_account_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["sales_gross_value"]) == two_tenants.t1_revenue
    assert Decimal(body["sales_gross_value"]) != two_tenants.t1_revenue + two_tenants.t2_revenue


@pytest.mark.contract
@pytest.mark.parametrize("endpoint", [
    "/api/v1/dashboard/summary?period=last_30d&account_id={account_id}",
    "/api/v1/dashboard/summary/all?account_id={account_id}",
    "/api/v1/dashboard/summary/comparisons?account_id={account_id}",
    "/api/v1/dashboard/products?period=last_30d&account_id={account_id}",
])
def test_dashboard_account_scoped_endpoints_404_for_foreign_account(two_tenants, endpoint):
    response = two_tenants.client_t1.get(endpoint.format(account_id=two_tenants.t2_account_id))
    assert response.status_code == 404


@pytest.mark.contract
def test_dashboard_product_detail_404_for_foreign_sku(two_tenants):
    response = two_tenants.client_t1.get(
        f"/api/v1/dashboard/product-detail?period=last_30d&sku_key={two_tenants.t2_sku_key}"
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_dashboard_products_only_returns_own_tenant_sku(two_tenants):
    response = two_tenants.client_t1.get("/api/v1/dashboard/products?period=last_30d")
    assert response.status_code == 200, response.text
    sku_keys = {row["sku_key"] for row in response.json()}
    assert two_tenants.t1_sku_key in sku_keys
    assert two_tenants.t2_sku_key not in sku_keys


@pytest.mark.contract
def test_patch_foreign_sku_master_returns_404(two_tenants):
    response = two_tenants.client_t1.patch(
        f"/api/v1/sku-masters/{two_tenants.t2_sku_id}",
        json={"name": "pwned"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404
    original = two_tenants.client_t2.get(f"/api/v1/sku-masters/{two_tenants.t2_sku_id}")
    assert original.status_code == 200
    assert original.json()["name"] != "pwned"


@pytest.mark.contract
def test_delete_foreign_sku_master_returns_404(two_tenants):
    response = two_tenants.client_t1.delete(
        f"/api/v1/sku-masters/{two_tenants.t2_sku_id}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404
    assert two_tenants.client_t2.get(f"/api/v1/sku-masters/{two_tenants.t2_sku_id}").status_code == 200


@pytest.mark.contract
def test_sku_alias_list_only_returns_own_tenant(two_tenants):
    response = two_tenants.client_t1.get("/api/v1/sku-aliases/")
    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()}
    assert two_tenants.t1_alias_id in ids
    assert two_tenants.t2_alias_id not in ids


@pytest.mark.contract
def test_create_sku_alias_with_foreign_sku_returns_404(two_tenants):
    response = two_tenants.client_t1.post(
        "/api/v1/sku-aliases/",
        json={
            "sku_master_id": two_tenants.t2_sku_id,
            "account_id": two_tenants.t1_account_id,
            "raw_name": "foreign-sku-alias",
            "multiplier": "1.0",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_create_sku_alias_with_foreign_account_returns_404(two_tenants):
    response = two_tenants.client_t1.post(
        "/api/v1/sku-aliases/",
        json={
            "sku_master_id": two_tenants.t1_sku_id,
            "account_id": two_tenants.t2_account_id,
            "raw_name": "foreign-account-alias",
            "multiplier": "1.0",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_patch_foreign_product_returns_404(two_tenants):
    response = two_tenants.client_t1.patch(
        f"/api/v1/products/{two_tenants.t2_sku_id}",
        json={"name": "pwned"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_stock_update_foreign_sku_returns_404(two_tenants):
    response = two_tenants.client_t1.put(
        f"/api/v1/stock/{two_tenants.t2_sku_id}",
        json={"quantity": 99},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_ads_import_list_foreign_account_returns_404(two_tenants):
    response = two_tenants.client_t1.get(f"/api/v1/ads-import/{two_tenants.t2_account_id}/list")
    assert response.status_code == 404


@pytest.mark.contract
def test_ads_import_delete_foreign_account_returns_404(two_tenants):
    response = two_tenants.client_t1.delete(
        f"/api/v1/ads-import/{two_tenants.t2_account_id}?date_from=2026-05-01&date_to=2026-05-04",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_import_sync_foreign_account_returns_404(two_tenants):
    response = two_tenants.client_t1.post(
        f"/api/v1/import/sync/{two_tenants.t2_account_id}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404


@pytest.mark.contract
def test_delete_foreign_account_preserves_database_row(two_tenants):
    account_id = two_tenants.t2_account_id
    response = two_tenants.client_t1.delete(
        f"/api/v1/accounts/{account_id}",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 404
    two_tenants.db.expire_all()
    assert two_tenants.db.get(Account, account_id) is not None


@pytest.mark.contract
@pytest.mark.parametrize("endpoint", [
    "/api/v1/allegro/auth/{account_id}",
    "/api/v1/allegro/orders/{account_id}?date_from=2026-01-01&date_to=2026-01-31",
    "/api/v1/allegro/billing/{account_id}?date_from=2026-01-01&date_to=2026-01-31",
    "/api/v1/allegro/offers/{account_id}",
])
def test_allegro_foreign_account_rejected_before_service(two_tenants, monkeypatch, endpoint):
    from app.api import allegro

    def unexpected_service(*args, **kwargs):
        pytest.fail("Allegro service must not be called for a foreign account")

    monkeypatch.setattr(allegro, "AllegroService", unexpected_service)
    response = two_tenants.client_t1.get(endpoint.format(account_id=two_tenants.t2_account_id))
    assert response.status_code == 404


@pytest.mark.contract
def test_stock_foreign_account_rejected(two_tenants):
    response = two_tenants.client_t1.get(
        "/api/v1/stock/", params={"account_id": two_tenants.t2_account_id}
    )
    assert response.status_code == 404


@pytest.mark.contract
@pytest.mark.parametrize("smart_only", ["true", "false"])
def test_recent_orders_foreign_account_returns_no_orders(two_tenants, smart_only):
    response = two_tenants.client_t1.get(
        "/api/v1/orders/recent",
        params={"account_id": two_tenants.t2_account_id, "smart_only": smart_only},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.contract
def test_create_account_belongs_to_current_tenant(two_tenants):
    db = two_tenants.db
    foreign = db.get(Account, two_tenants.t1_account_id)
    before = (foreign.name, foreign.allegro_client_id, foreign.tenant_id)
    client_id = foreign.allegro_client_id + '-new'
    response = two_tenants.client_t2.post('/api/v1/accounts/', json={
        'name': 'New account', 'allegro_client_id': client_id, 'allegro_client_secret': 'secret',
    })
    assert response.status_code == 201
    db.expire_all()
    created = db.get(Account, response.json()['id'])
    assert created.tenant_id == db.get(Account, two_tenants.t2_account_id).tenant_id
    foreign = db.get(Account, two_tenants.t1_account_id)
    assert (foreign.name, foreign.allegro_client_id, foreign.tenant_id) == before


@pytest.mark.contract
def test_sku_masters_list_only_current_tenant(two_tenants):
    response = two_tenants.client_t2.get('/api/v1/sku-masters/')
    assert response.status_code == 200
    ids = {row['id'] for row in response.json()}
    assert two_tenants.t2_sku_id in ids
    assert two_tenants.t1_sku_id not in ids


@pytest.mark.contract
def test_create_sku_master_belongs_to_current_tenant(two_tenants):
    db = two_tenants.db
    foreign = db.get(SkuMaster, two_tenants.t1_sku_id)
    before = (foreign.name, foreign.sku_key, foreign.tenant_id)
    response = two_tenants.client_t2.post('/api/v1/sku-masters/', json={
        'sku_key': two_tenants.t1_sku_key + '-new', 'name': 'New SKU',
    })
    assert response.status_code == 201
    db.expire_all()
    assert db.get(SkuMaster, response.json()['id']).tenant_id == db.get(Account, two_tenants.t2_account_id).tenant_id
    foreign = db.get(SkuMaster, two_tenants.t1_sku_id)
    assert (foreign.name, foreign.sku_key, foreign.tenant_id) == before


@pytest.mark.contract
@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_foreign_sku_alias_rejected_and_unchanged(two_tenants, method):
    db = two_tenants.db
    alias = db.get(SkuAlias, two_tenants.t1_alias_id)
    before = (alias.tenant_id, alias.sku_master_id, alias.account_id, alias.raw_name, alias.multiplier)
    kwargs = {'json': {'raw_name': 'changed'}} if method == 'patch' else {}
    response = getattr(two_tenants.client_t2, method)(f'/api/v1/sku-aliases/{alias.id}', **kwargs)
    assert response.status_code == 404
    db.expire_all()
    alias = db.get(SkuAlias, two_tenants.t1_alias_id)
    assert alias is not None
    assert (alias.tenant_id, alias.sku_master_id, alias.account_id, alias.raw_name, alias.multiplier) == before


@pytest.mark.contract
def test_ads_upload_foreign_account_rejected_and_unchanged(two_tenants):
    db = two_tenants.db
    account_id = two_tenants.t1_account_id
    before = [(row.id, row.cost) for row in db.query(AllegroAdsImport).filter_by(account_id=account_id).order_by(AllegroAdsImport.id)]
    response = two_tenants.client_t2.post(f'/api/v1/ads-import/{account_id}', files={'file': ('ads.csv', b'header\nvalue\n', 'text/csv')})
    assert response.status_code == 404
    db.expire_all()
    assert [(row.id, row.cost) for row in db.query(AllegroAdsImport).filter_by(account_id=account_id).order_by(AllegroAdsImport.id)] == before


@pytest.mark.contract
def test_allegro_auth_state_uses_current_tenant(two_tenants, monkeypatch):
    from app.api import allegro

    states = []

    def auth_url(self, redirect_uri, state):
        states.append(allegro._decode_oauth_state(state))
        return 'https://example.com/consent'

    monkeypatch.setattr(allegro.AllegroService, 'get_auth_url', auth_url)
    response = two_tenants.client_t2.get('/api/v1/allegro/auth', follow_redirects=False)
    assert response.status_code in (302, 307)
    assert len(states) == 1
    assert states[0]['tenant_id'] == two_tenants.db.get(Account, two_tenants.t2_account_id).tenant_id
    assert 'account_id' not in states[0]


@pytest.mark.contract
@pytest.mark.parametrize(('path', 'payload_a', 'payload_b'), [
    ('/api/v1/app-settings/', {'is_vat_payer': True}, {'is_vat_payer': False}),
    ('/api/v1/stock/settings', {'threshold_critical': 11, 'threshold_warning': 22}, {'threshold_critical': 3, 'threshold_warning': 8}),
])
def test_settings_read_and_write_are_tenant_scoped(two_tenants, path, payload_a, payload_b):
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t1_account_id).tenant_id
    tenant_b = db.get(Account, two_tenants.t2_account_id).tenant_id
    keys = list(payload_a)
    saved = db.execute(text('SELECT tenant_id, key, value FROM stock_settings WHERE tenant_id IN :tenants AND key IN :keys').bindparams(
        bindparam('tenants', expanding=True), bindparam('keys', expanding=True)),
        {'tenants': [tenant_a, tenant_b], 'keys': keys}).fetchall()
    try:
        assert two_tenants.client_t1.put(path, json=payload_a).status_code == 200
        assert two_tenants.client_t2.put(path, json=payload_b).status_code == 200
        for client, expected in [(two_tenants.client_t1, payload_a), (two_tenants.client_t2, payload_b)]:
            response = client.get(path)
            assert response.status_code == 200
            assert all(response.json()[key] == value for key, value in expected.items())
        db.expire_all()
        rows = db.execute(text('SELECT key, value FROM stock_settings WHERE tenant_id = :tenant'), {'tenant': tenant_a}).all()
        assert all(dict(rows)[key] == value for key, value in payload_a.items())
    finally:
        for tenant in (tenant_a, tenant_b):
            for key in keys:
                db.execute(text('DELETE FROM stock_settings WHERE tenant_id = :tenant AND key = :key'), {'tenant': tenant, 'key': key})
        for tenant, key, value in saved:
            db.execute(text('INSERT INTO stock_settings (tenant_id, key, value) VALUES (:tenant, :key, :value)'), {'tenant': tenant, 'key': key, 'value': value})
        db.commit()


@pytest.mark.contract
def test_stock_auto_import_only_current_tenant(two_tenants, monkeypatch):
    from app.api import stock
    from app.models.raw_data import StockLevel

    db = two_tenants.db
    account_b = db.get(Account, two_tenants.t2_account_id)
    account_a = db.get(Account, two_tenants.t1_account_id)
    account_a.access_token = account_b.access_token = 'test-token'
    db.add(StockLevel(tenant_id=account_a.tenant_id, sku_id=two_tenants.t1_sku_id, quantity=17, updated_by='manual'))
    db.commit()
    calls = []
    monkeypatch.setattr(stock.ImportService, 'sync_offers_only', lambda self, account_id: calls.append(account_id) or 0)
    try:
        response = two_tenants.client_t2.post('/api/v1/stock/auto-import')
        assert response.status_code == 200
        assert calls == [two_tenants.t2_account_id]
        db.expire_all()
        foreign_stock = db.query(StockLevel).filter_by(sku_id=two_tenants.t1_sku_id).one()
        assert (foreign_stock.tenant_id, foreign_stock.quantity, foreign_stock.updated_by) == (account_a.tenant_id, 17, 'manual')
        row = db.query(StockLevel).filter_by(sku_id=two_tenants.t2_sku_id).one()
        assert row.tenant_id == account_b.tenant_id
    finally:
        db.query(StockLevel).filter(StockLevel.sku_id.in_([two_tenants.t1_sku_id, two_tenants.t2_sku_id])).delete(synchronize_session=False)
        db.commit()


@pytest.mark.contract
def test_import_status_only_current_tenant(two_tenants):
    db = two_tenants.db
    for account_id in (two_tenants.t1_account_id, two_tenants.t2_account_id):
        db.get(Account, account_id).access_token = 'test-token'
    db.commit()
    response = two_tenants.client_t2.get('/api/v1/import/status')
    assert response.status_code == 200
    ids = {row['account_id'] for row in response.json()}
    assert two_tenants.t2_account_id in ids
    assert two_tenants.t1_account_id not in ids


@pytest.mark.contract
def test_sku_auto_import_foreign_account_rejected(two_tenants, monkeypatch):
    from app.api import products

    def unexpected(*args, **kwargs):
        pytest.fail('Import must not run for a foreign account')

    monkeypatch.setattr(products, 'auto_import_from_offers', unexpected)
    monkeypatch.setattr(products, 'auto_import_from_orders', unexpected)
    db = two_tenants.db
    foreign = db.get(Account, two_tenants.t1_account_id)
    tenant_id = foreign.tenant_id
    before = [(row.id, row.sku_key, row.name) for row in db.query(SkuMaster).filter_by(tenant_id=tenant_id).order_by(SkuMaster.id)]
    response = two_tenants.client_t2.post(f'/api/v1/sku/auto-import/{foreign.id}')
    assert response.status_code == 404
    db.expire_all()
    assert [(row.id, row.sku_key, row.name) for row in db.query(SkuMaster).filter_by(tenant_id=tenant_id).order_by(SkuMaster.id)] == before


@pytest.mark.contract
def test_unmatched_offers_only_current_tenant(two_tenants, monkeypatch):
    from app.api import sku_mapping

    monkeypatch.setattr(sku_mapping, 'load_patterns', lambda db, tenant_id: [])
    response = two_tenants.client_t2.get('/api/v1/sku-mapping/unmatched-offers', params={'limit': 500})
    assert response.status_code == 200
    keys = {row['sku'] for row in response.json()}
    assert two_tenants.t2_sku_key in keys
    assert two_tenants.t1_sku_key not in keys


@pytest.mark.contract
def test_billing_profile_read_write_is_tenant_scoped(two_tenants, monkeypatch):
    from app.core.config import settings
    from app.models.billing_profile import TenantBillingProfile

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t1_account_id).tenant_id
    tenant_b = db.get(Account, two_tenants.t2_account_id).tenant_id
    profile = db.query(TenantBillingProfile).filter_by(tenant_id=tenant_a).first()
    created = profile is None
    if created:
        profile = TenantBillingProfile(tenant_id=tenant_a, company_name='Firma A')
        db.add(profile)
    previous = profile.company_name
    profile.company_name = 'Firma izolowana A'
    db.commit()
    try:
        response = two_tenants.client_t2.get('/api/v1/billing/profile')
        assert response.status_code == 200
        assert response.json()['company_name'] != 'Firma izolowana A'
        response = two_tenants.client_t2.put('/api/v1/billing/profile', json={'company_name': 'Firma B'})
        assert response.status_code == 200
        assert response.json()['company_name'] == 'Firma B'
        db.expire_all()
        assert db.query(TenantBillingProfile).filter_by(tenant_id=tenant_a).one().company_name == 'Firma izolowana A'
    finally:
        db.query(TenantBillingProfile).filter_by(tenant_id=tenant_b).delete()
        profile = db.query(TenantBillingProfile).filter_by(tenant_id=tenant_a).one()
        if created:
            db.delete(profile)
        else:
            profile.company_name = previous
        db.commit()


@pytest.mark.contract
def test_billing_vat_lookup_does_not_modify_foreign_profile(two_tenants, monkeypatch):
    from app.api import billing
    from app.core.config import settings
    from app.models.billing_profile import TenantBillingProfile

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'result': {'subject': {'name': 'VAT result', 'nip': '1234567890'}}}
    monkeypatch.setattr(billing.httpx, 'get', lambda *args, **kwargs: Response())
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t2_account_id).tenant_id
    profile = TenantBillingProfile(tenant_id=tenant_a, company_name='Foreign VAT profile')
    db.add(profile)
    db.commit()
    try:
        response = two_tenants.client_t1.get('/api/v1/billing/vat-lookup/1234567890')
        assert response.status_code == 200
        assert response.json()['company_name'] == 'VAT result'
        db.expire_all()
        assert db.query(TenantBillingProfile).filter_by(tenant_id=tenant_a).one().company_name == 'Foreign VAT profile'
    finally:
        db.query(TenantBillingProfile).filter_by(tenant_id=tenant_a).delete()
        db.commit()


@pytest.mark.contract
def test_subscription_excludes_foreign_invoice(two_tenants, monkeypatch):
    from app.core.config import settings
    from app.models.billing_profile import TenantInvoice

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t2_account_id).tenant_id
    number = 'isolation-' + uuid4().hex
    invoice = TenantInvoice(tenant_id=tenant_a, number=number, period_month=date.today().replace(day=1))
    db.add(invoice)
    db.commit()
    try:
        response = two_tenants.client_t1.get('/api/v1/billing/subscription')
        assert response.status_code == 200
        assert number not in [item['number'] for item in response.json()['invoices']]
    finally:
        db.query(TenantInvoice).filter_by(number=number).delete()
        db.commit()


@pytest.mark.contract
def test_paid_plan_acceptance_is_tenant_scoped(two_tenants, monkeypatch):
    from app.core.config import settings
    from app.models.billing_profile import TenantPaidPlanAcceptance

    monkeypatch.setattr(settings, 'DEPLOYMENT_MODE', 'hosted')
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t1_account_id).tenant_id
    tenant_b = db.get(Account, two_tenants.t2_account_id).tenant_id
    version = uuid4().hex[:24]
    try:
        payload = {'terms_accepted': True, 'terms_version': version}
        assert two_tenants.client_t1.post('/api/v1/billing/paid-plan/accept', json=payload).status_code == 200
        original = db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_a, terms_version=version).one()
        original_id = original.id
        assert two_tenants.client_t2.post('/api/v1/billing/paid-plan/accept', json=payload).status_code == 200
        db.expire_all()
        assert db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_a, terms_version=version).one().id == original_id
        assert db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=tenant_b, terms_version=version).one().id != original_id
    finally:
        db.query(TenantPaidPlanAcceptance).filter_by(terms_version=version).delete()
        db.commit()


@pytest.mark.contract
def test_profit_by_ean_rejects_foreign_account(two_tenants, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'VAULT_SERVER_DECRYPTION_ENABLED', True)
    db = two_tenants.db
    account = db.get(Account, two_tenants.t1_account_id)
    name = account.name
    response = two_tenants.client_t2.post('/api/v1/integrations/profit-by-ean', json={
        'account_id': account.id, 'eans': ['12345678'], 'vault_code': 'test',
    })
    assert response.status_code == 404
    db.expire_all()
    assert db.get(Account, two_tenants.t1_account_id).name == name


@pytest.mark.contract
def test_add_cost_history_rejects_foreign_sku(two_tenants):
    from app.models.sku import EncryptedSkuCostHistory
    db = two_tenants.db
    sku_id = two_tenants.t1_sku_id
    before = db.query(EncryptedSkuCostHistory).filter_by(sku_master_id=sku_id).count()
    encrypted = {'ciphertext': 'test', 'nonce': 'test', 'key_version': 1, 'aad_context': 'test'}
    response = two_tenants.client_t2.post(f'/api/v1/products/{sku_id}/cost-history', json={
        'encrypted_cost': encrypted, 'current_encrypted_cost': encrypted, 'valid_from': '2026-01-01',
    })
    assert response.status_code == 404
    db.expire_all()
    assert db.query(EncryptedSkuCostHistory).filter_by(sku_master_id=sku_id).count() == before


@pytest.mark.contract
def test_delete_cost_history_rejects_foreign_sku(two_tenants):
    from app.models.sku import EncryptedSkuCostHistory
    db = two_tenants.db
    sku_id = two_tenants.t1_sku_id
    cost = db.query(EncryptedSkuCost).filter_by(sku_master_id=sku_id).one()
    history = EncryptedSkuCostHistory(tenant_id=cost.tenant_id, sku_master_id=sku_id, vault_id=cost.vault_id,
        ciphertext='foreign', nonce='nonce', key_version=1, aad_context='foreign', valid_from=date(2026, 1, 1))
    db.add(history)
    db.commit()
    history_id = history.id
    response = two_tenants.client_t2.delete(f'/api/v1/products/{sku_id}/cost-history/{history_id}')
    assert response.status_code == 404
    db.expire_all()
    assert db.get(EncryptedSkuCostHistory, history_id).ciphertext == 'foreign'


@pytest.mark.contract
def test_import_costs_cannot_modify_foreign_sku(two_tenants):
    db = two_tenants.db
    sku = db.get(SkuMaster, two_tenants.t1_sku_id)
    name = sku.name
    response = two_tenants.client_t2.post('/api/v1/products/import-costs', files={
        'file': ('costs.csv', f'sku,cost\n{sku.sku_key},1\n'.encode(), 'text/csv')})
    assert response.status_code == 410
    db.expire_all()
    assert db.get(SkuMaster, two_tenants.t1_sku_id).name == name


@pytest.mark.contract
def test_debug_billing_types_excludes_foreign_entries(two_tenants):
    db = two_tenants.db
    marker = 'iso-' + uuid4().hex
    row = db.query(BillingRaw).filter_by(account_id=two_tenants.t1_account_id).first()
    row.type = marker
    db.commit()
    response = two_tenants.client_t2.get('/api/v1/dashboard/debug/billing-types')
    assert response.status_code == 200
    assert marker not in [item['type'] for item in response.json()]


@pytest.mark.contract
def test_financial_vault_status_and_setup_are_tenant_scoped(two_tenants):
    db = two_tenants.db
    tenant_a = db.get(Account, two_tenants.t1_account_id).tenant_id
    tenant_b = db.get(Account, two_tenants.t2_account_id).tenant_id
    vault_a = db.query(FinancialVault).filter_by(tenant_id=tenant_a, scope='global').first()
    created = vault_a is None
    if created:
        vault_a = FinancialVault(tenant_id=tenant_a, scope='global', kdf='argon2id', salt='foreign-salt',
            memory_cost=1, time_cost=1, parallelism=1, verify_nonce='nonce', verify_ciphertext='cipher', key_version=1)
        db.add(vault_a)
        db.commit()
    vault_id, salt = vault_a.id, vault_a.salt
    try:
        response = two_tenants.client_t2.get('/api/v1/financial-vault/status')
        assert response.status_code == 200
        assert response.json() == {'configured': False}
        response = two_tenants.client_t2.post('/api/v1/financial-vault/setup', json={
            'salt': 'tenant-b-salt', 'memory_cost': 1, 'time_cost': 1, 'parallelism': 1,
            'verify_nonce': 'nonce', 'verify_ciphertext': 'cipher', 'key_version': 1})
        assert response.status_code == 201
        assert response.json()['id'] != vault_id
        db.expire_all()
        assert db.get(FinancialVault, vault_id).salt == salt
    finally:
        db.query(FinancialVault).filter_by(tenant_id=tenant_b, scope='global').delete()
        if created:
            db.query(FinancialVault).filter_by(id=vault_id).delete()
        db.commit()


@pytest.mark.contract
def test_support_ticket_uses_current_tenant_and_user(two_tenants, monkeypatch):
    from app.services import email as email_service
    calls = []
    monkeypatch.setattr(email_service, 'send_support_report_email', lambda **kwargs: calls.append(kwargs) or True)
    db = two_tenants.db
    tenant_b = db.get(Account, two_tenants.t2_account_id).tenant_id
    user_b = db.query(User).filter_by(tenant_id=tenant_b).one()
    response = two_tenants.client_t2.post('/api/v1/support/ticket', data={'message': 'Help from B'})
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0]['tenant_id'] == tenant_b
    assert calls[0]['from_user_email'] == user_b.email
