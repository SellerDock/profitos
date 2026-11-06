from datetime import date, timedelta

import pytest


@pytest.mark.contract
def test_patch_product_with_plaintext_cost_returns_422(authed_client, seeded_db):
    sku_id = seeded_db["sku_a_id"]
    response = authed_client.patch(f"/api/v1/products/{sku_id}", json={"cost": 199.99})
    assert response.status_code == 422, response.text
    assert "cost" in response.text.lower()

    from app.models.sku import SkuMaster

    sku = seeded_db["db"].get(SkuMaster, sku_id)
    for attr in ("cost", "cost_per_unit", "profit"):
        assert not hasattr(sku, attr), f"SkuMaster has plaintext attribute {attr}"


@pytest.mark.contract
def test_patch_product_with_plaintext_profit_returns_422(authed_client, seeded_db):
    sku_id = seeded_db["sku_a_id"]
    response = authed_client.patch(f"/api/v1/products/{sku_id}", json={"profit_net": 50.0})
    assert response.status_code == 422, response.text
    assert "profit_net" in response.text.lower()


@pytest.mark.contract
def test_patch_product_with_extra_unknown_field_returns_422(authed_client, seeded_db):
    sku_id = seeded_db["sku_a_id"]
    response = authed_client.patch(f"/api/v1/products/{sku_id}", json={"whatever_unknown": 1})
    assert response.status_code == 422, response.text
    assert "whatever_unknown" in response.text.lower()


@pytest.mark.contract
def test_patch_product_with_valid_envelope_succeeds(authed_client, seeded_db):
    sku_id = seeded_db["sku_b_id"]
    key_version = seeded_db["vault_key_version"]
    payload = {
        "encrypted_cost": {
            "ciphertext": "A" * 64,
            "nonce": "B" * 16,
            "key_version": key_version,
            "aad_context": f"profitos:sku-cost:{sku_id}:current:v{key_version}",
        },
        "history_encrypted_cost": {
            "ciphertext": "C" * 64,
            "nonce": "D" * 16,
            "key_version": key_version,
            "aad_context": (
                f"profitos:sku-cost:{sku_id}:history:{date.today().isoformat()}:v{key_version}"
            ),
        },
    }
    response = authed_client.patch(f"/api/v1/products/{sku_id}", json=payload)
    assert response.status_code in (200, 204), response.text


@pytest.mark.contract
def test_bounded_historical_cost_does_not_overwrite_current(authed_client, seeded_db):
    from app.models.sku import EncryptedSkuCost

    sku_id = seeded_db["sku_a_id"]
    key_version = seeded_db["vault_key_version"]
    db = seeded_db["db"]
    original = (
        db.query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.sku_master_id == sku_id)
        .one()
    )
    original_ciphertext = original.ciphertext
    valid_from = "1900-01-01"
    valid_to = (date.today() - timedelta(days=1)).isoformat()

    response = authed_client.post(f"/api/v1/products/{sku_id}/cost-history", json={
        "encrypted_cost": {
            "ciphertext": "E" * 64,
            "nonce": "F" * 16,
            "key_version": key_version,
            "aad_context": f"profitos:sku-cost:{sku_id}:history:{valid_from}:v{key_version}",
        },
        "current_encrypted_cost": {
            "ciphertext": "G" * 64,
            "nonce": "H" * 16,
            "key_version": key_version,
            "aad_context": f"profitos:sku-cost:{sku_id}:current:v{key_version}",
        },
        "valid_from": valid_from,
        "valid_to": valid_to,
    })

    assert response.status_code == 200, response.text
    db.expire_all()
    current = (
        db.query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.sku_master_id == sku_id)
        .one()
    )
    assert current.ciphertext == original_ciphertext


@pytest.mark.contract
def test_deleting_last_cost_history_entry_keeps_current_cost(authed_client, seeded_db):
    """Regression test: deleting the only remaining cost-history row must not
    delete the live encrypted cost. See products.py delete_cost_history."""
    from app.models.sku import EncryptedSkuCost

    sku_id = seeded_db["sku_a_id"]
    key_version = seeded_db["vault_key_version"]
    db = seeded_db["db"]

    valid_from = date.today().isoformat()
    create_response = authed_client.post(f"/api/v1/products/{sku_id}/cost-history", json={
        "encrypted_cost": {
            "ciphertext": "I" * 64,
            "nonce": "J" * 16,
            "key_version": key_version,
            "aad_context": f"profitos:sku-cost:{sku_id}:history:{valid_from}:v{key_version}",
        },
        "current_encrypted_cost": {
            "ciphertext": "K" * 64,
            "nonce": "L" * 16,
            "key_version": key_version,
            "aad_context": f"profitos:sku-cost:{sku_id}:current:v{key_version}",
        },
        "valid_from": valid_from,
    })
    assert create_response.status_code == 200, create_response.text
    history = create_response.json()["cost_history"]
    assert len(history) == 1
    history_id = history[0]["id"]

    delete_response = authed_client.delete(f"/api/v1/products/{sku_id}/cost-history/{history_id}")
    assert delete_response.status_code == 204, delete_response.text

    db.expire_all()
    current = (
        db.query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.sku_master_id == sku_id)
        .one_or_none()
    )
    assert current is not None, "deleting the last history entry must not delete the current cost"
    assert current.ciphertext == "K" * 64


@pytest.mark.contract
def test_legacy_import_costs_endpoint_returns_410(authed_client):
    response = authed_client.post("/api/v1/products/import-costs", json={"rows": []})
    assert response.status_code == 410
