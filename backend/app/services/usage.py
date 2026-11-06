from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.billing_profile import TenantSubscription
from app.models.raw_data import OrderRaw
from app.models.tenant import Tenant
from app.services.pricing import PRICING_TIERS


def orders_in_range(db: Session, tenant_id: int, start: date, end: date) -> int:
    return int(db.query(func.count(func.distinct(OrderRaw.order_id))).filter(
        OrderRaw.tenant_id == tenant_id,
        OrderRaw.bought_at >= datetime.combine(start, datetime.min.time()),
        OrderRaw.bought_at < datetime.combine(end, datetime.min.time()),
    ).scalar() or 0)


def pool_used(db: Session, tenant: Tenant) -> int:
    return int(db.query(func.count(func.distinct(OrderRaw.order_id))).filter(
        OrderRaw.tenant_id == tenant.id, OrderRaw.bought_at >= tenant.created_at,
    ).scalar() or 0)


def pool_remaining(db: Session, tenant: Tenant) -> int:
    return max(0, tenant.free_pool_orders - pool_used(db, tenant))


def active_subscription(db: Session, tenant_id: int, today: date) -> TenantSubscription | None:
    return db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id, TenantSubscription.status == "active",
        TenantSubscription.period_start <= today, TenantSubscription.period_end >= today,
    ).first()


def _month_offset(value: date, offset: int) -> date:
    month = value.year * 12 + value.month - 1 + offset
    return date(month // 12, month % 12 + 1, 1)


def usage_state(db: Session, tenant: Tenant, today: date) -> dict:
    used = pool_used(db, tenant)
    remaining = max(0, tenant.free_pool_orders - used)
    active = active_subscription(db, tenant.id, today)
    pending = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant.id,
        TenantSubscription.status.in_(("pending_invoice", "invoiced")),
    ).first()
    tier = next((tier for tier in PRICING_TIERS if active and tier.code == active.tier_code), None)
    limit = tier.max_orders if tier and tier.max_orders is not None else 200
    # A custom plan has no predefined ceiling.
    if tier and tier.is_custom:
        limit = None
    month = today.replace(day=1)
    count = orders_in_range(db, tenant.id, month, _month_offset(month, 1))
    previous = [orders_in_range(db, tenant.id, _month_offset(month, offset), _month_offset(month, offset + 1)) for offset in (-2, -1)]
    suggest = remaining == 0 and limit is not None and all(value > limit for value in previous)
    suggested = next((tier.code for tier in PRICING_TIERS if tier.billing_period == "year" and (tier.max_orders is None or max(previous) <= tier.max_orders)), None) if suggest else None
    return {
        "scheme": tenant.billing_scheme, "pool_total": tenant.free_pool_orders,
        "pool_used": used, "pool_remaining": remaining, "pool_active": remaining > 0,
        "month": month.strftime("%Y-%m"), "month_orders": count,
        "monthly_limit": None if remaining > 0 else limit,
        "over_limit": remaining == 0 and limit is not None and count > limit,
        "active_subscription": {"tier_code": active.tier_code, "period_start": active.period_start.isoformat(), "period_end": active.period_end.isoformat()} if active else None,
        "pending_subscription": {"id": pending.id, "tier_code": pending.tier_code, "status": pending.status, "invoice_number": pending.invoice_number} if pending else None,
        "upgrade_suggested": suggest, "suggested_tier_code": suggested,
    }
