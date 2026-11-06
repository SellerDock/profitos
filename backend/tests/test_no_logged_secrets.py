import logging

import pytest

SENSITIVE_TOKENS = (
    "ciphertext",
    "verify_ciphertext",
    "verify_nonce",
    "aad_context",
    "salt",
)


@pytest.mark.contract
def test_setup_vault_does_not_log_payload(authed_client, seeded_db, caplog):
    payload = {
        "salt": "AAAA" * 4,
        "memory_cost": 65536,
        "time_cost": 3,
        "parallelism": 1,
        "verify_ciphertext": "BBBB" * 8,
        "verify_nonce": "CCCC" * 4,
        "key_version": 1,
    }

    with caplog.at_level(logging.DEBUG):
        response = authed_client.post("/api/v1/financial-vault/setup", json=payload)

    assert response.status_code in (200, 201, 400, 409), response.text
    blob = caplog.text
    for token in (payload["verify_ciphertext"], payload["verify_nonce"], payload["salt"]):
        assert token not in blob, f"sensitive token leaked into logs: {token[:8]}..."


@pytest.mark.contract
def test_encrypted_cost_patch_does_not_log_payload(authed_client, seeded_db, caplog):
    sku_id = seeded_db["sku_b_id"]
    payload = {
        "encrypted_cost": {
            "ciphertext": "D" * 64,
            "nonce": "E" * 16,
            "key_version": 1,
            "aad_context": f"profitos:sku-cost:{sku_id}:current:v1",
        },
    }

    with caplog.at_level(logging.DEBUG):
        authed_client.patch(f"/api/v1/products/{sku_id}", json=payload)

    assert payload["encrypted_cost"]["ciphertext"] not in caplog.text
    assert payload["encrypted_cost"]["nonce"] not in caplog.text
