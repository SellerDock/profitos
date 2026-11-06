from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.config import is_selfhosted
from app.models.billing_profile import TenantPaidPlanAcceptance
from app.models.tenant import Tenant


def trial_ends_at(tenant: Tenant, today: date | None = None) -> date:
    anchor = today or date.today()
    trial_started = tenant.created_at.date() if tenant.created_at else anchor
    return trial_started + timedelta(days=30)


def has_paid_plan_acceptance(db: Session, tenant_id: int) -> bool:
    return bool(
        db.query(TenantPaidPlanAcceptance.id)
        .filter(TenantPaidPlanAcceptance.tenant_id == tenant_id)
        .first()
    )


def imports_allowed(db: Session, tenant: Tenant, today: date | None = None) -> bool:
    if not tenant.is_active:
        return False
    if is_selfhosted():
        return True
    anchor = today or date.today()
    if anchor < trial_ends_at(tenant, anchor):
        return True
    return has_paid_plan_acceptance(db, tenant.id)
