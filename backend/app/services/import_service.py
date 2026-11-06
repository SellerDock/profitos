import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.raw_data import (
    AccountImportState,
    BillingRaw,
    BillingTypeLabel,
    CustomerReturnItemRaw,
    CustomerReturnRaw,
    OfferCache,
    OrderEventRaw,
    OrderRaw,
    PaymentRefundLineItemRaw,
    PaymentRefundRaw,
    StockLevel,
    SyncLog,
)
from app.models.sku import SkuMaster
from app.services.allegro import AllegroService
from app.services.sku_import import auto_import_from_orders

# Codes we spotted in debug endpoint that lacked labels — log them on first fetch
_WATCH_CODES = {"PAD", "PBL", "DHR", "PB2", "PTR", "SUM", "DTR", "ITR"}
_BUNDLE_PREFIXES = ("2 x ", "2x ", "2X ", "2 X ")


def _normalize_sku(val: str | None) -> str | None:
    """Strip leading/trailing whitespace from a raw Allegro SKU; return None for empty."""
    if not val:
        return None
    stripped = val.strip()
    return stripped if stripped else None

# Synthetic, short-lived billing entry. It is deliberately in billing_raw so the
# established reporting/attribution path handles it exactly like real shipping
# fees. The row is removed as soon as Billing API provides a real Smart fee.
_SMART_ESTIMATE_TYPE = "SMART"
_SMART_ESTIMATE_PREFIX = "smart-estimate:"
_REAL_SMART_SHIPPING_TYPES = ("HB4", "HLB", "HXO", "ORB", "DPB", "DXP", "DHR", "DPA", "HB9", "XOR")
_SMART_ESTIMATE_RATES: tuple[tuple[Decimal, Decimal | None], ...] = (
    (Decimal("30.00"), Decimal("1.59")),
    (Decimal("45.00"), Decimal("3.19")),
    (Decimal("65.00"), Decimal("5.19")),
    (Decimal("100.00"), Decimal("7.89")),
    (Decimal("150.00"), Decimal("9.99")),
)
_SMART_ESTIMATE_TTL = timedelta(days=7)

logger = logging.getLogger(__name__)
_WARSAW = ZoneInfo("Europe/Warsaw")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_bundle(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in _BUNDLE_PREFIXES)


def _smart_estimate_rate(order_total: Decimal) -> Decimal | None:
    """Return the temporary carrier-independent Smart rate, if defined.

    The price list starts at 30 PLN. Production billing proves that costs below
    that level are variable, therefore an estimate must not be invented there.
    """
    if order_total < _SMART_ESTIMATE_RATES[0][0]:
        return None
    rate: Decimal | None = None
    for threshold, candidate in _SMART_ESTIMATE_RATES:
        if order_total >= threshold:
            rate = candidate
        else:
            break
    return rate


def _is_smart_order(row: dict) -> bool:
    """Return whether Allegro marks the checkout form as a Smart delivery.

    The temporary rate is intentionally carrier-independent. Allegro's real
    billing entry replaces it shortly afterwards and remains authoritative.
    """
    return row.get("delivery_is_smart") is True


class SyncResult:
    def __init__(
        self,
        account_id: int,
        account_name: str,
        orders_count: int,
        billing_count: int,
        offers_count: int,
        days_fetched: int,
        synced_at: datetime,
        error: str | None = None,
    ):
        self.account_id = account_id
        self.account_name = account_name
        self.orders_count = orders_count
        self.billing_count = billing_count
        self.offers_count = offers_count
        self.days_fetched = days_fetched
        self.synced_at = synced_at
        self.error = error

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "orders_count": self.orders_count,
            "billing_count": self.billing_count,
            "offers_count": self.offers_count,
            "days_fetched": self.days_fetched,
            "synced_at": self.synced_at.isoformat(),
            "error": self.error,
        }


class ImportService:
    def __init__(self, db: Session):
        self.db = db
        self.allegro = AllegroService(db)

    def sync_account(self, account_id: int, days: int = 90) -> SyncResult:
        account = self.db.get(Account, account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        tenant_id = account.tenant_id

        now = _now()
        date_from = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        date_to = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        orders_count = billing_count = offers_count = 0
        order_events_count = customer_returns_count = payment_refunds_count = 0
        error: str | None = None

        try:
            self._remove_expired_smart_estimates(account_id, tenant_id)
            self._sync_billing_types_if_stale(account_id)
            orders_count = self._sync_orders(account_id, tenant_id, date_from, date_to)
            billing_count = self._sync_billing(account_id, tenant_id, date_from, date_to)
            self._remove_replaced_smart_estimates(account_id, tenant_id)
            offers_count = self._sync_offers(account_id, tenant_id)
            customer_returns_count = self._sync_customer_returns(account_id, tenant_id, date_from, date_to)
            payment_refunds_count = self._sync_payment_refunds(account_id, tenant_id, date_from, date_to)
            order_events_count = self._sync_order_events(account_id, tenant_id)
            logger.info(
                "Sync OK account=%d orders=%d billing=%d offers=%d customer_returns=%d payment_refunds=%d order_events=%d days=%d",
                account_id, orders_count, billing_count, offers_count, customer_returns_count, payment_refunds_count, order_events_count, days,
            )
        except Exception as exc:
            error = str(exc)
            logger.error("Sync FAILED account=%d: %s", account_id, error)
            self.db.rollback()

        log = SyncLog(
            tenant_id=tenant_id,
            account_id=account_id,
            synced_at=now,
            days_fetched=days,
            orders_count=orders_count,
            billing_count=billing_count,
            offers_count=offers_count,
            error=error,
        )
        self.db.add(log)
        self.db.commit()

        return SyncResult(
            account_id=account_id,
            account_name=account.name,
            orders_count=orders_count,
            billing_count=billing_count,
            offers_count=offers_count,
            days_fetched=days,
            synced_at=now,
            error=error,
        )

    # ── Private sync methods ───────────────────────────────────────────────

    def sync_offers_only(self, account_id: int) -> int:
        account = self.db.get(Account, account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        return self._sync_offers(account.id, account.tenant_id)

    def _sync_orders(self, account_id: int, tenant_id: int, date_from: str, date_to: str) -> int:
        rows = self.allegro.get_all_orders(account_id, date_from, date_to)
        if not rows:
            return 0
        stmt = pg_insert(OrderRaw).values(
            [
                {
                    "line_item_id": r["line_item_id"],
                    "tenant_id": tenant_id,
                    "order_id": r["order_id"],
                    "account_id": account_id,
                    "offer_id": r["offer_id"],
                    "sku": _normalize_sku(r["sku"]),
                    "buyer_login": r["buyer_login"],
                    "quantity": r["quantity"],
                    "unit_price": Decimal(str(r["unit_price"])),
                    "vat_rate": Decimal(str(r["vat_rate"])) if r.get("vat_rate") else None,
                    "delivery_amount": Decimal(str(r.get("delivery_amount", "0") or "0")),
                    "currency": r["currency"],
                    "status": r["status"],
                    "bought_at": _parse_dt(r["bought_at"]),
                }
                for r in rows
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["line_item_id"],
            set_={
                "status": stmt.excluded.status,
                "unit_price": stmt.excluded.unit_price,
                "vat_rate": stmt.excluded.vat_rate,
                "quantity": stmt.excluded.quantity,
                "delivery_amount": stmt.excluded.delivery_amount,
            },
        )
        self.db.execute(stmt)
        self.db.commit()
        self._upsert_smart_shipping_estimates(account_id, tenant_id, rows)
        auto_import_from_orders(account_id, self.db)
        return len(rows)

    def _upsert_smart_shipping_estimates(self, account_id: int, tenant_id: int, rows: list[dict]) -> int:
        """Upsert one current Smart estimate per eligible checkout form.

        Estimates are intentionally limited to today/yesterday in Warsaw. The
        scheduler's 90-day backfill must never change settled historic P&L.
        """
        local_today = datetime.now(UTC).astimezone(_WARSAW).date()
        earliest = local_today - timedelta(days=1)
        totals: dict[str, dict] = {}
        for row in rows:
            if not _is_smart_order(row):
                continue
            bought_at = _parse_dt(row.get("bought_at"))
            if not bought_at or bought_at.replace(tzinfo=UTC).astimezone(_WARSAW).date() < earliest:
                continue
            if row.get("currency") not in (None, "PLN"):
                continue
            order_id = row.get("order_id")
            if not order_id:
                continue
            item = totals.setdefault(order_id, {"total": Decimal("0"), "bought_at": bought_at})
            item["total"] += Decimal(str(row.get("unit_price") or "0")) * int(row.get("quantity") or 0)
            item["bought_at"] = min(item["bought_at"], bought_at)

        estimate_rows: list[dict] = []
        for order_id, item in totals.items():
            rate = _smart_estimate_rate(item["total"])
            if rate is None:
                continue
            estimate_rows.append({
                "entry_id": f"{_SMART_ESTIMATE_PREFIX}{account_id}:{order_id}",
                "tenant_id": tenant_id,
                "account_id": account_id,
                "order_id": order_id,
                "type": _SMART_ESTIMATE_TYPE,
                "amount": -rate,
                "currency": "PLN",
                "occurred_at": item["bought_at"],
                "shipping_is_smart": True,
                "shipping_order_is_smart": True,
            })
        if not estimate_rows:
            return 0

        # Do not create an estimate when a real Smart fee is already present.
        order_ids = [row["order_id"] for row in estimate_rows]
        actual_order_ids = set(self.db.execute(text("""
            SELECT DISTINCT order_id
            FROM billing_raw
            WHERE tenant_id = :tenant_id
              AND account_id = :account_id
              AND order_id = ANY(:order_ids)
              AND type = ANY(:types)
              AND (shipping_is_smart IS TRUE OR shipping_order_is_smart IS TRUE)
        """), {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "order_ids": order_ids,
            "types": list(_REAL_SMART_SHIPPING_TYPES),
        }).scalars().all())
        estimate_rows = [row for row in estimate_rows if row["order_id"] not in actual_order_ids]
        if not estimate_rows:
            return 0

        stmt = pg_insert(BillingRaw).values(estimate_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["entry_id"],
            set_={
                "amount": stmt.excluded.amount,
                "occurred_at": stmt.excluded.occurred_at,
                "shipping_is_smart": True,
                "shipping_order_is_smart": True,
            },
        )
        self.db.execute(stmt)
        self.db.commit()
        logger.info("Smart estimate upserted account=%d orders=%d", account_id, len(estimate_rows))
        return len(estimate_rows)

    def _remove_replaced_smart_estimates(self, account_id: int, tenant_id: int) -> int:
        """Remove synthetic SMART only after the corresponding real API fee exists."""
        result = self.db.execute(text("""
            DELETE FROM billing_raw estimate
            WHERE estimate.tenant_id = :tenant_id
              AND estimate.account_id = :account_id
              AND estimate.type = :estimate_type
              AND estimate.entry_id LIKE :prefix
              AND EXISTS (
                  SELECT 1
                  FROM billing_raw actual
                  WHERE actual.tenant_id = estimate.tenant_id
                    AND actual.account_id = estimate.account_id
                    AND actual.order_id = estimate.order_id
                    AND actual.type = ANY(:types)
                    AND (actual.shipping_is_smart IS TRUE OR actual.shipping_order_is_smart IS TRUE)
              )
        """), {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "estimate_type": _SMART_ESTIMATE_TYPE,
            "prefix": f"{_SMART_ESTIMATE_PREFIX}%",
            "types": list(_REAL_SMART_SHIPPING_TYPES),
        })
        if result.rowcount:
            self.db.commit()
            logger.info("Smart estimate replaced by API fee account=%d orders=%d", account_id, result.rowcount)
        return result.rowcount or 0

    def _remove_expired_smart_estimates(
        self,
        account_id: int,
        tenant_id: int,
        *,
        as_of: datetime | None = None,
    ) -> int:
        """Remove synthetic Smart forecasts seven days after the order time."""
        cutoff = (as_of or _now()) - _SMART_ESTIMATE_TTL
        result = self.db.execute(text("""
            DELETE FROM billing_raw
            WHERE tenant_id = :tenant_id
              AND account_id = :account_id
              AND type = :estimate_type
              AND entry_id LIKE :prefix
              AND occurred_at <= :cutoff
        """), {
            "tenant_id": tenant_id,
            "account_id": account_id,
            "estimate_type": _SMART_ESTIMATE_TYPE,
            "prefix": f"{_SMART_ESTIMATE_PREFIX}%",
            "cutoff": cutoff,
        })
        if result.rowcount:
            self.db.commit()
            logger.info("Smart forecast expired account=%d orders=%d", account_id, result.rowcount)
        return result.rowcount or 0

    def _sync_order_events(self, account_id: int, tenant_id: int) -> int:
        state = self.db.get(AccountImportState, account_id)
        if not state:
            state = AccountImportState(account_id=account_id, tenant_id=tenant_id)
            self.db.add(state)
            self.db.flush()

        if not state.latest_order_event_id:
            latest = self.allegro.get_latest_order_event(account_id)
            if latest:
                state.latest_order_event_id = latest.get("id")
                state.latest_order_event_at = _parse_dt(latest.get("occurredAt"))
                self.db.commit()
            return 0

        events = self.allegro.get_order_events(account_id, state.latest_order_event_id)
        if not events:
            return 0

        stmt = pg_insert(OrderEventRaw).values(
            [
                {
                    "event_id": e.get("id"),
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "order_id": ((e.get("order") or {}).get("checkoutForm") or {}).get("id"),
                    "event_type": e.get("type"),
                    "checkout_form_revision": ((e.get("order") or {}).get("checkoutForm") or {}).get("revision"),
                    "occurred_at": _parse_dt(e.get("occurredAt")),
                }
                for e in events
                if e.get("id") and e.get("type")
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["event_id"],
            set_={
                "order_id": stmt.excluded.order_id,
                "event_type": stmt.excluded.event_type,
                "checkout_form_revision": stmt.excluded.checkout_form_revision,
                "occurred_at": stmt.excluded.occurred_at,
            },
        )
        self.db.execute(stmt)
        self._apply_order_events_to_orders(events, account_id, tenant_id)

        last = events[-1]
        state.latest_order_event_id = last.get("id")
        state.latest_order_event_at = _parse_dt(last.get("occurredAt"))
        self.db.commit()
        return len(events)

    def _apply_order_events_to_orders(self, events: list[dict], account_id: int, tenant_id: int) -> int:
        status_by_order: dict[str, str] = {}
        for event in events:
            order_id = ((event.get("order") or {}).get("checkoutForm") or {}).get("id")
            event_type = event.get("type")
            if not order_id or not event_type:
                continue
            if event_type in {"BUYER_CANCELLED", "AUTO_CANCELLED"}:
                status_by_order[order_id] = "CANCELLED"
            elif event_type == "READY_FOR_PROCESSING" and status_by_order.get(order_id) != "CANCELLED":
                status_by_order[order_id] = "READY_FOR_PROCESSING"

        if not status_by_order:
            return 0

        updated = 0
        for order_id, status in status_by_order.items():
            result = self.db.execute(
                text("""
                    UPDATE orders_raw
                    SET status = :status
                    WHERE tenant_id = :tenant_id
                      AND account_id = :account_id
                      AND order_id = :order_id
                      AND status IS DISTINCT FROM :status
                """),
                {
                    "status": status,
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "order_id": order_id,
                },
            )
            updated += result.rowcount or 0
        if updated:
            logger.info("Applied order events account=%d updated_order_lines=%d", account_id, updated)
        return updated

    def _sync_customer_returns(self, account_id: int, tenant_id: int, date_from: str, date_to: str) -> int:
        rows = self.allegro.get_all_customer_returns(account_id, date_from, date_to)
        if not rows:
            return 0
        rows = _dedupe_by_id(rows)

        stmt = pg_insert(CustomerReturnRaw).values(
            [
                {
                    "customer_return_id": r.get("id"),
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "order_id": r.get("orderId"),
                    "reference_number": r.get("referenceNumber"),
                    "buyer_login": ((r.get("buyer") or {}).get("login")),
                    "buyer_email": ((r.get("buyer") or {}).get("email")),
                    "status": r.get("status"),
                    "marketplace_id": r.get("marketplaceId"),
                    "is_fulfillment": bool(r.get("isFulfillment")),
                    "created_at": _parse_dt(r.get("createdAt")),
                }
                for r in rows
                if r.get("id")
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["customer_return_id"],
            set_={
                "order_id": stmt.excluded.order_id,
                "reference_number": stmt.excluded.reference_number,
                "buyer_login": stmt.excluded.buyer_login,
                "buyer_email": stmt.excluded.buyer_email,
                "status": stmt.excluded.status,
                "marketplace_id": stmt.excluded.marketplace_id,
                "is_fulfillment": stmt.excluded.is_fulfillment,
                "created_at": stmt.excluded.created_at,
            },
        )
        self.db.execute(stmt)

        ids = [r["id"] for r in rows if r.get("id")]
        if ids:
            self.db.execute(
                text("DELETE FROM customer_return_items_raw WHERE tenant_id = :tenant_id AND customer_return_id = ANY(:ids)"),
                {"tenant_id": tenant_id, "ids": ids},
            )

        item_rows = []
        for r in rows:
            return_id = r.get("id")
            if not return_id:
                continue
            for idx, item in enumerate(r.get("items") or []):
                price = item.get("price") or {}
                reason = item.get("reason") or {}
                item_rows.append(
                    {
                        "tenant_id": tenant_id,
                        "customer_return_id": return_id,
                        "item_index": idx,
                        "offer_id": item.get("offerId"),
                        "name": item.get("name"),
                        "quantity": int(item.get("quantity") or 0),
                        "unit_price": Decimal(str(price.get("amount"))) if price.get("amount") is not None else None,
                        "currency": price.get("currency"),
                        "reason_type": reason.get("type"),
                        "reason_user_comment": reason.get("userComment"),
                    }
                )

        if item_rows:
            self.db.execute(pg_insert(CustomerReturnItemRaw).values(item_rows))
        self.db.commit()
        return len(rows)

    def _sync_payment_refunds(self, account_id: int, tenant_id: int, date_from: str, date_to: str) -> int:
        rows = self.allegro.get_all_payment_refunds(account_id, date_from, date_to)
        if not rows:
            return 0
        rows = _dedupe_by_id(rows)

        stmt = pg_insert(PaymentRefundRaw).values(
            [
                {
                    "refund_id": r.get("id"),
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "payment_id": ((r.get("payment") or {}).get("id")),
                    "order_id": ((r.get("order") or {}).get("id")) if isinstance(r.get("order"), dict) else None,
                    "reason": r.get("reason"),
                    "status": r.get("status"),
                    "created_at": _parse_dt(r.get("createdAt") or r.get("occurredAt")),
                    "total_amount": Decimal(str(((r.get("totalValue") or {}).get("amount")) or "0")),
                    "currency": ((r.get("totalValue") or {}).get("currency")) or "PLN",
                    "delivery_amount": Decimal(str((((r.get("delivery") or {}).get("value") or {}).get("amount")) or "0")),
                    "overpaid_amount": Decimal(str((((r.get("overpaid") or {}).get("value") or {}).get("amount")) or "0")),
                    "additional_services_amount": Decimal(str((((r.get("additionalServices") or {}).get("value") or {}).get("amount")) or "0")),
                }
                for r in rows
                if r.get("id")
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["refund_id"],
            set_={
                "payment_id": stmt.excluded.payment_id,
                "order_id": stmt.excluded.order_id,
                "reason": stmt.excluded.reason,
                "status": stmt.excluded.status,
                "created_at": stmt.excluded.created_at,
                "total_amount": stmt.excluded.total_amount,
                "currency": stmt.excluded.currency,
                "delivery_amount": stmt.excluded.delivery_amount,
                "overpaid_amount": stmt.excluded.overpaid_amount,
                "additional_services_amount": stmt.excluded.additional_services_amount,
            },
        )
        self.db.execute(stmt)

        ids = [r["id"] for r in rows if r.get("id")]
        if ids:
            self.db.execute(
                text("DELETE FROM payment_refund_line_items_raw WHERE tenant_id = :tenant_id AND refund_id = ANY(:ids)"),
                {"tenant_id": tenant_id, "ids": ids},
            )

        item_rows = []
        for r in rows:
            refund_id = r.get("id")
            if not refund_id:
                continue
            for idx, item in enumerate(r.get("lineItems") or []):
                value = item.get("value") or {}
                item_rows.append(
                    {
                        "tenant_id": tenant_id,
                        "refund_id": refund_id,
                        "item_index": idx,
                        "line_item_id": item.get("id"),
                        "refund_type": item.get("type"),
                        "quantity": int(item.get("quantity")) if item.get("quantity") is not None else None,
                        "value_amount": Decimal(str(value.get("amount"))) if value.get("amount") is not None else None,
                        "value_currency": value.get("currency"),
                    }
                )

        if item_rows:
            self.db.execute(pg_insert(PaymentRefundLineItemRaw).values(item_rows))
        self.db.commit()
        return len(rows)

    def _sync_billing(self, account_id: int, tenant_id: int, date_from: str, date_to: str) -> int:
        rows = self.allegro.get_all_billing(account_id, date_from, date_to)
        if not rows:
            return 0
        stmt = pg_insert(BillingRaw).values(
            [
                {
                    "entry_id": r["entry_id"],
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "offer_id": r["offer_id"],
                    "order_id": r.get("order_id"),
                    "type": r["type"],
                    "amount": Decimal(str(r["amount"])),
                    "currency": r["currency"],
                    "occurred_at": _parse_dt(r["occurred_at"]),
                    "ads_service_date": date.fromisoformat(r["ads_service_date"]) if r.get("ads_service_date") else None,
                    "shipping_is_smart": r.get("shipping_is_smart"),
                    "shipping_order_is_smart": r.get("shipping_order_is_smart"),
                }
                for r in rows
            ]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["entry_id"],
            set_={
                "amount": stmt.excluded.amount,
                "order_id": stmt.excluded.order_id,
                "ads_service_date": func.coalesce(stmt.excluded.ads_service_date, BillingRaw.ads_service_date),
                "shipping_is_smart": func.coalesce(stmt.excluded.shipping_is_smart, BillingRaw.shipping_is_smart),
                "shipping_order_is_smart": func.coalesce(
                    stmt.excluded.shipping_order_is_smart,
                    BillingRaw.shipping_order_is_smart,
                ),
            },
        )
        self.db.execute(stmt)
        self.db.commit()
        return len(rows)

    def _sync_offers(self, account_id: int, tenant_id: int) -> int:
        rows = self.allegro.get_all_offers(account_id)
        now = _now()
        self.db.execute(
            text("""
                UPDATE offers_cache
                SET stock_available = NULL, synced_at = :synced_at
                WHERE tenant_id = :tenant_id AND account_id = :account_id
            """),
            {"tenant_id": tenant_id, "account_id": account_id, "synced_at": now},
        )
        if rows:
            stmt = pg_insert(OfferCache).values(
                [
                    {
                        "offer_id": r["offer_id"],
                        "tenant_id": tenant_id,
                        "account_id": account_id,
                        "sku": _normalize_sku(r["sku"]),
                        "name": r["name"],
                        "price": Decimal(str(r["price"])) if r["price"] else None,
                        "vat_rate": Decimal(str(r["vat_rate"])) if r.get("vat_rate") else None,
                        "stock_available": int(r["stock_available"]) if r.get("stock_available") is not None else None,
                        "currency": r["currency"],
                        "ean": r.get("ean"),
                        "synced_at": now,
                    }
                    for r in rows
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["account_id", "offer_id"],
                set_={
                    "sku": stmt.excluded.sku,
                    "name": stmt.excluded.name,
                    "price": stmt.excluded.price,
                    "vat_rate": stmt.excluded.vat_rate,
                    "stock_available": stmt.excluded.stock_available,
                    "ean": func.coalesce(stmt.excluded.ean, OfferCache.ean),
                    "synced_at": stmt.excluded.synced_at,
                },
            )
            self.db.execute(stmt)
        self._sync_stock_from_offer_cache(tenant_id)
        self.db.commit()
        return len(rows)

    def _sync_stock_from_offer_cache(self, tenant_id: int) -> dict:
        rows = self.db.execute(
            text("""
                SELECT sku, COALESCE(SUM(stock_available), 0) AS quantity
                FROM offers_cache
                WHERE tenant_id = :tenant_id
                  AND sku IS NOT NULL
                  AND stock_available IS NOT NULL
                GROUP BY sku
            """),
            {"tenant_id": tenant_id},
        ).fetchall()
        quantity_by_sku = {row.sku: int(row.quantity) for row in rows}
        if not quantity_by_sku:
            return {"added": 0, "updated": 0, "skipped": 0}

        skus = (
            self.db.query(SkuMaster)
            .filter(SkuMaster.tenant_id == tenant_id, SkuMaster.sku_key.in_(quantity_by_sku.keys()))
            .all()
        )
        existing = {
            row.sku_id: row
            for row in self.db.query(StockLevel).filter(StockLevel.tenant_id == tenant_id).all()
        }
        now = _now()
        added = updated = skipped = 0
        matched_keys: set[str] = set()
        for sku in skus:
            matched_keys.add(sku.sku_key)
            if _is_bundle(sku.name):
                skipped += 1
                continue
            quantity = quantity_by_sku[sku.sku_key]
            level = existing.get(sku.id)
            if level:
                if not level.sync_from_allegro:
                    skipped += 1
                    continue
                level.quantity = quantity
                level.updated_at = now
                level.updated_by = "allegro"
                updated += 1
            else:
                self.db.add(StockLevel(
                    tenant_id=tenant_id,
                    sku_id=sku.id,
                    quantity=quantity,
                    updated_by="allegro",
                    updated_at=now,
                    sync_from_allegro=True,
                ))
                added += 1
        skipped += len(set(quantity_by_sku) - matched_keys)
        return {"added": added, "updated": updated, "skipped": skipped}


    def _sync_billing_types_if_stale(self, account_id: int) -> None:
        """Fetch Allegro billing-types and upsert into DB; skips if data is <7 days old."""
        cutoff = _now() - timedelta(days=7)
        newest = self.db.execute(
            text("SELECT MAX(fetched_at) FROM billing_type_labels")
        ).scalar()
        if newest and newest > cutoff:
            logger.debug("billing_type_labels fresh (fetched %s), skipping", newest)
            return

        logger.info("Fetching billing types from Allegro API (account=%d)", account_id)
        try:
            types = self.allegro.get_billing_types(account_id)
        except Exception as exc:
            logger.warning("Could not fetch billing types: %s", exc)
            return

        now = _now()
        if not types:
            logger.warning("Allegro returned empty billingTypes list")
            return

        # API uses "description" field (not "name")
        rows = [{"type_id": t["id"], "name_pl": t.get("description") or t.get("name") or t["id"], "fetched_at": now} for t in types]
        stmt = pg_insert(BillingTypeLabel).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["type_id"],
            set_={"name_pl": stmt.excluded.name_pl, "fetched_at": stmt.excluded.fetched_at},
        )
        self.db.execute(stmt)
        self.db.commit()
        logger.info("billing_type_labels upserted %d rows", len(rows))

        # Log the previously-unknown codes
        fetched_ids = {t["id"] for t in types}
        for t in types:
            if t["id"] in _WATCH_CODES:
                label = t.get("description") or t.get("name") or "?"
                logger.info("BILLING TYPE resolved — %s → '%s'", t["id"], label)
        missing = _WATCH_CODES - fetched_ids
        if missing:
            logger.info("BILLING TYPE still not in Allegro response: %s", sorted(missing))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _dedupe_by_id(rows: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for row in rows:
        row_id = row.get("id")
        if row_id:
            deduped[row_id] = row
    return list(deduped.values())
