import base64
import logging
import os
from decimal import Decimal

import pytest
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models.sku import EncryptedSkuCost, FinancialVault
from app.services.vault_decryption import (
    VAULT_VERIFIER_AAD,
    VAULT_VERIFIER_PLAINTEXT,
    VaultKeyVersionError,
    VaultMalformedError,
    VaultWrongPasswordError,
    decrypt_sku_cost,
    decrypt_sku_cost_with_key,
    derive_financial_key,
    verify_financial_vault_key,
)

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "not-the-vault-password"
COST = "129.99"
SKU_ID = 42
KEY_VERSION = 1

# Low memory/time Argon2id parameters keep the synthetic vectors fast while
# staying compatible with the frontend default (argon2id, 256-bit key).
MEMORY_COST = 65536
TIME_COST = 2
PARALLELISM = 1


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


def _sku_cost_aad(sku_id: int = SKU_ID, key_version: int = KEY_VERSION) -> str:
    return f"profitos:sku-cost:{sku_id}:current:v{key_version}"


@pytest.fixture
def vault_and_envelope():
    salt = os.urandom(16)
    key = _derive_key(PASSWORD, salt)

    verify_ciphertext, verify_nonce = _aesgcm_encrypt(
        key, VAULT_VERIFIER_PLAINTEXT, VAULT_VERIFIER_AAD
    )
    vault = FinancialVault(
        kdf="argon2id",
        salt=base64.b64encode(salt).decode("ascii"),
        memory_cost=MEMORY_COST,
        time_cost=TIME_COST,
        parallelism=PARALLELISM,
        verify_nonce=verify_nonce,
        verify_ciphertext=verify_ciphertext,
        key_version=KEY_VERSION,
    )

    aad = _sku_cost_aad()
    cost_ciphertext, cost_nonce = _aesgcm_encrypt(key, COST, aad)
    envelope = EncryptedSkuCost(
        ciphertext=cost_ciphertext,
        nonce=cost_nonce,
        key_version=KEY_VERSION,
        aad_context=aad,
    )
    return vault, envelope


def test_decrypts_current_sku_cost_with_good_password(vault_and_envelope):
    vault, envelope = vault_and_envelope
    assert decrypt_sku_cost(PASSWORD, vault, envelope) == Decimal(COST)


def test_derived_key_is_deterministic(vault_and_envelope):
    vault, _ = vault_and_envelope
    assert derive_financial_key(PASSWORD, vault) == derive_financial_key(PASSWORD, vault)


def test_verify_key_accepts_only_the_vault_key(vault_and_envelope):
    vault, _ = vault_and_envelope
    assert verify_financial_vault_key(derive_financial_key(PASSWORD, vault), vault) is True
    assert verify_financial_vault_key(derive_financial_key(WRONG_PASSWORD, vault), vault) is False


def test_wrong_password_raises_safe_error(vault_and_envelope, caplog):
    vault, envelope = vault_and_envelope
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(VaultWrongPasswordError) as excinfo:
            decrypt_sku_cost(WRONG_PASSWORD, vault, envelope)
    message = str(excinfo.value)
    for secret in (PASSWORD, WRONG_PASSWORD, COST, VAULT_VERIFIER_PLAINTEXT,
                   vault.salt, vault.verify_ciphertext, vault.verify_nonce,
                   envelope.ciphertext, envelope.nonce):
        assert secret not in message
        assert secret not in caplog.text


def test_bad_aad_raises_safe_error(vault_and_envelope):
    vault, envelope = vault_and_envelope
    envelope.aad_context = _sku_cost_aad(sku_id=999)
    with pytest.raises(VaultMalformedError) as excinfo:
        decrypt_sku_cost(PASSWORD, vault, envelope)
    assert COST not in str(excinfo.value)


def test_key_version_mismatch_raises_safe_error(vault_and_envelope):
    vault, envelope = vault_and_envelope
    envelope.key_version = KEY_VERSION + 1
    with pytest.raises(VaultKeyVersionError) as excinfo:
        decrypt_sku_cost(PASSWORD, vault, envelope)
    assert COST not in str(excinfo.value)


def test_malformed_envelope_base64_raises_safe_error(vault_and_envelope):
    vault, envelope = vault_and_envelope
    envelope.ciphertext = "!!!not-base64!!!"
    with pytest.raises(VaultMalformedError) as excinfo:
        decrypt_sku_cost(PASSWORD, vault, envelope)
    assert COST not in str(excinfo.value)


def test_malformed_vault_salt_raises_safe_error(vault_and_envelope):
    vault, envelope = vault_and_envelope
    vault.salt = "!!!not-base64!!!"
    with pytest.raises(VaultMalformedError) as excinfo:
        decrypt_sku_cost(PASSWORD, vault, envelope)
    assert COST not in str(excinfo.value)


def test_no_secret_or_plaintext_is_logged(vault_and_envelope, caplog):
    vault, envelope = vault_and_envelope
    with caplog.at_level(logging.DEBUG):
        decrypt_sku_cost(PASSWORD, vault, envelope)
        try:
            decrypt_sku_cost(WRONG_PASSWORD, vault, envelope)
        except VaultWrongPasswordError:
            pass
    for secret in (PASSWORD, WRONG_PASSWORD, COST, VAULT_VERIFIER_PLAINTEXT,
                   vault.salt, vault.verify_ciphertext, vault.verify_nonce,
                   envelope.ciphertext, envelope.nonce):
        assert secret not in caplog.text


@pytest.mark.parametrize("invalid_cost", ["NaN", "Infinity", "-1"])
def test_rejects_nonfinite_or_negative_cost(vault_and_envelope, invalid_cost):
    vault, envelope = vault_and_envelope
    key = derive_financial_key(PASSWORD, vault)
    envelope.ciphertext, envelope.nonce = _aesgcm_encrypt(
        key, invalid_cost, envelope.aad_context
    )
    with pytest.raises(VaultMalformedError):
        decrypt_sku_cost_with_key(key, vault, envelope)


def test_batch_can_reuse_verified_key(vault_and_envelope):
    vault, envelope = vault_and_envelope
    key = derive_financial_key(PASSWORD, vault)
    assert verify_financial_vault_key(key, vault)
    assert decrypt_sku_cost_with_key(key, vault, envelope) == Decimal(COST)
    assert decrypt_sku_cost_with_key(key, vault, envelope) == Decimal(COST)
