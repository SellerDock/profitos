import os
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

os.environ["API_BEARER_TOKEN"] = "test-token"
os.environ["BACKEND_CORS_ORIGINS"] = "http://localhost:3001"

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.sku import EncryptedSkuCost, FinancialVault, SkuMaster


class _Query:
    def __init__(self, result: Any):
        self._result = result

    def filter_by(self, **_: Any):
        return self

    def filter(self, *_: Any):
        return self

    def first(self):
        return self._result


class _Db:
    def __init__(self, *, sku: SkuMaster | None, cost: EncryptedSkuCost | None, vault: FinancialVault | None):
        self.sku = sku
        self.cost = cost
        self.vault = vault

    def get(self, model: type, ident: int):
        if model is SkuMaster:
            return self.sku if self.sku and self.sku.id == ident else None
        if model is FinancialVault:
            return self.vault if self.vault and self.vault.id == ident else None
        return None

    def query(self, model: type):
        if model is EncryptedSkuCost:
            return _Query(self.cost)
        return _Query(None)


def _override_db(db: _Db):
    def _get_test_db():
        yield db

    app.dependency_overrides[get_db] = _get_test_db


def _client() -> TestClient:
    return TestClient(app)


def _sample_rows() -> tuple[SkuMaster, FinancialVault, EncryptedSkuCost]:
    sku = SkuMaster()
    sku.id = 7
    sku.tenant_id = 1
    sku.sku_key = "sku-test-7"
    sku.name = "Synthetic SKU"
    sku.vat_rate = Decimal("23")
    sku.target_margin_pct = Decimal("0")

    vault = FinancialVault()
    vault.id = 3
    vault.tenant_id = 1
    vault.scope = "global"
    vault.kdf = "argon2id"
    vault.salt = "MDEyMzQ1Njc4OWFiY2RlZg=="
    vault.memory_cost = 131072
    vault.time_cost = 4
    vault.parallelism = 1
    vault.verify_nonce = "YWJjZGVmZ2hpamts"
    vault.verify_ciphertext = "Y2lwaGVydGV4dC10YWc="
    vault.key_version = 1

    cost = EncryptedSkuCost()
    cost.id = 11
    cost.tenant_id = 1
    cost.sku_master_id = sku.id
    cost.vault_id = vault.id
    cost.ciphertext = "Y2lwaGVydGV4dC1wbHVzLTE2Yi10YWc="
    cost.nonce = "MDEyMzQ1Njc4OWFi"
    cost.key_version = 1
    cost.aad_context = "profitos:sku-cost:7:current:v1"
    return sku, vault, cost


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for child in value.values():
            found.update(_keys(child))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for child in value:
            found.update(_keys(child))
        return found
    return set()


def test_crypto_proof_returns_pinned_values():
    with _client() as client:
        response = client.get("/api/v1/security/crypto-proof")

    assert response.status_code == 200
    data = response.json()
    assert data["verifiable"]["cryptoVersion"] == settings.crypto_version
    assert data["verifiable"]["sourceCommit"] == settings.crypto_source_commit
    assert data["verifiable"]["bundleSha256"] == settings.crypto_bundle_sha256
    assert data["verifiable"]["bundleSri"] == settings.crypto_bundle_sri
    assert "operatorStatement" in data


def test_encrypted_cost_export_returns_envelope():
    sku, vault, cost = _sample_rows()
    _override_db(_Db(sku=sku, cost=cost, vault=vault))
    try:
        with _client() as client:
            response = client.get(
                "/api/v1/security/encrypted-cost-export/7",
                headers={"Authorization": "Bearer test-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["envelope"] == {
        "v": 1,
        "alg": "AES-256-GCM",
        "kdf": "argon2id",
        "kdfParams": {"memoryCost": 131072, "timeCost": 4, "parallelism": 1},
        "salt": vault.salt,
        "iv": cost.nonce,
        "ct": cost.ciphertext,
        "aad": cost.aad_context,
        "keyVersion": 1,
    }
    assert data["sku"] == {"id": 7, "sku_key": "sku-test-7", "name": "Synthetic SKU"}


def test_encrypted_cost_export_404_for_unknown_sku():
    _override_db(_Db(sku=None, cost=None, vault=None))
    try:
        with _client() as client:
            response = client.get(
                "/api/v1/security/encrypted-cost-export/999",
                headers={"Authorization": "Bearer test-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_encrypted_cost_export_never_returns_plaintext():
    sku, vault, cost = _sample_rows()
    _override_db(_Db(sku=sku, cost=cost, vault=vault))
    try:
        with _client() as client:
            response = client.get(
                "/api/v1/security/encrypted-cost-export/7",
                headers={"Authorization": "Bearer test-token"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert not {"plaintext", "cost", "value"}.intersection(_keys(response.json()))
