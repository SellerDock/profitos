from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.core.tenant import TenantScope, get_scope
from app.models.sku import EncryptedSkuCost, FinancialVault, SkuMaster

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/crypto-proof")
def crypto_proof():
    return {
        "verifiable": {
            "cryptoVersion": settings.crypto_version,
            "sourceRepo": settings.crypto_repo_url,
            "sourceCommit": settings.crypto_source_commit,
            "releaseUrl": settings.crypto_release_url,
            "bundleSha256": settings.crypto_bundle_sha256,
            "bundleSri": settings.crypto_bundle_sri,
            "bundleUrl": f"/static/crypto/profitos-crypto-v{settings.crypto_version}.js",
            "algorithm": "AES-256-GCM",
            "kdf": "argon2id",
            "argon2idParams": {
                "memoryCost": 131072,
                "timeCost": 4,
                "parallelism": 1,
            },
            "decryptToolUrl": settings.crypto_decrypt_html_url,
            "decryptToolSha256": settings.crypto_decrypt_html_sha256,
        },
        "operatorStatement": {
            "text": (
                "Serwer nie przechowuje plaintextu kosztów ani klucza szyfrującego. "
                "Klucz jest derived z hasła użytkownika w przeglądarce. Opcjonalny "
                "endpoint integracyjny POST /api/v1/integrations/profit-by-ean jest "
                "domyślnie wyłączony i działa tylko, gdy administrator instalacji włączy "
                "VAULT_SERVER_DECRYPTION_ENABLED. Endpoint może "
                "odszyfrować koszty po stronie serwera, ale tylko wtedy, gdy klient "
                "przekaże kod skarbca w treści każdego żądania; klucz i odszyfrowane "
                "koszty istnieją wyłącznie w pamięci pojedynczego żądania i nigdy nie "
                "są zapisywane ani logowane."
            ),
            "note": (
                "To deklaracja operatora. Weryfikowalne dowody w polu verifiable "
                "oraz w publicznym repozytorium."
            ),
        },
    }


@router.get("/encrypted-cost-export/{sku_master_id}")
def export_encrypted_cost(
    sku_master_id: int,
    scope: TenantScope = Depends(get_scope),
):
    sku = scope.db.get(SkuMaster, sku_master_id)
    scope.assert_owns(sku)
    cost = (
        scope.db.query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.tenant_id == scope.tenant_id, EncryptedSkuCost.sku_master_id == sku_master_id)
        .first()
    )
    if not cost:
        raise HTTPException(404, "no encrypted cost recorded")
    vault = scope.db.get(FinancialVault, cost.vault_id)
    if not vault:
        raise HTTPException(500, "vault metadata missing")
    scope.assert_owns(vault)
    return {
        "envelope": {
            "v": 1,
            "alg": "AES-256-GCM",
            "kdf": "argon2id",
            "kdfParams": {
                "memoryCost": vault.memory_cost,
                "timeCost": vault.time_cost,
                "parallelism": vault.parallelism,
            },
            "salt": vault.salt,
            "iv": cost.nonce,
            "ct": cost.ciphertext,
            "aad": cost.aad_context,
            "keyVersion": cost.key_version,
        },
        "sku": {"id": sku.id, "sku_key": sku.sku_key, "name": sku.name},
        "note": f"Aby odszyfrować lokalnie pobierz {settings.crypto_decrypt_html_url} i wklej powyższy envelope.",
    }
