import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.raw_data import OfferCache, OrderRaw
from app.models.account import Account
from app.models.sku import SkuAlias, SkuMaster
from app.services.sku_mapping_service import apply_multiplier, load_patterns

logger = logging.getLogger("apos.sku_import")


@dataclass
class AutoImportResult:
    added: int
    skipped: int
    no_sku: int  # offers without external.id


def auto_import_from_offers(account_id: int, db: Session) -> AutoImportResult:
    """Create SkuMaster + SkuAlias for every offer in offers_cache that has a SKU.
    Existing masters (matched by sku_key) are never overwritten."""
    account = db.get(Account, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    tenant_id = account.tenant_id
    offers = (
        db.query(OfferCache)
        .filter(OfferCache.tenant_id == tenant_id, OfferCache.account_id == account_id, OfferCache.sku.isnot(None))
        .all()
    )

    added = skipped = no_sku = 0
    patterns = load_patterns(db, tenant_id)
    order_vat_rows = (
        db.query(OrderRaw.sku, OrderRaw.vat_rate)
        .filter(
            OrderRaw.tenant_id == tenant_id,
            OrderRaw.account_id == account_id,
            OrderRaw.sku.isnot(None),
            OrderRaw.vat_rate.isnot(None),
        )
        .order_by(OrderRaw.bought_at.desc().nullslast())
        .all()
    )
    order_vat_by_sku = {}
    for sku, vat_rate in order_vat_rows:
        key = (sku or "").strip()
        if key and key not in order_vat_by_sku:
            order_vat_by_sku[key] = vat_rate

    for offer in offers:
        sku_key = (offer.sku or "").strip()
        if not sku_key:
            no_sku += 1
            continue

        imported_vat_rate = offer.vat_rate if offer.vat_rate is not None else order_vat_by_sku.get(sku_key)

        # Find or create SkuMaster
        master = db.query(SkuMaster).filter(SkuMaster.tenant_id == tenant_id, SkuMaster.sku_key == sku_key).first()
        if not master:
            master = SkuMaster(
                tenant_id=tenant_id,
                sku_key=sku_key,
                name=offer.name or sku_key,
                vat_rate=imported_vat_rate if imported_vat_rate is not None else 23,
            )
            db.add(master)
            db.flush()  # populate master.id before alias insert
            added += 1
            logger.info("Created SkuMaster sku_key=%s", sku_key)
        else:
            if imported_vat_rate is not None and master.vat_rate == 23 and imported_vat_rate != 23:
                master.vat_rate = imported_vat_rate
            skipped += 1

        # Create SkuAlias if not already present for this offer
        existing_alias = (
            db.query(SkuAlias)
            .filter(
                SkuAlias.tenant_id == tenant_id,
                SkuAlias.account_id == account_id,
                SkuAlias.raw_name == (offer.name or sku_key),
            )
            .first()
        )
        if not existing_alias:
            _, mult = apply_multiplier(offer.name or sku_key, patterns)
            db.add(
                SkuAlias(
                    tenant_id=tenant_id,
                    sku_master_id=master.id,
                    account_id=account_id,
                    raw_name=offer.name or sku_key,
                    multiplier=mult,
                )
            )

    db.commit()
    logger.info(
        "auto_import account=%d: added=%d skipped=%d no_sku=%d",
        account_id, added, skipped, no_sku,
    )
    return AutoImportResult(added=added, skipped=skipped, no_sku=no_sku)


def auto_import_from_orders(account_id: int, db: Session) -> AutoImportResult:
    """Create SkuMaster rows for sold order SKUs missing from the product catalog.

    Allegro orders can contain an external SKU that was not imported as an active
    offer. Dashboard P&L starts from sku_masters, so those sold SKUs must exist
    in the catalog before cost import and product-level reporting can cover them.
    """
    account = db.get(Account, account_id)
    if not account:
        raise ValueError(f"Account {account_id} not found")
    tenant_id = account.tenant_id

    rows = db.execute(
        text("""
        WITH latest_orders AS (
            SELECT DISTINCT ON (trim(o.sku))
                trim(o.sku) AS sku,
                o.offer_id,
                o.vat_rate
            FROM orders_raw o
            WHERE o.tenant_id = :tenant_id
              AND o.account_id = :account_id
              AND o.sku IS NOT NULL
              AND trim(o.sku) <> ''
            ORDER BY trim(o.sku), (o.vat_rate IS NULL), o.bought_at DESC NULLS LAST
        )
        SELECT
            lo.sku,
            lo.offer_id,
            lo.vat_rate,
            oc.name AS offer_name,
            sm.id AS master_id,
            sm.vat_rate AS master_vat_rate
        FROM latest_orders lo
        LEFT JOIN sku_masters sm ON sm.tenant_id = :tenant_id AND sm.sku_key = lo.sku
        LEFT JOIN offers_cache oc ON oc.tenant_id = :tenant_id AND oc.account_id = :account_id AND oc.offer_id = lo.offer_id
        WHERE sm.id IS NULL
           OR (sm.vat_rate = 23 AND lo.vat_rate IS NOT NULL AND lo.vat_rate <> 23)
        ORDER BY lo.sku
        """),
        {"tenant_id": tenant_id, "account_id": account_id},
    ).mappings().all()

    added = skipped = no_sku = 0
    patterns = load_patterns(db, tenant_id)
    for row in rows:
        sku_key = (row["sku"] or "").strip()
        if not sku_key:
            no_sku += 1
            continue
        existing = (
            db.query(SkuMaster)
            .filter(SkuMaster.tenant_id == tenant_id, SkuMaster.sku_key == sku_key)
            .first()
        )
        if existing:
            vat_rate = row["vat_rate"]
            if existing.vat_rate == Decimal("23") and vat_rate is not None and vat_rate != Decimal("23"):
                existing.vat_rate = vat_rate
            skipped += 1
            continue
        name = (row["offer_name"] or sku_key).strip()
        vat_rate = row["vat_rate"] if row["vat_rate"] is not None else Decimal("23")
        master = SkuMaster(
            tenant_id=tenant_id,
            sku_key=sku_key,
            name=name,
            vat_rate=vat_rate,
        )
        db.add(master)
        db.flush()
        added += 1
        _, mult = apply_multiplier(name, patterns)
        db.add(
            SkuAlias(
                tenant_id=tenant_id,
                sku_master_id=master.id,
                account_id=account_id,
                raw_name=name,
                multiplier=mult,
            )
        )

    db.commit()
    logger.info("auto_import_from_orders account=%d: added=%d skipped=%d no_sku=%d", account_id, added, skipped, no_sku)
    return AutoImportResult(added=added, skipped=skipped, no_sku=no_sku)
