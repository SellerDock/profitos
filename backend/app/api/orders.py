from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.core.tenant import TenantScope, get_scope

router = APIRouter(prefix="/orders", tags=["orders"])


def _d(v) -> Decimal:
    if v is None:
        return Decimal("0")
    return Decimal(str(v))


@router.get("/recent")
def recent_orders(
    limit: int = Query(100, ge=1, le=500),
    smart_only: bool = Query(False, description="Return only orders with assigned Allegro Smart delivery costs"),
    account_id: Optional[int] = None,
    scope: TenantScope = Depends(get_scope),
):
    """Return last N orders with per-line-item P&L breakdown.

    Matching of billing entries to orders:
      - Preferred: exact billing.order_id = orders.order_id
      - Fallback: offer_id matches a line item, occurred_at within ±30d of bought_at;
        entry is assigned to the order whose bought_at is closest (greedy, 1:1).
    """
    # ── 1. Last N distinct order_ids by most recent bought_at ─────────────────
    # "SMART" is our own forecast placeholder, kept in the cost sum so profit stays
    # complete before the real carrier entry lands in billing. The smart_only filter
    # must NOT match it — that switch means "has a settled Delivery Smart cost".
    _SMART_FORECAST_TYPES = ("SMART",)
    _SMART_DELIVERY_TYPES = ("HB4", "HLB", "HXO", "ORB", "DPB", "DXP", "DHR", "DPA", "HB9", "XOR")
    _SMART_TYPES = _SMART_FORECAST_TYPES + _SMART_DELIVERY_TYPES
    params: dict = {
        "lim": limit,
        "tenant_id": scope.tenant_id,
        "smart_types": list(_SMART_DELIVERY_TYPES),
    }
    account_filter = ""
    if account_id is not None:
        account_filter = "AND account_id = :acct"
        params["acct"] = account_id
    smart_filter = ""
    if smart_only:
        smart_filter = """
          AND EXISTS (
              SELECT 1
              FROM billing_raw b
              WHERE b.tenant_id = orders_raw.tenant_id
                AND b.order_id = orders_raw.order_id
                AND b.type = ANY(:smart_types)
                AND b.amount < 0
                AND (b.currency = 'PLN' OR b.currency IS NULL)
                AND (
                    b.shipping_is_smart IS TRUE
                    OR (b.shipping_is_smart IS NULL AND b.shipping_order_is_smart IS TRUE)
                    OR (
                        b.shipping_is_smart IS NULL
                        AND b.shipping_order_is_smart IS NULL
                        AND NOT EXISTS (
                            SELECT 1
                            FROM orders_raw od
                            WHERE od.tenant_id = orders_raw.tenant_id
                              AND od.order_id = orders_raw.order_id
                              AND COALESCE(od.delivery_amount, 0) > 0
                        )
                    )
                )
          )
        """

    order_ids = scope.db.execute(text(f"""
        SELECT order_id
        FROM orders_raw
        WHERE status NOT IN ('CANCELLED')
          AND tenant_id = :tenant_id
          AND (currency = 'PLN' OR currency IS NULL)
          {account_filter}
          {smart_filter}
        GROUP BY order_id
        ORDER BY MAX(bought_at) DESC
        LIMIT :lim
    """), params).scalars().all()

    if not order_ids:
        return []

    # ── 2. Fetch line items + SKU data ────────────────────────────────────────
    items = scope.db.execute(text("""
        SELECT o.order_id, o.line_item_id, o.account_id, o.offer_id, o.sku,
               o.buyer_login, o.quantity, o.unit_price, o.status, o.bought_at,
               a.name AS account_name,
               sm.id AS sku_id, sm.name AS sku_name, COALESCE(sm.vat_rate, o.vat_rate, 23) AS vat_rate,
               esc.ciphertext AS cost_ciphertext,
               esc.nonce AS cost_nonce,
               esc.key_version AS cost_key_version,
               esc.aad_context AS cost_aad_context
        FROM orders_raw o
        LEFT JOIN accounts     a  ON a.id = o.account_id AND a.tenant_id = :tenant_id
        LEFT JOIN sku_masters  sm ON sm.sku_key = o.sku AND sm.tenant_id = :tenant_id
        LEFT JOIN encrypted_sku_costs esc ON esc.sku_master_id = sm.id AND esc.tenant_id = :tenant_id
        WHERE o.order_id = ANY(:ids)
          AND o.tenant_id = :tenant_id
        ORDER BY o.bought_at DESC, o.order_id, o.line_item_id
    """), {"ids": list(order_ids), "tenant_id": scope.tenant_id}).fetchall()

    if not items:
        return []

    # ── 2b. Fetch max delivery_amount per order (to detect Smart passthrough) ──
    delivery_rows = scope.db.execute(text("""
        SELECT order_id, MAX(delivery_amount) AS max_delivery
        FROM orders_raw
        WHERE order_id = ANY(:ids)
          AND tenant_id = :tenant_id
        GROUP BY order_id
    """), {"ids": list(order_ids), "tenant_id": scope.tenant_id}).fetchall()
    order_delivery: dict[str, Decimal] = {r.order_id: _d(r.max_delivery) for r in delivery_rows}

    # ── 3. Fetch all billing entries that could belong to these orders ────────
    offer_ids = list({i.offer_id for i in items if i.offer_id})
    min_dt = min(i.bought_at for i in items) - timedelta(days=30)
    max_dt = max(i.bought_at for i in items) + timedelta(days=30)

    # a) Exact matches by order_id
    exact = scope.db.execute(text("""
        SELECT entry_id, order_id, offer_id, type, amount, occurred_at,
               shipping_is_smart, shipping_order_is_smart
        FROM billing_raw
        WHERE order_id = ANY(:ids)
          AND tenant_id = :tenant_id
    """), {"ids": list(order_ids), "tenant_id": scope.tenant_id}).fetchall()

    # b) Fuzzy matches by offer_id + time window (entries with NULL order_id only,
    #    to avoid double-counting those already matched exactly)
    # FEA ("Opłata za wyróżnienie") is an account-level subscription charged per offer,
    # not per individual order. Excluding it from fuzzy matching prevents it from being
    # attributed to specific orders — it belongs only in account-level dashboard totals.
    _ACCOUNT_LEVEL_TYPES = ('FEA',)

    fuzzy = []
    if offer_ids:
        fuzzy = scope.db.execute(text("""
            SELECT entry_id, offer_id, type, amount, occurred_at,
                   shipping_is_smart, shipping_order_is_smart
            FROM billing_raw
            WHERE order_id IS NULL
              AND tenant_id = :tenant_id
              AND offer_id = ANY(:offers)
              AND type != ALL(:excl)
              AND occurred_at BETWEEN :df AND :dt
        """), {
            "offers": offer_ids,
            "excl": list(_ACCOUNT_LEVEL_TYPES),
            "df": min_dt,
            "dt": max_dt,
            "tenant_id": scope.tenant_id,
        }).fetchall()

    # ── 4. Attribute billing entries to orders ────────────────────────────────
    # order_id -> list of billing entries as dicts
    order_billing: dict[str, list[dict]] = defaultdict(list)

    # Exact matches: billing.order_id directly references the order
    for b in exact:
        order_billing[b.order_id].append({
            "entry_id": b.entry_id, "type": b.type, "amount": str(b.amount),
            "offer_id": b.offer_id, "occurred_at": b.occurred_at.isoformat() if b.occurred_at else None,
            "shipping_is_smart": b.shipping_is_smart,
            "shipping_order_is_smart": b.shipping_order_is_smart,
            "match": "exact",
        })

    # Fuzzy: 1-to-1 greedy match per (offer_id, type) bucket.
    # Rationale: if offer X had 5 sales in one day, there are 5 SUC entries and
    # 5 line items — each entry should go to exactly one line item (closest by
    # time), not all pile onto the nearest visible order. Entries further than
    # ±2 days from any visible line item probably belong to orders NOT in our
    # top-N view, so we skip them.
    FUZZY_WINDOW_SEC = 2 * 86400

    # Group fuzzy entries by (offer_id, type)
    by_offer_type: dict[tuple[str, str], list] = defaultdict(list)
    for b in fuzzy:
        if b.offer_id and b.type:
            by_offer_type[(b.offer_id, b.type)].append(b)

    # Group line items by offer_id
    items_by_offer: dict[str, list] = defaultdict(list)
    for it in items:
        if it.offer_id:
            items_by_offer[it.offer_id].append(it)

    for (offer_id, type_code), entries_list in by_offer_type.items():
        item_list = items_by_offer.get(offer_id, [])
        if not item_list:
            continue

        # Build all (entry, item) pairs within the time window, ranked by closeness
        pairs: list[tuple[float, object, object]] = []
        for b in entries_list:
            for it in item_list:
                dist = abs((b.occurred_at - it.bought_at).total_seconds())
                if dist <= FUZZY_WINDOW_SEC:
                    pairs.append((dist, b, it))
        pairs.sort(key=lambda p: p[0])

        used_entries: set[str] = set()
        used_items: set[str]   = set()  # line_item_id — at most one entry per type per line item
        for dist, b, it in pairs:
            if b.entry_id in used_entries or it.line_item_id in used_items:
                continue
            used_entries.add(b.entry_id)
            used_items.add(it.line_item_id)
            order_billing[it.order_id].append({
                "entry_id": b.entry_id, "type": b.type, "amount": str(b.amount),
                "offer_id": b.offer_id, "occurred_at": b.occurred_at.isoformat() if b.occurred_at else None,
                "shipping_is_smart": b.shipping_is_smart,
                "shipping_order_is_smart": b.shipping_order_is_smart,
                "match": "approx",
            })

    # ── 6. Get billing type labels (optional, for Polish names) ───────────────
    labels_rows = scope.db.execute(text("SELECT type_id, name_pl FROM billing_type_labels")).fetchall()
    labels = {r.type_id: r.name_pl for r in labels_rows}
    labels.setdefault("SMART", "Smart Prognoza")

    # ── 7. Build response ─────────────────────────────────────────────────────
    # Group items by order_id
    orders_map: dict[str, dict] = {}
    for it in items:
        oid = it.order_id
        if oid not in orders_map:
            orders_map[oid] = {
                "order_id": oid,
                "bought_at": it.bought_at.isoformat() if it.bought_at else None,
                "buyer_login": it.buyer_login,
                "status": it.status,
                "account_id": it.account_id,
                "account_name": it.account_name,
                "items": [],
                "revenue_net": Decimal("0"),
            }
        revenue = _d(it.unit_price) * it.quantity
        encrypted_cost = None
        if it.cost_ciphertext and it.cost_nonce:
            encrypted_cost = {
                "ciphertext": it.cost_ciphertext,
                "nonce": it.cost_nonce,
                "key_version": it.cost_key_version,
                "aad_context": it.cost_aad_context,
            }
        orders_map[oid]["items"].append({
            "line_item_id": it.line_item_id,
            "sku": it.sku,
            "sku_id": it.sku_id,
            "sku_name": it.sku_name or it.sku,
            "offer_id": it.offer_id,
            "vat_rate": str(it.vat_rate),
            "quantity": it.quantity,
            "unit_price": str(it.unit_price),
            "revenue": str(revenue),
            "encrypted_cost": encrypted_cost,
            "cogs": None,
        })
        orders_map[oid]["revenue_net"] += revenue / (Decimal("1") + _d(it.vat_rate) / Decimal("100"))

    # Aggregate billing per order by type
    result = []
    for oid in order_ids:
        o = orders_map.get(oid)
        if not o:
            continue

        entries = order_billing.get(oid, [])
        costs_by_type: dict[str, Decimal] = defaultdict(Decimal)
        for e in entries:
            # abs() so costs shown as positive magnitudes; positive adjustments (refunds)
            # will also be positive here — client decides sign/color based on type
            costs_by_type[e["type"]] += _d(e["amount"])

        costs_breakdown = [
            {
                "type": t,
                "type_name": labels.get(t, t),
                "amount": str(v),
            }
            for t, v in sorted(costs_by_type.items(), key=lambda kv: -abs(kv[1]))
        ]

        order_has_delivery = order_delivery.get(oid, Decimal("0")) > 0

        def _is_smart_entry(e: dict) -> bool:
            # Smart cost counts only when the buyer did NOT pay delivery.
            # Legacy rows without Smart flags fall back to delivery_amount.
            return (
                e.get("shipping_is_smart") is True
                or (e.get("shipping_is_smart") is None and e.get("shipping_order_is_smart") is True)
                or (
                    e.get("shipping_is_smart") is None
                    and e.get("shipping_order_is_smart") is None
                    and not order_has_delivery
                )
            )

        def _sum_smart(types: tuple[str, ...]) -> Decimal:
            return sum(
                (_d(e["amount"]) for e in entries if e["type"] in types and _is_smart_entry(e)),
                Decimal("0"),
            )

        # Stored as negative, exposed as positive magnitudes.
        smart_forecast_cost = -_sum_smart(_SMART_FORECAST_TYPES)
        smart_delivery_cost = -_sum_smart(_SMART_DELIVERY_TYPES)
        smart_cost = smart_forecast_cost + smart_delivery_cost

        revenue = sum((_d(i["revenue"]) for i in o["items"]), Decimal("0"))
        # Allegro billing entries are stored as negative for costs, positive for refunds.
        # Net cost to the order is -sum(amounts) (negatives → positive cost).
        costs_net = sum((_d(e["amount"]) for e in entries), Decimal("0"))
        # For the order, "costs_total" = absolute cost to Allegro = -costs_net
        costs_total = -costs_net

        result.append({
            **o,
            "revenue":       str(revenue),
            "revenue_net":   str(o["revenue_net"]),
            "cogs":          None,
            "costs_total":   str(costs_total),
            "smart_cost":    str(smart_cost),
            "smart_forecast_cost": str(smart_forecast_cost),
            "smart_delivery_cost": str(smart_delivery_cost),
            "profit_net":    None,
            "margin_pct":    None,
            "costs":         costs_breakdown,
            "entries_count": len(entries),
            "exact_match_count": sum(1 for e in entries if e["match"] == "exact"),
        })

    return result
