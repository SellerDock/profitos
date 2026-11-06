from datetime import UTC, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import field_validator
from sqlalchemy import text

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.sku import SkuMaster
from app.models.raw_data import StockLevel
from app.schemas.strict import StrictMutationModel
from app.services.import_service import ImportService

router = APIRouter(prefix="/stock", tags=["stock"])

_DEFAULT_SETTINGS = {"threshold_critical": 14, "threshold_warning": 30}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _get_settings(scope: TenantScope) -> dict:
    rows = scope.db.execute(
        text("SELECT key, value FROM stock_settings WHERE tenant_id = :tenant_id"),
        {"tenant_id": scope.tenant_id},
    ).fetchall()
    result = dict(_DEFAULT_SETTINGS)
    for r in rows:
        result[r.key] = r.value
    return result

_BUNDLE_PREFIXES = ("2 x ", "2x ", "2X ", "2 X ")

_BUNDLE_PREFIXES_SQL = ("2 x %", "2x %", "2X %", "2 X %")


def _is_bundle(name: str) -> bool:
    return any(name.startswith(p) for p in _BUNDLE_PREFIXES)


def _avg_daily_sales(s15: int, s30: int, s90: int, s180: int) -> float:
    """Weighted average daily sales from 4 windows."""
    return (s15 / 15 * 0.25 + s30 / 30 * 0.25 + s90 / 90 * 0.25 + s180 / 180 * 0.25)


def _get_stock_rows(scope: TenantScope, account_id: int | None = None) -> list[dict]:
    now = _now()
    cut15  = now - timedelta(days=15)
    cut30  = now - timedelta(days=30)
    cut90  = now - timedelta(days=90)
    cut180 = now - timedelta(days=180)
    account_order_filter = "AND o.account_id = :account_id" if account_id is not None else ""
    account_sku_filter = """
          AND (
              EXISTS (
                  SELECT 1 FROM orders_raw oa
                  WHERE oa.tenant_id = :tenant_id
                    AND oa.account_id = :account_id
                    AND oa.sku = sm.sku_key
              )
              OR EXISTS (
                  SELECT 1 FROM offers_cache oc
                  WHERE oc.tenant_id = :tenant_id
                    AND oc.account_id = :account_id
                    AND oc.sku = sm.sku_key
              )
          )
    """ if account_id is not None else ""

    rows = scope.db.execute(text(f"""
        SELECT
            sm.id          AS sku_id,
            sm.sku_key,
            sm.name,
            COALESCE(sl.quantity, 0)    AS quantity,
            sl.updated_at,
            sl.updated_by,
            COALESCE(sl.sync_from_allegro, TRUE) AS sync_from_allegro,
            COALESCE(SUM(CASE WHEN o.bought_at >= :cut15  THEN o.quantity ELSE 0 END), 0) AS sold_15d,
            COALESCE(SUM(CASE WHEN o.bought_at >= :cut30  THEN o.quantity ELSE 0 END), 0) AS sold_30d,
            COALESCE(SUM(CASE WHEN o.bought_at >= :cut90  THEN o.quantity ELSE 0 END), 0) AS sold_90d,
            COALESCE(SUM(CASE WHEN o.bought_at >= :cut180 THEN o.quantity ELSE 0 END), 0) AS sold_180d
        FROM sku_masters sm
        LEFT JOIN stock_levels sl ON sl.sku_id = sm.id AND sl.tenant_id = :tenant_id
        LEFT JOIN orders_raw o ON o.sku = sm.sku_key
            AND o.tenant_id = :tenant_id
            AND o.bought_at >= :cut180
            AND o.status NOT IN ('CANCELLED', 'RETURNED')
            {account_order_filter}
        WHERE sm.tenant_id = :tenant_id
          AND sm.name NOT LIKE '2 x %'
          AND sm.name NOT LIKE '2x %'
          AND sm.name NOT LIKE '2X %'
          AND sm.name NOT LIKE '2 X %'
          {account_sku_filter}
        GROUP BY sm.id, sm.sku_key, sm.name, sl.quantity, sl.updated_at, sl.updated_by, sl.sync_from_allegro
        ORDER BY sm.name
    """), {
        "cut15": cut15, "cut30": cut30, "cut90": cut90, "cut180": cut180,
        "tenant_id": scope.tenant_id,
        "account_id": account_id,
    }).fetchall()

    result = []
    for r in rows:
        s15, s30, s90, s180 = int(r.sold_15d), int(r.sold_30d), int(r.sold_90d), int(r.sold_180d)
        avg = _avg_daily_sales(s15, s30, s90, s180)
        days_left = int(r.quantity / avg) if avg > 0 and r.quantity >= 0 else None

        result.append({
            "sku_id":      r.sku_id,
            "sku_key":     r.sku_key,
            "name":        r.name,
            "quantity":    int(r.quantity),
            "updated_at":  r.updated_at.isoformat() if r.updated_at else None,
            "updated_by":  r.updated_by or "manual",
            "sync_from_allegro": bool(r.sync_from_allegro),
            "sold_15d":    s15,
            "sold_30d":    s30,
            "sold_90d":    s90,
            "avg_daily":   round(avg, 4),
            "days_left":   days_left,
        })

    return result


@router.get("/settings")
def get_settings(scope: TenantScope = Depends(get_scope)):
    return _get_settings(scope)


class SettingsUpdate(StrictMutationModel):
    threshold_critical: int
    threshold_warning: int

    @field_validator('threshold_critical', 'threshold_warning')
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Threshold must be > 0")
        return v

    def model_post_init(self, __context: object) -> None:
        if self.threshold_critical >= self.threshold_warning:
            raise ValueError("threshold_critical must be less than threshold_warning")


@router.put("/settings")
def update_settings(data: SettingsUpdate, scope: TenantScope = Depends(get_scope)):
    for key, value in {"threshold_critical": data.threshold_critical,
                       "threshold_warning": data.threshold_warning}.items():
        scope.db.execute(text(
            "INSERT INTO stock_settings (tenant_id, key, value) VALUES (:tenant_id, :k, :v) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET value = :v"
        ), {"tenant_id": scope.tenant_id, "k": key, "v": value})
    scope.db.commit()
    return _get_settings(scope)


@router.get("/")
def list_stock(account_id: int | None = None, scope: TenantScope = Depends(get_scope)):
    if account_id is not None:
        account = scope.db.get(Account, account_id)
        scope.assert_owns(account)
    return _get_stock_rows(scope, account_id)


class StockUpdate(StrictMutationModel):
    quantity: int
    sync_from_allegro: bool | None = None


@router.put("/{sku_id}")
def update_stock(sku_id: int, data: StockUpdate, scope: TenantScope = Depends(get_scope)):
    sku = scope.db.get(SkuMaster, sku_id)
    scope.assert_owns(sku)
    if _is_bundle(sku.name):
        raise HTTPException(400, "Cannot set stock for bundle SKUs")

    sl = scope.db.query(StockLevel).filter(
        StockLevel.tenant_id == scope.tenant_id,
        StockLevel.sku_id == sku_id,
    ).first()
    if sl:
        sl.quantity = data.quantity
        sl.updated_at = _now()
        sl.updated_by = "manual"
        if data.sync_from_allegro is not None:
            sl.sync_from_allegro = data.sync_from_allegro
    else:
        sl = StockLevel(tenant_id=scope.tenant_id, sku_id=sku_id, quantity=data.quantity, updated_by="manual",
                        updated_at=_now(), sync_from_allegro=data.sync_from_allegro if data.sync_from_allegro is not None else True)
        scope.db.add(sl)

    scope.db.commit()
    return {"sku_id": sku_id, "quantity": sl.quantity, "updated_by": sl.updated_by,
            "updated_at": sl.updated_at.isoformat(), "sync_from_allegro": sl.sync_from_allegro}


@router.post("/auto-import")
def auto_import_stock(scope: TenantScope = Depends(get_scope)):
    """Import stock from Allegro offers, then create zero rows for base SKUs without stock."""
    imported = 0
    accounts = (
        scope.db.query(Account)
        .filter(Account.tenant_id == scope.tenant_id, Account.access_token.isnot(None))
        .all()
    )
    if accounts:
        service = ImportService(scope.db)
        for account in accounts:
            imported += service.sync_offers_only(account.id)

    skus = scope.db.query(SkuMaster).filter(SkuMaster.tenant_id == scope.tenant_id).all()
    added = 0
    for sku in skus:
        if _is_bundle(sku.name):
            continue
        exists = scope.db.query(StockLevel).filter(
            StockLevel.tenant_id == scope.tenant_id,
            StockLevel.sku_id == sku.id,
        ).first()
        if not exists:
            scope.db.add(StockLevel(tenant_id=scope.tenant_id, sku_id=sku.id, quantity=0, updated_by="auto",
                              updated_at=_now(), sync_from_allegro=True))
            added += 1

    scope.db.commit()
    return {"added": added, "imported": imported, "accounts": len(accounts)}
