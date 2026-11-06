from fastapi import APIRouter, Depends
from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.sku import SkuMaster, SkuAlias
from app.schemas.sku import (
    SkuMasterCreate, SkuMasterRead, SkuMasterUpdate,
    SkuAliasCreate, SkuAliasRead, SkuAliasUpdate,
)

router = APIRouter(tags=["skus"])

masters = APIRouter(prefix="/sku-masters")
aliases = APIRouter(prefix="/sku-aliases")


@masters.get("/", response_model=list[SkuMasterRead])
def list_masters(scope: TenantScope = Depends(get_scope)):
    return scope.db.query(SkuMaster).filter(SkuMaster.tenant_id == scope.tenant_id).all()


@masters.post("/", response_model=SkuMasterRead, status_code=201)
def create_master(data: SkuMasterCreate, scope: TenantScope = Depends(get_scope)):
    sku = SkuMaster(**data.model_dump(), tenant_id=scope.tenant_id)
    scope.db.add(sku)
    scope.db.commit()
    scope.db.refresh(sku)
    return sku


@masters.get("/{sku_id}", response_model=SkuMasterRead)
def get_master(sku_id: int, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    return sku


@masters.patch("/{sku_id}", response_model=SkuMasterRead)
def update_master(sku_id: int, data: SkuMasterUpdate, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sku, field, value)
    scope.db.commit()
    scope.db.refresh(sku)
    return sku


@masters.delete("/{sku_id}", status_code=204)
def delete_master(sku_id: int, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    scope.db.delete(sku)
    scope.db.commit()


@aliases.get("/", response_model=list[SkuAliasRead])
def list_aliases(scope: TenantScope = Depends(get_scope)):
    return scope.db.query(SkuAlias).filter(SkuAlias.tenant_id == scope.tenant_id).all()


@aliases.post("/", response_model=SkuAliasRead, status_code=201)
def create_alias(data: SkuAliasCreate, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, data.sku_master_id)
    scope.assert_owns(sku)
    account = scope.db.get(Account, data.account_id)
    scope.assert_owns(account)
    alias = SkuAlias(**data.model_dump(), tenant_id=scope.tenant_id)
    scope.db.add(alias)
    scope.db.commit()
    scope.db.refresh(alias)
    return alias


@aliases.get("/{alias_id}", response_model=SkuAliasRead)
def get_alias(alias_id: int, scope: TenantScope = Depends(get_scope)):
    alias = scope.db.get(SkuAlias, alias_id)
    scope.assert_owns(alias)
    return alias


@aliases.patch("/{alias_id}", response_model=SkuAliasRead)
def update_alias(alias_id: int, data: SkuAliasUpdate, scope: TenantScope = Depends(get_scope)):
    alias = scope.db.get(SkuAlias, alias_id)
    scope.assert_owns(alias)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(alias, field, value)
    scope.db.commit()
    scope.db.refresh(alias)
    return alias


@aliases.delete("/{alias_id}", status_code=204)
def delete_alias(alias_id: int, scope: TenantScope = Depends(get_scope)):
    alias = scope.db.get(SkuAlias, alias_id)
    scope.assert_owns(alias)
    scope.db.delete(alias)
    scope.db.commit()


router.include_router(masters)
router.include_router(aliases)
