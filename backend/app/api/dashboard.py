from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from typing import Optional
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import calendar

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.services.dashboard_cache import cached_call
from app.services.dashboard_engine import DashboardEngine, Period, SUPPORTED_PERIOD_KEYS, get_period, get_custom_period

# Polish labels for Allegro billing type codes (frontend-side mapping mirrored here for debug)
_BILLING_LABELS: dict[str, str] = {
    # _SUC — commission
    "SUC": "Prowizja od sprzedaży",
    # _FSF — featuring commission
    "FSF": "Prowizja od sprzedaży oferty wyróżnionej",
    # _ADS — daily campaign fee
    "NSP": "Opłata za kampanię Ads",
    # _SMART_SHIPPING — Allegro Delivery Smart per carrier
    "SMART": "Smart Prognoza",
    "HB4": "Dopłata do wysyłki Smart (InPost)",
    "HLB": "Dopłata do wysyłki Smart (DHL)",
    "HXO": "Dopłata do wysyłki Smart (One Kurier — kurier)",
    "DXP": "Dopłata do wysyłki Smart (One Kurier — paczkomat/punkt)",
    "ORB": "Dopłata do wysyłki Smart (ORLEN Paczka)",
    "DPB": "Dopłata do wysyłki Smart (DPD)",
    "DHR": "Opłata dodatkowa za dostawę DHL",
    "DPA": "Opłata dodatkowa za dostawę DPD Allegro Delivery",
    "HB9": "Opłata za dostawę Packeta",
    "XOR": "Opłata dodatkowa za dostawę One Kurier Allegro Delivery",
    # _FOREIGN_SHIPPING — buyer passthrough, excluded from profit
    "HB1": "Koszt wysyłki kupującego (kurier zagraniczny — Dania)",
    "HB8": "Koszt wysyłki kupującego (kurier zagraniczny)",
    # _FEATURING — subscription wyróżnienie
    "FEA": "Opłata za wyróżnienie (subskrypcja)",
    # _COINS — Allegro Monety per-offer
    "CPF": "Opłata za monety",
    "RCP": "Zwrot opłaty za monety",
    # _PRICE_ADJUST — Allegro Ceny rebate
    "PS1": "Wyrównanie Allegro Ceny",
    "PSA": "Wyrównanie Allegro Ceny",
    # _PROTECT
    "INS": "Allegro Protect",
    # _LOCAL
    "ALC": "Dopłata lokalna (ALC)",
    "ALS": "Dopłata lokalna (ALS)",
    "ALK": "Dopłata lokalna (ALK)",
    "ALI": "Dopłata lokalna (ALI)",
    "ALL": "Dopłata lokalna (ALL)",
    "ALP": "Dopłata lokalna (ALP)",
    # _SUBSCRIPTION
    "SB1": "Abonament Allegro (SB1)",
    "SB2": "Abonament Allegro (SB2)",
    "SB3": "Abonament Allegro (SB3)",
    "SB4": "Abonament Allegro (SB4)",
    "SBL": "Abonament Allegro (SBL)",
    "SBP": "Abonament Allegro (SBP)",
    "SH0": "Abonament próbny (SH0)",
    "SH1": "Abonament 1 miesiąc (SH1)",
    "ST1": "Statystyki (ST1)",
    "ST2": "Statystyki (ST2)",
    "ILF": "Opłata utrzymaniowa (ILF)",
    "ABO": "Abonament (ABO)",
    # _REFUND — positive
    "REF": "Zwrot prowizji",
    # _FULFILLMENT
    "SHIPMENT_SURCHARGE": "Dopłata do wysyłki (Fulfillment)",
    "OFA": "Fulfillment - opłata podstawowa",
    "OFB": "Fulfillment - magazynowanie pow. 30 dni",
    "OFC": "Fulfillment - magazynowanie pow. 180 dni",
    "OFD": "Fulfillment - magazynowanie pow. 360 dni",
    "OFE": "Fulfillment - obsługa zwrotów (produkty pełnowartościowe)",
    "OFF": "Fulfillment - obsługa zwrotów (produkty o obniżonej wartości)",
    "OFG": "Fulfillment - rozbieżność w przyjęciu do magazynu (niezgodność EAN)",
    "OFH": "Fulfillment - wycofanie produktu z magazynu",
    "OFI": "Fulfillment - transport zwrotny produktu",
    "OFJ": "Fulfillment - utylizacja produktów niepełnowartościowych",
    "OFK": "Fulfillment - rozbieżność w przyjęciu do magazynu (niezgodność regulaminowa)",
    "OFL": "Fulfillment - rozbieżność w przyjęciu do magazynu (nadwyżka)",
    "OFM": "Fulfillment - subskrypcja",
    "OFN": "Fulfillment - etykiety awizo",
    "OFP": "Fulfillment - obsługa dostawy kontenerowej",
    "OFQ": "Fulfillment - magazynowanie pow. 150 dni",
    "OFR": "Fulfillment - magazynowanie pow. 60 dni",
    "OFS": "Fulfillment - magazynowanie pow. 90 dni",
    "OFT": "Fulfillment VAS - zestawy prepakowane",
    "OFU": "Fulfillment - magazynowanie pow. 120 dni",
    "OFW": "Fulfillment - przeniesienie towarów",
    "OFX": "Fulfillment - zabezpieczenie towarów podrobionych",
    "OFY": "Fulfillment - wydanie organom towarów podrobionych",
    "OFZ": "Fulfillment - magazynowanie do 30 dni",
    # _EXCLUDE — bookkeeping, excluded from P&L
    "PAD": "Operacja księgowa (wykluczona z P&L)",
    "PB2": "Operacja księgowa (wykluczona z P&L)",
    "PBL": "Operacja księgowa (wykluczona z P&L)",
    "SUM": "Operacja księgowa (wykluczona z P&L)",
    "PAL": "Operacja księgowa (wykluczona z P&L)",
    "PAK": "Operacja księgowa (wykluczona z P&L)",
    "PFB": "Operacja księgowa (wykluczona z P&L)",
    "PFC": "Operacja księgowa (wykluczona z P&L)",
    "PKO": "Operacja księgowa (wykluczona z P&L)",
    "RFF": "Operacja księgowa (wykluczona z P&L)",
    "MFB": "Operacja księgowa (wykluczona z P&L)",
    "PCO": "Operacja księgowa (wykluczona z P&L)",
    "PAY": "Operacja księgowa (wykluczona z P&L)",
    "PRR": "Operacja księgowa (wykluczona z P&L)",
    "PRT": "Operacja księgowa (wykluczona z P&L)",
    "PRU": "Operacja księgowa (wykluczona z P&L)",
    "PRV": "Operacja księgowa (wykluczona z P&L)",
    "PRW": "Operacja księgowa (wykluczona z P&L)",
    "TRF": "Operacja księgowa (wykluczona z P&L)",
    "PRA": "Operacja księgowa (wykluczona z P&L)",
    "PMC": "Operacja księgowa (wykluczona z P&L)",
    "OVR": "Operacja księgowa (wykluczona z P&L)",
    "APF": "Operacja księgowa (wykluczona z P&L)",
    "AFP": "Operacja księgowa (wykluczona z P&L)",
    "VER": "Operacja księgowa (wykluczona z P&L)",
    "VAT": "Operacja VAT (wykluczona z P&L)",
    "VEP": "Operacja VAT (wykluczona z P&L)",
    "VEC": "Operacja VAT (wykluczona z P&L)",
    "VRF": "Operacja VAT (wykluczona z P&L)",
    "COR": "Korekta salda (wykluczona z P&L)",
    "CXR": "Korekta salda (wykluczona z P&L)",
    "COL": "Korekta salda (wykluczona z P&L)",
    "RIC": "Korekta salda (wykluczona z P&L)",
    "RIP": "Korekta salda (wykluczona z P&L)",
    "DIS": "Korekta salda (wykluczona z P&L)",
    "PUK": "Korekta salda (wykluczona z P&L)",
    "WOM": "Korekta salda (wykluczona z P&L)",
    "RET": "Korekta salda (wykluczona z P&L)",
    "CPS": "Korekta salda (wykluczona z P&L)",
    "ZNP": "Korekta salda (wykluczona z P&L)",
}

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_VALID_PERIODS = (
    "today",
    "yesterday",
    "last_7d",
    "last_14d",
    "last_30d",
    "last_90d",
    "current_month",
    "last_month",
    "previous_month",
    "ytd",
)
_LAST_N_DAYS = {"last_7d": 7, "last_14d": 14, "last_30d": 30, "last_90d": 90}
_COMPARISON_PERIODS = (
    "today", "yesterday",
    "last_7d", "last_14d", "last_30d", "last_90d",
    "current_month", "last_month", "previous_month", "ytd",
)
WARSAW = ZoneInfo("Europe/Warsaw")


def _cache_key(scope: TenantScope, method: str, account_id: Optional[int], currency: str, period: Period, search: Optional[str] = None) -> tuple:
    """Cache key isolating results per tenant/account/method/period/currency/search.

    tenant_id must always be first and always present — this is what keeps
    one tenant's cached numbers from ever being served to another tenant.
    """
    return (
        scope.tenant_id,
        method,
        account_id,
        currency,
        period.date_from.isoformat(),
        period.date_to.isoformat(),
        search or None,
    )


def _requested_periods(periods: Optional[str], allowed: tuple[str, ...], label: str) -> tuple[str, ...]:
    """Parse the optional compact period list while preserving request order."""
    if not periods:
        return allowed
    requested = tuple(dict.fromkeys(key.strip() for key in periods.split(",") if key.strip()))
    invalid = set(requested) - set(allowed)
    if invalid:
        raise HTTPException(422, f"Unknown {label} periods: {sorted(invalid)}")
    return requested


def _resolve_period(period: str, date_from: Optional[str], date_to: Optional[str]):
    """Return a Period object from either a named key or explicit date strings."""
    if period == "previous_month":
        period = "last_month"
    if period == "custom":
        if not date_from or not date_to:
            raise HTTPException(422, "date_from and date_to are required for custom period")
        try:
            return get_custom_period(date_from, date_to)
        except ValueError as e:
            raise HTTPException(422, f"Invalid date format: {e}")
    if period not in SUPPORTED_PERIOD_KEYS:
        raise HTTPException(
            422,
            f"unknown period: {period}, supported: {sorted(SUPPORTED_PERIOD_KEYS)}",
        )
    try:
        return get_period(period)
    except ValueError as e:
        raise HTTPException(
            422,
            f"unknown period: {period}, supported: {sorted(SUPPORTED_PERIOD_KEYS)}",
        ) from e


def _assert_account_if_present(scope: TenantScope, account_id: int | None) -> None:
    if account_id is None:
        return
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)


def _to_utc_naive(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _build_period_from_local(start_local: datetime, end_local: datetime, label: str) -> Period:
    return Period(
        date_from=_to_utc_naive(start_local),
        date_to=_to_utc_naive(end_local),
        label=label,
    )


def _previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _comparison_period_for(key: str, now_local: datetime) -> tuple[Period, str]:
    if key == "previous_month":
        key = "last_month"

    if key in _LAST_N_DAYS:
        n = _LAST_N_DAYS[key]
        current_start_day = now_local.date() - timedelta(days=n - 1)
        compare_end_day = current_start_day - timedelta(days=1)
        compare_start_day = compare_end_day - timedelta(days=n - 1)
        compare_start = datetime.combine(compare_start_day, time.min, tzinfo=WARSAW)
        compare_end = datetime.combine(compare_end_day, time.min, tzinfo=WARSAW) + timedelta(days=1)
        label = f"vs poprzednie {n} dni"
        return _build_period_from_local(compare_start, compare_end, label), label

    if key == "today":
        today_start = datetime.combine(now_local.date(), time.min, tzinfo=WARSAW)
        elapsed = now_local - today_start
        compare_start = today_start - timedelta(days=1)
        compare_end = compare_start + elapsed
        label = f"vs wczoraj do {now_local.strftime('%H:%M')}"
        return _build_period_from_local(compare_start, compare_end, label), label

    if key == "yesterday":
        yesterday = now_local.date() - timedelta(days=1)
        compare_day = yesterday - timedelta(days=7)
        compare_start = datetime.combine(compare_day, time.min, tzinfo=WARSAW)
        compare_end = compare_start + timedelta(days=1)
        label = "vs ten sam dzień tydzień wcześniej"
        return _build_period_from_local(compare_start, compare_end, label), label

    if key == "current_month":
        prev_year, prev_month = _previous_month(now_local.year, now_local.month)
        compare_day = min(now_local.day, calendar.monthrange(prev_year, prev_month)[1])
        compare_start = datetime(prev_year, prev_month, 1, 0, 0, 0, tzinfo=WARSAW)
        compare_end = datetime(
            prev_year,
            prev_month,
            compare_day,
            now_local.hour,
            now_local.minute,
            now_local.second,
            now_local.microsecond,
            tzinfo=WARSAW,
        )
        label = f"vs 1-{compare_day} poprzedniego miesiąca do {now_local.strftime('%H:%M')}"
        return _build_period_from_local(compare_start, compare_end, label), label

    if key == "last_month":
        prev_year, prev_month = _previous_month(now_local.year, now_local.month)
        earlier_year, earlier_month = _previous_month(prev_year, prev_month)
        compare_start = datetime(earlier_year, earlier_month, 1, 0, 0, 0, tzinfo=WARSAW)
        compare_end = datetime(prev_year, prev_month, 1, 0, 0, 0, tzinfo=WARSAW)
        label = "vs wcześniejszy pełny miesiąc"
        return _build_period_from_local(compare_start, compare_end, label), label

    if key == "ytd":
        compare_start = datetime(now_local.year - 1, 1, 1, 0, 0, 0, tzinfo=WARSAW)
        compare_end = datetime(now_local.year - 1, now_local.month, now_local.day, 0, 0, 0, tzinfo=WARSAW) + timedelta(days=1)
        label = "vs analogiczny okres poprzedniego roku"
        return _build_period_from_local(compare_start, compare_end, label), label

    raise HTTPException(400, f"Unsupported comparison period: {key}")


@router.get("/debug/billing-types", tags=["debug"])
def debug_billing_types(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD filter start"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD filter end"),
    scope: TenantScope = Depends(get_scope),
):
    """List all unique billing type codes found in billing_raw with Polish labels."""
    if date_from and date_to:
        try:
            p = get_custom_period(date_from, date_to)
        except ValueError as e:
            raise HTTPException(400, f"Invalid date: {e}")
        rows = scope.db.execute(
            text("""
                SELECT type, COUNT(*) AS cnt
                FROM billing_raw
                WHERE tenant_id = :tenant_id
                  AND occurred_at BETWEEN :df AND :dt
                GROUP BY type ORDER BY cnt DESC
            """),
            {"tenant_id": scope.tenant_id, "df": p.date_from, "dt": p.date_to},
        ).fetchall()
    else:
        rows = scope.db.execute(
            text("""
                SELECT type, COUNT(*) AS cnt
                FROM billing_raw
                WHERE tenant_id = :tenant_id
                GROUP BY type ORDER BY cnt DESC
            """),
            {"tenant_id": scope.tenant_id},
        ).fetchall()
    return [
        {
            "type": r.type,
            "count": r.cnt,
            "label": _BILLING_LABELS.get(r.type) if r.type else None,
            "mapped": r.type in _BILLING_LABELS if r.type else False,
        }
        for r in rows
    ]


@router.get("/summary")
def dashboard_summary(
    period: str = Query("today", description="today|yesterday|last_7d|last_14d|last_30d|last_90d|current_month|previous_month|ytd|custom"),
    account_id: Optional[int] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD, required when period=custom"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD, required when period=custom"),
    search: Optional[str] = Query(None, description="Filter by offer name (ILIKE substring)"),
    scope: TenantScope = Depends(get_scope),
):
    p = _resolve_period(period, date_from, date_to)
    _assert_account_if_present(scope, account_id)
    key = _cache_key(scope, "summary", account_id, currency, p, search)
    return cached_call(key, lambda: DashboardEngine(scope).summary(p, account_id, currency, search=search or None).to_dict())


@router.get("/summary/all")
def dashboard_summary_all(
    account_id: Optional[int] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    search: Optional[str] = Query(None, description="Filter by offer name (ILIKE substring)"),
    periods: Optional[str] = Query(None, description="Comma-separated subset of dashboard period keys"),
    scope: TenantScope = Depends(get_scope),
):
    """Return requested dashboard tile periods (all periods by default)."""
    _assert_account_if_present(scope, account_id)
    requested_periods = _requested_periods(periods, _VALID_PERIODS, "dashboard")
    engine = DashboardEngine(scope)
    result = {}
    for k in requested_periods:
        p = get_period(k)
        key = _cache_key(scope, "summary", account_id, currency, p, search)
        result[k] = cached_call(key, lambda p=p: engine.summary(p, account_id, currency, search=search or None).to_dict())
    return result


@router.get("/summary/comparisons")
def dashboard_summary_comparisons(
    account_id: Optional[int] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    search: Optional[str] = Query(None, description="Filter by offer name (ILIKE substring)"),
    periods: Optional[str] = Query(None, description="Comma-separated subset of dashboard period keys"),
    scope: TenantScope = Depends(get_scope),
):
    _assert_account_if_present(scope, account_id)
    requested_periods = _requested_periods(periods, _COMPARISON_PERIODS, "comparison")
    engine = DashboardEngine(scope)
    now_local = datetime.now(timezone.utc).astimezone(WARSAW)
    result = {}
    for k in requested_periods:
        compare_period, compare_label = _comparison_period_for(k, now_local)
        cache_key = _cache_key(scope, "summary", account_id, currency, compare_period, search)
        compare_summary = cached_call(
            cache_key,
            lambda compare_period=compare_period: engine.summary(compare_period, account_id, currency, search=search or None).to_dict(),
        )
        result[k] = {
            "comparison_label": compare_label,
            "comparison_revenue_gross": compare_summary.get("revenue_gross", "0.00"),
            "comparison_revenue_net": compare_summary.get("revenue_net", "0.00"),
        }
    return result


@router.get("/summary/daily")
def dashboard_summary_daily(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    account_id: Optional[int] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    search: Optional[str] = Query(None, description="Filter by offer name (ILIKE substring)"),
    scope: TenantScope = Depends(get_scope),
):
    _assert_account_if_present(scope, account_id)
    try:
        start = datetime.fromisoformat(date_from).date()
        end = datetime.fromisoformat(date_to).date()
    except ValueError as e:
        raise HTTPException(422, f"Invalid date format: {e}") from e
    if end < start:
        raise HTTPException(422, "date_to must be greater than or equal to date_from")
    if (end - start).days > 62:
        raise HTTPException(422, "daily summary range cannot exceed 63 days")

    engine = DashboardEngine(scope)
    result = {}
    current = start
    while current <= end:
        key = current.isoformat()
        period = get_custom_period(key, key)
        cache_key = _cache_key(scope, "summary", account_id, currency, period, search)
        result[key] = cached_call(
            cache_key,
            lambda period=period: engine.summary(period, account_id, currency, search=search or None).to_dict(),
        )
        current += timedelta(days=1)
    return result


@router.get("/product-detail")
def dashboard_product_detail(
    sku_key: str = Query(..., description="SKU key"),
    period: str = Query("current_month"),
    account_id: Optional[int] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    scope: TenantScope = Depends(get_scope),
):
    p = _resolve_period(period, date_from, date_to)
    _assert_account_if_present(scope, account_id)

    def _compute():
        detail = DashboardEngine(scope).product_detail(sku_key, p, account_id, currency)
        return detail.to_dict() if detail else None

    key = _cache_key(scope, f"product_detail:{sku_key}", account_id, currency, p)
    detail_dict = cached_call(key, _compute)
    if not detail_dict:
        raise HTTPException(404, f"SKU '{sku_key}' not found")
    return detail_dict


@router.get("/products")
def dashboard_products(
    period: str = Query("today"),
    account_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    currency: str = Query("PLN", description="Currency code: PLN|CZK|EUR|HUF"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    scope: TenantScope = Depends(get_scope),
):
    p = _resolve_period(period, date_from, date_to)
    _assert_account_if_present(scope, account_id)
    key = _cache_key(scope, "products", account_id, currency, p, search)
    return cached_call(key, lambda: [r.to_dict() for r in DashboardEngine(scope).products(p, account_id, search, currency)])
