from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import Field, SecretStr, field_validator

from app.core.config import settings
from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.raw_data import OfferCache
from app.models.sku import FinancialVault
from app.schemas.strict import StrictMutationModel
from app.services.dashboard_engine import DashboardEngine, get_period
from app.services.vault_decryption import (
    FinancialVaultError,
    decrypt_sku_cost_with_key,
    derive_financial_key,
    verify_financial_vault_key,
)

class VaultDecryptionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded_handler(request: Request):
            if not settings.VAULT_SERVER_DECRYPTION_ENABLED:
                raise HTTPException(status_code=404, detail="Not Found")
            return await handler(request)

        return guarded_handler


router = APIRouter(prefix="/integrations", tags=["integrations"], route_class=VaultDecryptionRoute)

_VAULT_SCOPE = "global"
_GROSS_TO_NET_23 = Decimal("1.23")


class InvalidFinancialData(Exception):
    """A product row contains a value that cannot safely be used for profit."""


class ProfitByEanRequest(StrictMutationModel):
    """Batch profit lookup by EAN.

    The client opts in to server-side decryption by supplying the Financial
    Vault code. The code, the derived key and decrypted costs exist only in the
    memory of the single request and are never persisted or logged.
    """

    eans: list[str] = Field(
        min_length=1,
        max_length=100,
        description="EAN codes to look up: 1-100 numeric strings of 8-14 digits",
    )
    vault_code: SecretStr = Field(
        description="Financial Vault code used to unlock encrypted purchase costs"
    )
    account_id: int | None = Field(
        default=None,
        description="Optional Allegro account; must belong to the caller tenant",
    )

    @field_validator("eans")
    @classmethod
    def _validate_eans(cls, value: list[str]) -> list[str]:
        for ean in value:
            if not ean.isascii() or not ean.isdigit() or not (8 <= len(ean) <= 14):
                raise ValueError("each EAN must be a numeric string of 8 to 14 digits")
        return value


def _money(value: str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidFinancialData from exc
    if not amount.is_finite():
        raise InvalidFinancialData
    return amount


def _two_decimal(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _units_value(units: int) -> int:
    return max(int(units), 0)


def _gross_to_net_23(value: Decimal) -> Decimal:
    return value / _GROSS_TO_NET_23 if value else Decimal("0")


def _multiplier_or_one(raw: str | None) -> Decimal:
    if raw is None:
        return Decimal("1")
    try:
        multiplier = Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("1")
    if not multiplier.is_finite() or multiplier <= 0:
        return Decimal("1")
    return multiplier


def _result_for_ean(
    ean: str,
    skus: set[str] | None,
    row_by_sku: dict[str, object],
    vault: FinancialVault,
    key: bytes,
) -> dict:
    if not skus:
        return {"ean": ean, "status": "not_found", "sku": None,
                "units_sold": None, "profit_per_unit_net": None, "profit_net_total": None}
    if len(skus) > 1:
        return {"ean": ean, "status": "ambiguous", "sku": None,
                "units_sold": None, "profit_per_unit_net": None, "profit_net_total": None}

    sku = next(iter(skus))
    row = row_by_sku.get(sku)
    if row is None:
        return {"ean": ean, "status": "no_sales", "sku": sku,
                "units_sold": 0, "profit_per_unit_net": None, "profit_net_total": None}
    if row.encrypted_cost is None:
        return {"ean": ean, "status": "missing_cost", "sku": sku,
                "units_sold": _units_value(row.units_sold),
                "profit_per_unit_net": None, "profit_net_total": None}

    try:
        envelope = SimpleNamespace(**row.encrypted_cost)
        cost = decrypt_sku_cost_with_key(key, vault, envelope)
        unit_cost = cost * _multiplier_or_one(row.cost_multiplier)
        cogs_units = max(_money(row.cogs_units), Decimal("0"))
        cogs = unit_cost * cogs_units
        profit = (
            _money(row.revenue_net)
            - _money(row.total_allegro_net)
            + _gross_to_net_23(_money(row.price_adjust_cost))
            + _gross_to_net_23(_money(row.campaign_bonus))
            + _gross_to_net_23(_money(row.refund_commission))
            + _gross_to_net_23(_money(row.commission_refunds_amount))
            - cogs
        )
        units = _units_value(row.units_sold)
        profit_per_unit = profit / Decimal(units) if units > 0 else None
        total_text = _two_decimal(profit)
        unit_text = _two_decimal(profit_per_unit) if profit_per_unit is not None else None
    except (FinancialVaultError, InvalidFinancialData, InvalidOperation, TypeError, ValueError, AttributeError):
        return {"ean": ean, "status": "invalid_data", "sku": sku,
                "units_sold": _units_value(row.units_sold),
                "profit_per_unit_net": None, "profit_net_total": None}

    return {
        "ean": ean,
        "status": "ok",
        "sku": sku,
        "units_sold": _units_value(row.units_sold),
        "profit_per_unit_net": unit_text,
        "profit_net_total": total_text,
    }


@router.post("/profit-by-ean")
def profit_by_ean(
    payload: ProfitByEanRequest,
    scope: TenantScope = Depends(get_scope),
):
    if scope.user.id == 0:
        raise HTTPException(
            403,
            "legacy bearer API tokens (user id 0) are not allowed for this endpoint",
        )

    if payload.account_id is not None:
        account = scope.db.get(Account, payload.account_id)
        scope.assert_owns(account)

    vault = (
        scope.db.query(FinancialVault)
        .filter(
            FinancialVault.tenant_id == scope.tenant_id,
            FinancialVault.scope == _VAULT_SCOPE,
        )
        .first()
    )
    if vault is None:
        raise HTTPException(404, "financial vault is not configured for this tenant")

    vault_code = payload.vault_code.get_secret_value()
    try:
        key = derive_financial_key(vault_code, vault)
    except FinancialVaultError:
        raise HTTPException(400, "financial vault is misconfigured")
    finally:
        del vault_code

    if not verify_financial_vault_key(key, vault):
        raise HTTPException(403, "incorrect vault code")

    eans = payload.eans
    offer_query = scope.db.query(OfferCache).filter(
        OfferCache.tenant_id == scope.tenant_id,
        OfferCache.ean.in_(eans),
    )
    if payload.account_id is not None:
        offer_query = offer_query.filter(OfferCache.account_id == payload.account_id)
    offers = offer_query.all()
    skus_by_ean: dict[str, set[str]] = {}
    for offer in offers:
        sku = offer.sku.strip() if offer.sku else ""
        if offer.ean and sku:
            skus_by_ean.setdefault(offer.ean, set()).add(sku)

    rows = DashboardEngine(scope).products(get_period("last_7d"), payload.account_id, None, "PLN")
    row_by_sku = {row.sku_key: row for row in rows}

    return {
        "period": "last_7d",
        "currency": "PLN",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "results": [_result_for_ean(ean, skus_by_ean.get(ean), row_by_sku, vault, key) for ean in eans],
    }
