import base64
import logging
import os
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from app.core.auth_dep import get_current_user
from app.core.config import Settings, settings
from app.core.database import get_db
from app.main import app
from app.models.account import Account
from app.models.raw_data import OfferCache
from app.models.sku import FinancialVault
from app.services.dashboard_engine import DashboardEngine, ProductSummaryRow, get_period
from app.services.vault_decryption import (
    VAULT_VERIFIER_AAD,
    VAULT_VERIFIER_PLAINTEXT,
    derive_financial_key,
)

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "not-the-vault-code"
MEMORY_COST = 65536
TIME_COST = 2
PARALLELISM = 1
KEY_VERSION = 1

TENANT_ID = 501
OTHER_TENANT_ID = 502

EAN_A = "5901234567890"
EAN_B = "1234567890123"
EAN_C = "12345678"
EAN_D = "1234567890"
EAN_UNKNOWN = "99999999"

URL = "/api/v1/integrations/profit-by-ean"


@pytest.fixture(autouse=True)
def enable_vault_server_decryption(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_SERVER_DECRYPTION_ENABLED", True)


# ── Crypto helpers (mirror test_vault_decryption.py) ──────────────────────────

def _derive_key(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=TIME_COST,
        memory_cost=MEMORY_COST,
        parallelism=PARALLELISM,
        hash_len=32,
        type=Type.ID,
    )


def _aesgcm_encrypt(key: bytes, plaintext: str, aad: str):
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return (
        base64.b64encode(ciphertext).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def _cost_aad(sku_id: int, key_version: int = KEY_VERSION) -> str:
    return f"profitos:sku-cost:{sku_id}:current:v{key_version}"


def cost_envelope(key: bytes, sku_id: int, cost: str, key_version: int = KEY_VERSION) -> dict:
    aad = _cost_aad(sku_id, key_version)
    ciphertext, nonce = _aesgcm_encrypt(key, str(cost), aad)
    return {"ciphertext": ciphertext, "nonce": nonce, "key_version": key_version, "aad_context": aad}


@pytest.fixture
def vault_and_key():
    salt = os.urandom(16)
    key = _derive_key(PASSWORD, salt)
    verify_ciphertext, verify_nonce = _aesgcm_encrypt(key, VAULT_VERIFIER_PLAINTEXT, VAULT_VERIFIER_AAD)
    vault = FinancialVault(
        tenant_id=TENANT_ID,
        scope="global",
        kdf="argon2id",
        salt=base64.b64encode(salt).decode("ascii"),
        memory_cost=MEMORY_COST,
        time_cost=TIME_COST,
        parallelism=PARALLELISM,
        verify_nonce=verify_nonce,
        verify_ciphertext=verify_ciphertext,
        key_version=KEY_VERSION,
    )
    return vault, key


# ── Product row factory ───────────────────────────────────────────────────────

def make_row(
    sku_key: str,
    *,
    encrypted_cost: dict | None = None,
    units_sold: int = 3,
    cogs_units: str = "3.00",
    revenue_net: str = "100.00",
    total_allegro_net: str = "10.00",
    price_adjust_cost: str = "0.00",
    campaign_bonus: str = "0.00",
    refund_commission: str = "0.00",
    commission_refunds_amount: str = "0.00",
    cost_multiplier: str = "1.0000",
) -> ProductSummaryRow:
    return ProductSummaryRow(
        sku_id=1,
        sku_key=sku_key,
        name=sku_key,
        sell_price="0.00",
        encrypted_cost=encrypted_cost,
        cost_multiplier=cost_multiplier,
        ean=None,
        vat_rate="23.00",
        units_sold=units_sold,
        cogs_units=cogs_units,
        returns_units=0,
        returns_pending_units=0,
        returns_rejected_units=0,
        revenue_gross="0.00",
        revenue_net=revenue_net,
        commission_cost="0.00",
        featuring_commission_cost="0.00",
        ads_cost="0.00",
        ads_imported_cost="0.00",
        ads_nsp_adjustment_cost="0.00",
        smart_shipping_cost="0.00",
        smart_forecast_cost="0.00",
        shipping_passthrough_cost="0.00",
        foreign_shipping_cost="0.00",
        featuring_cost="0.00",
        coins_cost="0.00",
        campaign_commission_cost="0.00",
        campaign_bonus=campaign_bonus,
        price_adjust_cost=price_adjust_cost,
        protect_cost="0.00",
        local_cost="0.00",
        subscription_cost="0.00",
        refund_commission=refund_commission,
        commission_refunds_amount=commission_refunds_amount,
        fulfillment="0.00",
        total_allegro="0.00",
        total_allegro_net=total_allegro_net,
        cogs=None,
        profit_net=None,
        profit_per_unit=None,
        margin_pct=None,
        roi_pct=None,
    )


def make_offer(ean: str, sku: str | None, *, account_id: int = 1) -> OfferCache:
    return OfferCache(tenant_id=TENANT_ID, offer_id=f"offer-{ean}-{sku}", account_id=account_id,
                      sku=sku, name=sku or ean, ean=ean)


# ── Fake DB capturing query construction ──────────────────────────────────────

class _OfferQuery:
    def __init__(self, db: "_Db"):
        self._db = db

    def filter(self, *clauses):
        self._db._filters.setdefault(OfferCache, []).append(tuple(clauses))
        return self

    def all(self):
        return self._db.offers


class _VaultQuery:
    def __init__(self, db: "_Db"):
        self._db = db

    def filter(self, *clauses):
        self._db._filters.setdefault(FinancialVault, []).append(tuple(clauses))
        return self

    def first(self):
        return self._db.vault


class _Db:
    def __init__(self, *, offers=None, vault=None, accounts=None):
        self.offers = offers if offers is not None else []
        self.vault = vault
        self.accounts = accounts if accounts is not None else {}
        self._filters: dict = {}
        self.offer_query_calls = 0
        self.vault_query_calls = 0

    def get(self, model, ident):
        if model is Account:
            return self.accounts.get(ident)
        return None

    def query(self, model):
        if model is OfferCache:
            self.offer_query_calls += 1
            return _OfferQuery(self)
        if model is FinancialVault:
            self.vault_query_calls += 1
            return _VaultQuery(self)
        raise AssertionError(f"unexpected query model: {model}")

    def compiled_filters(self, model) -> list[list[str]]:
        return [
            [" ".join(str(clause.compile(compile_kwargs={"literal_binds": True})).split()) for clause in clauses]
            for clauses in self._filters.get(model, [])
        ]


@contextmanager
def _override(user=None, db=None):
    if user is not None:
        app.dependency_overrides[get_current_user] = (lambda u=user: u)
    if db is not None:
        def _get_test_db():
            yield db

        app.dependency_overrides[get_db] = _get_test_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fake_products(monkeypatch):
    calls: list = []

    def install(rows):
        def _products(self, period, account_id=None, search=None, currency="PLN"):
            calls.append((period, account_id, search, currency))
            return list(rows)

        monkeypatch.setattr(DashboardEngine, "products", _products)
        return calls

    yield install


def default_user() -> SimpleNamespace:
    return SimpleNamespace(id=901, tenant_id=TENANT_ID)


def _client() -> TestClient:
    return TestClient(app)


def _post(client, eans, vault_code=PASSWORD, account_id=None, extra=None, headers=None, *, auth=True):
    body = {"eans": list(eans), "vault_code": vault_code}
    if account_id is not None:
        body["account_id"] = account_id
    if extra:
        body.update(extra)
    request_headers = {"X-Requested-With": "XMLHttpRequest"}
    if auth:
        request_headers["Authorization"] = "Bearer test-token"
    if headers:
        request_headers.update(headers)
    return client.post(URL, json=body, headers=request_headers)


# ── Auth ──────────────────────────────────────────────────────────────────────

def test_server_decryption_disabled_with_authenticated_valid_request(monkeypatch):
    monkeypatch.setattr(settings, "VAULT_SERVER_DECRYPTION_ENABLED", False)
    with _override(user=default_user()), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_server_decryption_disabled_is_indistinguishable_from_missing_route(monkeypatch):
    """Disabled endpoint answers exactly like a non-existent /api/v1 path.

    Without credentials the auth middleware answers 401 for every /api/v1 path,
    so the disabled endpoint must give the same 401 as a missing route. With a
    session cookie (even an invalid one) the request reaches routing and must get
    404 before session validation and before the malformed body is parsed.
    """
    monkeypatch.setattr(settings, "VAULT_SERVER_DECRYPTION_ENABLED", False)
    headers = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"}
    missing = "/api/v1/integrations/does-not-exist"
    with _client() as client:
        anon = client.post(URL, content="{", headers=headers)
        anon_missing = client.post(missing, content="{", headers=headers)
        assert (anon.status_code, anon.json()) == (anon_missing.status_code, anon_missing.json())

        client.cookies.set("apos_session", "invalid-session")
        with_cookie = client.post(URL, content="{", headers=headers)
        with_cookie_missing = client.post(missing, content="{", headers=headers)
    assert with_cookie.status_code == 404
    assert with_cookie.json() == {"detail": "Not Found"}
    assert (with_cookie.status_code, with_cookie.json()) == (
        with_cookie_missing.status_code, with_cookie_missing.json()
    )


def test_server_decryption_disabled_by_default():
    assert Settings.model_fields["VAULT_SERVER_DECRYPTION_ENABLED"].default is False


def test_unauthenticated_request_is_rejected():
    with _client() as client:
        response = _post(client, [EAN_A], auth=False)
    assert response.status_code == 401


def test_missing_csrf_header_rejected():
    with _client() as client:
        response = client.post(
            URL,
            json={"eans": [EAN_A], "vault_code": PASSWORD},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 403


def test_legacy_bearer_pseudo_user_rejected():
    db = _Db()
    with _override(db=db), _client() as client:
        response = _post(
            client,
            [EAN_A],
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 403
    assert "user id 0" in response.json()["detail"]


# ── Tenant / account scope ────────────────────────────────────────────────────

def test_account_foreign_tenant_rejected(vault_and_key):
    vault, _key = vault_and_key
    db = _Db(accounts={10: Account(id=10, tenant_id=OTHER_TENANT_ID, name="x",
                                   allegro_client_id="c", allegro_client_secret="s")})
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A], account_id=10)
    assert response.status_code == 404


def test_account_unknown_rejected(vault_and_key):
    vault, _key = vault_and_key
    db = _Db(vault=vault)
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A], account_id=999)
    assert response.status_code == 404


def test_account_owned_by_tenant_accepted(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(
        vault=vault,
        accounts={10: Account(id=10, tenant_id=TENANT_ID, name="mine",
                              allegro_client_id="c", allegro_client_secret="s")},
        offers=[make_offer(EAN_A, "SKU-A")],
    )
    calls = fake_products([make_row("SKU-A", encrypted_cost=cost_envelope(key, 1, "10.00"))])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A], account_id=10)
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "ok"
    assert len(calls) == 1
    _period, account_id, search, currency = calls[0]
    assert account_id == 10
    assert search is None
    assert currency == "PLN"
    assert _period.label == get_period("last_7d").label
    offer_filters = " ".join(
        clause for group in db.compiled_filters(OfferCache) for clause in group
    )
    assert "account_id = 10" in offer_filters


# ── Offers query construction ─────────────────────────────────────────────────

def test_offers_queried_once_with_tenant_and_exact_ean_filter(vault_and_key, fake_products):
    vault, _key = vault_and_key
    db = _Db(vault=vault, offers=[])
    fake_products([])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A, EAN_B])
    assert response.status_code == 200
    assert db.offer_query_calls == 1
    offer_filters = db.compiled_filters(OfferCache)
    assert len(offer_filters) == 1
    joined = " AND ".join(offer_filters[0])
    assert f"tenant_id = {TENANT_ID}" in joined
    assert f"ean IN ('{EAN_A}', '{EAN_B}')" in joined


# ── Statuses and input order ──────────────────────────────────────────────────

def test_statuses_returned_in_input_order(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(
        vault=vault,
        offers=[
            make_offer(EAN_A, "SKU-A"),
            make_offer(EAN_B, "SKU-B1"),
            make_offer(EAN_B, "SKU-B2"),
            make_offer(EAN_C, "SKU-C"),
            make_offer(EAN_D, "SKU-D"),
        ],
    )
    fake_products([
        make_row("SKU-A", encrypted_cost=cost_envelope(key, 1, "10.00")),
        make_row("SKU-D"),
    ])
    request_order = [EAN_B, EAN_C, EAN_D, EAN_A, EAN_UNKNOWN, EAN_B]
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, request_order)
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["ean"] for r in results] == request_order
    by_ean = {r["ean"]: r for r in results}
    assert by_ean[EAN_B]["status"] == "ambiguous"
    assert by_ean[EAN_B]["sku"] is None
    assert by_ean[EAN_C]["status"] == "no_sales"
    assert by_ean[EAN_C]["sku"] == "SKU-C"
    assert by_ean[EAN_C]["units_sold"] == 0
    assert by_ean[EAN_D]["status"] == "missing_cost"
    assert by_ean[EAN_D]["sku"] == "SKU-D"
    assert by_ean[EAN_D]["profit_net_total"] is None
    assert by_ean[EAN_A]["status"] == "ok"
    assert by_ean[EAN_UNKNOWN]["status"] == "not_found"
    assert by_ean[EAN_UNKNOWN]["sku"] is None


def test_duplicate_offers_same_sku_deduped(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(
        vault=vault,
        offers=[
            make_offer(EAN_A, "SKU-A"),
            make_offer(EAN_A, " SKU-A "),
        ],
    )
    fake_products([make_row("SKU-A", encrypted_cost=cost_envelope(key, 1, "10.00"))])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "ok"
    assert result["sku"] == "SKU-A"


def test_batch_of_100_eans_queries_engine_once(vault_and_key, fake_products):
    vault, _key = vault_and_key
    eans = [f"{i:08d}" for i in range(1, 101)]
    db = _Db(vault=vault, offers=[])
    calls = fake_products([])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, eans)
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 100
    assert all(r["ean"] == e for r, e in zip(results, eans))
    assert all(r["status"] == "not_found" for r in results)
    assert len(calls) == 1
    _period, account_id, search, currency = calls[0]
    assert account_id is None


# ── Wrong vault code ──────────────────────────────────────────────────────────

def test_wrong_vault_code_rejected_before_offers_lookup(vault_and_key, caplog):
    vault, _key = vault_and_key
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    with caplog.at_level(logging.DEBUG):
        with _override(user=default_user(), db=db), _client() as client:
            response = _post(client, [EAN_A], vault_code=WRONG_PASSWORD)
    assert response.status_code == 403
    assert db.offer_query_calls == 0
    body = response.text
    assert WRONG_PASSWORD not in body
    assert PASSWORD not in body
    assert WRONG_PASSWORD not in caplog.text


def test_missing_vault_config_404(vault_and_key):
    _vault, _key = vault_and_key
    db = _Db(vault=None)
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 404


# ── Numeric parity with the frontend net-mode formula ────────────────────────

def test_numeric_parity_multiplier_cogs_and_adjustments(vault_and_key, fake_products):
    vault, key = vault_and_key
    envelope = cost_envelope(key, 1, "100.00")
    db = _Db(
        vault=vault,
        offers=[
            make_offer(EAN_A, "SKU-A"),
            make_offer(EAN_B, "SKU-B"),
            make_offer(EAN_C, "SKU-C"),
        ],
    )
    rows = [
        make_row(
            "SKU-A",
            encrypted_cost=envelope,
            units_sold=4,
            cogs_units="3.50",
            revenue_net="500.00",
            total_allegro_net="30.00",
            price_adjust_cost="12.30",
            campaign_bonus="12.30",
            refund_commission="6.15",
            commission_refunds_amount="6.15",
            cost_multiplier="2.0000",
        ),
        make_row(
            "SKU-B",
            encrypted_cost=envelope,
            units_sold=4,
            cogs_units="3.50",
            revenue_net="500.00",
            total_allegro_net="30.00",
            price_adjust_cost="12.30",
            campaign_bonus="12.30",
            refund_commission="6.15",
            commission_refunds_amount="6.15",
            cost_multiplier="not-a-multiplier",
        ),
        make_row(
            "SKU-C",
            encrypted_cost=envelope,
            units_sold=4,
            cogs_units="-2.00",
            revenue_net="500.00",
            total_allegro_net="30.00",
            price_adjust_cost="12.30",
            campaign_bonus="12.30",
            refund_commission="6.15",
            commission_refunds_amount="6.15",
        ),
    ]
    fake_products(rows)
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A, EAN_B, EAN_C])
    assert response.status_code == 200
    by_ean = {r["ean"]: r for r in response.json()["results"]}

    # unitCost = 100 * 2 = 200; cogs = 200 * 3.5 = 700
    # profit = 500 - 30 + 10 + 10 + 5 + 5 - 700 = -200
    a = by_ean[EAN_A]
    assert a["status"] == "ok"
    assert a["units_sold"] == 4
    assert a["profit_per_unit_net"] == "-50.00"
    assert a["profit_net_total"] == "-200.00"

    # invalid multiplier falls back to 1 → cogs = 100 * 3.5 = 350
    # profit = 500 - 30 + 30 - 350 = 150
    b = by_ean[EAN_B]
    assert b["units_sold"] == 4
    assert b["profit_per_unit_net"] == "37.50"
    assert b["profit_net_total"] == "150.00"

    # negative cogs_units is clamped to 0 → cogs = 0, profit = 500 - 30 + 30 = 500
    c = by_ean[EAN_C]
    assert c["units_sold"] == 4
    assert c["profit_per_unit_net"] == "125.00"
    assert c["profit_net_total"] == "500.00"


def test_half_cent_rounds_like_display(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([make_row(
        "SKU-A", encrypted_cost=cost_envelope(key, 1, "0"),
        units_sold=1, cogs_units="1", revenue_net="1.005",
        total_allegro_net="0",
    )])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    result = response.json()["results"][0]
    assert result["profit_per_unit_net"] == "1.01"
    assert result["profit_net_total"] == "1.01"


def test_profit_per_unit_null_without_positive_units(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([
        make_row("SKU-A", encrypted_cost=cost_envelope(key, 1, "10.00"),
                 units_sold=0, cogs_units="0.00", revenue_net="0.00"),
    ])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    result = response.json()["results"][0]
    assert result["status"] == "ok"
    assert result["units_sold"] == 0
    assert result["profit_per_unit_net"] is None
    assert result["profit_net_total"] == "-10.00"


# ── Safe generic error for malformed envelopes ────────────────────────────────

def test_malformed_envelope_returns_generic_error(vault_and_key, fake_products, caplog):
    vault, _key = vault_and_key
    broken = {"ciphertext": "!!!not-base64!!!", "nonce": "AAAA", "key_version": KEY_VERSION,
              "aad_context": _cost_aad(1)}
    secret_cost = "777.77"
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([make_row("SKU-A", encrypted_cost=broken)])
    with caplog.at_level(logging.DEBUG):
        with _override(user=default_user(), db=db), _client() as client:
            response = _post(client, [EAN_A])
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "invalid_data"
    assert response.json()["results"][0]["profit_per_unit_net"] is None
    body = response.text
    assert PASSWORD not in body
    assert secret_cost not in body
    assert "not-base64" not in body
    assert PASSWORD not in caplog.text


def test_key_version_mismatch_returns_generic_error(vault_and_key, fake_products):
    vault, key = vault_and_key
    envelope = cost_envelope(key, 1, "10.00", key_version=KEY_VERSION + 1)
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([make_row("SKU-A", encrypted_cost=envelope)])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "invalid_data"


def test_invalid_financial_value_is_reported_per_ean(vault_and_key, fake_products):
    vault, key = vault_and_key
    db = _Db(vault=vault, offers=[
        make_offer(EAN_A, "SKU-A"),
        make_offer(EAN_B, "SKU-B"),
    ])
    fake_products([
        make_row("SKU-A", encrypted_cost=cost_envelope(key, 1, "10.00"),
                 revenue_net="NaN"),
        make_row("SKU-B", encrypted_cost=cost_envelope(key, 2, "10.00")),
    ])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A, EAN_B])
    assert response.status_code == 200
    first, second = response.json()["results"]
    assert first["status"] == "invalid_data"
    assert first["profit_per_unit_net"] is None
    assert second["status"] == "ok"


# ── Input validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "eans",
    [
        [],
        ["1234567"],
        ["123456789012345"],
        ["1234567A"],
        ["123456 78"],
        ["１２３４５６７８"],
        [EAN_A, "SHORT"],
    ],
)
def test_invalid_ean_lists_rejected(eans):
    with _client() as client:
        response = client.post(
            URL,
            json={"eans": eans, "vault_code": PASSWORD},
            headers={"X-Requested-With": "XMLHttpRequest", "Authorization": "Bearer test-token"},
        )
    assert response.status_code == 422


def test_extra_fields_rejected(vault_and_key, fake_products):
    vault, _key = vault_and_key
    db = _Db(vault=vault, offers=[])
    fake_products([])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A], extra={"currency": "EUR", "period": "last_30d"})
    assert response.status_code == 422


def test_missing_vault_code_rejected():
    with _client() as client:
        response = client.post(
            URL,
            json={"eans": [EAN_A]},
            headers={"X-Requested-With": "XMLHttpRequest", "Authorization": "Bearer test-token"},
        )
    assert response.status_code == 422


def test_too_many_eans_rejected():
    eans = [f"{i:08d}" for i in range(1, 102)]
    with _client() as client:
        response = client.post(
            URL,
            json={"eans": eans, "vault_code": PASSWORD},
            headers={"X-Requested-With": "XMLHttpRequest", "Authorization": "Bearer test-token"},
        )
    assert response.status_code == 422


def test_top_level_metadata_and_no_secrets(vault_and_key, fake_products):
    vault, _key = vault_and_key
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([make_row("SKU-A")])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 200
    data = response.json()
    assert data["period"] == "last_7d"
    assert data["currency"] == "PLN"
    assert data["as_of"].endswith("+00:00")
    assert "vault_code" not in response.text
    assert PASSWORD not in response.text


def test_vault_discovery_from_tenant_id(vault_and_key, fake_products):
    vault, _key = vault_and_key
    db = _Db(vault=vault, offers=[make_offer(EAN_A, "SKU-A")])
    fake_products([])
    with _override(user=default_user(), db=db), _client() as client:
        response = _post(client, [EAN_A])
    assert response.status_code == 200
    assert db.vault_query_calls == 1
    vault_filters = db.compiled_filters(FinancialVault)
    assert len(vault_filters) == 1
    joined = " AND ".join(vault_filters[0])
    assert f"tenant_id = {TENANT_ID}" in joined
    assert "scope = 'global'" in joined
