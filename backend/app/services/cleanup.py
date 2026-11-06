from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.user import ActivationToken, User, UserSession, WaitlistEntry


TENANT_TABLES_IN_DELETE_ORDER = [
    "encrypted_sku_cost_history",
    "encrypted_sku_costs",
    "financial_vaults",
    "sku_aliases",
    "sku_masters",
    "allegro_ads_imports",
    "sync_log",
    "account_import_state",
    "customer_return_items_raw",
    "customer_returns_raw",
    "payment_refund_line_items_raw",
    "payment_refunds_raw",
    "order_events_raw",
    "orders_raw",
    "billing_raw",
    "offers_cache",
    "stock_levels",
    "stock_settings",
    "accounts",
]


def _hard_delete_user(db: Session, user: User, also_delete_tenant: bool) -> None:
    """Cascade-delete one user. Optionally delete the tenant if user was last."""
    tenant_id = user.tenant_id
    db.query(UserSession).filter(UserSession.user_id == user.id).delete(synchronize_session=False)
    db.execute(
        text("UPDATE activation_tokens SET created_by_user_id = NULL WHERE created_by_user_id = :uid"),
        {"uid": user.id},
    )
    db.query(ActivationToken).filter(ActivationToken.email == user.email).delete(synchronize_session=False)
    db.query(WaitlistEntry).filter(WaitlistEntry.email == user.email).delete(synchronize_session=False)
    db.delete(user)
    db.flush()

    if also_delete_tenant:
        _hard_delete_tenant_data(db, tenant_id)

    db.commit()


def _hard_delete_tenant_data(db: Session, tenant_id: int) -> None:
    """Delete all operational data for a tenant.

    Order matters: leaf tables first, tenant root last.
    """
    if tenant_id == 1:
        raise HTTPException(403, "Operator tenant cannot be deleted")

    db.query(ActivationToken).filter(ActivationToken.tenant_id == tenant_id).delete(synchronize_session=False)

    for table in TENANT_TABLES_IN_DELETE_ORDER:
        db.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})

    db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
