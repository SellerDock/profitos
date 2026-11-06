from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func

from app.core.tenant import TenantScope, get_scope
from app.models.sku import EncryptedSkuCost, EncryptedSkuCostHistory, FinancialVault
from app.schemas.strict import StrictMutationModel

router = APIRouter(prefix="/financial-vault", tags=["financial-vault"])

_SCOPE = "global"


class VaultSetup(StrictMutationModel):
    salt: str
    memory_cost: int = Field(gt=0)
    time_cost: int = Field(gt=0)
    parallelism: int = Field(gt=0)
    verify_nonce: str
    verify_ciphertext: str
    key_version: int = Field(default=1, gt=0)


def _vault_to_dict(vault: FinancialVault | None, scope: TenantScope) -> dict:
    if not vault:
        return {"configured": False}

    encrypted_costs = (
        scope.db.query(func.count(EncryptedSkuCost.id))
        .filter(EncryptedSkuCost.tenant_id == scope.tenant_id)
        .scalar()
        or 0
    )
    encrypted_history = (
        scope.db.query(func.count(EncryptedSkuCostHistory.id))
        .filter(EncryptedSkuCostHistory.tenant_id == scope.tenant_id)
        .scalar()
        or 0
    )
    return {
        "configured": True,
        "id": vault.id,
        "scope": vault.scope,
        "kdf": vault.kdf,
        "salt": vault.salt,
        "memory_cost": vault.memory_cost,
        "time_cost": vault.time_cost,
        "parallelism": vault.parallelism,
        "verify_nonce": vault.verify_nonce,
        "verify_ciphertext": vault.verify_ciphertext,
        "key_version": vault.key_version,
        "encrypted_costs": encrypted_costs,
        "encrypted_history": encrypted_history,
    }


@router.get("/status")
def vault_status(scope: TenantScope = Depends(get_scope)):
    vault = (
        scope.db.query(FinancialVault)
        .filter(FinancialVault.tenant_id == scope.tenant_id, FinancialVault.scope == _SCOPE)
        .first()
    )
    return _vault_to_dict(vault, scope)


@router.post("/setup", status_code=201)
def setup_vault(data: VaultSetup, scope: TenantScope = Depends(get_scope)):
    existing = (
        scope.db.query(FinancialVault)
        .filter(FinancialVault.tenant_id == scope.tenant_id, FinancialVault.scope == _SCOPE)
        .first()
    )
    if existing:
        raise HTTPException(409, "Financial vault already exists")

    vault = FinancialVault(
        tenant_id=scope.tenant_id,
        scope=_SCOPE,
        kdf="argon2id",
        salt=data.salt,
        memory_cost=data.memory_cost,
        time_cost=data.time_cost,
        parallelism=data.parallelism,
        verify_nonce=data.verify_nonce,
        verify_ciphertext=data.verify_ciphertext,
        key_version=data.key_version,
    )
    scope.db.add(vault)
    scope.db.commit()
    scope.db.refresh(vault)
    return _vault_to_dict(vault, scope)
