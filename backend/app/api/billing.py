from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import is_selfhosted
from app.core.deployment import require_hosted
from app.core.tenant import TenantScope, get_scope
from app.core.database import get_db
from app.core.legal import TERMS_VERSION
from app.models.billing_profile import TenantBillingProfile, TenantInvoice, TenantPaidPlanAcceptance
from app.models.raw_data import BillingTypeLabel
from app.models.raw_data import OrderRaw
from app.models.tenant import Tenant
from app.schemas.strict import StrictMutationModel
from app.services.billing_state import has_paid_plan_acceptance, imports_allowed, trial_ends_at

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


class PricingTier(BaseModel):
    code: str
    label: str
    max_orders: int | None
    price_pln: int
    billing_period: Literal["year", "free"]
    is_custom: bool = False


PRICING_TIERS = [
    PricingTier(code="free_200", label="Do 200 zamówień", max_orders=200, price_pln=0, billing_period="free"),
    PricingTier(code="year_1000", label="Do 1000 zamówień", max_orders=1000, price_pln=99, billing_period="year"),
    PricingTier(code="year_5000", label="Do 5000 zamówień", max_orders=5000, price_pln=299, billing_period="year"),
    PricingTier(code="year_25000", label="Do 25 000 zamówień", max_orders=25000, price_pln=499, billing_period="year"),
    PricingTier(code="custom", label="Powyżej 25 000 zamówień", max_orders=None, price_pln=0, billing_period="year", is_custom=True),
]


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
        "trial_started_at": trial_started.isoformat(),
        "trial_ends_at": trial_ends.isoformat(),
        "trial_active": today < trial_ends,
        "terms_version": TERMS_VERSION,
        "paid_plan_accepted": paid_plan_accepted,
        "imports_paused": not imports_allowed(scope.db, tenant, today),
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
    return int(
        scope.db.query(func.count(func.distinct(OrderRaw.order_id)))
        .filter(
            OrderRaw.tenant_id == scope.tenant_id,
            OrderRaw.bought_at >= datetime.combine(start, datetime.min.time()),
            OrderRaw.bought_at < datetime.combine(end, datetime.min.time()),
        )
        .scalar()
        or 0
    )


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
