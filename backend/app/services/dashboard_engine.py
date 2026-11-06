"""
Dashboard Engine — computes P&L summary and per-SKU breakdown for a given period.

Billing type classification (canonical taxonomy — each code appears in exactly one group):
  _SUC               = ("SUC",)                                  commission_cost
  _FSF               = ("FSF",)                                  featuring_commission_cost
  _ADS               = ("NSP",)                                  ads_cost (daily campaign fee, no order_id)
  _SMART_SHIPPING    = ("HB4","HLB","HXO","ORB","DPB","DXP",
                        "DHR","DPA","HB9","XOR")               shipping fees, split by Allegro Smart flags
  _FOREIGN_SHIPPING  = ("HB1","HB8")                             foreign_shipping_cost (buyer passthrough — excluded from profit)
  _FEATURING         = ("FEA",)                                  featuring_cost
  _COINS             = ("CPF","RCP")                             coins_cost (net of coin refunds)
  _PRICE_ADJUST      = ("PS1","PSA")                             price_adjust_cost (can be positive)
  _PROTECT           = ("INS",)                                  protect_cost
  _LOCAL             = ("ALC","ALS","ALK","ALI","ALL","ALP")     local_cost
  _SUBSCRIPTION      = ("SB1","SB2","SB3","SB4","SBL","SBP","SH0","SH1","ST1","ST2","ILF","ABO")  subscription_cost
  _REFUND            = ("REF",)                                  refund_commission (positive)
  _FULFILLMENT_BASE  = ("OFA",)                                  fulfillment_base_cost
  _FULFILLMENT_STORAGE = ("OF1","OFB","OFC","OFD","OFQ","OFR","OFS","OFU","OFZ") fulfillment_storage_cost
  _FULFILLMENT_RETURNS = ("OFE","OFF","OFI")                     fulfillment_returns_cost
  _FULFILLMENT_SUBSCRIPTION = ("OFM",)                           fulfillment_subscription_cost
  _FULFILLMENT_OTHER = ("SHIPMENT_SURCHARGE","OFG","OFH","OFJ","OFK","OFL","OFN","OFP","OFT","OFW","OFX","OFY") fulfillment_other_cost
  _EXCLUDE           = ("PAD","PB2","PBL",...)                   bookkeeping — excluded from all aggregates

Order-date attribution:
  Codes in _ATTRIBUTED_BY_ORDER are re-attributed from their billing date (occurred_at)
  to the order's purchase date (bought_at). This corrects per-day P&L when Allegro books
  shipping/commission fees days after the order was placed. ADS uses Allegro's feeDate
  ("Opłata za dzień") when present, then falls back to billing date. Other account-level
  fees (subscription, local, protect) keep their billing date.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional
import calendar
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.tenant import TenantScope

WARSAW = ZoneInfo("Europe/Warsaw")

SUPPORTED_PERIOD_KEYS = (
    "today",
    "yesterday",
    "last_7d",
    "last_14d",
    "last_30d",
    "last_90d",
    "current_month",
    "last_month",
    "ytd",
    "custom",
)

# ── Billing type sets ──────────────────────────────────────────────────────────

_SUC            = ("SUC",)
_FSF            = ("FSF",)
_ADS            = ("NSP",)
_SMART_SHIPPING = ("SMART", "HB4", "HLB", "HXO", "ORB", "DPB", "DXP", "DHR", "DPA", "HB9", "XOR")
_FOREIGN_SHIPPING = ("HB1", "HB8")
_FEATURING      = ("FEA",)
_COINS          = ("CPF", "RCP")
_CAMPAIGN_COST  = ("BRG",)
_CAMPAIGN_BONUS = ("CB2",)
_PRICE_ADJUST   = ("PS1", "PSA")
_PROTECT        = ("INS",)
_LOCAL          = ("ALC", "ALS", "ALK", "ALI", "ALL", "ALP")
_SUBSCRIPTION   = ("SB1", "SB2", "SB3", "SB4", "SBL", "SBP", "SH0", "SH1", "ST1", "ST2", "ILF", "ABO")
_REFUND         = ("REF",)
_FULFILLMENT_BASE         = ("OFA",)
_FULFILLMENT_STORAGE      = ("OF1", "OFB", "OFC", "OFD", "OFQ", "OFR", "OFS", "OFU", "OFZ")
_FULFILLMENT_RETURNS      = ("OFE", "OFF", "OFI")
_FULFILLMENT_SUBSCRIPTION = ("OFM",)
_FULFILLMENT_OTHER        = ("SHIPMENT_SURCHARGE", "OFG", "OFH", "OFJ", "OFK", "OFL", "OFN", "OFP", "OFT", "OFW", "OFX", "OFY")
_FULFILLMENT              = (
    _FULFILLMENT_BASE
    + _FULFILLMENT_STORAGE
    + _FULFILLMENT_RETURNS
    + _FULFILLMENT_SUBSCRIPTION
    + _FULFILLMENT_OTHER
)

_EXCLUDE = (
    # Deposits / withdrawals / balance transfers — not real costs or revenue
    "PAD", "PB2", "PBL",
    # Legacy transfers and misc bookkeeping
    "SUM", "PAL", "PAK", "PFB", "PFC", "PKO",
    "RFF", "MFB", "PCO", "PAY", "PRR", "PRT", "PRU", "PRV", "PRW",
    "TRF", "PRA", "PMC", "OVR", "APF", "AFP", "VER",
    # VAT postings — handled separately in accounting
    "VAT", "VEP", "VEC", "VRF",
    # Corrections / adjustments to account balance (not per-sale)
    "COR", "CXR", "COL", "RIC", "RIP",
    "DIS", "PUK", "WOM", "RET", "CPS", "ZNP",
)

# ── Disjoint-category assertion ────────────────────────────────────────────────
# Each billing code must appear in exactly one classification tuple.
_ALL_CATEGORIES: list[tuple[str, tuple]] = [
    ("_SUC",            _SUC),
    ("_FSF",            _FSF),
    ("_ADS",            _ADS),
    ("_SMART_SHIPPING", _SMART_SHIPPING),
    ("_FOREIGN_SHIPPING", _FOREIGN_SHIPPING),
    ("_FEATURING",      _FEATURING),
    ("_COINS",          _COINS),
    ("_CAMPAIGN_COST",  _CAMPAIGN_COST),
    ("_CAMPAIGN_BONUS", _CAMPAIGN_BONUS),
    ("_PRICE_ADJUST",   _PRICE_ADJUST),
    ("_PROTECT",        _PROTECT),
    ("_LOCAL",          _LOCAL),
    ("_SUBSCRIPTION",   _SUBSCRIPTION),
    ("_REFUND",         _REFUND),
    ("_FULFILLMENT_BASE", _FULFILLMENT_BASE),
    ("_FULFILLMENT_STORAGE", _FULFILLMENT_STORAGE),
    ("_FULFILLMENT_RETURNS", _FULFILLMENT_RETURNS),
    ("_FULFILLMENT_SUBSCRIPTION", _FULFILLMENT_SUBSCRIPTION),
    ("_FULFILLMENT_OTHER", _FULFILLMENT_OTHER),
    ("_EXCLUDE",        _EXCLUDE),
]

_seen: dict[str, str] = {}
for _cat_name, _cat_codes in _ALL_CATEGORIES:
    for _code in _cat_codes:
        if _code in _seen:
            raise AssertionError(
                f"Billing code '{_code}' appears in both {_seen[_code]} and {_cat_name}. "
                "Category tuples must be disjoint."
            )
        _seen[_code] = _cat_name
del _seen, _cat_name, _cat_codes, _code

# ── SQL helpers ────────────────────────────────────────────────────────────────
def _dedup(t): return tuple(dict.fromkeys(t))
_EXCLUDE = _dedup(_EXCLUDE)

def _sql_in(types: tuple) -> str:
    return "(" + ",".join(f"'{t}'" for t in types) + ")"

_SUC_IN             = _sql_in(_SUC)
_FSF_IN             = _sql_in(_FSF)
_ADS_IN             = _sql_in(_ADS)
_SMART_IN           = _sql_in(_SMART_SHIPPING)
_SMART_FORECAST_IN  = _sql_in(("SMART",))
_BILLING_LOCAL_DATE_SQL = "((b.occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date"
_ADS_OR_BILLING_DATE_SQL = (
    f"CASE WHEN b.type IN {_ADS_IN} AND b.ads_service_date IS NOT NULL "
    f"THEN b.ads_service_date ELSE {_BILLING_LOCAL_DATE_SQL} END"
)
_SMART_SHIPPING_WHERE = (
    f"type IN {_SMART_IN} AND "
    "("
    "shipping_is_smart IS TRUE OR "
    "(shipping_is_smart IS NULL AND shipping_order_is_smart IS TRUE) OR "
    "(shipping_is_smart IS NULL AND shipping_order_is_smart IS NULL AND order_delivery_amount = 0)"
    ")"
)
_SHIPPING_PASSTHROUGH_WHERE = (
    f"type IN {_SMART_IN} AND "
    "("
    "shipping_is_smart IS FALSE OR "
    "(shipping_is_smart IS NULL AND shipping_order_is_smart IS FALSE) OR "
    "(shipping_is_smart IS NULL AND shipping_order_is_smart IS NULL AND order_delivery_amount > 0)"
    ")"
)
_SMART_SHIPPING_WHERE_B = (
    f"b.type IN {_SMART_IN} AND "
    "("
    "b.shipping_is_smart IS TRUE OR "
    "(b.shipping_is_smart IS NULL AND b.shipping_order_is_smart IS TRUE) OR "
    "(b.shipping_is_smart IS NULL AND b.shipping_order_is_smart IS NULL AND b.order_delivery_amount = 0)"
    ")"
)
_SHIPPING_PASSTHROUGH_WHERE_B = (
    f"b.type IN {_SMART_IN} AND "
    "("
    "b.shipping_is_smart IS FALSE OR "
    "(b.shipping_is_smart IS NULL AND b.shipping_order_is_smart IS FALSE) OR "
    "(b.shipping_is_smart IS NULL AND b.shipping_order_is_smart IS NULL AND b.order_delivery_amount > 0)"
    ")"
)
_FOREIGN_IN         = _sql_in(_FOREIGN_SHIPPING)
_FEATURING_IN       = _sql_in(_FEATURING)
_COINS_IN           = _sql_in(_COINS)
_CAMPAIGN_COST_IN   = _sql_in(_CAMPAIGN_COST)
_CAMPAIGN_BONUS_IN  = _sql_in(_CAMPAIGN_BONUS)
_PRICE_ADJUST_IN    = _sql_in(_PRICE_ADJUST)
_PROTECT_IN         = _sql_in(_PROTECT)
_LOCAL_IN           = _sql_in(_LOCAL)
_SUBSCRIPTION_IN    = _sql_in(_SUBSCRIPTION)
_REFUND_IN          = _sql_in(_REFUND)
_FULFIL_BASE_IN     = _sql_in(_FULFILLMENT_BASE)
_FULFIL_STORAGE_IN  = _sql_in(_FULFILLMENT_STORAGE)
_FULFIL_RETURNS_IN  = _sql_in(_FULFILLMENT_RETURNS)
_FULFIL_SUBS_IN     = _sql_in(_FULFILLMENT_SUBSCRIPTION)
_FULFIL_OTHER_IN    = _sql_in(_FULFILLMENT_OTHER)
_FULFIL_IN          = _sql_in(_FULFILLMENT)
_EXCL_IN            = _sql_in(_EXCLUDE)

# All known codes that enter any aggregate (i.e. NOT _EXCLUDE)
_ALL_KNOWN = tuple(code for _, codes in _ALL_CATEGORIES if codes is not _EXCLUDE for code in codes)

# ── Order-date attribution ─────────────────────────────────────────────────────
# These codes are re-attributed from billing date to the order's purchase date.
# Codes with offer_id (SUC, FSF, COINS, campaign rebates/bonuses) have a direct order link.
# Shipping codes (SMART, FOREIGN) are order-level and booked days after delivery.
# ADS is account-level but uses ads_service_date from Allegro feeDate when present.
# FEATURING, PROTECT, LOCAL, SUBSCRIPTION are account-level and kept on billing date.
_ATTRIBUTED_BY_ORDER = (
    _SMART_SHIPPING + _FOREIGN_SHIPPING + _COINS + _CAMPAIGN_COST
    + _CAMPAIGN_BONUS + _PRICE_ADJUST
    + _SUC + _FSF
)
_ATTRIBUTED_BY_ORDER_IN = _sql_in(_ATTRIBUTED_BY_ORDER)

_RETURN_APPROVED_STATUSES = ("COMMISSION_REFUNDED", "FINISHED")
_RETURN_PENDING_STATUSES = ("CREATED", "IN_TRANSIT")
_RETURN_REJECTED_STATUSES = ("REJECTED",)
_RETURN_APPROVED_IN = _sql_in(_RETURN_APPROVED_STATUSES)
_RETURN_PENDING_IN = _sql_in(_RETURN_PENDING_STATUSES)
_RETURN_REJECTED_IN = _sql_in(_RETURN_REJECTED_STATUSES)


def _commission_refund_exclusion_sql(alias: str, account_id: int | None, per_sku: bool = False) -> str:
    """Exclude only positive SUC/FSF rows separately added as approved-return refunds."""
    account_filter = f"AND cr.account_id = {account_id}" if account_id else ""
    sku_join = "JOIN customer_return_items_raw cri ON cri.customer_return_id = cr.customer_return_id AND cri.tenant_id = cr.tenant_id AND cri.offer_id = ro.offer_id" if per_sku else ""
    sku_filter = f"AND ro.offer_id = {alias}.offer_id AND trim(ro.sku) = trim({alias}.sku)" if per_sku else ""
    return f"""NOT (
        {alias}.amount > 0 AND EXISTS (
            SELECT 1
            FROM customer_returns_raw cr
            JOIN orders_raw ro ON ro.order_id = cr.order_id
                              AND ro.account_id = cr.account_id
                              AND ro.tenant_id = cr.tenant_id
            {sku_join}
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cr.order_id = {alias}.order_id
              {account_filter}
              AND (ro.currency = :currency OR ro.currency IS NULL)
              AND ((ro.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {sku_filter}
        )
    )"""


# ── Period helpers ─────────────────────────────────────────────────────────────

@dataclass
class Period:
    date_from: datetime
    date_to: datetime
    label: str

    @property
    def date_from_str(self) -> str:
        return self.date_from.strftime("%Y-%m-%d %H:%M:%S")

    @property
    def date_to_str(self) -> str:
        return self.date_to.strftime("%Y-%m-%d %H:%M:%S")


def _warsaw_midnight_to_utc(d: date) -> datetime:
    """Convert a Warsaw-timezone calendar date midnight to a naive UTC datetime."""
    aware = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=WARSAW)
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def get_period(period_key: str) -> Period:
    """Return UTC start/end for the requested period using Europe/Warsaw timezone (DST-aware)."""
    now_utc = datetime.now(tz=timezone.utc)
    today_warsaw = now_utc.astimezone(WARSAW).date()

    if period_key == "today":
        start = _warsaw_midnight_to_utc(today_warsaw)
        # Use midnight of *next* day so that after the dt_date = dt_date_raw - 1 adjustment
        # in summary(), the effective end date is today (inclusive).
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = "Dzisiaj"
    elif period_key == "last_7d":
        start_day = today_warsaw - timedelta(days=6)
        start = _warsaw_midnight_to_utc(start_day)
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = "Ostatnie 7 dni"
    elif period_key == "last_14d":
        start_day = today_warsaw - timedelta(days=13)
        start = _warsaw_midnight_to_utc(start_day)
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = "Ostatnie 14 dni"
    elif period_key == "last_30d":
        start_day = today_warsaw - timedelta(days=29)
        start = _warsaw_midnight_to_utc(start_day)
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = "Ostatnie 30 dni"
    elif period_key == "last_90d":
        start_day = today_warsaw - timedelta(days=89)
        start = _warsaw_midnight_to_utc(start_day)
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = "Ostatnie 90 dni"
    elif period_key == "yesterday":
        yesterday = today_warsaw - timedelta(days=1)
        start = _warsaw_midnight_to_utc(yesterday)
        end = _warsaw_midnight_to_utc(today_warsaw)
        label = "Wczoraj"
    elif period_key == "current_month":
        first = today_warsaw.replace(day=1)
        start = _warsaw_midnight_to_utc(first)
        end = now_utc.replace(tzinfo=None)
        label = today_warsaw.strftime("%B %Y")
    elif period_key in {"last_month", "previous_month"}:
        first_this = today_warsaw.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        start = _warsaw_midnight_to_utc(first_prev)
        end = _warsaw_midnight_to_utc(first_this)
        label = first_prev.strftime("%B %Y")
    elif period_key == "ytd":
        first = date(today_warsaw.year, 1, 1)
        start = _warsaw_midnight_to_utc(first)
        end = _warsaw_midnight_to_utc(today_warsaw + timedelta(days=1))
        label = f"Rok {today_warsaw.year}"
    else:
        raise ValueError(f"Unknown period: {period_key}")

    return Period(date_from=start, date_to=end, label=label)


def get_custom_period(date_from_str: str, date_to_str: str) -> Period:
    """Build a Period from explicit YYYY-MM-DD strings (Warsaw midnight → UTC)."""
    from_date = date.fromisoformat(date_from_str)
    to_date = date.fromisoformat(date_to_str)
    # end of the to_date day = start of the next day
    start = _warsaw_midnight_to_utc(from_date)
    end = _warsaw_midnight_to_utc(to_date + timedelta(days=1))

    def _fmt(d: date) -> str:
        PL_MONTHS = ["", "sty", "lut", "mar", "kwi", "maj", "cze",
                     "lip", "sie", "wrz", "paź", "lis", "gru"]
        return f"{d.day} {PL_MONTHS[d.month]}"

    if from_date.year == to_date.year:
        label = f"{_fmt(from_date)} – {_fmt(to_date)} {to_date.year}"
    else:
        label = f"{_fmt(from_date)} {from_date.year} – {_fmt(to_date)} {to_date.year}"

    return Period(date_from=start, date_to=end, label=label)


# ── Summary dataclasses ────────────────────────────────────────────────────────

@dataclass
class PnLSummary:
    period_label: str
    date_from: str
    date_to: str

    revenue_gross: str = "0.00"
    revenue_net: str = "0.00"
    sales_gross_value: str = "0.00"
    sales_net_value: str = "0.00"
    buyer_shipping_revenue: str = "0.00"
    buyer_shipping_revenue_net: str = "0.00"
    units_sold: int = 0
    orders_count: int = 0

    # Allegro costs (positive magnitudes; all reduce profit unless noted)
    commission_cost: str = "0.00"             # SUC
    featuring_commission_cost: str = "0.00"   # FSF
    ads_cost: str = "0.00"                    # Allegro Ads total after import/NSP reconciliation
    ads_imported_cost: str = "0.00"           # Allegro Ads IMP from uploaded offer stats
    ads_nsp_adjustment_cost: str = "0.00"     # NSP billing reconciliation; may be negative when import exceeds NSP
    smart_shipping_cost: str = "0.00"         # delivery codes with Allegro Smart flag
    smart_forecast_cost: str = "0.00"         # synthetic SMART forecast included in smart_shipping_cost
    shipping_passthrough_cost: str = "0.00"  # HB4/HLB/… with non-Smart flag — not in profit
    foreign_shipping_cost: str = "0.00"       # HB1/HB8 — buyer passthrough, NOT in profit
    featuring_cost: str = "0.00"              # FEA
    coins_cost: str = "0.00"                  # CPF/RCP — net of coin refunds
    campaign_commission_cost: str = "0.00"    # BRG
    campaign_bonus: str = "0.00"              # CB2 — positive
    price_adjust_cost: str = "0.00"           # PS1/PSA — positive rebate (shown as positive magnitude)
    protect_cost: str = "0.00"                # INS
    local_cost: str = "0.00"                  # ALC/ALS/ALK/ALI/ALL/ALP
    subscription_cost: str = "0.00"           # SB*/SH*/ST*/ILF/ABO
    refund_commission: str = "0.00"           # REF — positive (reduces cost)
    fulfillment: str = "0.00"                 # SHIPMENT_SURCHARGE
    fulfillment_base_cost: str = "0.00"       # OFA
    fulfillment_storage_cost: str = "0.00"    # OF1/OFB/OFC/OFD/OFQ/OFR/OFS/OFU/OFZ
    fulfillment_returns_cost: str = "0.00"    # OFE/OFF/OFI
    fulfillment_subscription_cost: str = "0.00"  # OFM
    fulfillment_other_cost: str = "0.00"      # SHIPMENT_SURCHARGE + remaining OF*

    # total_allegro = sum of all named aggregates EXCEPT foreign_shipping_cost
    total_allegro: str = "0.00"
    total_allegro_net: str = "0.00"

    # Source of ads_cost: "imported", "billing", "mixed", or "none"
    ads_cost_source: str = "billing"

    # Returns (not tracked in current data model)
    returns_revenue: str = "0.00"             # value of returned goods (customer returns)
    returns_revenue_net: str = "0.00"
    returns_count: int = 0
    returns_units: int = 0
    returns_goods_value: str = "0.00"
    returns_goods_value_net: str = "0.00"
    returns_refund_value: str = "0.00"        # payment refunds linked to real returns
    returns_pending_count: int = 0
    returns_pending_units: int = 0
    returns_rejected_count: int = 0
    returns_rejected_units: int = 0
    neutral_cancelled_orders_count: int = 0
    neutral_cancelled_units: int = 0
    neutral_cancelled_value: str = "0.00"

    # Refund metrics
    commission_refunds_amount: str = "0.00"   # Informational: positive Allegro refunds for approved returns
    comparison_revenue_net: str | None = None
    comparison_delta_value_net: str | None = None
    comparison_delta_pct_net: str | None = None
    # refund_cost removed: revenue follows order status; billing refunds are separate metrics.

    # COGS
    cogs: str | None = None

    # Result
    profit_net: str | None = None
    margin_pct: str | None = None
    roi_pct: str | None = None
    kp_ratio: str | None = None
    kcap_ratio: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProductSummaryRow:
    sku_id: int
    sku_key: str
    name: str
    sell_price: str
    encrypted_cost: dict | None
    cost_multiplier: str
    ean: str | None
    vat_rate: str
    units_sold: int
    cogs_units: str  # units used for COGS calc (frontend); can be fractional, see neutral_refund_lines
    returns_units: int
    returns_pending_units: int
    returns_rejected_units: int
    revenue_gross: str
    revenue_net: str
    commission_cost: str
    featuring_commission_cost: str
    ads_cost: str
    ads_imported_cost: str
    ads_nsp_adjustment_cost: str
    smart_shipping_cost: str
    smart_forecast_cost: str
    shipping_passthrough_cost: str
    foreign_shipping_cost: str
    featuring_cost: str
    coins_cost: str
    campaign_commission_cost: str
    campaign_bonus: str
    price_adjust_cost: str
    protect_cost: str
    local_cost: str
    subscription_cost: str
    refund_commission: str
    commission_refunds_amount: str
    fulfillment: str
    total_allegro: str
    total_allegro_net: str
    cogs: str | None
    profit_net: str | None
    profit_per_unit: str | None
    margin_pct: str | None
    roi_pct: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProductDetail:
    """Full P&L breakdown for a single SKU in a given period."""
    sku_id: int
    sku_key: str
    name: str
    sell_price: str
    encrypted_cost: dict | None
    cost_multiplier: str
    ean: str | None
    vat_rate: str
    period_label: str
    date_from: str
    date_to: str

    # Revenue
    revenue_gross: str
    revenue_net: str
    sales_gross_value: str
    sales_net_value: str
    units_sold: int
    cogs_units: str  # units used for COGS calc (frontend); can be fractional, see neutral_refund_lines

    # Allegro costs (positive magnitudes)
    commission_cost: str           # SUC
    featuring_commission_cost: str # FSF
    ads_cost: str                  # NSP (account-level, allocated proportionally)
    ads_imported_cost: str
    ads_nsp_adjustment_cost: str
    smart_shipping_cost: str       # delivery codes with Allegro Smart flag (allocated)
    smart_forecast_cost: str       # synthetic SMART forecast included above (allocated)
    shipping_passthrough_cost: str # HB4/HLB/… with non-Smart flag — not in profit (allocated)
    foreign_shipping_cost: str     # HB1/HB8 — buyer passthrough, NOT in profit (allocated)
    featuring_cost: str            # FEA (allocated)
    coins_cost: str                # CPF/RCP — net of coin refunds
    campaign_commission_cost: str  # BRG
    campaign_bonus: str            # CB2 — positive
    price_adjust_cost: str         # PS1/PSA — positive rebate
    protect_cost: str              # INS
    local_cost: str                # ALC/ALS/ALK/ALI/ALL/ALP (allocated)
    subscription_cost: str         # SB*/SH*/ST*/ILF/ABO (allocated)
    refund_commission: str         # REF — positive
    fulfillment: str               # SHIPMENT_SURCHARGE
    total_allegro_net: str
    fulfillment_base_cost: str
    fulfillment_storage_cost: str
    fulfillment_returns_cost: str
    fulfillment_subscription_cost: str
    fulfillment_other_cost: str

    # Returns
    returns_revenue: str
    returns_revenue_net: str
    returns_goods_value: str
    returns_goods_value_net: str
    returns_count: int
    returns_units: int
    returns_refund_value: str
    returns_pending_count: int
    returns_pending_units: int
    returns_rejected_count: int
    returns_rejected_units: int
    commission_refunds_amount: str

    # Placeholder
    transaction_fee: str

    # COGS
    cogs: str | None

    # Results
    profit_net: str | None
    margin_pct: str | None
    roi_pct: str | None
    kp_ratio: str | None
    kcap_ratio: str | None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Engine ─────────────────────────────────────────────────────────────────────

class DashboardEngine:
    def __init__(self, scope: TenantScope):
        self.scope = scope
        self.db = scope.db
        self.tenant_id = scope.tenant_id
        # A summary/all or summary/daily request reuses one engine for many
        # periods. Resolve a human search term once, then let every aggregate
        # use a cheap SKU membership predicate instead of correlated ILIKE
        # subqueries over orders/offers.
        self._search_skus_cache: dict[tuple[str, int | None], tuple[str, ...]] = {}

    def _resolve_search_skus(self, search: str, account_id: int | None) -> tuple[str, ...]:
        normalized = search.strip()
        cache_key = (normalized, account_id)
        cached = self._search_skus_cache.get(cache_key)
        if cached is not None:
            return cached

        result = self._resolve_search_skus_from_catalog(normalized, account_id)
        if not result:
            result = self._resolve_search_skus_from_orders(normalized, account_id)
        self._search_skus_cache[cache_key] = result
        return result

    def _resolve_search_skus_from_catalog(self, search: str, account_id: int | None) -> tuple[str, ...]:
        """Resolve current product metadata before touching the much larger orders table."""
        offer_account_clause = "AND oc.account_id = :search_account_id" if account_id else ""
        rows = self.db.execute(text(f"""
            SELECT DISTINCT sku
            FROM (
                SELECT sm.sku_key AS sku
                FROM sku_masters sm
                WHERE sm.tenant_id = :tenant_id
                  AND (
                    COALESCE(sm.sku_key, '') ILIKE '%' || :search || '%'
                    OR COALESCE(sm.name, '') ILIKE '%' || :search || '%'
                  )

                UNION

                SELECT trim(oc.sku) AS sku
                FROM offers_cache oc
                WHERE oc.tenant_id = :tenant_id
                  {offer_account_clause}
                  AND oc.sku IS NOT NULL
                  AND trim(oc.sku) <> ''
                  AND (
                    COALESCE(oc.sku, '') ILIKE '%' || :search || '%'
                    OR COALESCE(oc.name, '') ILIKE '%' || :search || '%'
                    OR COALESCE(oc.ean, '') ILIKE '%' || :search || '%'
                    OR COALESCE(oc.offer_id, '') ILIKE '%' || :search || '%'
                  )
            ) matched
            WHERE sku IS NOT NULL AND sku <> ''
        """), {
            "tenant_id": self.tenant_id,
            "search": search,
            **({"search_account_id": account_id} if account_id else {}),
        }).scalars().all()
        return tuple(rows)

    def _resolve_search_skus_from_orders(self, search: str, account_id: int | None) -> tuple[str, ...]:
        """Fallback for ended offers no longer present in offers_cache."""
        order_account_clause = "AND o.account_id = :search_account_id" if account_id else ""
        rows = self.db.execute(text(f"""
            SELECT DISTINCT trim(o.sku) AS sku
            FROM orders_raw o
            LEFT JOIN offers_cache oc_order
              ON oc_order.tenant_id = o.tenant_id
             AND oc_order.offer_id = o.offer_id
             AND oc_order.account_id = o.account_id
            WHERE o.tenant_id = :tenant_id
              {order_account_clause}
              AND o.sku IS NOT NULL
              AND trim(o.sku) <> ''
              AND (
                COALESCE(trim(o.sku), '') ILIKE '%' || :search || '%'
                OR COALESCE(o.offer_id, '') ILIKE '%' || :search || '%'
                OR COALESCE(oc_order.sku, '') ILIKE '%' || :search || '%'
                OR COALESCE(oc_order.name, '') ILIKE '%' || :search || '%'
                OR COALESCE(oc_order.ean, '') ILIKE '%' || :search || '%'
                OR COALESCE(oc_order.offer_id, '') ILIKE '%' || :search || '%'
              )
        """), {
            "tenant_id": self.tenant_id,
            "search": search,
            **({"search_account_id": account_id} if account_id else {}),
        }).scalars().all()
        return tuple(rows)

    @staticmethod
    def _search_sku_filter(sku_expr: str, search_skus: tuple[str, ...]) -> str:
        # Do not pass an empty array: FALSE is clearer and avoids any
        # dialect-specific empty-array adaptation edge cases.
        return f"AND {sku_expr} = ANY(:search_skus)" if search_skus else "AND FALSE"

    def summary(
        self,
        period: Period,
        account_id: int | None = None,
        currency: str = "PLN",
        search: str | None = None,
    ) -> PnLSummary:
        refund_exclusion = ("TRUE" if search else _commission_refund_exclusion_sql("attributed_billing", account_id))
        acct_filter = f"AND o.account_id = {account_id}" if account_id else ""

        # When search is active, restrict to orders whose product identifiers match.
        # Account-level billing entries (NSP/FEA/subscription/…) are excluded
        # entirely because they are not attributable to individual products.
        search_skus = self._resolve_search_skus(search, account_id) if search else ()
        search_sku_filter = self._search_sku_filter("trim(o.sku)", search_skus) if search else ""

        # ── Orders (exclude CANCELLED and FILLED_IN — not real sales) ────────
        # Revenue follows order status. Later billing refunds/adjustments are
        # reported separately and must not remove READY_FOR_PROCESSING sales.
        orders_sql = text(f"""
            WITH sales_order_items AS (
                SELECT
                    o.order_id,
                    o.unit_price,
                    o.quantity,
                    COALESCE(o.delivery_amount, 0) AS delivery_amount,
                    COALESCE(sm.vat_rate, o.vat_rate, 23) AS vat_rate
                FROM orders_raw o
                LEFT JOIN sku_masters sm ON sm.sku_key = trim(o.sku) AND sm.tenant_id = :tenant_id
                WHERE o.bought_at BETWEEN :df AND :dt
                  AND o.tenant_id = :tenant_id
                  AND o.status = 'READY_FOR_PROCESSING'
                  AND (o.currency = :currency OR o.currency IS NULL)
                  {acct_filter}
                  {search_sku_filter}
            ),
            sales_orders AS (
                SELECT
                    order_id,
                    COALESCE(SUM(unit_price * quantity), 0) AS merchandise_revenue,
                    COALESCE(SUM((unit_price * quantity) / (1 + (vat_rate / 100.0))), 0) AS merchandise_revenue_net,
                    COALESCE(SUM(quantity), 0) AS units,
                    COALESCE(MAX(delivery_amount), 0) AS buyer_shipping_revenue,
                    COALESCE(MAX(delivery_amount) / 1.23, 0) AS buyer_shipping_revenue_net
                FROM sales_order_items
                GROUP BY order_id
            )
            SELECT
                COALESCE(SUM(merchandise_revenue), 0) AS revenue,
                COALESCE(SUM(merchandise_revenue_net), 0) AS revenue_net,
                COALESCE(SUM(units), 0) AS units,
                COUNT(*) AS orders_cnt,
                COALESCE(SUM(buyer_shipping_revenue), 0) AS buyer_shipping_revenue,
                COALESCE(SUM(buyer_shipping_revenue_net), 0) AS buyer_shipping_revenue_net
            FROM sales_orders
        """)
        orders_params: dict = {
            "df": period.date_from,
            "dt": period.date_to,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }
        if search and search_skus:
            orders_params["search_skus"] = list(search_skus)
        row = self.db.execute(orders_sql, orders_params).mappings().one()
        gross_sales_value = _d(row["revenue"])
        gross_sales_value_net = _d(row["revenue_net"])
        buyer_shipping_revenue = _d(row["buyer_shipping_revenue"])
        buyer_shipping_revenue_net = _d(row["buyer_shipping_revenue_net"])
        units = int(row["units"])
        orders_cnt = int(row["orders_cnt"])

        # ── Billing aggregates with order-date attribution ─────────────────────
        # attributed_billing CTE re-dates order-level costs to the order's purchase date.
        # Filtering is by effective_date (Warsaw local date) for attributed codes,
        # and by occurred_local for non-attributed codes.
        # Return-related Allegro refunds are computed separately using bought_at attribution.
        # order_dates only includes PLN orders — non-PLN order dates must not drive attribution.
        # attributed_billing drops billing entries linked to non-PLN orders; account-level entries
        # (b.order_id IS NULL) pass through unconditionally so NSP/FEA/subscriptions are unaffected —
        # UNLESS search is active, in which case account-level entries are excluded entirely
        # (they are not attributable to individual products).
        if search:
            # When filtering by product, only include billing entries that are tied
            # to orders containing matching SKUs. Account-level costs (NSP, FEA, subscription,
            # protect, local) are excluded — they cannot be attributed to a specific product.
            billing_search_filter = (
                "AND b.order_id IN ("
                "  SELECT DISTINCT o2.order_id FROM orders_raw o2"
                "  WHERE o2.tenant_id = :tenant_id"
                "  AND o2.order_id IS NOT NULL"
                f"  {self._search_sku_filter('trim(o2.sku)', search_skus)}"
                ")"
            )
        else:
            billing_search_filter = ""

        if account_id:
            billing_sql = text(f"""
                WITH order_dates AS (
                    SELECT order_id,
                           MIN(((bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date) AS order_date
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                      AND currency = :currency
                      AND status = 'READY_FOR_PROCESSING'
                    GROUP BY order_id
                ),
                order_delivery AS (
                    SELECT order_id, MAX(delivery_amount) AS max_delivery
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                    GROUP BY order_id
                ),
                order_currencies AS (
                    SELECT order_id, MAX(currency) AS currency
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                    GROUP BY order_id
                ),
                attributed_billing AS (
                    SELECT b.*,
                           ((b.occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date AS occurred_local,
                           CASE
                             WHEN b.type IN {_ATTRIBUTED_BY_ORDER_IN}
                               THEN COALESCE(od.order_date, {_ADS_OR_BILLING_DATE_SQL})
                             ELSE {_ADS_OR_BILLING_DATE_SQL}
                           END AS effective_date,
                           COALESCE(odel.max_delivery, 0) AS order_delivery_amount
                    FROM billing_raw b
                    LEFT JOIN order_dates od ON od.order_id = b.order_id
                    LEFT JOIN order_delivery odel ON odel.order_id = b.order_id
                    LEFT JOIN order_currencies o_cur ON o_cur.order_id = b.order_id
                    WHERE b.tenant_id = :tenant_id
                      AND b.account_id = {account_id}
                      AND b.type NOT IN {_EXCL_IN}
                      AND b.currency = :currency
                      AND (b.order_id IS NULL OR b.type NOT IN {_ATTRIBUTED_BY_ORDER_IN} OR od.order_id IS NOT NULL)
                      AND (b.order_id IS NULL OR o_cur.order_id IS NULL OR o_cur.currency = :currency)
                      {'AND b.order_id IS NOT NULL' if search else ''}
                      {billing_search_filter}
                )
                SELECT
                    COALESCE(LEAST(SUM(amount) FILTER (WHERE type IN {_SUC_IN} AND {refund_exclusion} AND effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS commission_cost,
                    COALESCE(LEAST(SUM(amount) FILTER (WHERE type IN {_FSF_IN} AND {refund_exclusion} AND effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS featuring_commission_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_ADS_IN}          AND effective_date BETWEEN :df_date AND :dt_date), 0) AS ads_cost,
                    COALESCE(SUM(amount) FILTER (WHERE {_SMART_SHIPPING_WHERE} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_shipping_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_SMART_FORECAST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_forecast_cost,
                    COALESCE(SUM(amount) FILTER (WHERE {_SHIPPING_PASSTHROUGH_WHERE} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS shipping_passthrough_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FOREIGN_IN}      AND effective_date BETWEEN :df_date AND :dt_date), 0) AS foreign_shipping_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FEATURING_IN}    AND effective_date BETWEEN :df_date AND :dt_date), 0) AS featuring_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_COINS_IN}        AND effective_date BETWEEN :df_date AND :dt_date), 0) AS coins_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_CAMPAIGN_COST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_commission_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_CAMPAIGN_BONUS_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_bonus,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_PRICE_ADJUST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS price_adjust_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_PROTECT_IN}      AND effective_date BETWEEN :df_date AND :dt_date), 0) AS protect_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_LOCAL_IN}        AND effective_date BETWEEN :df_date AND :dt_date), 0) AS local_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_SUBSCRIPTION_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS subscription_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_REFUND_IN}       AND effective_date BETWEEN :df_date AND :dt_date), 0) AS refund_commission,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_BASE_IN}  AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_base_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_STORAGE_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_storage_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_RETURNS_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_returns_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_SUBS_IN}  AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_subscription_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_OTHER_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_other_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_IN}       AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment
                FROM attributed_billing
            """)
        else:
            billing_sql = text(f"""
                WITH order_dates AS (
                    SELECT order_id,
                           MIN(((bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date) AS order_date
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                      AND currency = :currency
                      AND status = 'READY_FOR_PROCESSING'
                    GROUP BY order_id
                ),
                order_delivery AS (
                    SELECT order_id, MAX(delivery_amount) AS max_delivery
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                    GROUP BY order_id
                ),
                order_currencies AS (
                    SELECT order_id, MAX(currency) AS currency
                    FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
                    GROUP BY order_id
                ),
                attributed_billing AS (
                    SELECT b.*,
                           ((b.occurred_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date AS occurred_local,
                           CASE
                             WHEN b.type IN {_ATTRIBUTED_BY_ORDER_IN}
                               THEN COALESCE(od.order_date, {_ADS_OR_BILLING_DATE_SQL})
                             ELSE {_ADS_OR_BILLING_DATE_SQL}
                           END AS effective_date,
                           COALESCE(odel.max_delivery, 0) AS order_delivery_amount
                    FROM billing_raw b
                    LEFT JOIN order_dates od ON od.order_id = b.order_id
                    LEFT JOIN order_delivery odel ON odel.order_id = b.order_id
                    LEFT JOIN order_currencies o_cur ON o_cur.order_id = b.order_id
                    WHERE b.tenant_id = :tenant_id
                      AND b.type NOT IN {_EXCL_IN}
                      AND b.currency = :currency
                      AND (b.order_id IS NULL OR b.type NOT IN {_ATTRIBUTED_BY_ORDER_IN} OR od.order_id IS NOT NULL)
                      AND (b.order_id IS NULL OR o_cur.order_id IS NULL OR o_cur.currency = :currency)
                      {'AND b.order_id IS NOT NULL' if search else ''}
                      {billing_search_filter}
                )
                SELECT
                    COALESCE(LEAST(SUM(amount) FILTER (WHERE type IN {_SUC_IN} AND {refund_exclusion} AND effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS commission_cost,
                    COALESCE(LEAST(SUM(amount) FILTER (WHERE type IN {_FSF_IN} AND {refund_exclusion} AND effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS featuring_commission_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_ADS_IN}          AND effective_date BETWEEN :df_date AND :dt_date), 0) AS ads_cost,
                    COALESCE(SUM(amount) FILTER (WHERE {_SMART_SHIPPING_WHERE} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_shipping_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_SMART_FORECAST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_forecast_cost,
                    COALESCE(SUM(amount) FILTER (WHERE {_SHIPPING_PASSTHROUGH_WHERE} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS shipping_passthrough_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FOREIGN_IN}      AND effective_date BETWEEN :df_date AND :dt_date), 0) AS foreign_shipping_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FEATURING_IN}    AND effective_date BETWEEN :df_date AND :dt_date), 0) AS featuring_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_COINS_IN}        AND effective_date BETWEEN :df_date AND :dt_date), 0) AS coins_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_CAMPAIGN_COST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_commission_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_CAMPAIGN_BONUS_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_bonus,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_PRICE_ADJUST_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS price_adjust_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_PROTECT_IN}      AND effective_date BETWEEN :df_date AND :dt_date), 0) AS protect_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_LOCAL_IN}        AND effective_date BETWEEN :df_date AND :dt_date), 0) AS local_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_SUBSCRIPTION_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS subscription_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_REFUND_IN}       AND effective_date BETWEEN :df_date AND :dt_date), 0) AS refund_commission,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_BASE_IN}  AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_base_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_STORAGE_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_storage_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_RETURNS_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_returns_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_SUBS_IN}  AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_subscription_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_OTHER_IN} AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment_other_cost,
                    COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_IN}       AND effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment
                FROM attributed_billing
            """)

        # Convert UTC period boundaries to Warsaw local dates for the effective_date filter
        df_date, dt_date = _period_to_local_dates(period)

        billing_params: dict = {
            "df_date": df_date,
            "dt_date": dt_date,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }
        if search and search_skus:
            billing_params["search_skus"] = list(search_skus)
        br = self.db.execute(billing_sql, billing_params).mappings().one()

        if search:
            returns_row = {
                "returns_count": 0,
                "returns_units": 0,
                "returns_goods_value": 0,
                "returns_goods_value_net": 0,
                "returns_pending_count": 0,
                "returns_pending_units": 0,
                "returns_rejected_count": 0,
                "returns_rejected_units": 0,
            }
            returns_refund_row = {"returns_refund_value": 0}
            allegro_refunds_row = {"commission_refunds_amount": 0}
            neutral_payment_refund_row = {
                "neutral_refund_orders_count": 0,
                "neutral_refund_units": 0,
                "neutral_refund_value": 0,
                "neutral_refund_value_net": 0,
            }
            neutral_cancelled_row = {
                "neutral_cancelled_orders_count": 0,
                "neutral_cancelled_units": 0,
                "neutral_cancelled_value": 0,
            }
        else:
            returns_row = self.db.execute(
                _build_customer_returns_summary_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().one()
            returns_refund_row = self.db.execute(
                _build_payment_refunds_for_returns_summary_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().one()
            allegro_refunds_row = self.db.execute(
                _build_returns_allegro_refunds_summary_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().one()
            neutral_payment_refund_row = self.db.execute(
                _build_neutral_payment_refunds_summary_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().one()
            neutral_cancelled_row = self.db.execute(
                _build_neutral_cancelled_orders_summary_sql(account_id),
                {"df": period.date_from, "dt": period.date_to, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().one()

        commission_cost            = _d(br["commission_cost"])            # negative
        featuring_commission_cost  = _d(br["featuring_commission_cost"])  # negative
        ads_cost_nsp               = _d(br["ads_cost"])                   # negative (NSP billing)
        smart_shipping_cost        = _d(br["smart_shipping_cost"])        # negative (Smart flag; legacy fallback by delivery amount)
        smart_forecast_cost        = _d(br["smart_forecast_cost"])        # negative; subset of smart_shipping_cost
        shipping_passthrough_cost  = _d(br["shipping_passthrough_cost"])  # negative (non-Smart flag; not in profit)
        foreign_shipping_cost      = _d(br["foreign_shipping_cost"])      # negative (buyer passthrough)
        featuring_cost             = _d(br["featuring_cost"])             # negative
        coins_cost                 = _d(br["coins_cost"])                 # negative
        campaign_commission_cost   = _d(br["campaign_commission_cost"])   # negative
        campaign_bonus             = _d(br["campaign_bonus"])             # positive
        price_adjust_cost          = _d(br["price_adjust_cost"])          # positive (rebate from Allegro)
        protect_cost               = _d(br["protect_cost"])               # negative
        local_cost                 = _d(br["local_cost"])                 # negative
        subscription_cost          = _d(br["subscription_cost"])          # negative
        refund_commission          = _d(br["refund_commission"])          # positive
        fulfillment_base_cost      = _d(br["fulfillment_base_cost"])      # negative
        fulfillment_storage_cost   = _d(br["fulfillment_storage_cost"])   # negative
        fulfillment_returns_cost   = _d(br["fulfillment_returns_cost"])   # negative
        fulfillment_subscription_cost = _d(br["fulfillment_subscription_cost"])  # negative
        fulfillment_other_cost     = _d(br["fulfillment_other_cost"])     # negative
        fulfillment                = _d(br["fulfillment"])                # negative
        commission_refunds_amount  = _d(allegro_refunds_row["commission_refunds_amount"])  # positive, informational
        returns_count              = int(returns_row["returns_count"] or 0)
        returns_units              = int(returns_row["returns_units"] or 0)
        returns_goods_value        = _d(returns_row["returns_goods_value"])
        returns_goods_value_net    = _d(returns_row["returns_goods_value_net"])
        returns_refund_value       = _d(returns_refund_row["returns_refund_value"])
        neutral_refund_orders_count = int(neutral_payment_refund_row["neutral_refund_orders_count"] or 0)
        neutral_refund_units       = int(neutral_payment_refund_row["neutral_refund_units"] or 0)
        neutral_refund_value       = _d(neutral_payment_refund_row["neutral_refund_value"])
        neutral_refund_value_net   = _d(neutral_payment_refund_row["neutral_refund_value_net"])
        returns_pending_count      = int(returns_row["returns_pending_count"] or 0)
        returns_pending_units      = int(returns_row["returns_pending_units"] or 0)
        returns_rejected_count     = int(returns_row["returns_rejected_count"] or 0)
        returns_rejected_units     = int(returns_row["returns_rejected_units"] or 0)
        neutral_cancelled_orders_count = (
            int(neutral_cancelled_row["neutral_cancelled_orders_count"] or 0)
            + neutral_refund_orders_count
        )
        neutral_cancelled_units    = int(neutral_cancelled_row["neutral_cancelled_units"] or 0) + neutral_refund_units
        neutral_cancelled_value    = _d(neutral_cancelled_row["neutral_cancelled_value"]) + neutral_refund_value
        revenue = gross_sales_value - returns_goods_value - neutral_refund_value
        revenue_net = gross_sales_value_net - returns_goods_value_net - neutral_refund_value_net
        net_units = max(units - returns_units - neutral_refund_units, 0)
        net_orders_count = max(orders_cnt - neutral_refund_orders_count, 0)

        # ── Ads cost: imported offer Ads + NSP reconciliation ────────────────
        # Imported offer stats are shown separately. NSP billing is the source
        # of truth once available, so the NSP line becomes the signed difference
        # needed to reconcile imported Ads to the billing total.
        # When search is active, ads_cost is already 0 from billing (account-level excluded above)
        # and imported ads are account-level too — skip the lookup and keep 0.
        if search:
            ads_cost = Decimal("0")
            ads_imported_cost = Decimal("0")
            ads_nsp_adjustment = Decimal("0")
            ads_cost_source = "billing"
        else:
            imported_ads_sql_params: dict = {
                "aid": account_id,
                "df": df_date,
                "dt": dt_date,
                "tenant_id": self.tenant_id,
            }
            if account_id:
                imported_ads_sql = text("""
                    SELECT COALESCE(SUM(cost), 0) AS imported_cost
                    FROM allegro_ads_imports
                    WHERE tenant_id = :tenant_id
                      AND account_id = :aid
                      AND ad_date BETWEEN :df AND :dt
                """)
            else:
                imported_ads_sql = text("""
                    SELECT COALESCE(SUM(cost), 0) AS imported_cost
                    FROM allegro_ads_imports
                    WHERE tenant_id = :tenant_id
                      AND ad_date BETWEEN :df AND :dt
                """)
                imported_ads_sql_params = {"df": df_date, "dt": dt_date, "tenant_id": self.tenant_id}
            imported_ads_row = self.db.execute(imported_ads_sql, imported_ads_sql_params).mappings().one()
            imported_ads_cost = _d(imported_ads_row["imported_cost"])  # positive magnitude
            billing_ads_cost = abs(ads_cost_nsp)
            ads_imported_cost = imported_ads_cost

            if imported_ads_cost > 0 and billing_ads_cost > 0:
                ads_nsp_adjustment = billing_ads_cost - imported_ads_cost
                ads_cost = -billing_ads_cost
                ads_cost_source = "mixed"
            elif imported_ads_cost > 0:
                ads_nsp_adjustment = Decimal("0")
                ads_cost = -imported_ads_cost
                ads_cost_source = "imported"
            else:
                ads_nsp_adjustment = billing_ads_cost
                ads_cost = ads_cost_nsp  # already negative from billing_raw
                ads_cost_source = "billing"

        # The zero-knowledge vault keeps purchase costs on the client side.
        # Backend still returns revenue and Allegro cost components, while COGS
        # and profit metrics are computed in the browser after vault unlock.
        total_allegro_signed = (
            commission_cost + featuring_commission_cost + ads_cost
            + smart_shipping_cost + featuring_cost + coins_cost + campaign_commission_cost
            + protect_cost + local_cost + subscription_cost
            + fulfillment
        )  # all negative; shipping_passthrough_cost excluded (buyer-paid passthrough)
        total_allegro = abs(total_allegro_signed)
        total_allegro_net = _gross_to_net_23(total_allegro)

        return PnLSummary(
            period_label=period.label,
            date_from=period.date_from_str,
            date_to=period.date_to_str,
            revenue_gross=_s(revenue),
            revenue_net=_s(revenue_net),
            sales_gross_value=_s(gross_sales_value),
            sales_net_value=_s(gross_sales_value_net),
            buyer_shipping_revenue=_s(buyer_shipping_revenue),
            buyer_shipping_revenue_net=_s(buyer_shipping_revenue_net),
            units_sold=net_units,
            orders_count=net_orders_count,
            commission_cost=_s(abs(commission_cost)),
            featuring_commission_cost=_s(abs(featuring_commission_cost)),
            ads_cost=_s(abs(ads_cost)),
            ads_imported_cost=_s(ads_imported_cost),
            ads_nsp_adjustment_cost=_s(ads_nsp_adjustment),
            smart_shipping_cost=_s(abs(smart_shipping_cost)),
            smart_forecast_cost=_s(abs(smart_forecast_cost)),
            shipping_passthrough_cost=_s(abs(shipping_passthrough_cost)),
            foreign_shipping_cost=_s(abs(foreign_shipping_cost)),
            featuring_cost=_s(abs(featuring_cost)),
            coins_cost=_s(abs(coins_cost)),
            campaign_commission_cost=_s(abs(campaign_commission_cost)),
            campaign_bonus=_s(campaign_bonus),
            price_adjust_cost=_s(price_adjust_cost),        # positive magnitude (rebate)
            protect_cost=_s(abs(protect_cost)),
            local_cost=_s(abs(local_cost)),
            subscription_cost=_s(abs(subscription_cost)),
            refund_commission=_s(refund_commission),         # positive magnitude
            fulfillment_base_cost=_s(abs(fulfillment_base_cost)),
            fulfillment_storage_cost=_s(abs(fulfillment_storage_cost)),
            fulfillment_returns_cost=_s(abs(fulfillment_returns_cost)),
            fulfillment_subscription_cost=_s(abs(fulfillment_subscription_cost)),
            fulfillment_other_cost=_s(abs(fulfillment_other_cost)),
            fulfillment=_s(abs(fulfillment)),
            total_allegro=_s(total_allegro),
            total_allegro_net=_s(total_allegro_net),
            ads_cost_source=ads_cost_source,
            returns_revenue=_s(returns_goods_value),
            returns_revenue_net=_s(returns_goods_value_net),
            returns_count=returns_count,
            returns_units=returns_units,
            returns_goods_value=_s(returns_goods_value),
            returns_goods_value_net=_s(returns_goods_value_net),
            returns_refund_value=_s(returns_refund_value),
            returns_pending_count=returns_pending_count,
            returns_pending_units=returns_pending_units,
            returns_rejected_count=returns_rejected_count,
            returns_rejected_units=returns_rejected_units,
            neutral_cancelled_orders_count=neutral_cancelled_orders_count,
            neutral_cancelled_units=neutral_cancelled_units,
            neutral_cancelled_value=_s(neutral_cancelled_value),
            commission_refunds_amount=_s(commission_refunds_amount),
            cogs=None,
            profit_net=None,
            margin_pct=None,
            roi_pct=None,
            kp_ratio=None,
            kcap_ratio=None,
        )

    def products(
        self,
        period: Period,
        account_id: int | None = None,
        search: str | None = None,
        currency: str = "PLN",
    ) -> list[ProductSummaryRow]:
        acct_filter = f"AND o.account_id = {account_id}" if account_id else ""
        search_skus = self._resolve_search_skus(search, account_id) if search else ()
        search_sku_filter = self._search_sku_filter("trim(o.sku)", search_skus) if search else ""

        # Compute Warsaw-local date bounds for effective_date filtering
        df_date, dt_date = _period_to_local_dates(period)

        # ── Total gross period revenue for proportional account-level allocation ──
        total_rev_sql = text(f"""
            SELECT COALESCE(SUM(o.unit_price * o.quantity), 0) AS total
            FROM orders_raw o
            WHERE o.bought_at BETWEEN :df AND :dt
              AND o.tenant_id = :tenant_id
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
              {acct_filter}
        """)
        total_rev = _d(self.db.execute(total_rev_sql, {
            "df": period.date_from,
            "dt": period.date_to,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).scalar())
        neutral_payment_refund_total = self.db.execute(
            _build_neutral_payment_refunds_summary_sql(account_id),
            {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
        ).mappings().one()
        total_rev = max(total_rev - _d(neutral_payment_refund_total["neutral_refund_value"]), Decimal("0"))

        # ── Total account-level (no offer_id) billing for allocation ────────
        # Includes smart_shipping, foreign_shipping, featuring, ads, protect, local, subscription, fulfillment
        # These use effective_date after attribution.
        _ACCT_LEVEL_IN = _sql_in(
            _ADS + _PROTECT + _LOCAL + _SUBSCRIPTION + _FULFILLMENT
        )
        acct_bill_sql = _build_attributed_acct_billing_sql(account_id, _ACCT_LEVEL_IN)
        acct_totals = self.db.execute(acct_bill_sql, {
            "df_date": df_date,
            "dt_date": dt_date,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().one()
        total_acct = _d(acct_totals["total"])  # for proportional allocation

        # ── Per-offer imported ads costs ────────────────────────────────────
        # Fetch SUM(cost) per offer_id from allegro_ads_imports for the period.
        # Used in per-product loop: if imported cost exists for an offer, use it; else proportional NSP.
        _ads_import_acct = f"AND account_id = {account_id}" if account_id else ""
        ads_import_sql = text(f"""
            SELECT offer_id, SUM(cost) AS imported_cost
            FROM allegro_ads_imports
            WHERE ad_date BETWEEN :df_date AND :dt_date
              AND tenant_id = :tenant_id
              {_ads_import_acct}
            GROUP BY offer_id
        """)
        ads_import_rows = self.db.execute(ads_import_sql, {
            "df_date": df_date,
            "dt_date": dt_date,
            "tenant_id": self.tenant_id,
        }).mappings().all()
        # offer_id → positive Decimal cost
        offer_imported_ads: dict[str, Decimal] = {r["offer_id"]: _d(r["imported_cost"]) for r in ads_import_rows}

        # Total imported ads cost (account-level) — used to decide COALESCE strategy
        total_imported_ads = sum(offer_imported_ads.values(), Decimal("0"))
        total_billing_ads = abs(_d(acct_totals["ads_cost"]))
        if total_imported_ads > 0 and total_billing_ads > 0:
            total_ads_nsp_adjustment = total_billing_ads - total_imported_ads
        elif total_imported_ads > 0:
            total_ads_nsp_adjustment = Decimal("0")
        else:
            total_ads_nsp_adjustment = total_billing_ads

        # Fetch sku → list of offer_ids mapping. Ended offers can disappear from
        # offers_cache, so fall back to the SKU most often seen in historical
        # orders for that offer.
        _oc_acct = f"AND account_id = {account_id}" if account_id else ""
        _orders_acct = f"AND o.account_id = {account_id}" if account_id else ""
        _hist_oc_acct = f"AND oc.account_id = {account_id}" if account_id else ""
        sku_offer_sql = text(f"""
            WITH historical_offer_skus AS (
                SELECT offer_id, sku
                FROM (
                    SELECT
                        o.offer_id,
                        trim(o.sku) AS sku,
                        row_number() OVER (
                            PARTITION BY o.offer_id
                            ORDER BY COUNT(*) DESC, MAX(o.bought_at) DESC
                        ) AS rn
                    FROM orders_raw o
                    WHERE o.tenant_id = :tenant_id
                      AND o.offer_id IS NOT NULL
                      AND o.sku IS NOT NULL
                      AND trim(o.sku) <> ''
                      {_orders_acct}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM offers_cache oc
                          WHERE oc.tenant_id = o.tenant_id
                            AND oc.offer_id = o.offer_id
                            {_hist_oc_acct}
                      )
                    GROUP BY o.offer_id, trim(o.sku)
                ) ranked
                WHERE rn = 1
            )
            SELECT sku, offer_id
            FROM offers_cache
            WHERE tenant_id = :tenant_id
              AND sku IS NOT NULL
              {_oc_acct}
            UNION ALL
            SELECT sku, offer_id
            FROM historical_offer_skus
        """)
        sku_offer_rows = self.db.execute(sku_offer_sql, {"tenant_id": self.tenant_id}).mappings().all()
        sku_to_offers: dict[str, list[str]] = {}
        for r in sku_offer_rows:
            sku_to_offers.setdefault(r["sku"], []).append(r["offer_id"])

        # ── Per-SKU aggregation ─────────────────────────────────────────────
        # Per-offer billing codes (SUC, FSF, COINS, PRICE_ADJUST, REFUND, FULFILLMENT)
        # are attributed to order dates via the CTE.
        sku_bill_sql = _build_attributed_sku_billing_sql(account_id)
        sku_bill_rows = self.db.execute(sku_bill_sql, {
            "df_date": df_date,
            "dt_date": dt_date,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().all()
        # Index by sku
        sku_billing: dict[str, dict] = {}
        for r in sku_bill_rows:
            sku_billing[r["sku"]] = dict(r)

        returns_per_sku_rows = self.db.execute(
            _build_customer_returns_per_sku_sql(account_id),
            {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
        ).mappings().all()
        returns_per_sku: dict[str, dict] = {r["sku"]: dict(r) for r in returns_per_sku_rows}
        neutral_cancelled_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_neutral_payment_refunds_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        allegro_refunds_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_returns_allegro_refunds_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        # ── Gross orders per SKU ─────────────────────────────────────────────
        alias_offer_account_clause = f"AND oc.account_id = {account_id}" if account_id else ""
        sku_orders_sql = text(f"""
            WITH orders_agg AS (
                SELECT
                    trim(o.sku) AS sku,
                    SUM(o.unit_price * o.quantity)  AS revenue,
                    SUM(o.quantity)                  AS units,
                    COUNT(DISTINCT o.order_id)       AS orders_cnt,
                    MAX(COALESCE(o.vat_rate, 23))    AS order_vat_rate,
                    (ARRAY_AGG(o.unit_price ORDER BY o.bought_at DESC NULLS LAST, o.id DESC))[1] AS last_sell_price
                FROM orders_raw o
                WHERE o.bought_at BETWEEN :df AND :dt
                  AND o.tenant_id = :tenant_id
                  AND o.status = 'READY_FOR_PROCESSING'
                  AND o.sku IS NOT NULL
                  AND trim(o.sku) <> ''
                  AND (o.currency = :currency OR o.currency IS NULL)
                  {acct_filter}
                  {search_sku_filter}
                GROUP BY trim(o.sku)
            )
            SELECT
                COALESCE(sm.id, 0) AS sku_id,
                oa.sku AS sku_key,
                COALESCE(sm.name, oa.sku) AS name,
                COALESCE(sm.vat_rate, oa.order_vat_rate, 23) AS vat_rate,
                COALESCE(esc.ciphertext, alias_cost.ciphertext, base_esc.ciphertext) AS cost_ciphertext,
                COALESCE(esc.nonce, alias_cost.nonce, base_esc.nonce) AS cost_nonce,
                COALESCE(esc.key_version, alias_cost.key_version, base_esc.key_version) AS cost_key_version,
                COALESCE(esc.aad_context, alias_cost.aad_context, base_esc.aad_context) AS cost_aad_context,
                CASE
                  WHEN esc.ciphertext IS NULL
                   AND alias_cost.ciphertext IS NOT NULL
                    THEN alias_cost.multiplier::text
                  WHEN esc.ciphertext IS NULL
                   AND alias_cost.ciphertext IS NULL
                   AND base_esc.ciphertext IS NOT NULL
                   AND oa.sku ~* '^\\s*[0-9]+\\s*x\\s+'
                    THEN substring(oa.sku from '^\\s*([0-9]+)\\s*x\\s+')
                  ELSE '1'
                END AS cost_multiplier,
                COALESCE(oa.last_sell_price, (SELECT MAX(price) FROM offers_cache WHERE tenant_id = :tenant_id AND sku = oa.sku), 0) AS sell_price,
                COALESCE((SELECT MAX(ean)   FROM offers_cache WHERE tenant_id = :tenant_id AND sku = oa.sku AND ean IS NOT NULL), NULL) AS ean,
                COALESCE(oa.revenue,       0) AS revenue,
                COALESCE(oa.units,         0) AS units
            FROM orders_agg oa
            LEFT JOIN sku_masters sm ON sm.sku_key = oa.sku AND sm.tenant_id = :tenant_id
            LEFT JOIN encrypted_sku_costs esc ON esc.sku_master_id = sm.id AND esc.tenant_id = :tenant_id
            LEFT JOIN LATERAL (
                SELECT
                    alias_esc.ciphertext,
                    alias_esc.nonce,
                    alias_esc.key_version,
                    alias_esc.aad_context,
                    sa.multiplier
                FROM offers_cache oc
                JOIN sku_aliases sa
                  ON sa.tenant_id = :tenant_id
                 AND sa.account_id = oc.account_id
                 AND sa.raw_name = oc.name
                JOIN encrypted_sku_costs alias_esc
                  ON alias_esc.tenant_id = :tenant_id
                 AND alias_esc.sku_master_id = sa.sku_master_id
                WHERE oc.tenant_id = :tenant_id
                  AND oc.sku = oa.sku
                  AND oc.name IS NOT NULL
                  {alias_offer_account_clause}
                ORDER BY sa.id
                LIMIT 1
            ) alias_cost ON TRUE
            LEFT JOIN sku_masters base_sm
              ON base_sm.tenant_id = :tenant_id
             AND oa.sku ~* '^\\s*[0-9]+\\s*x\\s+'
             AND base_sm.sku_key = regexp_replace(oa.sku, '^\\s*[0-9]+\\s*x\\s+', '', 'i')
            LEFT JOIN encrypted_sku_costs base_esc ON base_esc.sku_master_id = base_sm.id AND base_esc.tenant_id = :tenant_id
            WHERE (COALESCE(oa.revenue, 0) > 0 OR COALESCE(oa.units, 0) > 0)
            ORDER BY COALESCE(oa.revenue, 0) DESC
        """)
        sql_params: dict = {
            "df": period.date_from,
            "dt": period.date_to,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }
        if search and search_skus:
            sql_params["search_skus"] = list(search_skus)
        order_rows = list(self.db.execute(sku_orders_sql, sql_params).mappings().all())
        order_row_skus = {r["sku_key"] for r in order_rows}
        billing_only_skus = [
            sku for sku, values in sku_billing.items()
            if sku not in order_row_skus
            and any(_d(values.get(key, 0)) != 0 for key in (
                "commission_cost",
                "featuring_commission_cost",
                "smart_shipping_cost",
                "smart_forecast_cost",
                "shipping_passthrough_cost",
                "foreign_shipping_cost",
                "featuring_cost",
                "coins_cost",
                "campaign_commission_cost",
                "campaign_bonus",
                "price_adjust_cost",
                "refund_commission",
                "fulfillment",
            ))
        ]
        for sku, values in allegro_refunds_per_sku.items():
            if sku not in order_row_skus and _d(values.get("commission_refunds_amount", 0)) != 0:
                billing_only_skus.append(sku)
        billing_only_skus = sorted(set(billing_only_skus))
        if billing_only_skus:
            billing_only_name_filter = self._search_sku_filter("sm.sku_key", search_skus) if search else ""
            alias_billing_account_clause = f"AND oc.account_id = {account_id}" if account_id else ""
            billing_only_sql = text(f"""
                SELECT
                    sm.id AS sku_id,
                    sm.sku_key,
                    sm.name,
                    COALESCE(sm.vat_rate, 23) AS vat_rate,
                    COALESCE(esc.ciphertext, alias_cost.ciphertext, base_esc.ciphertext) AS cost_ciphertext,
                    COALESCE(esc.nonce, alias_cost.nonce, base_esc.nonce) AS cost_nonce,
                    COALESCE(esc.key_version, alias_cost.key_version, base_esc.key_version) AS cost_key_version,
                    COALESCE(esc.aad_context, alias_cost.aad_context, base_esc.aad_context) AS cost_aad_context,
                    CASE
                      WHEN esc.ciphertext IS NULL
                       AND alias_cost.ciphertext IS NOT NULL
                        THEN alias_cost.multiplier::text
                      WHEN esc.ciphertext IS NULL
                       AND alias_cost.ciphertext IS NULL
                       AND base_esc.ciphertext IS NOT NULL
                       AND sm.sku_key ~* '^\\s*[0-9]+\\s*x\\s+'
                        THEN substring(sm.sku_key from '^\\s*([0-9]+)\\s*x\\s+')
                      ELSE '1'
                    END AS cost_multiplier,
                    COALESCE(
                        (
                            SELECT o.unit_price
                            FROM orders_raw o
                            WHERE o.tenant_id = :tenant_id
                              AND o.status = 'READY_FOR_PROCESSING'
                              AND o.sku IS NOT NULL
                              AND trim(o.sku) = sm.sku_key
                              AND (o.currency = :currency OR o.currency IS NULL)
                              {acct_filter}
                            ORDER BY o.bought_at DESC NULLS LAST, o.id DESC
                            LIMIT 1
                        ),
                        (SELECT MAX(price) FROM offers_cache WHERE tenant_id = :tenant_id AND sku = sm.sku_key),
                        0
                    ) AS sell_price,
                    COALESCE((SELECT MAX(ean)   FROM offers_cache WHERE tenant_id = :tenant_id AND sku = sm.sku_key AND ean IS NOT NULL), NULL) AS ean,
                    0 AS revenue,
                    0 AS units
                FROM sku_masters sm
                LEFT JOIN encrypted_sku_costs esc ON esc.sku_master_id = sm.id AND esc.tenant_id = :tenant_id
                LEFT JOIN LATERAL (
                    SELECT
                        alias_esc.ciphertext,
                        alias_esc.nonce,
                        alias_esc.key_version,
                        alias_esc.aad_context,
                        sa.multiplier
                    FROM offers_cache oc
                    JOIN sku_aliases sa
                      ON sa.tenant_id = :tenant_id
                     AND sa.account_id = oc.account_id
                     AND sa.raw_name = oc.name
                    JOIN encrypted_sku_costs alias_esc
                      ON alias_esc.tenant_id = :tenant_id
                     AND alias_esc.sku_master_id = sa.sku_master_id
                    WHERE oc.tenant_id = :tenant_id
                      AND oc.sku = sm.sku_key
                      AND oc.name IS NOT NULL
                      {alias_billing_account_clause}
                    ORDER BY sa.id
                    LIMIT 1
                ) alias_cost ON TRUE
                LEFT JOIN sku_masters base_sm
                  ON base_sm.tenant_id = :tenant_id
                 AND sm.sku_key ~* '^\\s*[0-9]+\\s*x\\s+'
                 AND base_sm.sku_key = regexp_replace(sm.sku_key, '^\\s*[0-9]+\\s*x\\s+', '', 'i')
                LEFT JOIN encrypted_sku_costs base_esc ON base_esc.sku_master_id = base_sm.id AND base_esc.tenant_id = :tenant_id
                WHERE sm.tenant_id = :tenant_id
                  AND sm.sku_key = ANY(:billing_only_skus)
                  {billing_only_name_filter}
                ORDER BY sm.sku_key
            """)
            billing_only_params: dict = {
                "tenant_id": self.tenant_id,
                "billing_only_skus": billing_only_skus,
                "currency": currency,
            }
            if search and search_skus:
                billing_only_params["search_skus"] = list(search_skus)
            order_rows.extend(self.db.execute(billing_only_sql, billing_only_params).mappings().all())

        results: list[ProductSummaryRow] = []
        for r in order_rows:
            sku_key                  = r["sku_key"]
            neutral_cancelled_data   = neutral_cancelled_per_sku.get(sku_key, {})
            neutral_cancelled_units  = int(neutral_cancelled_data.get("neutral_cancelled_units", 0) or 0)
            neutral_cancelled_value  = _d(neutral_cancelled_data.get("neutral_cancelled_value", 0))
            neutral_cancelled_cost_discount = _d(neutral_cancelled_data.get("neutral_cancelled_cost_discount", 0))
            gross_revenue            = max(_d(r["revenue"]) - neutral_cancelled_value, Decimal("0"))
            gross_units              = max(int(r["units"]) - neutral_cancelled_units, 0)
            vat_rate                 = _d(r["vat_rate"])
            b                        = sku_billing.get(sku_key, {})
            returns_data             = returns_per_sku.get(sku_key, {})
            approved_returns_units   = int(returns_data.get("returns_units", 0) or 0)
            approved_returns_value   = _d(returns_data.get("returns_goods_value", 0))
            approved_returns_value_net = _d(returns_data.get("returns_goods_value_net", 0))
            commission_cost           = _d(b.get("commission_cost", 0))
            featuring_commission_cost = _d(b.get("featuring_commission_cost", 0))
            coins_cost                = _d(b.get("coins_cost", 0))
            campaign_commission_cost  = _d(b.get("campaign_commission_cost", 0))
            campaign_bonus            = _d(b.get("campaign_bonus", 0))
            price_adjust_cost         = _d(b.get("price_adjust_cost", 0))
            refund_commission         = _d(b.get("refund_commission", 0))
            sku_allegro_refunds       = _d(allegro_refunds_per_sku.get(sku_key, {}).get("commission_refunds_amount", 0))
            fulfillment_val           = _d(b.get("fulfillment", 0))
            smart_shipping_cost        = _d(b.get("smart_shipping_cost", 0))
            smart_forecast_cost        = _d(b.get("smart_forecast_cost", 0))
            shipping_passthrough_cost  = _d(b.get("shipping_passthrough_cost", 0))
            foreign_shipping_cost      = _d(b.get("foreign_shipping_cost", 0))
            featuring_cost             = _d(b.get("featuring_cost", 0))
            net_revenue              = gross_revenue - approved_returns_value
            net_revenue_value        = _gross_to_net_by_rate(gross_revenue, vat_rate) - approved_returns_value_net
            net_units                = max(gross_units - approved_returns_units, 0)
            cogs_units               = max(_d(net_units) - neutral_cancelled_cost_discount, Decimal("0"))
            if net_units == 0 and net_revenue == 0 and neutral_cancelled_units > 0:
                continue

            # Proportional allocation of account-level costs uses gross sales share.
            share = (gross_revenue / total_rev) if total_rev > 0 and gross_revenue > 0 else Decimal("0")

            # Per-offer imported Ads plus signed NSP reconciliation.
            sku_offer_ids = sku_to_offers.get(sku_key, [])
            sku_imported_ads = sum(
                (offer_imported_ads.get(oid, Decimal("0")) for oid in sku_offer_ids),
                Decimal("0"),
            )
            sku_ads_nsp_adjustment = total_ads_nsp_adjustment * share
            ads_alloc = -(sku_imported_ads + sku_ads_nsp_adjustment)

            protect_alloc               = _d(acct_totals["protect_cost"])               * share
            local_alloc                 = _d(acct_totals["local_cost"])                 * share
            subscription_alloc          = _d(acct_totals["subscription_cost"])          * share
            fulfillment_alloc           = _d(acct_totals["fulfillment"])                * share

            # total_allegro excludes foreign_shipping and shipping_passthrough (buyer passthroughs)
            total_allegro_signed = (
                commission_cost + featuring_commission_cost + coins_cost
                + campaign_commission_cost
                + ads_alloc + smart_shipping_cost + featuring_cost
                + protect_alloc + local_alloc + subscription_alloc
                + fulfillment_val + fulfillment_alloc
            )
            total_allegro = abs(total_allegro_signed)
            total_allegro_net = _gross_to_net_23(total_allegro)
            encrypted_cost = None
            if r["cost_ciphertext"] and r["cost_nonce"]:
                encrypted_cost = {
                    "ciphertext": r["cost_ciphertext"],
                    "nonce": r["cost_nonce"],
                    "key_version": r["cost_key_version"],
                    "aad_context": r["cost_aad_context"],
                }

            results.append(ProductSummaryRow(
                sku_id=int(r["sku_id"]),
                sku_key=sku_key,
                name=r["name"],
                sell_price=_s(_d(r["sell_price"])),
                encrypted_cost=encrypted_cost,
                cost_multiplier=str(_d(r["cost_multiplier"]).quantize(Decimal("0.0001"))),
                ean=r["ean"],
                vat_rate=_s(vat_rate),
                units_sold=net_units,
                cogs_units=_s(cogs_units),
                returns_units=approved_returns_units,
                returns_pending_units=int(returns_data.get("returns_pending_units", 0) or 0),
                returns_rejected_units=int(returns_data.get("returns_rejected_units", 0) or 0),
                revenue_gross=_s(net_revenue),
                revenue_net=_s(net_revenue_value),
                commission_cost=_s(abs(commission_cost)),
                featuring_commission_cost=_s(abs(featuring_commission_cost)),
                ads_cost=_s(abs(ads_alloc)),
                ads_imported_cost=_s(sku_imported_ads),
                ads_nsp_adjustment_cost=_s(sku_ads_nsp_adjustment),
                smart_shipping_cost=_s(abs(smart_shipping_cost)),
                smart_forecast_cost=_s(abs(smart_forecast_cost)),
                shipping_passthrough_cost=_s(abs(shipping_passthrough_cost)),
                foreign_shipping_cost=_s(abs(foreign_shipping_cost)),
                featuring_cost=_s(abs(featuring_cost)),
                coins_cost=_s(abs(coins_cost)),
                campaign_commission_cost=_s(abs(campaign_commission_cost)),
                campaign_bonus=_s(campaign_bonus),
                price_adjust_cost=_s(price_adjust_cost),
                protect_cost=_s(abs(protect_alloc)),
                local_cost=_s(abs(local_alloc)),
                subscription_cost=_s(abs(subscription_alloc)),
                refund_commission=_s(refund_commission),
                commission_refunds_amount=_s(sku_allegro_refunds),
                fulfillment=_s(abs(fulfillment_val + fulfillment_alloc)),
                total_allegro=_s(total_allegro),
                total_allegro_net=_s(total_allegro_net),
                cogs=None,
                profit_net=None,
                profit_per_unit=None,
                margin_pct=None,
                roi_pct=None,
            ))

        return results

    def product_detail(
        self,
        sku_key: str,
        period: Period,
        account_id: int | None = None,
        currency: str = "PLN",
    ) -> ProductDetail | None:
        acct_filter = f"AND o.account_id = {account_id}" if account_id else ""
        alias_offer_account_clause = f"AND oc.account_id = {account_id}" if account_id else ""

        df_date, dt_date = _period_to_local_dates(period)

        # ── SKU master info ──────────────────────────────────────────────────
        meta_sql = text(f"""
            SELECT sm.name,
                   sm.id AS sku_id,
                   COALESCE(sm.vat_rate, 23) AS vat_rate,
                   COALESCE(esc.ciphertext, alias_cost.ciphertext, base_esc.ciphertext) AS cost_ciphertext,
                   COALESCE(esc.nonce, alias_cost.nonce, base_esc.nonce) AS cost_nonce,
                   COALESCE(esc.key_version, alias_cost.key_version, base_esc.key_version) AS cost_key_version,
                   COALESCE(esc.aad_context, alias_cost.aad_context, base_esc.aad_context) AS cost_aad_context,
                   CASE
                     WHEN esc.ciphertext IS NULL
                      AND alias_cost.ciphertext IS NOT NULL
                       THEN alias_cost.multiplier::text
                     WHEN esc.ciphertext IS NULL
                      AND alias_cost.ciphertext IS NULL
                      AND base_esc.ciphertext IS NOT NULL
                      AND sm.sku_key ~* '^\\s*[0-9]+\\s*x\\s+'
                       THEN substring(sm.sku_key from '^\\s*([0-9]+)\\s*x\\s+')
                     ELSE '1'
                   END AS cost_multiplier,
                   COALESCE(
                       (
                           SELECT o.unit_price
                           FROM orders_raw o
                           WHERE o.tenant_id = :tenant_id
                             AND o.status = 'READY_FOR_PROCESSING'
                             AND o.sku IS NOT NULL
                             AND trim(o.sku) = sm.sku_key
                             AND o.bought_at BETWEEN :df AND :dt
                             AND (o.currency = :currency OR o.currency IS NULL)
                             {acct_filter}
                           ORDER BY o.bought_at DESC NULLS LAST, o.id DESC
                           LIMIT 1
                       ),
                       (SELECT MAX(price) FROM offers_cache WHERE tenant_id = :tenant_id AND sku = sm.sku_key),
                       0
                   ) AS sell_price,
                   COALESCE((SELECT MAX(ean)   FROM offers_cache WHERE tenant_id = :tenant_id AND sku = sm.sku_key AND ean IS NOT NULL), NULL) AS ean
            FROM sku_masters sm
            LEFT JOIN encrypted_sku_costs esc ON esc.sku_master_id = sm.id AND esc.tenant_id = :tenant_id
            LEFT JOIN LATERAL (
                SELECT
                    alias_esc.ciphertext,
                    alias_esc.nonce,
                    alias_esc.key_version,
                    alias_esc.aad_context,
                    sa.multiplier
                FROM offers_cache oc
                JOIN sku_aliases sa
                  ON sa.tenant_id = :tenant_id
                 AND sa.account_id = oc.account_id
                 AND sa.raw_name = oc.name
                JOIN encrypted_sku_costs alias_esc
                  ON alias_esc.tenant_id = :tenant_id
                 AND alias_esc.sku_master_id = sa.sku_master_id
                WHERE oc.tenant_id = :tenant_id
                  AND oc.sku = sm.sku_key
                  AND oc.name IS NOT NULL
                  {alias_offer_account_clause}
                ORDER BY sa.id
                LIMIT 1
            ) alias_cost ON TRUE
            LEFT JOIN sku_masters base_sm
              ON base_sm.tenant_id = :tenant_id
             AND sm.sku_key ~* '^\\s*[0-9]+\\s*x\\s+'
             AND base_sm.sku_key = regexp_replace(sm.sku_key, '^\\s*[0-9]+\\s*x\\s+', '', 'i')
            LEFT JOIN encrypted_sku_costs base_esc ON base_esc.sku_master_id = base_sm.id AND base_esc.tenant_id = :tenant_id
            WHERE sm.sku_key = :sku
              AND sm.tenant_id = :tenant_id
        """)
        meta = self.db.execute(meta_sql, {
            "sku": sku_key,
            "df": period.date_from,
            "dt": period.date_to,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().first()
        if not meta:
            return None

        encrypted_cost = None
        if meta["cost_ciphertext"] and meta["cost_nonce"]:
            encrypted_cost = {
                "ciphertext": meta["cost_ciphertext"],
                "nonce": meta["cost_nonce"],
                "key_version": meta["cost_key_version"],
                "aad_context": meta["cost_aad_context"],
            }

        # ── Gross revenue for this SKU ───────────────────────────────────────
        rev_sql = text(f"""
            SELECT
                COALESCE(SUM(o.unit_price * o.quantity), 0) AS revenue,
                COALESCE(SUM(o.quantity), 0)                AS units
            FROM orders_raw o
            WHERE o.bought_at BETWEEN :df AND :dt
              AND o.tenant_id = :tenant_id
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
              AND trim(o.sku) = :sku
              {acct_filter}
        """)
        rev_row = self.db.execute(rev_sql, {
            "df": period.date_from,
            "dt": period.date_to,
            "sku": sku_key,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().one()
        gross_revenue = _d(rev_row["revenue"])
        gross_units   = int(rev_row["units"])
        vat_rate      = _d(meta["vat_rate"])

        # ── Per-offer billing for this SKU (with order-date attribution) ────
        # Find the offer_id(s) for this SKU
        sku_bill_sql = _build_attributed_sku_detail_billing_sql(account_id)
        br = self.db.execute(sku_bill_sql, {
            "df_date": df_date,
            "dt_date": dt_date,
            "sku": sku_key,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().one()

        commission_cost           = _d(br["commission_cost"])           # negative
        featuring_commission_cost = _d(br["featuring_commission_cost"]) # negative
        coins_cost                = _d(br["coins_cost"])                # negative
        campaign_commission_cost  = _d(br["campaign_commission_cost"])  # negative
        campaign_bonus            = _d(br["campaign_bonus"])            # positive
        price_adjust_cost         = _d(br["price_adjust_cost"])         # positive
        refund_commission         = _d(br["refund_commission"])         # positive
        fulfillment               = _d(br["fulfillment"])               # negative
        smart_shipping_cost       = _d(br["smart_shipping_cost"])       # negative
        smart_forecast_cost       = _d(br["smart_forecast_cost"])       # negative; subset of smart_shipping_cost
        shipping_passthrough_cost = _d(br["shipping_passthrough_cost"]) # negative (buyer passthrough)
        foreign_shipping_cost     = _d(br["foreign_shipping_cost"])     # negative (buyer passthrough)
        featuring_cost            = _d(br["featuring_cost"])            # negative

        # ── Account-level billing — proportional allocation ──────────────────
        total_rev_sql = text(f"""
            SELECT COALESCE(SUM(o.unit_price * o.quantity), 0) AS total
            FROM orders_raw o
            WHERE o.bought_at BETWEEN :df AND :dt
              AND o.tenant_id = :tenant_id
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
              {acct_filter}
        """)
        total_rev = _d(self.db.execute(total_rev_sql, {
            "df": period.date_from,
            "dt": period.date_to,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).scalar())
        neutral_payment_refund_total = self.db.execute(
            _build_neutral_payment_refunds_summary_sql(account_id),
            {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
        ).mappings().one()
        total_rev = max(total_rev - _d(neutral_payment_refund_total["neutral_refund_value"]), Decimal("0"))

        _ACCT_LEVEL_IN = _sql_in(
            _ADS + _PROTECT + _LOCAL + _SUBSCRIPTION + _FULFILLMENT
        )
        acct_bill_sql = _build_attributed_acct_billing_sql(account_id, _ACCT_LEVEL_IN)
        acct = self.db.execute(acct_bill_sql, {
            "df_date": df_date,
            "dt_date": dt_date,
            "currency": currency,
            "tenant_id": self.tenant_id,
        }).mappings().one()

        returns_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_customer_returns_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        refunds_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_payment_refunds_for_returns_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        allegro_refunds_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_returns_allegro_refunds_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        neutral_cancelled_per_sku = {
            r["sku"]: dict(r)
            for r in self.db.execute(
                _build_neutral_payment_refunds_per_sku_sql(account_id),
                {"df_date": df_date, "dt_date": dt_date, "currency": currency, "tenant_id": self.tenant_id},
            ).mappings().all()
        }
        sku_returns = returns_per_sku.get(sku_key, {})
        neutral_cancelled_data = neutral_cancelled_per_sku.get(sku_key, {})
        neutral_cancelled_units = int(neutral_cancelled_data.get("neutral_cancelled_units", 0) or 0)
        neutral_cancelled_value = _d(neutral_cancelled_data.get("neutral_cancelled_value", 0))
        neutral_cancelled_cost_discount = _d(neutral_cancelled_data.get("neutral_cancelled_cost_discount", 0))
        gross_revenue = max(gross_revenue - neutral_cancelled_value, Decimal("0"))
        gross_units = max(gross_units - neutral_cancelled_units, 0)
        sku_returns_count = int(sku_returns.get("returns_count", 0) or 0)
        sku_returns_units = int(sku_returns.get("returns_units", 0) or 0)
        sku_returns_goods_value = _d(sku_returns.get("returns_goods_value", 0))
        sku_returns_goods_value_net = _d(sku_returns.get("returns_goods_value_net", 0))
        sku_returns_refund_value = _d(refunds_per_sku.get(sku_key, {}).get("returns_refund_value", 0))
        sku_returns_pending_count = int(sku_returns.get("returns_pending_count", 0) or 0)
        sku_returns_pending_units = int(sku_returns.get("returns_pending_units", 0) or 0)
        sku_returns_rejected_count = int(sku_returns.get("returns_rejected_count", 0) or 0)
        sku_returns_rejected_units = int(sku_returns.get("returns_rejected_units", 0) or 0)
        sku_allegro_refunds = _d(allegro_refunds_per_sku.get(sku_key, {}).get("commission_refunds_amount", 0))
        net_revenue = gross_revenue - sku_returns_goods_value
        net_revenue_value = _gross_to_net_by_rate(gross_revenue, vat_rate) - sku_returns_goods_value_net
        net_units = max(gross_units - sku_returns_units, 0)
        cogs_units = max(_d(net_units) - neutral_cancelled_cost_discount, Decimal("0"))
        share = (gross_revenue / total_rev) if total_rev > 0 and gross_revenue > 0 else Decimal("0")

        # Per-offer imported ads cost for this SKU
        _detail_ads_acct = f"AND ai.account_id = {account_id}" if account_id else ""
        _detail_orders_acct = f"AND o.account_id = {account_id}" if account_id else ""
        _detail_hist_oc_acct = f"AND oc.account_id = {account_id}" if account_id else ""
        _detail_oc_acct = f"AND account_id = {account_id}" if account_id else ""
        detail_ads_import_sql = text(f"""
            WITH historical_offer_skus AS (
                SELECT offer_id, sku
                FROM (
                    SELECT
                        o.offer_id,
                        trim(o.sku) AS sku,
                        row_number() OVER (
                            PARTITION BY o.offer_id
                            ORDER BY COUNT(*) DESC, MAX(o.bought_at) DESC
                        ) AS rn
                    FROM orders_raw o
                    WHERE o.tenant_id = :tenant_id
                      AND o.offer_id IS NOT NULL
                      AND o.sku IS NOT NULL
                      AND trim(o.sku) <> ''
                      {_detail_orders_acct}
                      AND NOT EXISTS (
                          SELECT 1
                          FROM offers_cache oc
                          WHERE oc.tenant_id = o.tenant_id
                            AND oc.offer_id = o.offer_id
                            {_detail_hist_oc_acct}
                      )
                    GROUP BY o.offer_id, trim(o.sku)
                ) ranked
                WHERE rn = 1
            ),
            offer_skus AS (
                SELECT sku, offer_id
                FROM offers_cache
                WHERE tenant_id = :tenant_id
                  AND sku IS NOT NULL
                  {_detail_oc_acct}
                UNION ALL
                SELECT sku, offer_id
                FROM historical_offer_skus
            )
            SELECT COALESCE(SUM(ai.cost), 0) AS imported_cost
            FROM allegro_ads_imports ai
            JOIN offer_skus os ON os.offer_id = ai.offer_id
            WHERE os.sku = :sku
              AND ai.tenant_id = :tenant_id
              AND ai.ad_date BETWEEN :df_date AND :dt_date
              {_detail_ads_acct}
        """)
        detail_imported_row = self.db.execute(
            detail_ads_import_sql,
            {"sku": sku_key, "df_date": df_date, "dt_date": dt_date, "tenant_id": self.tenant_id},
        ).mappings().one()
        detail_imported_ads = _d(detail_imported_row["imported_cost"])  # positive magnitude

        _det_acct_check = f"AND account_id = {account_id}" if account_id else ""
        acct_imported_total_row = self.db.execute(
            text(f"""
                SELECT COALESCE(SUM(cost), 0) AS total
                FROM allegro_ads_imports
                WHERE ad_date BETWEEN :df_date AND :dt_date
                  AND tenant_id = :tenant_id
                  {_det_acct_check}
            """),
            {"df_date": df_date, "dt_date": dt_date, "tenant_id": self.tenant_id},
        ).mappings().one()
        detail_total_imported_ads = _d(acct_imported_total_row["total"])
        detail_billing_ads = abs(_d(acct["ads_cost"]))
        if detail_total_imported_ads > 0 and detail_billing_ads > 0:
            detail_nsp_adjustment_total = detail_billing_ads - detail_total_imported_ads
        elif detail_total_imported_ads > 0:
            detail_nsp_adjustment_total = Decimal("0")
        else:
            detail_nsp_adjustment_total = detail_billing_ads
        detail_nsp_adjustment = detail_nsp_adjustment_total * share
        ads_alloc = -(detail_imported_ads + detail_nsp_adjustment)

        protect_alloc              = _d(acct["protect_cost"])              * share  # negative
        local_alloc                = _d(acct["local_cost"])                * share  # negative
        subscription_alloc         = _d(acct["subscription_cost"])        * share  # negative
        fulfillment_base_alloc     = _d(acct["fulfillment_base_cost"])    * share  # negative
        fulfillment_storage_alloc  = _d(acct["fulfillment_storage_cost"]) * share  # negative
        fulfillment_returns_alloc  = _d(acct["fulfillment_returns_cost"]) * share  # negative
        fulfillment_subs_alloc     = _d(acct["fulfillment_subscription_cost"]) * share  # negative
        fulfillment_other_alloc    = _d(acct["fulfillment_other_cost"])   * share  # negative
        fulfillment_alloc          = _d(acct["fulfillment"])              * share  # negative

        # ── Client-side financial metrics ───────────────────────────────────
        # COGS, profit, margin and ROI are computed in the browser after the
        # financial vault is unlocked.
        # foreign_shipping and shipping_passthrough excluded from profit (buyer passthroughs)
        total_allegro_signed = (
            commission_cost + featuring_commission_cost + coins_cost
            + campaign_commission_cost
            + ads_alloc + smart_shipping_cost + featuring_cost
            + protect_alloc + local_alloc + subscription_alloc
            + fulfillment + fulfillment_alloc
        )
        total_allegro_net = _gross_to_net_23(abs(total_allegro_signed))
        return ProductDetail(
            sku_id=int(meta["sku_id"]),
            sku_key=sku_key,
            name=meta["name"],
            sell_price=_s(_d(meta["sell_price"])),
            encrypted_cost=encrypted_cost,
            cost_multiplier=str(_d(meta["cost_multiplier"]).quantize(Decimal("0.0001"))),
            ean=meta["ean"],
            vat_rate=_s(vat_rate),
            period_label=period.label,
            date_from=period.date_from_str,
            date_to=period.date_to_str,
            revenue_gross=_s(net_revenue),
            revenue_net=_s(net_revenue_value),
            sales_gross_value=_s(gross_revenue),
            sales_net_value=_s(_gross_to_net_by_rate(gross_revenue, vat_rate)),
            units_sold=net_units,
            cogs_units=_s(cogs_units),
            commission_cost=_s(abs(commission_cost)),
            featuring_commission_cost=_s(abs(featuring_commission_cost)),
            ads_cost=_s(abs(ads_alloc)),
            ads_imported_cost=_s(detail_imported_ads),
            ads_nsp_adjustment_cost=_s(detail_nsp_adjustment),
            smart_shipping_cost=_s(abs(smart_shipping_cost)),
            smart_forecast_cost=_s(abs(smart_forecast_cost)),
            shipping_passthrough_cost=_s(abs(shipping_passthrough_cost)),
            foreign_shipping_cost=_s(abs(foreign_shipping_cost)),
            featuring_cost=_s(abs(featuring_cost)),
            coins_cost=_s(abs(coins_cost)),
            campaign_commission_cost=_s(abs(campaign_commission_cost)),
            campaign_bonus=_s(campaign_bonus),
            price_adjust_cost=_s(price_adjust_cost),
            protect_cost=_s(abs(protect_alloc)),
            local_cost=_s(abs(local_alloc)),
            subscription_cost=_s(abs(subscription_alloc)),
            refund_commission=_s(refund_commission),
            fulfillment_base_cost=_s(abs(fulfillment_base_alloc)),
            fulfillment_storage_cost=_s(abs(fulfillment_storage_alloc)),
            fulfillment_returns_cost=_s(abs(fulfillment_returns_alloc)),
            fulfillment_subscription_cost=_s(abs(fulfillment_subs_alloc)),
            fulfillment_other_cost=_s(abs(fulfillment_other_alloc)),
            fulfillment=_s(abs(fulfillment + fulfillment_alloc)),
            total_allegro_net=_s(total_allegro_net),
            returns_revenue=_s(sku_returns_goods_value),
            returns_revenue_net=_s(sku_returns_goods_value_net),
            returns_goods_value=_s(sku_returns_goods_value),
            returns_goods_value_net=_s(sku_returns_goods_value_net),
            returns_count=sku_returns_count,
            returns_units=sku_returns_units,
            returns_refund_value=_s(sku_returns_refund_value),
            returns_pending_count=sku_returns_pending_count,
            returns_pending_units=sku_returns_pending_units,
            returns_rejected_count=sku_returns_rejected_count,
            returns_rejected_units=sku_returns_rejected_units,
            commission_refunds_amount=_s(sku_allegro_refunds),
            transaction_fee="0.00",
            cogs=None,
            profit_net=None,
            margin_pct=None,
            roi_pct=None,
            kp_ratio=None,
            kcap_ratio=None,
        )


# ── SQL builder helpers ────────────────────────────────────────────────────────

def _period_to_local_dates(period: Period) -> tuple[date, date]:
    """Convert UTC period boundaries to Warsaw-local dates (inclusive on both ends)."""
    df_date = datetime(*period.date_from.timetuple()[:6], tzinfo=timezone.utc).astimezone(WARSAW).date()
    dt_local = datetime(*period.date_to.timetuple()[:6], tzinfo=timezone.utc).astimezone(WARSAW)
    # If date_to lands exactly on local midnight, it is an exclusive upper bound
    # (today/yesterday/custom/previous_month). Otherwise (e.g. current_month "now")
    # we keep the local date inclusive.
    if dt_local.hour == 0 and dt_local.minute == 0 and dt_local.second == 0:
        dt_date = dt_local.date() - timedelta(days=1)
    else:
        dt_date = dt_local.date()
    return df_date, dt_date


def _build_attributed_acct_billing_sql(account_id: int | None, type_in: str) -> text:
    """
    Build SQL for account-level (no offer_id) billing aggregation using order-date attribution.
    Returns one row with total and per-category breakdowns.
    Requires :currency, :df_date, :dt_date bind parameters at execute time.
    smart_shipping_cost: Allegro fee/order Smart flags; legacy rows fall back to delivery_amount = 0.
    shipping_passthrough_cost: Allegro non-Smart flags; legacy rows fall back to delivery_amount > 0.
    """
    acct_where = f"AND b.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH order_dates AS (
            SELECT order_id,
                   MIN(((bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date) AS order_date
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              AND currency = :currency
              AND status = 'READY_FOR_PROCESSING'
            GROUP BY order_id
        ),
        order_delivery AS (
            SELECT order_id, MAX(delivery_amount) AS max_delivery
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
            GROUP BY order_id
        ),
        order_currencies AS (
            SELECT order_id, MAX(currency) AS currency
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
            GROUP BY order_id
        ),
        attributed_billing AS (
            SELECT b.*,
                   CASE
                     WHEN b.type IN {_ATTRIBUTED_BY_ORDER_IN}
                       THEN COALESCE(od.order_date, {_ADS_OR_BILLING_DATE_SQL})
                     ELSE {_ADS_OR_BILLING_DATE_SQL}
                   END AS effective_date,
                   COALESCE(odel.max_delivery, 0) AS order_delivery_amount
            FROM billing_raw b
                    LEFT JOIN order_dates od ON od.order_id = b.order_id
            LEFT JOIN order_delivery odel ON odel.order_id = b.order_id
            LEFT JOIN order_currencies o_cur ON o_cur.order_id = b.order_id
            WHERE (b.offer_id IS NULL OR b.type IN {_FEATURING_IN})
              AND b.tenant_id = :tenant_id
              AND b.type IN {type_in}
              AND b.currency = :currency
              AND (b.order_id IS NULL OR b.type NOT IN {_ATTRIBUTED_BY_ORDER_IN} OR od.order_id IS NOT NULL)
              AND (b.order_id IS NULL OR o_cur.order_id IS NULL OR o_cur.currency = :currency)
              {acct_where}
        )
        SELECT
            COALESCE(SUM(amount) FILTER (WHERE effective_date BETWEEN :df_date AND :dt_date),                                                                      0) AS total,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_ADS_IN}          AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS ads_cost,
            COALESCE(SUM(amount) FILTER (WHERE {_SMART_SHIPPING_WHERE} AND effective_date BETWEEN :df_date AND :dt_date),                0) AS smart_shipping_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_SMART_FORECAST_IN} AND effective_date BETWEEN :df_date AND :dt_date),           0) AS smart_forecast_cost,
            COALESCE(SUM(amount) FILTER (WHERE {_SHIPPING_PASSTHROUGH_WHERE} AND effective_date BETWEEN :df_date AND :dt_date),                0) AS shipping_passthrough_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FOREIGN_IN}      AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS foreign_shipping_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FEATURING_IN}    AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS featuring_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_PROTECT_IN}      AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS protect_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_LOCAL_IN}        AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS local_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_SUBSCRIPTION_IN} AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS subscription_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_BASE_IN}  AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS fulfillment_base_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_STORAGE_IN} AND effective_date BETWEEN :df_date AND :dt_date),                                      0) AS fulfillment_storage_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_RETURNS_IN} AND effective_date BETWEEN :df_date AND :dt_date),                                      0) AS fulfillment_returns_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_SUBS_IN}  AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS fulfillment_subscription_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_OTHER_IN} AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS fulfillment_other_cost,
            COALESCE(SUM(amount) FILTER (WHERE type IN {_FULFIL_IN}       AND effective_date BETWEEN :df_date AND :dt_date),                                        0) AS fulfillment
        FROM attributed_billing
    """)


def _build_attributed_sku_billing_sql(account_id: int | None) -> text:
    """
    Build SQL to aggregate SKU-attributable billing codes, grouped by SKU.

    Prefer exact order-line SKU attribution for order/offer billing. Fall back to
    offer cache for offer-only rows (for example FEA). Order-level rows without
    offer_id (for example Smart/delivery) are allocated across order lines by
    line gross value. Only truly account-level rows stay in the proportional
    account allocation path.
    Requires :currency, :df_date, :dt_date bind parameters at execute time.
    """
    refund_exclusion = _commission_refund_exclusion_sql("b", account_id, per_sku=True)
    acct_where = f"AND b.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH order_dates AS (
            SELECT order_id,
                   MIN(((bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date) AS order_date
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
              AND currency = :currency
              AND status = 'READY_FOR_PROCESSING'
            GROUP BY order_id
        ),
        order_delivery AS (
            SELECT order_id, MAX(delivery_amount) AS max_delivery
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
            GROUP BY order_id
        ),
        order_currencies AS (
            SELECT order_id, MAX(currency) AS currency
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
            GROUP BY order_id
        ),
        order_lines AS (
            SELECT order_id,
                   trim(sku) AS sku,
                   SUM(
                       unit_price * GREATEST(
                           quantity - COALESCE((
                               SELECT COALESCE(SUM(
                                   CASE
                                       WHEN pri.refund_type = 'QUANTITY' THEN COALESCE(pri.quantity, 0)
                                       ELSE 0
                                   END
                               ), 0)
                               + CASE WHEN COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0) > 0
                                      AND o.unit_price > 0
                                      -- Not full amount -> no unit subtracted (see neutral_refund_lines).
                                      THEN FLOOR(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY') / o.unit_price)
                                      ELSE 0 END
                               FROM payment_refund_line_items_raw pri
                               JOIN payment_refunds_raw pr ON pr.refund_id = pri.refund_id
                               WHERE pri.line_item_id = o.line_item_id
                                 AND pri.tenant_id = :tenant_id
                                 AND pr.tenant_id = :tenant_id
                                 AND pr.status IN ('SUCCESS', 'PARTIAL', 'IN_PROGRESS')
                                 AND pr.currency = :currency
                           ), 0),
                           0
                       )
                   ) AS line_gross
            FROM orders_raw o
                    WHERE o.tenant_id = :tenant_id
                      AND o.order_id IS NOT NULL
              AND o.sku IS NOT NULL
              {acct_where_orders}
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
            GROUP BY o.order_id, trim(o.sku)
        ),
        order_totals AS (
            SELECT order_id, SUM(line_gross) AS order_gross
            FROM order_lines
            GROUP BY order_id
        ),
        order_sku_map AS (
            SELECT DISTINCT order_id, offer_id, trim(sku) AS sku
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              AND offer_id IS NOT NULL
              AND sku IS NOT NULL
              {acct_where_orders}
              AND status = 'READY_FOR_PROCESSING'
              AND (currency = :currency OR currency IS NULL)
        ),
        attributed_billing AS (
            SELECT b.*,
                   CASE
                     WHEN b.type IN {_ATTRIBUTED_BY_ORDER_IN}
                       THEN COALESCE(od.order_date, {_ADS_OR_BILLING_DATE_SQL})
                     ELSE {_ADS_OR_BILLING_DATE_SQL}
                   END AS effective_date,
                   COALESCE(
                       NULLIF(osm.sku, ''),
                       NULLIF(trim(oc.sku), ''),
                       NULLIF(ol.sku, '')
                   ) AS sku,
                   CASE
                     WHEN COALESCE(NULLIF(osm.sku, ''), NULLIF(trim(oc.sku), '')) IS NOT NULL
                       THEN b.amount
                     WHEN ol.sku IS NOT NULL AND ot.order_gross > 0
                       THEN b.amount * ol.line_gross / ot.order_gross
                     ELSE NULL
                   END AS allocated_amount,
                   COALESCE(odel.max_delivery, 0) AS order_delivery_amount
            FROM billing_raw b
                    LEFT JOIN order_dates od ON od.order_id = b.order_id
            LEFT JOIN order_currencies o_cur ON o_cur.order_id = b.order_id
            LEFT JOIN order_delivery odel ON odel.order_id = b.order_id
            LEFT JOIN offers_cache oc ON b.offer_id = oc.offer_id AND oc.account_id = b.account_id AND oc.tenant_id = :tenant_id
            LEFT JOIN order_sku_map osm ON osm.order_id = b.order_id AND osm.offer_id = b.offer_id
            LEFT JOIN order_lines ol ON ol.order_id = b.order_id AND b.offer_id IS NULL
            LEFT JOIN order_totals ot ON ot.order_id = ol.order_id
            WHERE b.tenant_id = :tenant_id
              AND b.type NOT IN {_EXCL_IN}
              AND b.currency = :currency
              AND (b.order_id IS NULL OR b.type NOT IN {_ATTRIBUTED_BY_ORDER_IN} OR od.order_id IS NOT NULL)
              AND (b.order_id IS NULL OR o_cur.order_id IS NULL OR o_cur.currency = :currency)
              {acct_where}
        )
        SELECT
            b.sku AS sku,
            COALESCE(LEAST(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_SUC_IN} AND {refund_exclusion} AND b.effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS commission_cost,
            COALESCE(LEAST(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FSF_IN} AND {refund_exclusion} AND b.effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS featuring_commission_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE {_SMART_SHIPPING_WHERE_B} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_shipping_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_SMART_FORECAST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_forecast_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE {_SHIPPING_PASSTHROUGH_WHERE_B} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS shipping_passthrough_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FOREIGN_IN}      AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS foreign_shipping_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FEATURING_IN}    AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS featuring_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_COINS_IN}        AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS coins_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_CAMPAIGN_COST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_commission_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_CAMPAIGN_BONUS_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_bonus,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_PRICE_ADJUST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS price_adjust_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_REFUND_IN}       AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS refund_commission,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FULFIL_IN}       AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment
        FROM attributed_billing b
        WHERE b.sku IS NOT NULL
        GROUP BY b.sku
    """)


def _build_attributed_sku_detail_billing_sql(account_id: int | None) -> text:
    """
    Build SQL to aggregate SKU-attributable billing codes for a single SKU.
    Requires :currency, :df_date, :dt_date, :sku bind parameters at execute time.
    """
    refund_exclusion = _commission_refund_exclusion_sql("b", account_id, per_sku=True)
    acct_where = f"AND b.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH order_dates AS (
            SELECT order_id,
                   MIN(((bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date) AS order_date
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
              AND currency = :currency
              AND status = 'READY_FOR_PROCESSING'
            GROUP BY order_id
        ),
        order_delivery AS (
            SELECT order_id, MAX(delivery_amount) AS max_delivery
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
            GROUP BY order_id
        ),
        order_currencies AS (
            SELECT order_id, MAX(currency) AS currency
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              {acct_where_orders}
            GROUP BY order_id
        ),
        order_lines AS (
            SELECT order_id,
                   trim(sku) AS sku,
                   SUM(
                       unit_price * GREATEST(
                           quantity - COALESCE((
                               SELECT COALESCE(SUM(
                                   CASE
                                       WHEN pri.refund_type = 'QUANTITY' THEN COALESCE(pri.quantity, 0)
                                       ELSE 0
                                   END
                               ), 0)
                               + CASE WHEN COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0) > 0
                                      AND o.unit_price > 0
                                      -- Not full amount -> no unit subtracted (see neutral_refund_lines).
                                      THEN FLOOR(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY') / o.unit_price)
                                      ELSE 0 END
                               FROM payment_refund_line_items_raw pri
                               JOIN payment_refunds_raw pr ON pr.refund_id = pri.refund_id
                               WHERE pri.line_item_id = o.line_item_id
                                 AND pri.tenant_id = :tenant_id
                                 AND pr.tenant_id = :tenant_id
                                 AND pr.status IN ('SUCCESS', 'PARTIAL', 'IN_PROGRESS')
                                 AND pr.currency = :currency
                           ), 0),
                           0
                       )
                   ) AS line_gross
            FROM orders_raw o
                    WHERE o.tenant_id = :tenant_id
                      AND o.order_id IS NOT NULL
              AND o.sku IS NOT NULL
              {acct_where_orders}
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
            GROUP BY o.order_id, trim(o.sku)
        ),
        order_totals AS (
            SELECT order_id, SUM(line_gross) AS order_gross
            FROM order_lines
            GROUP BY order_id
        ),
        order_sku_map AS (
            SELECT DISTINCT order_id, offer_id, trim(sku) AS sku
            FROM orders_raw
                    WHERE tenant_id = :tenant_id
                      AND order_id IS NOT NULL
              AND offer_id IS NOT NULL
              AND sku IS NOT NULL
              {acct_where_orders}
              AND status = 'READY_FOR_PROCESSING'
              AND (currency = :currency OR currency IS NULL)
        ),
        attributed_billing AS (
            SELECT b.*,
                   CASE
                     WHEN b.type IN {_ATTRIBUTED_BY_ORDER_IN}
                       THEN COALESCE(od.order_date, {_ADS_OR_BILLING_DATE_SQL})
                     ELSE {_ADS_OR_BILLING_DATE_SQL}
                   END AS effective_date,
                   COALESCE(
                       NULLIF(osm.sku, ''),
                       NULLIF(trim(oc.sku), ''),
                       NULLIF(ol.sku, '')
                   ) AS sku,
                   CASE
                     WHEN COALESCE(NULLIF(osm.sku, ''), NULLIF(trim(oc.sku), '')) IS NOT NULL
                       THEN b.amount
                     WHEN ol.sku IS NOT NULL AND ot.order_gross > 0
                       THEN b.amount * ol.line_gross / ot.order_gross
                     ELSE NULL
                   END AS allocated_amount,
                   COALESCE(odel.max_delivery, 0) AS order_delivery_amount
            FROM billing_raw b
                    LEFT JOIN order_dates od ON od.order_id = b.order_id
            LEFT JOIN order_currencies o_cur ON o_cur.order_id = b.order_id
            LEFT JOIN order_delivery odel ON odel.order_id = b.order_id
            LEFT JOIN offers_cache oc ON b.offer_id = oc.offer_id AND oc.account_id = b.account_id AND oc.tenant_id = :tenant_id
            LEFT JOIN order_sku_map osm ON osm.order_id = b.order_id AND osm.offer_id = b.offer_id
            LEFT JOIN order_lines ol ON ol.order_id = b.order_id AND b.offer_id IS NULL
            LEFT JOIN order_totals ot ON ot.order_id = ol.order_id
            WHERE b.tenant_id = :tenant_id
              AND b.type NOT IN {_EXCL_IN}
              AND b.currency = :currency
              AND (b.order_id IS NULL OR b.type NOT IN {_ATTRIBUTED_BY_ORDER_IN} OR od.order_id IS NOT NULL)
              AND (b.order_id IS NULL OR o_cur.order_id IS NULL OR o_cur.currency = :currency)
              {acct_where}
        )
        SELECT
            COALESCE(LEAST(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_SUC_IN} AND {refund_exclusion} AND b.effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS commission_cost,
            COALESCE(LEAST(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FSF_IN} AND {refund_exclusion} AND b.effective_date BETWEEN :df_date AND :dt_date), 0), 0) AS featuring_commission_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE {_SMART_SHIPPING_WHERE_B} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_shipping_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_SMART_FORECAST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS smart_forecast_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE {_SHIPPING_PASSTHROUGH_WHERE_B} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS shipping_passthrough_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FOREIGN_IN}      AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS foreign_shipping_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FEATURING_IN}    AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS featuring_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_COINS_IN}        AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS coins_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_CAMPAIGN_COST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_commission_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_CAMPAIGN_BONUS_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS campaign_bonus,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_PRICE_ADJUST_IN} AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS price_adjust_cost,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_REFUND_IN}       AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS refund_commission,
            COALESCE(SUM(b.allocated_amount) FILTER (WHERE b.type IN {_FULFIL_IN}       AND b.effective_date BETWEEN :df_date AND :dt_date), 0) AS fulfillment
        FROM attributed_billing b
        WHERE b.sku = :sku
    """)


def _neutral_full_refund_orders_ctes(account_id: int | None) -> str:
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    acct_where_refunds = f"AND pr.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    return f"""
        eligible_order_items AS (
            SELECT
                o.order_id,
                o.line_item_id,
                trim(o.sku) AS sku,
                o.quantity,
                o.unit_price,
                COALESCE(sm.vat_rate, o.vat_rate, 23) AS vat_rate,
                COALESCE(o.delivery_amount, 0) AS delivery_amount
            FROM orders_raw o
            LEFT JOIN sku_masters sm ON sm.sku_key = trim(o.sku) AND sm.tenant_id = :tenant_id
            WHERE o.order_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND o.status = 'READY_FOR_PROCESSING'
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {acct_where_orders}
        ),
        order_totals AS (
            SELECT
                order_id,
                COALESCE(SUM(quantity), 0) AS units,
                COALESCE(SUM(unit_price * quantity), 0) AS order_value,
                COALESCE(SUM((unit_price * quantity) / (1 + (vat_rate / 100.0))), 0) AS order_value_net,
                COALESCE(MAX(delivery_amount), 0) AS delivery_value
            FROM eligible_order_items
            GROUP BY order_id
        ),
        approved_return_orders AS (
            SELECT DISTINCT cr.order_id
            FROM customer_returns_raw cr
            JOIN order_totals ot ON ot.order_id = cr.order_id
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cr.order_id IS NOT NULL
              {acct_where_returns}
        ),
        refund_order_map AS (
            SELECT
                pr.refund_id,
                COALESCE(pr.order_id, MIN(eoi.order_id)) AS order_id,
                pr.total_amount
            FROM payment_refunds_raw pr
            LEFT JOIN payment_refund_line_items_raw pri ON pri.refund_id = pr.refund_id
            LEFT JOIN eligible_order_items eoi ON eoi.line_item_id = pri.line_item_id
            WHERE pr.status IN ('SUCCESS', 'PARTIAL')
              AND pr.tenant_id = :tenant_id
              AND pr.currency = :currency
              AND (pri.refund_id IS NULL OR pri.tenant_id = :tenant_id)
              {acct_where_refunds}
            GROUP BY pr.refund_id, pr.order_id, pr.total_amount
        ),
        refunded_orders AS (
            SELECT
                rom.order_id,
                COALESCE(SUM(rom.total_amount), 0) AS refunded_value
            FROM refund_order_map rom
            WHERE rom.order_id IS NOT NULL
            GROUP BY rom.order_id
        ),
        /*
         * Payment refunds can cover only selected lines in a checkout form.
         * Keep the refund at line-item granularity; using pr.total_amount at
         * order level incorrectly leaves a partially refunded order intact.
         * IN_PROGRESS is included deliberately: Allegro has already issued
         * the line-level refund and the conservative P&L view must not count
         * that line as realised revenue while the payment is settling.
         */
        neutral_refund_lines AS (
            SELECT
                eoi.order_id,
                eoi.line_item_id,
                eoi.sku,
                LEAST(
                    eoi.quantity,
                    GREATEST(
                        COALESCE(SUM(
                            CASE
                                WHEN pri.refund_type = 'QUANTITY' THEN COALESCE(pri.quantity, 0)
                                ELSE 0
                            END
                        ), 0) + CASE
                            WHEN COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0) > 0
                                 AND eoi.unit_price > 0
                            -- Only a refund covering a full unit price removes a sold unit;
                            -- a partial money refund (e.g. price correction, goodwill,
                            -- overpayment) is not a return of goods and must not zero out
                            -- units sold. FLOOR (not CEIL) enforces "not full amount -> no
                            -- unit subtracted".
                            THEN FLOOR(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY') / eoi.unit_price)
                            ELSE 0
                        END,
                        0
                    )
                )::integer AS refunded_units,
                -- "2 x ..." bundle SKUs: a partial (sub-unit) AMOUNT refund left over after
                -- whole-unit refunds are removed above is treated as half the bundle's cost
                -- (one of the two items), not a full unit and not zero.
                CASE
                    WHEN eoi.sku ILIKE '2 x %'
                         AND eoi.unit_price > 0
                         AND COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0) > 0
                         AND (
                             COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0)
                             - FLOOR(COALESCE(SUM(pri.value_amount) FILTER (WHERE pri.refund_type <> 'QUANTITY'), 0) / eoi.unit_price) * eoi.unit_price
                         ) > 0.01
                    THEN 0.5::numeric
                    ELSE 0::numeric
                END AS cost_discount_units,
                LEAST(
                    eoi.unit_price * eoi.quantity,
                    GREATEST(
                        COALESCE(SUM(
                            CASE
                                WHEN pri.refund_type = 'QUANTITY'
                                    THEN COALESCE(pri.quantity, 0) * eoi.unit_price
                                ELSE COALESCE(pri.value_amount, 0)
                            END
                        ), 0),
                        0
                    )
                ) AS refunded_value,
                LEAST(
                    (eoi.unit_price * eoi.quantity) / (1 + (eoi.vat_rate / 100.0)),
                    GREATEST(
                        COALESCE(SUM(
                            CASE
                                WHEN pri.refund_type = 'QUANTITY'
                                    THEN COALESCE(pri.quantity, 0) * eoi.unit_price / (1 + (eoi.vat_rate / 100.0))
                                ELSE COALESCE(pri.value_amount, 0) / (1 + (eoi.vat_rate / 100.0))
                            END
                        ), 0),
                        0
                    )
                ) AS refunded_value_net
            FROM eligible_order_items eoi
            JOIN payment_refund_line_items_raw pri
              ON pri.line_item_id = eoi.line_item_id
             AND pri.tenant_id = :tenant_id
            JOIN payment_refunds_raw pr
              ON pr.refund_id = pri.refund_id
             AND pr.tenant_id = :tenant_id
            LEFT JOIN approved_return_orders aro ON aro.order_id = eoi.order_id
            WHERE pr.status IN ('SUCCESS', 'PARTIAL', 'IN_PROGRESS')
              AND pr.currency = :currency
              {acct_where_refunds}
              AND aro.order_id IS NULL
            GROUP BY eoi.order_id, eoi.line_item_id, eoi.sku,
                     eoi.quantity, eoi.unit_price, eoi.vat_rate
        ),
        neutral_orders AS (
            SELECT ot.*
            FROM order_totals ot
            JOIN refunded_orders ro ON ro.order_id = ot.order_id
            LEFT JOIN approved_return_orders aro ON aro.order_id = ot.order_id
            WHERE aro.order_id IS NULL
              AND ro.refunded_value >= ot.order_value + ot.delivery_value - 0.01
        )
    """


def _build_customer_returns_summary_sql(account_id: int | None) -> text:
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH {_neutral_full_refund_orders_ctes(account_id)},
        return_lines AS (
            SELECT
                cr.customer_return_id,
                cr.status,
                cri.quantity,
                COALESCE(cri.unit_price, 0) AS unit_price,
                COALESCE(sm.vat_rate, om.vat_rate, 23) AS vat_rate
            FROM customer_returns_raw cr
            JOIN customer_return_items_raw cri ON cri.customer_return_id = cr.customer_return_id
            JOIN (
                SELECT DISTINCT o.order_id, o.offer_id, trim(o.sku) AS sku, o.vat_rate
                FROM orders_raw o
                WHERE o.order_id IS NOT NULL
                  AND o.tenant_id = :tenant_id
                  AND o.offer_id IS NOT NULL
                  AND (o.currency = :currency OR o.currency IS NULL)
                  AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
                  {acct_where_orders}
            ) om ON om.order_id = cr.order_id AND om.offer_id = cri.offer_id
            LEFT JOIN sku_masters sm ON sm.sku_key = om.sku AND sm.tenant_id = :tenant_id
            WHERE 1 = 1
              AND cr.tenant_id = :tenant_id
              AND cri.tenant_id = :tenant_id
              AND NOT EXISTS (
                  SELECT 1 FROM neutral_orders no WHERE no.order_id = cr.order_id
              )
              {acct_where_returns}
        )
        SELECT
            COUNT(DISTINCT customer_return_id) FILTER (WHERE status IN {_RETURN_APPROVED_IN}) AS returns_count,
            COALESCE(SUM(quantity) FILTER (WHERE status IN {_RETURN_APPROVED_IN}), 0) AS returns_units,
            COALESCE(SUM(quantity * unit_price) FILTER (WHERE status IN {_RETURN_APPROVED_IN}), 0) AS returns_goods_value,
            COALESCE(SUM((quantity * unit_price) / (1 + (vat_rate / 100.0))) FILTER (WHERE status IN {_RETURN_APPROVED_IN}), 0) AS returns_goods_value_net,
            COUNT(DISTINCT customer_return_id) FILTER (WHERE status IN {_RETURN_PENDING_IN}) AS returns_pending_count,
            COALESCE(SUM(quantity) FILTER (WHERE status IN {_RETURN_PENDING_IN}), 0) AS returns_pending_units,
            COUNT(DISTINCT customer_return_id) FILTER (WHERE status IN {_RETURN_REJECTED_IN}) AS returns_rejected_count,
            COALESCE(SUM(quantity) FILTER (WHERE status IN {_RETURN_REJECTED_IN}), 0) AS returns_rejected_units
        FROM return_lines
    """)


def _build_customer_returns_per_sku_sql(account_id: int | None) -> text:
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH {_neutral_full_refund_orders_ctes(account_id)},
        order_sku_map AS (
            SELECT DISTINCT o.order_id, o.offer_id, trim(o.sku) AS sku, o.vat_rate
            FROM orders_raw o
            WHERE o.order_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND o.offer_id IS NOT NULL
              AND o.sku IS NOT NULL
              {acct_where_orders}
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
        )
        SELECT
            osm.sku,
            COUNT(DISTINCT cr.customer_return_id) FILTER (WHERE cr.status IN {_RETURN_APPROVED_IN}) AS returns_count,
            COALESCE(SUM(cri.quantity) FILTER (WHERE cr.status IN {_RETURN_APPROVED_IN}), 0) AS returns_units,
            COALESCE(SUM(cri.quantity * COALESCE(cri.unit_price, 0)) FILTER (WHERE cr.status IN {_RETURN_APPROVED_IN}), 0) AS returns_goods_value,
            COALESCE(SUM((cri.quantity * COALESCE(cri.unit_price, 0)) / (1 + (COALESCE(sm.vat_rate, osm.vat_rate, 23) / 100.0))) FILTER (WHERE cr.status IN {_RETURN_APPROVED_IN}), 0) AS returns_goods_value_net,
            COUNT(DISTINCT cr.customer_return_id) FILTER (WHERE cr.status IN {_RETURN_PENDING_IN}) AS returns_pending_count,
            COALESCE(SUM(cri.quantity) FILTER (WHERE cr.status IN {_RETURN_PENDING_IN}), 0) AS returns_pending_units,
            COUNT(DISTINCT cr.customer_return_id) FILTER (WHERE cr.status IN {_RETURN_REJECTED_IN}) AS returns_rejected_count,
            COALESCE(SUM(cri.quantity) FILTER (WHERE cr.status IN {_RETURN_REJECTED_IN}), 0) AS returns_rejected_units
        FROM customer_returns_raw cr
        JOIN customer_return_items_raw cri ON cri.customer_return_id = cr.customer_return_id
        JOIN order_sku_map osm ON osm.order_id = cr.order_id AND osm.offer_id = cri.offer_id
        LEFT JOIN sku_masters sm ON sm.sku_key = osm.sku AND sm.tenant_id = :tenant_id
        WHERE 1 = 1
          AND cr.tenant_id = :tenant_id
          AND cri.tenant_id = :tenant_id
          AND NOT EXISTS (
              SELECT 1 FROM neutral_orders no WHERE no.order_id = cr.order_id
          )
          {acct_where_returns}
        GROUP BY osm.sku
    """)


def _build_payment_refunds_for_returns_summary_sql(account_id: int | None) -> text:
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    acct_where_refunds = f"AND pr.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH eligible_orders AS (
            SELECT DISTINCT o.order_id
            FROM orders_raw o
            WHERE o.order_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {acct_where_orders}
        ),
        approved_return_orders AS (
            SELECT DISTINCT cr.order_id
            FROM customer_returns_raw cr
            JOIN eligible_orders eo ON eo.order_id = cr.order_id
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cr.order_id IS NOT NULL
              {acct_where_returns}
        ),
        order_line_map AS (
            SELECT DISTINCT o.line_item_id, o.order_id
            FROM orders_raw o
            WHERE o.line_item_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {acct_where_orders}
        ),
        refund_order_map AS (
            SELECT
                pr.refund_id,
                COALESCE(pr.order_id, MIN(olm.order_id)) AS order_id,
                pr.total_amount
            FROM payment_refunds_raw pr
            LEFT JOIN payment_refund_line_items_raw pri ON pri.refund_id = pr.refund_id
            LEFT JOIN order_line_map olm ON olm.line_item_id = pri.line_item_id
            WHERE pr.status IN ('SUCCESS', 'PARTIAL')
              AND pr.tenant_id = :tenant_id
              AND (pri.refund_id IS NULL OR pri.tenant_id = :tenant_id)
              {acct_where_refunds}
            GROUP BY pr.refund_id, pr.order_id, pr.total_amount
        )
        SELECT COALESCE(SUM(rom.total_amount), 0) AS returns_refund_value
        FROM refund_order_map rom
        JOIN approved_return_orders aro ON aro.order_id = rom.order_id
    """)


def _build_neutral_payment_refunds_summary_sql(account_id: int | None) -> text:
    return text(f"""
        WITH {_neutral_full_refund_orders_ctes(account_id)},
        neutral_refund_values AS (
            SELECT order_id, refunded_units AS units, refunded_value AS order_value,
                   refunded_value_net AS order_value_net
            FROM neutral_refund_lines
            UNION ALL
            SELECT no.order_id, no.units, no.order_value, no.order_value_net
            FROM neutral_orders no
            WHERE NOT EXISTS (
                SELECT 1 FROM neutral_refund_lines nrl
                WHERE nrl.order_id = no.order_id
            )
        )
        SELECT
            (SELECT COUNT(*) FROM neutral_orders) AS neutral_refund_orders_count,
            COALESCE(SUM(units), 0) AS neutral_refund_units,
            COALESCE(SUM(order_value), 0) AS neutral_refund_value,
            COALESCE(SUM(order_value_net), 0) AS neutral_refund_value_net
        FROM neutral_refund_values
    """)


def _build_neutral_payment_refunds_per_sku_sql(account_id: int | None) -> text:
    return text(f"""
        WITH {_neutral_full_refund_orders_ctes(account_id)},
        neutral_refund_values AS (
            SELECT order_id, sku, refunded_units AS units, refunded_value AS order_value,
                   cost_discount_units
            FROM neutral_refund_lines
            UNION ALL
            SELECT eoi.order_id, eoi.sku, eoi.quantity, eoi.unit_price * eoi.quantity,
                   0::numeric AS cost_discount_units
            FROM eligible_order_items eoi
            JOIN neutral_orders no ON no.order_id = eoi.order_id
            WHERE NOT EXISTS (
                SELECT 1 FROM neutral_refund_lines nrl
                WHERE nrl.order_id = no.order_id
            )
        )
        SELECT
            sku,
            COALESCE(SUM(units), 0) AS neutral_cancelled_units,
            COALESCE(SUM(order_value), 0) AS neutral_cancelled_value,
            COALESCE(SUM(cost_discount_units), 0) AS neutral_cancelled_cost_discount
        FROM neutral_refund_values
        WHERE sku IS NOT NULL
          AND trim(sku) <> ''
        GROUP BY sku
    """)


def _build_payment_refunds_for_returns_per_sku_sql(account_id: int | None) -> text:
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    acct_where_refunds = f"AND pr.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH approved_return_orders AS (
            SELECT DISTINCT cr.order_id
            FROM customer_returns_raw cr
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cr.order_id IS NOT NULL
              {acct_where_returns}
        )
        SELECT
            trim(o.sku) AS sku,
            COALESCE(SUM(
                CASE
                    WHEN pri.refund_type = 'QUANTITY' THEN COALESCE(pri.quantity, 0) * COALESCE(o.unit_price, 0)
                    ELSE COALESCE(pri.value_amount, 0)
                END
            ), 0) AS returns_refund_value
        FROM payment_refunds_raw pr
        JOIN payment_refund_line_items_raw pri ON pri.refund_id = pr.refund_id
        JOIN orders_raw o ON o.line_item_id = pri.line_item_id
        JOIN approved_return_orders aro ON aro.order_id = o.order_id
        WHERE pr.status IN ('SUCCESS', 'PARTIAL')
          AND pr.tenant_id = :tenant_id
          AND pri.tenant_id = :tenant_id
          AND o.tenant_id = :tenant_id
          {acct_where_refunds}
          {acct_where_orders}
          AND (o.currency = :currency OR o.currency IS NULL)
          AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
          AND o.sku IS NOT NULL
        GROUP BY trim(o.sku)
    """)


def _build_returns_allegro_refunds_summary_sql(account_id: int | None) -> text:
    acct_where_billing = f"AND b.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH approved_return_orders AS (
            SELECT DISTINCT cr.order_id
            FROM customer_returns_raw cr
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cr.order_id IS NOT NULL
              {acct_where_returns}
        ),
        eligible_orders AS (
            SELECT DISTINCT o.order_id
            FROM orders_raw o
            JOIN approved_return_orders aro ON aro.order_id = o.order_id
            WHERE o.order_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {acct_where_orders}
        )
        SELECT COALESCE(SUM(b.amount), 0) AS commission_refunds_amount
        FROM billing_raw b
        JOIN eligible_orders eo ON eo.order_id = b.order_id
        WHERE b.type IN ('SUC', 'FSF')
          AND b.tenant_id = :tenant_id
          AND b.amount > 0
          AND b.currency = :currency
          {acct_where_billing}
    """)


def _build_returns_allegro_refunds_per_sku_sql(account_id: int | None) -> text:
    acct_where_billing = f"AND b.account_id = {account_id}" if account_id else ""
    acct_where_orders = f"AND o.account_id = {account_id}" if account_id else ""
    acct_where_returns = f"AND cr.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH approved_return_lines AS (
            SELECT DISTINCT cr.order_id, cri.offer_id
            FROM customer_returns_raw cr
            JOIN customer_return_items_raw cri ON cri.customer_return_id = cr.customer_return_id
            WHERE cr.status IN {_RETURN_APPROVED_IN}
              AND cr.tenant_id = :tenant_id
              AND cri.tenant_id = :tenant_id
              AND cr.order_id IS NOT NULL
              AND cri.offer_id IS NOT NULL
              {acct_where_returns}
        ),
        order_sku_map AS (
            SELECT DISTINCT o.order_id, o.offer_id, trim(o.sku) AS sku
            FROM orders_raw o
            JOIN approved_return_lines arl ON arl.order_id = o.order_id AND arl.offer_id = o.offer_id
            WHERE o.order_id IS NOT NULL
              AND o.tenant_id = :tenant_id
              AND o.offer_id IS NOT NULL
              AND o.sku IS NOT NULL
              AND (o.currency = :currency OR o.currency IS NULL)
              AND ((o.bought_at AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Warsaw')::date BETWEEN :df_date AND :dt_date
              {acct_where_orders}
        )
        SELECT
            osm.sku,
            COALESCE(SUM(b.amount), 0) AS commission_refunds_amount
        FROM billing_raw b
        JOIN order_sku_map osm ON osm.order_id = b.order_id AND osm.offer_id = b.offer_id
        WHERE b.type IN ('SUC', 'FSF')
          AND b.tenant_id = :tenant_id
          AND b.amount > 0
          AND b.currency = :currency
          {acct_where_billing}
        GROUP BY osm.sku
    """)


def _build_neutral_cancelled_orders_summary_sql(account_id: int | None) -> text:
    acct_where = f"AND o.account_id = {account_id}" if account_id else ""
    return text(f"""
        WITH cancelled_orders AS (
            SELECT
                o.order_id,
                COALESCE(SUM(o.quantity), 0) AS units,
                COALESCE(SUM(o.unit_price * o.quantity), 0) AS gross_value
            FROM orders_raw o
            WHERE o.bought_at BETWEEN :df AND :dt
              AND o.tenant_id = :tenant_id
              AND o.status = 'CANCELLED'
              AND (o.currency = :currency OR o.currency IS NULL)
              {acct_where}
            GROUP BY o.order_id
        )
        SELECT
            COUNT(*) AS neutral_cancelled_orders_count,
            COALESCE(SUM(units), 0) AS neutral_cancelled_units,
            COALESCE(SUM(gross_value), 0) AS neutral_cancelled_value
        FROM cancelled_orders
    """)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _d(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))

def _s(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))

def _s2(v: Decimal | None) -> str | None:
    if v is None:
        return None
    return str(v.quantize(Decimal("0.01")))


def _allocate_signed_amount_by_weight(
    total: Decimal,
    weighted_keys: list[tuple[str, Decimal]],
) -> dict[str, Decimal]:
    cent = Decimal("0.01")
    rounded_total = total.quantize(cent)
    if rounded_total == 0:
        return {key: Decimal("0.00") for key, _ in weighted_keys}

    positive_weights = [(key, weight) for key, weight in weighted_keys if weight > 0]
    weight_sum = sum((weight for _, weight in positive_weights), Decimal("0"))
    if weight_sum <= 0:
        return {key: Decimal("0.00") for key, _ in weighted_keys}

    sign = Decimal("-1") if rounded_total < 0 else Decimal("1")
    magnitude = abs(rounded_total)
    raw_rows: list[tuple[str, Decimal, Decimal]] = []
    for key, weight in positive_weights:
        raw = magnitude * weight / weight_sum
        base = raw.quantize(cent, rounding=ROUND_DOWN)
        raw_rows.append((key, base, raw - base))

    allocated = {key: Decimal("0.00") for key, _ in weighted_keys}
    base_sum = sum((base for _, base, _ in raw_rows), Decimal("0"))
    remainder_cents = int(((magnitude - base_sum) / cent).to_integral_value())
    remainder_keys = [key for key, _, _ in sorted(raw_rows, key=lambda row: row[2], reverse=True)]
    increments = set(remainder_keys[:remainder_cents])

    for key, base, _fraction in raw_rows:
        amount = base + (cent if key in increments else Decimal("0.00"))
        allocated[key] = (amount * sign).quantize(cent)
    return allocated


def _gross_to_net_23(v: Decimal) -> Decimal:
    return v / Decimal("1.23") if v else Decimal("0")


def _gross_to_net_by_rate(v: Decimal, vat_rate: Decimal) -> Decimal:
    divisor = Decimal("1") + (vat_rate / Decimal("100"))
    return v / divisor if v else Decimal("0")
