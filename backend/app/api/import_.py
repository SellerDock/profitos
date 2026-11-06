from fastapi import APIRouter, Depends, HTTPException

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.raw_data import SyncLog
from app.services.import_service import ImportService

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/sync/{account_id}")
def sync_account(account_id: int, days: int = 90, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    if not account.access_token:
        raise HTTPException(status_code=400, detail="Account not connected to Allegro — run OAuth first")

    service = ImportService(scope.db)
    result = service.sync_account(account_id, days=days)

    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    return result.to_dict()


@router.get("/status")
def get_sync_status(scope: TenantScope = Depends(get_scope)):
    """Return last sync log entry per account."""
    accounts = (
        scope.db.query(Account)
        .filter(Account.tenant_id == scope.tenant_id, Account.access_token.isnot(None))
        .all()
    )
    out = []
    for account in accounts:
        last = (
            scope.db.query(SyncLog)
            .filter(SyncLog.tenant_id == scope.tenant_id, SyncLog.account_id == account.id)
            .order_by(SyncLog.synced_at.desc())
            .first()
        )
        out.append({
            "account_id": account.id,
            "account_name": account.name,
            "color": account.color,
            "is_connected": True,
            "last_sync": {
                "synced_at": last.synced_at.isoformat() if last else None,
                "days_fetched": last.days_fetched if last else None,
                "orders_count": last.orders_count if last else 0,
                "billing_count": last.billing_count if last else 0,
                "offers_count": last.offers_count if last else 0,
                "error": last.error if last else None,
            } if last else None,
        })
    return out
