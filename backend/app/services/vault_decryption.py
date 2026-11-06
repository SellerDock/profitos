from __future__ import annotations

import base64
from binascii import Error as Base64DecodeError
from decimal import Decimal, InvalidOperation

from argon2.exceptions import HashingError
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.models.sku import EncryptedSkuCost, FinancialVault

# Must stay in sync with frontend/src/crypto/financialVault.ts.
VAULT_VERIFIER_AAD = "profitos:vault-verifier:v1"
VAULT_VERIFIER_PLAINTEXT = "profitos-financial-vault-v1"

_KEY_BYTES = 32  # AES-256


class FinancialVaultError(Exception):
    """Base error for Financial Vault decryption failures. Never carries secrets."""


class VaultWrongPasswordError(FinancialVaultError):
    """The supplied financial password did not unlock the vault."""


class VaultMalformedError(FinancialVaultError):
    """Vault or SKU cost envelope is malformed or fails integrity checks."""


class VaultKeyVersionError(VaultMalformedError):
    """The SKU cost envelope key_version does not match the vault key_version."""


def derive_financial_key(password: str, vault: FinancialVault) -> bytes:
    """Derive the 256-bit AES key once from the vault Argon2id metadata.

    Returns a raw key intended to be reused for verifier check and envelope
    decryption. The derived key is never logged or returned to callers that
    would persist it in plaintext.
    """
    if vault.kdf != "argon2id":
        raise VaultMalformedError("unsupported vault KDF")
    if not vault.salt:
        raise VaultMalformedError("vault salt is missing")
    if not (vault.memory_cost and vault.time_cost and vault.parallelism):
        raise VaultMalformedError("vault KDF parameters are incomplete")
    try:
        salt = base64.b64decode(vault.salt, altchars=b"-_", validate=True)
    except (Base64DecodeError, ValueError, TypeError) as exc:
        raise VaultMalformedError("vault salt is not valid base64") from exc
    if not salt:
        raise VaultMalformedError("vault salt is empty")
    try:
        return hash_secret_raw(
            password.encode("utf-8"),
            salt,
            time_cost=vault.time_cost,
            memory_cost=vault.memory_cost,
            parallelism=vault.parallelism,
            hash_len=_KEY_BYTES,
            type=Type.ID,
        )
    except HashingError as exc:
        raise VaultMalformedError("vault KDF parameters are invalid") from exc


def verify_financial_vault_key(key: bytes, vault: FinancialVault) -> bool:
    """Verify the derived key against the vault verifier payload."""
    try:
        plaintext = _aesgcm_decrypt(key, vault.verify_nonce, vault.verify_ciphertext, VAULT_VERIFIER_AAD)
    except VaultMalformedError:
        return False
    return plaintext == VAULT_VERIFIER_PLAINTEXT


def decrypt_sku_cost(password: str, vault: FinancialVault, encrypted: EncryptedSkuCost) -> Decimal:
    """Decrypt the current SKU cost with the vault-derived key.

    Derives the key once, verifies it against the vault verifier, then
    decrypts the envelope bound to its own aad_context. Raises safe
    exceptions that never contain the password, the key, or plaintext.
    """
    key = derive_financial_key(password, vault)
    if not verify_financial_vault_key(key, vault):
        raise VaultWrongPasswordError("incorrect financial vault password")
    return decrypt_sku_cost_with_key(key, vault, encrypted)


def decrypt_sku_cost_with_key(key: bytes, vault: FinancialVault, encrypted: EncryptedSkuCost) -> Decimal:
    """Decrypt one cost after the caller has verified the key once per batch."""
    if encrypted.key_version != vault.key_version:
        raise VaultKeyVersionError("SKU cost envelope key version does not match the vault")
    plaintext = _aesgcm_decrypt(key, encrypted.nonce, encrypted.ciphertext, encrypted.aad_context)
    try:
        cost = Decimal(plaintext.strip())
    except InvalidOperation as exc:
        raise VaultMalformedError("SKU cost envelope plaintext is not a valid cost") from exc
    if not cost.is_finite() or cost < 0:
        raise VaultMalformedError("SKU cost envelope plaintext is not a valid cost")
    return cost


def _aesgcm_decrypt(key: bytes, nonce_b64: str, ciphertext_b64: str, aad: str) -> str:
    """Decrypt an AES-256-GCM envelope. Raises VaultMalformedError on bad input."""
    if key is None or len(key) != _KEY_BYTES:
        raise VaultMalformedError("invalid derived key length")
    nonce = _decode_b64(nonce_b64, "nonce")
    ciphertext = _decode_b64(ciphertext_b64, "ciphertext")
    if len(nonce) != 12 or len(ciphertext) < 16:
        raise VaultMalformedError("envelope fields are invalid")
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8"))
    except InvalidTag as exc:
        raise VaultMalformedError("envelope failed authentication") from exc
    except ValueError as exc:
        raise VaultMalformedError("envelope fields are invalid") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VaultMalformedError("envelope plaintext is not valid UTF-8") from exc


def _decode_b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, altchars=b"-_", validate=True)
    except (Base64DecodeError, TypeError, ValueError) as exc:
        raise VaultMalformedError(f"envelope {field} is not valid base64") from exc