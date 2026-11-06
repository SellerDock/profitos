import base64
import binascii
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.raw_data import OfferCache, OrderRaw
from app.models.sku import EncryptedSkuCost, EncryptedSkuCostHistory, FinancialVault, SkuMaster
from app.schemas.strict import StrictMutationModel
from app.services.sku_import import auto_import_from_offers, auto_import_from_orders

router = APIRouter(tags=["products"])


# ── Auto-import ────────────────────────────────────────────────────────────────

@router.post("/sku/auto-import/{account_id}")
def auto_import_sku(account_id: int, scope: TenantScope = Depends(get_scope)):
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    offers_result = auto_import_from_offers(account_id, scope.db)
    orders_result = auto_import_from_orders(account_id, scope.db)
    result_added = offers_result.added + orders_result.added
    result_skipped = offers_result.skipped + orders_result.skipped
    result_no_sku = offers_result.no_sku + orders_result.no_sku
    return {"added": result_added, "skipped": result_skipped, "no_sku": result_no_sku}


# ── SKU list for Products management page ─────────────────────────────────────

@router.get("/products/")
def list_products(account_id: int | None = None, scope: TenantScope = Depends(get_scope)):
    """Products management view — all SKU with encrypted cost history."""
    if account_id is not None:
        account = scope.db.get(Account, account_id)
        scope.assert_owns(account)

    sku_query = scope.db.query(SkuMaster).filter(SkuMaster.tenant_id == scope.tenant_id)
    if account_id is not None:
        # Use func.trim() so SKU values with trailing whitespace from Allegro
        # (e.g. 'Natural Factors DGL ') still match the stripped sku_key stored
        # by sku_import. dashboard_engine already applies trim() consistently.
        linked_sku_keys = (
            scope.db.query(func.trim(OrderRaw.sku).label("sku_key"))
            .filter(
                OrderRaw.tenant_id == scope.tenant_id,
                OrderRaw.account_id == account_id,
                OrderRaw.sku.isnot(None),
            )
            .union(
                scope.db.query(func.trim(OfferCache.sku).label("sku_key")).filter(
                    OfferCache.tenant_id == scope.tenant_id,
                    OfferCache.account_id == account_id,
                    OfferCache.sku.isnot(None),
                )
            )
            .subquery()
        )
        sku_query = sku_query.filter(SkuMaster.sku_key.in_(scope.db.query(linked_sku_keys.c.sku_key)))

    skus = (
        sku_query
        .order_by(SkuMaster.sku_key)
        .all()
    )
    encrypted_current = {
        row.sku_master_id: row
        for row in scope.db.query(EncryptedSkuCost).filter(EncryptedSkuCost.tenant_id == scope.tenant_id).all()
    }
    encrypted_history: dict[int, list[EncryptedSkuCostHistory]] = {}
    for row in (
        scope.db.query(EncryptedSkuCostHistory)
        .filter(EncryptedSkuCostHistory.tenant_id == scope.tenant_id)
        .order_by(EncryptedSkuCostHistory.valid_from.desc())
        .all()
    ):
        encrypted_history.setdefault(row.sku_master_id, []).append(row)
    offer_ids_by_sku: dict[str, set[str]] = {}
    for sku, offer_id in (
        scope.db.query(func.trim(OrderRaw.sku).label("sku"), OrderRaw.offer_id)
        .filter(
            OrderRaw.tenant_id == scope.tenant_id,
            *( [OrderRaw.account_id == account_id] if account_id is not None else [] ),
            OrderRaw.sku.isnot(None),
            OrderRaw.offer_id.isnot(None),
        )
        .distinct()
        .all()
    ):
        offer_ids_by_sku.setdefault(str(sku), set()).add(str(offer_id))
    eans_by_sku: dict[str, set[str]] = {}
    for sku, offer_id, ean in (
        scope.db.query(func.trim(OfferCache.sku).label("sku"), OfferCache.offer_id, OfferCache.ean)
        .filter(
            OfferCache.tenant_id == scope.tenant_id,
            *( [OfferCache.account_id == account_id] if account_id is not None else [] ),
            OfferCache.sku.isnot(None),
        )
        .distinct()
        .all()
    ):
        if offer_id:
            offer_ids_by_sku.setdefault(str(sku), set()).add(str(offer_id))
        if ean:
            eans_by_sku.setdefault(str(sku), set()).add(str(ean))
    return [
        _sku_to_dict(
            s,
            encrypted_current.get(s.id),
            encrypted_history.get(s.id, []),
            sorted(offer_ids_by_sku.get(s.sku_key, set())),
            sorted(eans_by_sku.get(s.sku_key, set())),
        )
        for s in skus
    ]


def _encrypted_payload(row: EncryptedSkuCost | EncryptedSkuCostHistory | None) -> dict | None:
    if not row:
        return None
    return {
        "ciphertext": row.ciphertext,
        "nonce": row.nonce,
        "key_version": row.key_version,
        "aad_context": row.aad_context,
    }


def _sku_to_dict(
    s: SkuMaster,
    encrypted_cost: EncryptedSkuCost | None = None,
    encrypted_history: list[EncryptedSkuCostHistory] | None = None,
    offer_ids: list[str] | None = None,
    eans: list[str] | None = None,
) -> dict:
    history = encrypted_history or []
    return {
        "id": s.id,
        "sku_key": s.sku_key,
        "name": s.name,
        "vat_rate": str(s.vat_rate),
        "target_margin_pct": str(s.target_margin_pct),
        "offer_ids": offer_ids or [],
        "eans": eans or [],
        "encrypted_cost": _encrypted_payload(encrypted_cost),
        "cost_history": [
            {
                "id": h.id,
                "encrypted_cost": _encrypted_payload(h),
                "valid_from": h.valid_from.isoformat(),
                "valid_to": h.valid_to.isoformat() if h.valid_to else None,
                "note": h.note,
            }
            for h in history
        ],
    }


# ── Inline patch ───────────────────────────────────────────────────────────────

class EncryptedCostPayload(StrictMutationModel):
    ciphertext: str = Field(min_length=1, max_length=4096)
    nonce: str = Field(min_length=1, max_length=128)
    key_version: int = Field(default=1, gt=0)
    aad_context: str = Field(min_length=1, max_length=255)


class SkuPatch(StrictMutationModel):
    encrypted_cost: Optional[EncryptedCostPayload] = None
    history_encrypted_cost: Optional[EncryptedCostPayload] = None
    vat_rate: Optional[Decimal] = None
    target_margin_pct: Optional[Decimal] = None
    name: Optional[str] = None


def _get_vault(scope: TenantScope) -> FinancialVault:
    vault = (
        scope.db.query(FinancialVault)
        .filter(FinancialVault.tenant_id == scope.tenant_id, FinancialVault.scope == "global")
        .first()
    )
    if not vault:
        raise HTTPException(400, "Financial vault is not configured")
    return vault


def _decode_b64(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(422, f"Invalid base64 in {field}") from exc


def _current_aad(sku_id: int, key_version: int) -> str:
    return f"profitos:sku-cost:{sku_id}:current:v{key_version}"


def _history_aad(sku_id: int, valid_from: date, key_version: int) -> str:
    return f"profitos:sku-cost:{sku_id}:history:{valid_from.isoformat()}:v{key_version}"


def _validate_encrypted_payload(
    payload: EncryptedCostPayload,
    vault: FinancialVault,
    expected_aad: str,
) -> None:
    nonce = _decode_b64(payload.nonce, "nonce")
    ciphertext = _decode_b64(payload.ciphertext, "ciphertext")
    if len(nonce) != 12:
        raise HTTPException(422, "AES-GCM nonce must be 12 bytes")
    if len(ciphertext) < 16 or len(ciphertext) > 3072:
        raise HTTPException(422, "Ciphertext length is invalid")
    if payload.key_version != vault.key_version:
        raise HTTPException(422, "Encrypted payload key_version does not match active vault")
    if payload.aad_context != expected_aad:
        raise HTTPException(422, "Encrypted payload AAD context does not match this SKU")


def _upsert_current_cost(scope: TenantScope, sku_id: int, payload: EncryptedCostPayload) -> EncryptedSkuCost:
    vault = _get_vault(scope)
    current = (
        scope.db.query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.tenant_id == scope.tenant_id, EncryptedSkuCost.sku_master_id == sku_id)
        .first()
    )
    if current:
        current.vault_id = vault.id
        current.ciphertext = payload.ciphertext
        current.nonce = payload.nonce
        current.key_version = payload.key_version
        current.aad_context = payload.aad_context
        return current

    current = EncryptedSkuCost(
        tenant_id=scope.tenant_id,
        sku_master_id=sku_id,
        vault_id=vault.id,
        ciphertext=payload.ciphertext,
        nonce=payload.nonce,
        key_version=payload.key_version,
        aad_context=payload.aad_context,
    )
    scope.db.add(current)
    return current


@router.patch("/products/{sku_id}")
def patch_product(sku_id: int, data: SkuPatch, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)

    if data.vat_rate is not None and (data.vat_rate < Decimal("0") or data.vat_rate > Decimal("25")):
        raise HTTPException(422, "VAT rate must be between 0 and 25")

    if data.encrypted_cost is not None:
        vault = _get_vault(scope)
        if data.history_encrypted_cost is None:
            raise HTTPException(422, "history_encrypted_cost is required when encrypted_cost is updated")
        today = date.today()
        _validate_encrypted_payload(data.encrypted_cost, vault, _current_aad(sku.id, vault.key_version))
        _validate_encrypted_payload(data.history_encrypted_cost, vault, _history_aad(sku.id, today, vault.key_version))
        _upsert_current_cost(scope, sku.id, data.encrypted_cost)
        for h in scope.db.query(EncryptedSkuCostHistory).filter(
            EncryptedSkuCostHistory.tenant_id == scope.tenant_id,
            EncryptedSkuCostHistory.sku_master_id == sku.id,
            EncryptedSkuCostHistory.valid_to.is_(None),
        ):
            h.valid_to = today
        scope.db.add(EncryptedSkuCostHistory(
            tenant_id=scope.tenant_id,
            sku_master_id=sku.id,
            vault_id=vault.id,
            ciphertext=data.history_encrypted_cost.ciphertext,
            nonce=data.history_encrypted_cost.nonce,
            key_version=data.history_encrypted_cost.key_version,
            aad_context=data.history_encrypted_cost.aad_context,
            valid_from=today,
        ))

    for f in ("vat_rate", "target_margin_pct", "name"):
        v = getattr(data, f)
        if v is not None:
            setattr(sku, f, v)

    scope.db.commit()
    scope.db.refresh(sku)
    current = scope.db.query(EncryptedSkuCost).filter(
        EncryptedSkuCost.tenant_id == scope.tenant_id,
        EncryptedSkuCost.sku_master_id == sku.id,
    ).first()
    history = scope.db.query(EncryptedSkuCostHistory).filter(
        EncryptedSkuCostHistory.tenant_id == scope.tenant_id,
        EncryptedSkuCostHistory.sku_master_id == sku.id
    ).order_by(EncryptedSkuCostHistory.valid_from.desc()).all()
    return _sku_to_dict(sku, current, history)


# ── Cost history endpoints ─────────────────────────────────────────────────────

class CostHistoryCreate(StrictMutationModel):
    encrypted_cost: EncryptedCostPayload
    current_encrypted_cost: EncryptedCostPayload
    valid_from: date
    valid_to: Optional[date] = None
    note: Optional[str] = None


@router.post("/products/{sku_id}/cost-history")
def add_cost_history(sku_id: int, data: CostHistoryCreate, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    today = date.today()

    if data.valid_to is not None and data.valid_to < data.valid_from:
        raise HTTPException(422, "valid_to must be greater than or equal to valid_from")

    vault = _get_vault(scope)
    _validate_encrypted_payload(data.encrypted_cost, vault, _history_aad(sku.id, data.valid_from, vault.key_version))
    _validate_encrypted_payload(data.current_encrypted_cost, vault, _current_aad(sku.id, vault.key_version))

    should_update_current = data.valid_from <= today and (data.valid_to is None or data.valid_to >= today)

    # Close any open entry that starts before this current/future one. Historical
    # bounded rows from CSV should not rewrite the current open cost window.
    for h in scope.db.query(EncryptedSkuCostHistory).filter(
        EncryptedSkuCostHistory.tenant_id == scope.tenant_id,
        EncryptedSkuCostHistory.sku_master_id == sku.id,
    ):
        if should_update_current and h.valid_to is None and h.valid_from < data.valid_from:
            h.valid_to = data.valid_from

    scope.db.add(EncryptedSkuCostHistory(
        tenant_id=scope.tenant_id,
        sku_master_id=sku_id,
        vault_id=vault.id,
        ciphertext=data.encrypted_cost.ciphertext,
        nonce=data.encrypted_cost.nonce,
        key_version=data.encrypted_cost.key_version,
        aad_context=data.encrypted_cost.aad_context,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
        note=data.note,
    ))
    if should_update_current:
        _upsert_current_cost(scope, sku.id, data.current_encrypted_cost)
    scope.db.commit()
    scope.db.refresh(sku)
    current = scope.db.query(EncryptedSkuCost).filter(
        EncryptedSkuCost.tenant_id == scope.tenant_id,
        EncryptedSkuCost.sku_master_id == sku.id,
    ).first()
    history = scope.db.query(EncryptedSkuCostHistory).filter(
        EncryptedSkuCostHistory.tenant_id == scope.tenant_id,
        EncryptedSkuCostHistory.sku_master_id == sku.id
    ).order_by(EncryptedSkuCostHistory.valid_from.desc()).all()
    return _sku_to_dict(sku, current, history)


class CostHistoryDelete(StrictMutationModel):
    current_encrypted_cost: Optional[EncryptedCostPayload] = None


@router.delete("/products/{sku_id}/cost-history/{history_id}", status_code=204)
def delete_cost_history(
    sku_id: int,
    history_id: int,
    data: Optional[CostHistoryDelete] = None,
    scope: TenantScope = Depends(get_scope),
):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    h = scope.db.get(EncryptedSkuCostHistory, history_id)
    if not h or h.sku_master_id != sku_id:
        raise HTTPException(404, "History entry not found")
    scope.assert_owns(h)
    scope.db.delete(h)
    remaining = scope.db.query(EncryptedSkuCostHistory).filter(
        EncryptedSkuCostHistory.tenant_id == scope.tenant_id,
        EncryptedSkuCostHistory.sku_master_id == sku_id,
        EncryptedSkuCostHistory.id != history_id,
    ).order_by(EncryptedSkuCostHistory.valid_from.desc()).all()
    if remaining and data and data.current_encrypted_cost is not None:
        vault = _get_vault(scope)
        _validate_encrypted_payload(
            data.current_encrypted_cost, vault, _current_aad(sku.id, vault.key_version)
        )
        _upsert_current_cost(scope, sku.id, data.current_encrypted_cost)
    # If no history entries remain, leave the current cost untouched. History is
    # a log of past changes; deleting the last log entry must never erase the
    # live encrypted cost (it has no undo — the ciphertext would be unrecoverable).
    # If remaining entries exist but no current_encrypted_cost was provided by
    # the client, the current cost stays unchanged — the frontend is responsible
    # for re-encrypting the latest history entry with the current-format AAD and
    # sending it as current_encrypted_cost.
    scope.db.commit()


# ── XLSX cost import ──────────────────────────────────────────────────────────

@router.post("/products/import-costs")
async def import_costs():
    raise HTTPException(
        410,
        "Cost imports must be encrypted in the browser before upload. Use the encrypted product endpoints.",
    )
