from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.auth_dep import require_operator
from app.core.config import settings
from app.core.deployment import require_hosted
from app.core.database import get_db
from app.core.session import SESSION_TTL
from app.api.billing import _add_months, _tier_for_orders
from app.models.account import Account
from app.models.raw_data import OrderRaw
from app.models.sku import SkuMaster
from app.models.tenant import Tenant
from app.models.user import ActivationToken, User, UserSession, WaitlistEntry
from app.schemas.strict import StrictMutationModel
from app.services.billing_state import has_paid_plan_acceptance, trial_ends_at
from app.services.email import send_activation_email

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("app.security")


class ApproveWaitlistRequest(StrictMutationModel):
    tenant_name: str = Field(min_length=2, max_length=255)


class RejectWaitlistRequest(StrictMutationModel):
    reason: str = Field(min_length=1, max_length=1000)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:56] or "tenant"


def _unique_slug(db: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    counter = 2
    while db.query(Tenant).filter(Tenant.slug == slug).first():
        suffix = f"-{counter}"
        slug = f"{base[:64 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def _activation_url(raw_token: str) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}/activate?token={raw_token}"


def _created_by_id(db: Session, user: User) -> int:
    if user.id != 0:
        return user.id
    operator = db.query(User).filter(User.is_operator.is_(True), User.id != 0).order_by(User.id.asc()).first()
    if not operator:
        raise HTTPException(400, "A real operator account is required to approve waitlist entries")
    return operator.id


def _waitlist_status(entry: WaitlistEntry) -> str:
    if entry.notes and entry.notes.startswith("#rejected:"):
        return "rejected"
    if entry.approved_at:
        return "approved"
    return "pending"


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _orders_count_for_tenant(db: Session, tenant_id: int, start: date, end: date) -> int:
    return int(
        db.query(func.count(func.distinct(OrderRaw.order_id)))
        .filter(
            OrderRaw.tenant_id == tenant_id,
            OrderRaw.bought_at >= datetime.combine(start, datetime.min.time()),
            OrderRaw.bought_at < datetime.combine(end, datetime.min.time()),
        )
        .scalar()
        or 0
    )


def _trial_ends_at(tenant: Tenant) -> date:
    return trial_ends_at(tenant)


def _estimate_subscription_amount_net(tenant: Tenant, orders_count: int, month_start: date) -> tuple[Decimal, int, int]:
    month_end = _add_months(month_start, 1)
    month_days = (month_end - month_start).days
    if not tenant.is_active:
        return Decimal("0.00"), 0, month_days
    billable_start = max(month_start, _trial_ends_at(tenant))
    if billable_start >= month_end:
        return Decimal("0.00"), 0, month_days
    tier = _tier_for_orders(orders_count)
    billable_days = (month_end - billable_start).days
    amount = (
        Decimal(tier.price_pln) * Decimal(billable_days) / Decimal(month_days)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, billable_days, month_days


@router.get("/waitlist", dependencies=[Depends(require_hosted)])
def list_waitlist(
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    rows = db.query(WaitlistEntry).order_by(WaitlistEntry.created_at.desc()).all()
    filtered = [row for row in rows if status is None or _waitlist_status(row) == status]
    page = filtered[offset : offset + limit]
    return {
        "items": [
            {
                "id": row.id,
                "email": row.email,
                "company": row.company,
                "phone": row.phone,
                "monthly_orders": row.monthly_orders,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "approved_at": row.approved_at.isoformat() if row.approved_at else None,
                "status": _waitlist_status(row),
                "notes": row.notes,
            }
            for row in page
        ],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
    }


@router.post("/waitlist/{entry_id}/approve", dependencies=[Depends(require_hosted)])
def approve_waitlist_entry(
    entry_id: int,
    data: ApproveWaitlistRequest,
    operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    entry = db.get(WaitlistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "waitlist entry not found")
    if entry.approved_at:
        raise HTTPException(409, "waitlist entry already approved")
    if entry.notes and entry.notes.startswith("#rejected:"):
        raise HTTPException(409, "waitlist entry was rejected")

    tenant = Tenant(name=data.tenant_name, slug=_unique_slug(db, data.tenant_name), is_active=True)
    db.add(tenant)
    db.flush()

    raw_token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=7)
    activation = ActivationToken(
        token_hash=_token_hash(raw_token),
        waitlist_entry_id=entry.id,
        tenant_id=tenant.id,
        email=entry.email.lower(),
        created_by_user_id=_created_by_id(db, operator),
        expires_at=expires_at,
    )
    entry.approved_at = _now()
    db.add(activation)
    db.commit()

    activation_url = _activation_url(raw_token)
    activation_email_sent = False
    activation_email_error: str | None = None
    try:
        activation_email_sent = send_activation_email(
            to_email=entry.email.lower(),
            activation_url=activation_url,
            tenant_name=data.tenant_name,
            expires_at=expires_at,
        )
    except Exception as exc:
        activation_email_error = str(exc)
        logger.warning("admin activation_email_failed entry_id=%s email=%s error=%s", entry.id, entry.email, activation_email_error)

    response = {
        "activation_url": activation_url,
        "activation_email_sent": activation_email_sent,
        "expires_at": expires_at.isoformat(),
        "tenant_id": tenant.id,
        "tenant_slug": tenant.slug,
    }
    if activation_email_error:
        response["activation_email_error"] = activation_email_error
    return response


@router.post("/waitlist/{entry_id}/reject", dependencies=[Depends(require_hosted)])
def reject_waitlist_entry(
    entry_id: int,
    data: RejectWaitlistRequest,
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    entry = db.get(WaitlistEntry, entry_id)
    if not entry:
        raise HTTPException(404, "waitlist entry not found")
    if entry.approved_at:
        raise HTTPException(409, "waitlist entry already approved")
    entry.notes = f"#rejected:{data.reason}"
    db.commit()
    return {"status": "rejected"}


@router.get("/tenants", dependencies=[Depends(require_hosted)])
def list_tenants(
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    current_month = _month_start(date.today())
    previous_month = _add_months(current_month, -1)
    next_month = _add_months(current_month, 1)
    rows = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    items = []
    for tenant in rows:
        users_count = db.query(func.count(User.id)).filter(User.tenant_id == tenant.id).scalar() or 0
        accounts_count = db.query(func.count(Account.id)).filter(Account.tenant_id == tenant.id).scalar() or 0
        sku_count = db.query(func.count(SkuMaster.id)).filter(SkuMaster.tenant_id == tenant.id).scalar() or 0
        orders_count = db.query(func.count(func.distinct(OrderRaw.order_id))).filter(OrderRaw.tenant_id == tenant.id).scalar() or 0
        current_month_orders = _orders_count_for_tenant(db, tenant.id, current_month, next_month)
        previous_month_orders = _orders_count_for_tenant(db, tenant.id, previous_month, current_month)
        last_activity_at = db.execute(
            text("""
                SELECT MAX(last_seen_at) FROM user_sessions us
                JOIN users u ON u.id = us.user_id
                WHERE u.tenant_id = :tenant_id
            """),
            {"tenant_id": tenant.id},
        ).scalar()
        items.append({
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "is_active": tenant.is_active,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "users_count": users_count,
            "accounts_count": accounts_count,
            "sku_count": sku_count,
            "orders_count": orders_count,
            "current_month": current_month.isoformat(),
            "previous_month": previous_month.isoformat(),
            "current_month_orders": current_month_orders,
            "previous_month_orders": previous_month_orders,
            "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        })
    return {"items": items}


@router.get("/revenue", dependencies=[Depends(require_hosted)])
def revenue_estimate(
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    current_month = _month_start(date.today())
    previous_month = _add_months(current_month, -1)
    next_month = _add_months(current_month, 1)
    tenants = db.query(Tenant).filter(Tenant.id != 1).order_by(Tenant.created_at.desc()).all()

    def empty_summary() -> dict:
        return {
            "customers_count": 0,
            "billable_customers_count": 0,
            "current_month_orders": 0,
            "previous_month_orders": 0,
            "current_month_estimate_net": "0.00",
            "previous_month_estimate_net": "0.00",
        }

    totals = {
        "all_customers": empty_summary(),
        "active_customers": empty_summary(),
    }
    current_total = Decimal("0.00")
    previous_total = Decimal("0.00")
    current_active_total = Decimal("0.00")
    previous_active_total = Decimal("0.00")
    items = []

    for tenant in tenants:
        current_orders = _orders_count_for_tenant(db, tenant.id, current_month, next_month)
        previous_orders = _orders_count_for_tenant(db, tenant.id, previous_month, current_month)
        current_tier = _tier_for_orders(current_orders)
        previous_tier = _tier_for_orders(previous_orders)
        current_amount, current_billable_days, current_month_days = _estimate_subscription_amount_net(
            tenant, current_orders, current_month
        )
        previous_amount, previous_billable_days, previous_month_days = _estimate_subscription_amount_net(
            tenant, previous_orders, previous_month
        )
        paid_plan_accepted = has_paid_plan_acceptance(db, tenant.id)
        trial_ends = _trial_ends_at(tenant)

        totals["all_customers"]["customers_count"] += 1
        totals["all_customers"]["current_month_orders"] += current_orders
        totals["all_customers"]["previous_month_orders"] += previous_orders
        if current_amount > 0 or previous_amount > 0:
            totals["all_customers"]["billable_customers_count"] += 1
        current_total += current_amount
        previous_total += previous_amount

        if paid_plan_accepted:
            totals["active_customers"]["customers_count"] += 1
            totals["active_customers"]["current_month_orders"] += current_orders
            totals["active_customers"]["previous_month_orders"] += previous_orders
            if current_amount > 0 or previous_amount > 0:
                totals["active_customers"]["billable_customers_count"] += 1
            current_active_total += current_amount
            previous_active_total += previous_amount

        items.append({
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "is_active": tenant.is_active,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
            "trial_ends_at": trial_ends.isoformat(),
            "trial_active": date.today() < trial_ends,
            "paid_plan_accepted": paid_plan_accepted,
            "current_month_orders": current_orders,
            "previous_month_orders": previous_orders,
            "current_month_tier": current_tier.model_dump(),
            "previous_month_tier": previous_tier.model_dump(),
            "current_month_estimate_net": str(current_amount),
            "previous_month_estimate_net": str(previous_amount),
            "current_month_billable_days": current_billable_days,
            "previous_month_billable_days": previous_billable_days,
            "current_month_days": current_month_days,
            "previous_month_days": previous_month_days,
        })

    totals["all_customers"]["current_month_estimate_net"] = str(current_total)
    totals["all_customers"]["previous_month_estimate_net"] = str(previous_total)
    totals["active_customers"]["current_month_estimate_net"] = str(current_active_total)
    totals["active_customers"]["previous_month_estimate_net"] = str(previous_active_total)

    return {
        "current_month": current_month.isoformat(),
        "previous_month": previous_month.isoformat(),
        "pricing_net": True,
        "operator_tenant_excluded": True,
        "active_customer_definition": "accepted_paid_plan_terms",
        "paid_invoice_statuses": [],
        "totals": totals,
        "items": items,
    }


def _set_tenant_active(db: Session, tenant_id: int, active: bool) -> dict:
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.id == 1:
        raise HTTPException(404, "tenant not found")
    tenant.is_active = active
    if not active:
        now = _now()
        sessions = (
            db.query(UserSession)
            .join(User, User.id == UserSession.user_id)
            .filter(User.tenant_id == tenant.id, UserSession.revoked_at.is_(None))
            .all()
        )
        for session in sessions:
            session.revoked_at = now
    db.commit()
    return {"status": "active" if active else "inactive"}


@router.post("/tenants/{tenant_id}/deactivate", dependencies=[Depends(require_hosted)])
def deactivate_tenant(
    tenant_id: int,
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return _set_tenant_active(db, tenant_id, False)


@router.post("/tenants/{tenant_id}/reactivate", dependencies=[Depends(require_hosted)])
def reactivate_tenant(
    tenant_id: int,
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return _set_tenant_active(db, tenant_id, True)


@router.delete("/tenants/{tenant_id}", status_code=204, dependencies=[Depends(require_hosted)])
def hard_delete_tenant(
    tenant_id: int,
    confirm: bool = Query(False),
    slug: str = Query(...),
    operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    if not confirm:
        raise HTTPException(400, "?confirm=true required")
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "tenant not found")
    if tenant.id == 1:
        raise HTTPException(403, "Operator tenant cannot be deleted")
    if tenant.slug != slug:
        raise HTTPException(400, "slug confirmation does not match")

    db.execute(
        text("""
            UPDATE user_sessions SET revoked_at = now()
            WHERE revoked_at IS NULL
            AND user_id IN (SELECT id FROM users WHERE tenant_id = :tid)
        """),
        {"tid": tenant.id},
    )
    db.query(ActivationToken).filter(ActivationToken.tenant_id == tenant.id).delete(synchronize_session=False)
    db.query(User).filter(User.tenant_id == tenant.id).delete(synchronize_session=False)

    from app.services.cleanup import _hard_delete_tenant_data

    _hard_delete_tenant_data(db, tenant.id)
    db.commit()
    logger.info("admin hard_delete_tenant tenant_id=%s slug=%s by_user=%s", tenant_id, slug, operator.email)


@router.get("/system-health")
def system_health(
    _operator: User = Depends(require_operator),
    db: Session = Depends(get_db),
):
    tenants_count = db.query(func.count(Tenant.id)).scalar()
    users_count = db.query(func.count(User.id)).scalar()
    now = _now()
    active_sessions = db.query(func.count(func.distinct(UserSession.user_id))).filter(
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now,
        UserSession.last_seen_at > now - SESSION_TTL,
    ).scalar()
    pending_activations = db.query(func.count(ActivationToken.id)).filter(
        ActivationToken.used_at.is_(None),
        ActivationToken.revoked_at.is_(None),
        ActivationToken.expires_at > _now(),
    ).scalar()
    pending_waitlist = db.query(func.count(WaitlistEntry.id)).filter(
        WaitlistEntry.approved_at.is_(None),
    ).scalar()
    last_sync = db.execute(text("SELECT MAX(synced_at) FROM sync_log")).scalar()

    try:
        db_ok = db.execute(text("SELECT 1")).scalar() == 1
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "tenants_count": tenants_count,
        "users_count": users_count,
        "active_sessions": active_sessions,
        "pending_activations": pending_activations,
        "pending_waitlist": pending_waitlist,
        "last_sync_at": last_sync.isoformat() if last_sync else None,
        "checked_at": _now().isoformat(),
    }
