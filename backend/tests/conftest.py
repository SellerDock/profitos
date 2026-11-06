import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

os.environ["SECRET_KEY"] = "test-key-0123456789abcdef0123456789abcdef"
os.environ["API_BEARER_TOKEN"] = "test-token"
os.environ["AUTH_COOKIE_SECURE"] = "false"
# Force a deterministic CORS origin for the test session — the staging/prod
# container env sets BACKEND_CORS_ORIGINS (e.g. a production domain),
# and setdefault() would silently keep it, breaking test_security.py.
os.environ["BACKEND_CORS_ORIGINS"] = "http://localhost:3001"
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["SMTP_FROM_EMAIL"] = ""
os.environ["WAITLIST_ADMIN_EMAIL"] = ""

from app.core.config import settings
from app.main import app
from app.models.account import Account
from app.models.raw_data import AllegroAdsImport, BillingRaw, OfferCache, OrderRaw
from app.models.sku import EncryptedSkuCost, FinancialVault, SkuMaster
from app.models.tenant import Tenant
from app.services import dashboard_cache

# ── Safety guard — must not run against the live application database ──────────
#
# We use pytest.exit() at module-level so the guard fires during collection,
# before any fixture touches the database, and cannot be skipped with -k.
# raise RuntimeError would also stop collection but produces a noisy traceback;
# pytest.exit() emits a clean message and exits with a non-zero code.
#
# Both guards must appear before every @pytest.fixture definition so that the
# intention "no fixture body runs on the live DB" is obvious from the code layout.

_db_host = os.environ.get("POSTGRES_HOST", "apos-db")
_db_name = os.environ.get("POSTGRES_DB", "apos_db")

# Guard 1 (unconditional): the canonical production pair is never allowed,
# even if APOS_TEST_DB=1 is set — defence against "I'll set the flag and
# run on prod" mistakes.
if _db_host == "apos-db" and _db_name == "apos_db":
    pytest.exit(
        "\n[GUARD] Testy NIE mogą uruchomić się na bazie produkcyjnej!\n"
        f"  Wykryty host: {_db_host!r}, baza: {_db_name!r}\n"
        "  Para (apos-db, apos_db) jest nienaruszalną bazą aplikacji — jej dane\n"
        "  zostałyby skasowane przez fixture'y testowe. Ta blokada jest bezwzględna.\n"
        "  Uruchom testy na OSOBNEJ instancji PostgreSQL:\n"
        "    POSTGRES_HOST=localhost POSTGRES_DB=apos_test APOS_TEST_DB=1 pytest tests -q",
        returncode=3,
    )

# Guard 2: require explicit opt-in via APOS_TEST_DB, so tests never run
# accidentally on any non-test database (e.g. a staging DB on a different host).
_test_db_flag = os.environ.get("APOS_TEST_DB", "").strip().lower()
if _test_db_flag not in ("1", "true", "yes"):
    pytest.exit(
        "\n[GUARD] Zmienna APOS_TEST_DB nie jest ustawiona.\n"
        f"  Wykryty host: {_db_host!r}, baza: {_db_name!r}\n"
        "  Ustaw POSTGRES_HOST i POSTGRES_DB na dedykowaną bazę testową\n"
        "  oraz APOS_TEST_DB=1 przed uruchomieniem testów. Przykład:\n"
        "    POSTGRES_HOST=localhost POSTGRES_DB=apos_test APOS_TEST_DB=1 pytest tests -q",
        returncode=3,
    )

_DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('POSTGRES_USER', 'apos_user')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'apos_pass')}@"
    f"{_db_host}/"
    f"{_db_name}"
)



@pytest.fixture(autouse=True)
def _isolated_dashboard_cache() -> Iterator[None]:
    """Clear the in-process dashboard cache around every test.

    The cache (app/services/dashboard_cache.py, 90 s TTL) is keyed by
    tenant/account/method/period, so a test can otherwise be served stale
    results computed from another test's fixture data (observed: tenant-1
    'products?period=last_30d' cached with seeded_db TEST-A/TEST-B leaked
    into test_tenant_isolation_endpoints). Production behavior is unchanged.
    """
    with dashboard_cache._cache_lock:
        dashboard_cache._cache.clear()
        dashboard_cache._key_locks.clear()
    yield
    with dashboard_cache._cache_lock:
        dashboard_cache._cache.clear()
        dashboard_cache._key_locks.clear()


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authed_client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        client.headers.update({"Authorization": f"Bearer {settings.API_BEARER_TOKEN}"})
        yield client


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(_DB_URL)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_db() -> Iterator[dict]:
    engine = create_engine(_DB_URL)
    db = Session(engine)
    created_vault = False

    def cleanup() -> None:
        db.execute(text("DELETE FROM allegro_ads_imports WHERE tenant_id = 1 AND (imported_filename = 'contract-no-plaintext.csv' OR offer_id LIKE 'contract-offer-%')"))
        db.execute(text("DELETE FROM billing_raw WHERE tenant_id = 1 AND entry_id LIKE 'contract-billing-%'"))
        db.execute(text("DELETE FROM orders_raw WHERE tenant_id = 1 AND (line_item_id LIKE 'contract-line-%' OR order_id LIKE 'contract-order-%')"))
        db.execute(text("DELETE FROM offers_cache WHERE tenant_id = 1 AND (offer_id LIKE 'contract-offer-%' OR sku IN ('TEST-A', 'TEST-B'))"))
        db.execute(text(
            "DELETE FROM encrypted_sku_cost_history WHERE sku_master_id IN "
            "(SELECT id FROM sku_masters WHERE tenant_id = 1 AND sku_key IN ('TEST-A', 'TEST-B'))"
        ))
        db.execute(text(
            "DELETE FROM encrypted_sku_costs WHERE sku_master_id IN "
            "(SELECT id FROM sku_masters WHERE tenant_id = 1 AND sku_key IN ('TEST-A', 'TEST-B'))"
        ))
        db.execute(text(
            "DELETE FROM sku_aliases WHERE sku_master_id IN "
            "(SELECT id FROM sku_masters WHERE tenant_id = 1 AND sku_key IN ('TEST-A', 'TEST-B'))"
        ))
        db.execute(text("DELETE FROM sku_masters WHERE tenant_id = 1 AND sku_key IN ('TEST-A', 'TEST-B')"))
        db.execute(text("DELETE FROM accounts WHERE allegro_client_id = 'contract-client'"))
        db.commit()

    cleanup()

    if db.get(Tenant, 1) is None:
        db.add(Tenant(id=1, name="Operator", slug="operator", is_active=True))
        db.flush()

    account = Account(
        tenant_id=1,
        name="Contract Test Account",
        allegro_client_id="contract-client",
        allegro_client_secret="contract-secret",
        color="#334155",
    )
    db.add(account)
    db.flush()

    sku_a = SkuMaster(
        tenant_id=1,
        sku_key="TEST-A",
        name="Contract Test SKU A",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("25"),
    )
    sku_b = SkuMaster(
        tenant_id=1,
        sku_key="TEST-B",
        name="Contract Test SKU B",
        vat_rate=Decimal("23"),
        target_margin_pct=Decimal("0"),
    )
    db.add_all([sku_a, sku_b])
    db.flush()

    vault = db.query(FinancialVault).filter(FinancialVault.tenant_id == 1, FinancialVault.scope == "global").first()
    if vault is None:
        vault = FinancialVault(
            tenant_id=1,
            scope="global",
            kdf="argon2id",
            salt="MDEyMzQ1Njc4OWFiY2RlZg==",
            memory_cost=131072,
            time_cost=4,
            parallelism=1,
            verify_nonce="MDEyMzQ1Njc4OWFi",
            verify_ciphertext="Y29udHJhY3QtdmVyaWZpZXItY2lwaGVydGV4dC10YWc=",
            key_version=1,
        )
        db.add(vault)
        db.flush()
        created_vault = True

    encrypted_cost = EncryptedSkuCost(
        tenant_id=1,
        sku_master_id=sku_a.id,
        vault_id=vault.id,
        ciphertext="Y29udHJhY3QtZW5jcnlwdGVkLWNvc3Qtd2l0aC10YWc=",
        nonce="MDEyMzQ1Njc4OWFi",
        key_version=vault.key_version,
        aad_context=f"profitos:sku-cost:{sku_a.id}:current:v{vault.key_version}",
    )
    db.add(encrypted_cost)

    now = datetime.utcnow().replace(microsecond=0)
    offers = [
        OfferCache(
            tenant_id=1,
            offer_id="contract-offer-a",
            account_id=account.id,
            sku="TEST-A",
            name="Contract Offer A",
            price=Decimal("100.00"),
            currency="PLN",
            synced_at=now,
        ),
        OfferCache(
            tenant_id=1,
            offer_id="contract-offer-b",
            account_id=account.id,
            sku="TEST-B",
            name="Contract Offer B",
            price=Decimal("150.00"),
            currency="PLN",
            synced_at=now,
        ),
    ]
    db.add_all(offers)

    orders: list[OrderRaw] = []
    for idx in range(5):
        sku_key = "TEST-A" if idx < 3 else "TEST-B"
        offer_id = "contract-offer-a" if sku_key == "TEST-A" else "contract-offer-b"
        orders.append(OrderRaw(
            tenant_id=1,
            line_item_id=f"contract-line-{idx}",
            order_id=f"contract-order-{idx}",
            account_id=account.id,
            offer_id=offer_id,
            sku=sku_key,
            buyer_login=f"contract-buyer-{idx}",
            quantity=1,
            unit_price=Decimal("100.00") + Decimal(idx),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="READY_FOR_PROCESSING",
            bought_at=now - timedelta(hours=idx),
        ))
    db.add_all(orders)

    billing_types = ["SUC", "FSF", "CPF", "REF", "NSP", "SUC", "FSF", "CPF", "REF", "NSP"]
    billing_rows: list[BillingRaw] = []
    for idx, type_code in enumerate(billing_types):
        order_idx = idx % len(orders)
        is_ads = type_code == "NSP"
        billing_rows.append(BillingRaw(
            tenant_id=1,
            entry_id=f"contract-billing-{idx}",
            account_id=account.id,
            offer_id="contract-offer-a" if order_idx < 3 else "contract-offer-b",
            order_id=None if is_ads else f"contract-order-{order_idx}",
            type=type_code,
            amount=Decimal("2.50") if type_code == "REF" else Decimal("-3.25"),
            currency="PLN",
            occurred_at=now - timedelta(hours=idx),
        ))
    db.add_all(billing_rows)

    db.add(AllegroAdsImport(
        tenant_id=1,
        account_id=account.id,
        offer_id="contract-offer-a",
        campaign_name="Contract Campaign",
        ad_group="Contract Group",
        ad_date=date.today(),
        impressions=100,
        clicks=10,
        interest=2,
        cpc=Decimal("0.5000"),
        ctr=Decimal("0.1000"),
        cost=Decimal("5.00"),
        roas=Decimal("20.00"),
        units_sold_via_ad=1,
        sales_value=Decimal("100.00"),
        imported_filename="contract-no-plaintext.csv",
    ))
    db.commit()

    try:
        yield {
            "db": db,
            "account_id": account.id,
            "sku_a_id": sku_a.id,
            "sku_b_id": sku_b.id,
            "sku_a_key": sku_a.sku_key,
            "sku_b_key": sku_b.sku_key,
            "vault_key_version": vault.key_version,
        }
    finally:
        cleanup()
        if created_vault:
            # tenant_id = 1 is mandatory here: financial_vaults.id is referenced by
            # encrypted_sku_costs.vault_id / encrypted_sku_cost_history.vault_id with
            # ondelete=CASCADE, so an unfiltered delete would wipe every tenant's
            # encrypted purchase costs — unrecoverable, the backend has no key.
            db.execute(text("DELETE FROM financial_vaults WHERE tenant_id = 1 AND scope = 'global'"))
            db.commit()
        db.close()
