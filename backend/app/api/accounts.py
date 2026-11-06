from fastapi import APIRouter, Depends
from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.sku import SkuAlias
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/", response_model=list[AccountRead])
def list_accounts(scope: TenantScope = Depends(get_scope)):
    accounts = scope.db.query(Account).filter(Account.tenant_id == scope.tenant_id).all()
    return [AccountRead.from_orm_with_status(a) for a in accounts]


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(data: AccountCreate, scope: TenantScope = Depends(get_scope)):
    account = Account(**data.model_dump(), tenant_id=scope.tenant_id)
    scope.db.add(account)
    scope.db.commit()
    scope.db.refresh(account)
    return AccountRead.from_orm_with_status(account)


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    return AccountRead.from_orm_with_status(account)


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(account_id: int, data: AccountUpdate, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    scope.db.commit()
    scope.db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    # sku_aliases.account_id has no ON DELETE CASCADE; drop them first or the delete fails with an FK error.
    scope.db.query(SkuAlias).filter(
        SkuAlias.tenant_id == scope.tenant_id,
        SkuAlias.account_id == account.id,
    ).delete(synchronize_session=False)
    scope.db.delete(account)
    scope.db.commit()
