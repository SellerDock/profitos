from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import is_selfhosted
from app.core.deployment import require_hosted
from app.core.tenant import TenantScope, get_scope
from app.core.database import get_db
from app.core.legal import TERMS_VERSION
from app.models.billing_profile import TenantBillingProfile, TenantInvoice, TenantPaidPlanAcceptance, TenantSubscription
from app.models.raw_data import BillingTypeLabel
from app.models.tenant import Tenant
from app.schemas.strict import StrictMutationModel
from app.services.billing_state import has_paid_plan_acceptance, imports_allowed, trial_ends_at
from app.services.email import send_subscription_request_admin_email
from app.services.pricing import PRICING_TIERS, PricingTier
from app.services.usage import orders_in_range, usage_state

router = APIRouter(prefix="/billing", tags=["billing"])


class BillingProfilePayload(StrictMutationModel):
    company_name: str | None = None
    nip: str | None = None
    regon: str | None = None
    krs: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str = "PL"
    invoice_email: str | None = None
    vat_status: str | None = None


class PaidPlanAcceptancePayload(StrictMutationModel):
    terms_accepted: bool
    terms_version: str


@router.get("/types")
def list_billing_types(db: Session = Depends(get_db)):
    """Return all known billing type codes with Polish names from DB."""
    rows = db.query(BillingTypeLabel).order_by(BillingTypeLabel.type_id).all()
    return {r.type_id: r.name_pl for r in rows}


@router.get("/profile", dependencies=[Depends(require_hosted)])
def get_billing_profile(scope: TenantScope = Depends(get_scope)):
    profile = _get_profile(scope)
    return _profile_payload(profile)


@router.put("/profile", dependencies=[Depends(require_hosted)])
def update_billing_profile(data: BillingProfilePayload, scope: TenantScope = Depends(get_scope)):
    profile = _get_profile(scope)
    for field, value in data.model_dump().items():
        if field == "nip" and value:
            value = _clean_nip(value)
        setattr(profile, field, value)
    scope.db.commit()
    scope.db.refresh(profile)
    return _profile_payload(profile)


@router.get("/vat-lookup/{nip}", dependencies=[Depends(require_hosted)])
def vat_lookup(
    nip: str,
    lookup_date: date = Query(default_factory=date.today),
):
    clean_nip = _clean_nip(nip)
    if len(clean_nip) != 10:
        raise HTTPException(400, "NIP powinien mieć 10 cyfr")
    url = f"https://wl-api.mf.gov.pl/api/search/nip/{clean_nip}"
    try:
        response = httpx.get(url, params={"date": lookup_date.isoformat()}, timeout=10)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "Nie znaleziono firmy dla tego NIP")
        raise HTTPException(502, "Nie udało się pobrać danych z wykazu VAT")
    except httpx.HTTPError:
        raise HTTPException(502, "Nie udało się połączyć z wykazem VAT")

    subject = ((response.json() or {}).get("result") or {}).get("subject") or {}
    if not subject:
        raise HTTPException(404, "Nie znaleziono firmy dla tego NIP")
    address = _split_address(subject.get("workingAddress") or subject.get("residenceAddress") or "")
    return {
        "company_name": subject.get("name"),
        "nip": subject.get("nip") or clean_nip,
        "regon": subject.get("regon"),
        "krs": subject.get("krs"),
        "vat_status": subject.get("statusVat"),
        **address,
        "country": "PL",
    }


@router.get("/subscription")
def subscription(scope: TenantScope = Depends(get_scope)):
    tenant = scope.db.get(Tenant, scope.tenant_id)
    if not tenant:
        raise HTTPException(404, "tenant not found")
    if is_selfhosted():
        return {
            "deployment_mode": "selfhosted",
            "billing_scheme": None,
            "usage": None,
            "trial_started_at": None,
            "trial_ends_at": None,
            "trial_active": None,
            "terms_version": None,
            "paid_plan_accepted": None,
            "imports_paused": False,
            "current_month": None,
            "current_month_orders": None,
            "previous_month": None,
            "previous_month_orders": None,
            "current_tier": None,
            "pricing": [],
            "invoices": [],
        }
    today = date.today()
    current_month = today.replace(day=1)
    previous_month = _add_months(current_month, -1)
    next_month = _add_months(current_month, 1)
    trial_started = tenant.created_at.date() if tenant.created_at else today
    trial_ends = trial_ends_at(tenant, today)
    paid_plan_accepted = has_paid_plan_acceptance(scope.db, scope.tenant_id)
    current_orders = _orders_count(scope, current_month, next_month)
    previous_orders = _orders_count(scope, previous_month, current_month)
    tier = _tier_for_orders(current_orders)
    invoices = (
        scope.db.query(TenantInvoice)
        .filter(TenantInvoice.tenant_id == scope.tenant_id)
        .order_by(TenantInvoice.period_month.desc(), TenantInvoice.created_at.desc())
        .all()
    )
    return {
        "deployment_mode": "hosted",
        "billing_scheme": tenant.billing_scheme,
        "usage": usage_state(scope.db, tenant, today),
        "trial_started_at": trial_started.isoformat() if tenant.billing_scheme != "pool_v2" else None,
        "trial_ends_at": trial_ends.isoformat() if tenant.billing_scheme != "pool_v2" else None,
        "trial_active": today < trial_ends if tenant.billing_scheme != "pool_v2" else None,
        "terms_version": TERMS_VERSION,
        "paid_plan_accepted": paid_plan_accepted,
        "imports_paused": not imports_allowed(scope.db, tenant, today) if tenant.billing_scheme != "pool_v2" else False,
        "current_month": current_month.isoformat(),
        "current_month_orders": current_orders,
        "previous_month": previous_month.isoformat(),
        "previous_month_orders": previous_orders,
        "current_tier": tier.model_dump(),
        "pricing": [tier.model_dump() for tier in PRICING_TIERS],
        "invoices": [
            {
                "id": invoice.id,
                "number": invoice.number,
                "period_month": invoice.period_month.isoformat(),
                "issue_date": invoice.issue_date.isoformat() if invoice.issue_date else None,
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "amount_net": str(invoice.amount_net),
                "amount_gross": str(invoice.amount_gross),
                "currency": invoice.currency,
                "status": invoice.status,
                "pdf_url": invoice.pdf_url,
            }
            for invoice in invoices
        ],
    }


class SubscriptionRequestPayload(StrictMutationModel):
    tier_code: str
    terms_version: str


@router.post("/subscription/request", dependencies=[Depends(require_hosted)])
def request_subscription(data: SubscriptionRequestPayload, request: Request, scope: TenantScope = Depends(get_scope)):
    tier = next((t for t in PRICING_TIERS if t.code == data.tier_code and t.billing_period == "year" and not t.is_custom), None)
    if not tier:
        raise HTTPException(422, "Nieprawidłowy pakiet")
    if data.terms_version != TERMS_VERSION:
        raise HTTPException(409, "Nieaktualna wersja regulaminu")
    # Serialize requests for the same tenant, including acceptance creation.
    scope.db.query(Tenant).filter(Tenant.id == scope.tenant_id).with_for_update().one()
    profile = scope.db.query(TenantBillingProfile).filter_by(tenant_id=scope.tenant_id).first()
    if not profile or any(not (getattr(profile, field) or "").strip() for field in ("company_name", "nip", "street", "postal_code", "city", "invoice_email")):
        raise HTTPException(409, "billing_profile_incomplete")
    pending = scope.db.query(TenantSubscription).filter(TenantSubscription.tenant_id == scope.tenant_id, TenantSubscription.status.in_(("pending_invoice", "invoiced"))).first()
    if pending:
        raise HTTPException(409, "subscription_pending")
    today = date.today()
    actives = scope.db.query(TenantSubscription).filter_by(tenant_id=scope.tenant_id, status="active").all()
    current = next((a for a in actives if a.period_start and a.period_start <= today <= a.period_end), None)
    if any(a.period_start and a.period_start > today for a in actives):
        raise HTTPException(409, "subscription_renewed")
    if current:
        active_tier = next((t for t in PRICING_TIERS if t.code == current.tier_code), None)
        is_upgrade = bool(active_tier and active_tier.max_orders is not None and tier.max_orders > active_tier.max_orders)
        in_renewal_window = (current.period_end - today).days <= 30
        if not (is_upgrade or in_renewal_window):
            raise HTTPException(409, "subscription_active")
    sub = TenantSubscription(tenant_id=scope.tenant_id, tier_code=tier.code, price_pln=tier.price_pln,
                             status="pending_invoice", requested_by_user_id=scope.user.id, terms_version=data.terms_version)
    scope.db.add(sub)
    if not scope.db.query(TenantPaidPlanAcceptance).filter_by(tenant_id=scope.tenant_id, terms_version=data.terms_version).first():
        scope.db.add(TenantPaidPlanAcceptance(tenant_id=scope.tenant_id, user_id=scope.user.id,
            terms_version=data.terms_version, ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent")))
    scope.db.commit()
    scope.db.refresh(sub)
    try:
        send_subscription_request_admin_email(subscription=sub, profile=profile)
    except Exception:
        # The order is already saved; a mail failure must not encourage duplicate orders.
        import logging
        logging.getLogger(__name__).warning("Nie udało się wysłać powiadomienia o zamówieniu %s", sub.id)
    return {"id": sub.id, "status": sub.status, "tier_code": sub.tier_code, "price_pln": sub.price_pln}


@router.post("/subscription/{subscription_id}/cancel", dependencies=[Depends(require_hosted)])
def cancel_subscription(subscription_id: int, scope: TenantScope = Depends(get_scope)):
    sub = scope.db.query(TenantSubscription).filter_by(id=subscription_id, tenant_id=scope.tenant_id).with_for_update().first()
    if not sub:
        raise HTTPException(404, "Nie znaleziono subskrypcji")
    if sub.status != "pending_invoice":
        raise HTTPException(409, "Nie można anulować subskrypcji")
    sub.status = "cancelled"
    sub.cancelled_at = datetime.now(UTC).replace(tzinfo=None)
    scope.db.commit()
    return {"id": sub.id, "status": sub.status}


@router.post("/paid-plan/accept", dependencies=[Depends(require_hosted)])
def accept_paid_plan(
    data: PaidPlanAcceptancePayload,
    request: Request,
    scope: TenantScope = Depends(get_scope),
):
    if not data.terms_accepted:
        raise HTTPException(422, "Akceptacja regulaminu jest wymagana")
    if not data.terms_version:
        raise HTTPException(422, "Brak wersji regulaminu")
    existing = (
        scope.db.query(TenantPaidPlanAcceptance)
        .filter(
            TenantPaidPlanAcceptance.tenant_id == scope.tenant_id,
            TenantPaidPlanAcceptance.terms_version == data.terms_version,
        )
        .first()
    )
    if existing:
        return _paid_plan_acceptance_payload(existing)
    acceptance = TenantPaidPlanAcceptance(
        tenant_id=scope.tenant_id,
        user_id=scope.user.id,
        terms_version=data.terms_version,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    scope.db.add(acceptance)
    scope.db.commit()
    scope.db.refresh(acceptance)
    return _paid_plan_acceptance_payload(acceptance)


def _paid_plan_acceptance_payload(acceptance: TenantPaidPlanAcceptance) -> dict[str, Any]:
    return {
        "paid_plan_accepted": True,
        "terms_version": acceptance.terms_version,
        "accepted_at": acceptance.accepted_at.isoformat() if acceptance.accepted_at else None,
    }


def _get_profile(scope: TenantScope) -> TenantBillingProfile:
    profile = (
        scope.db.query(TenantBillingProfile)
        .filter(TenantBillingProfile.tenant_id == scope.tenant_id)
        .first()
    )
    if profile:
        return profile
    profile = TenantBillingProfile(tenant_id=scope.tenant_id)
    scope.db.add(profile)
    scope.db.flush()
    return profile


def _profile_payload(profile: TenantBillingProfile) -> dict[str, Any]:
    return {
        "company_name": profile.company_name,
        "nip": profile.nip,
        "regon": profile.regon,
        "krs": profile.krs,
        "street": profile.street,
        "postal_code": profile.postal_code,
        "city": profile.city,
        "country": profile.country,
        "invoice_email": profile.invoice_email,
        "vat_status": profile.vat_status,
        "fetched_from_vat_api_at": profile.fetched_from_vat_api_at.isoformat() if profile.fetched_from_vat_api_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _clean_nip(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _split_address(address: str) -> dict[str, str | None]:
    if not address:
        return {"street": None, "postal_code": None, "city": None}
    parts = [part.strip() for part in address.split(",") if part.strip()]
    city_part = parts[-1] if parts else ""
    postal_code = None
    city = city_part
    tokens = city_part.split(" ", 1)
    if tokens and len(tokens[0]) == 6 and tokens[0][2] == "-":
        postal_code = tokens[0]
        city = tokens[1] if len(tokens) > 1 else ""
    return {
        "street": ", ".join(parts[:-1]) if len(parts) > 1 else address,
        "postal_code": postal_code,
        "city": city or None,
    }


def _orders_count(scope: TenantScope, start: date, end: date) -> int:
    return orders_in_range(scope.db, scope.tenant_id, start, end)


def _tier_for_orders(orders: int) -> PricingTier:
    for tier in PRICING_TIERS:
        if tier.max_orders is None or orders <= tier.max_orders:
            return tier
    raise ValueError("No pricing tier covers the order count")


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)
