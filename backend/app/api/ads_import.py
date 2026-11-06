"""
Allegro Ads cost import endpoint.

Accepts XLSX or CSV files exported from Allegro panel ("Statystyki ofert").
Parses per-offer per-day cost data and stores in allegro_ads_imports table.
Supports idempotent re-import via ON CONFLICT DO UPDATE.
"""
import csv
import io
import logging
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.tenant import TenantScope, get_scope
from app.models.account import Account
from app.models.raw_data import AllegroAdsImport

logger = logging.getLogger("apos.ads_import")

router = APIRouter(prefix="/ads-import", tags=["ads-import"])


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)

# Expected header columns (normalised)
_EXPECTED_HEADERS = {
    "Nazwa kampanii",
    "Nazwa grupy reklam",
    "Tytuł klikniętej oferty",
    "Numer klikniętej oferty",
    "Wyświetlenia",
    "Kliknięcia",
    "Zainteresowanie",
    "CPC(PLN)",
    "CTR",
    "Koszt(PLN)",
    "Koszt brutto",
    "Koszt netto",
    "ROAS(PLN)",
    "Liczba sprzedanych sztuk",
    "Wartość sprzedaży(PLN)",
    "Okres",
}


def _strip_pln(value: str) -> str:
    """Remove 'PLN' suffix, strip whitespace, replace comma decimal separator."""
    return value.replace("PLN", "").replace("%", "").replace(",", ".").strip()


def _parse_decimal(value: str) -> Decimal:
    cleaned = _strip_pln(str(value))
    if not cleaned:
        return Decimal("0")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return Decimal("0")


def _parse_int(value: str) -> int:
    cleaned = _strip_pln(str(value)).split(".")[0].strip()
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except (ValueError, TypeError):
        return 0


def _header_key(value: str) -> str:
    return re.sub(r"[^0-9a-ząćęłńóśźż]+", "", str(value).strip().lower())


def _has_header(values: list[str], *headers: str) -> bool:
    wanted = {_header_key(h) for h in headers}
    return any(_header_key(v) in wanted for v in values)


def _row_value(row: dict, *keys: str) -> str:
    wanted = {_header_key(key) for key in keys}
    for key, value in row.items():
        if _header_key(key) in wanted:
            return value
    return ""


def _first_decimal(row: dict, *keys: str) -> Decimal:
    for key in keys:
        value = _row_value(row, key)
        if str(value).strip():
            return _parse_decimal(value)
    return Decimal("0")


def _parse_date(value: str) -> date:
    """Parse Allegro Ads date values from CSV/XLSX exports."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{value}'")


def _parse_rows_from_csv(content: bytes) -> list[dict]:
    """Parse CSV bytes, trying UTF-8 first then cp1250 fallback."""
    for encoding in ("utf-8-sig", "utf-8", "cp1250"):
        try:
            text_content = content.decode(encoding)
            reader = csv.DictReader(io.StringIO(text_content))
            rows = list(reader)
            if rows and reader.fieldnames:
                # Verify we have expected columns (spot-check a key column)
                fieldnames = [f.strip() for f in reader.fieldnames]
                if _has_header(fieldnames, "Koszt(PLN)", "Koszt brutto", "Koszt brutto PLN", "Okres"):
                    return rows
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError("Cannot decode CSV — tried UTF-8 and cp1250")


def _parse_rows_from_xlsx(content: bytes) -> list[dict]:
    """Parse XLSX bytes using openpyxl."""
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        # Some Allegro exports contain multiple sheets, and the active sheet is not
        # guaranteed to be the one with offer statistics. Scan all worksheets and
        # return the first sheet that contains the expected header row.
        for ws in wb.worksheets:
            if hasattr(ws, "reset_dimensions"):
                ws.reset_dimensions()
            headers = None
            data_rows = []
            for row in ws.iter_rows(values_only=True):
                row_vals = [str(c).strip() if c is not None else "" for c in row]
                if headers is None:
                    if _has_header(row_vals, "Koszt(PLN)", "Koszt brutto", "Koszt brutto PLN", "Okres"):
                        headers = row_vals
                    continue
                if any(v for v in row_vals):
                    data_rows.append(dict(zip(headers, row_vals)))
            if headers is not None:
                return data_rows
    finally:
        wb.close()

    raise ValueError("No header row found in XLSX (expected 'Koszt(PLN)', 'Koszt brutto' or 'Okres' column)")


def _rows_to_records(
    rows: list[dict],
    account_id: int,
    filename: str,
    known_offer_ids: set[str],
    tenant_id: int = 1,
) -> tuple[list[dict], list[str]]:
    """
    Convert raw row dicts to DB record dicts.
    Returns (records, unmatched_offer_ids).
    """
    records: list[dict] = []
    unmatched: list[str] = []

    for raw in rows:
        # Normalise keys (strip whitespace); skip None keys (extra columns past header in CSV)
        row = {
            k.strip(): (v.strip() if isinstance(v, str) else str(v) if v is not None else "")
            for k, v in raw.items()
            if k is not None
        }

        offer_id = row.get("Numer klikniętej oferty", "").strip()
        campaign_name = row.get("Nazwa kampanii", "").strip()
        ad_group = row.get("Nazwa grupy reklam", "").strip()
        period_str = row.get("Okres", "").strip()

        # Skip completely empty rows
        if not offer_id and not period_str:
            continue

        try:
            ad_date = _parse_date(period_str)
        except ValueError as e:
            logger.warning("Skipping row with unparseable date '%s': %s", period_str, e)
            continue

        cost = _first_decimal(row, "Koszt brutto", "Koszt brutto PLN", "Koszt(PLN)")
        cpc = _parse_decimal(row.get("CPC(PLN)", "0"))
        ctr_raw = row.get("CTR", "0")
        ctr = _parse_decimal(ctr_raw) / Decimal("100") if "%" in ctr_raw else _parse_decimal(ctr_raw)
        roas = _parse_decimal(row.get("ROAS(PLN)", "0"))
        impressions = _parse_int(row.get("Wyświetlenia", "0"))
        clicks = _parse_int(row.get("Kliknięcia", "0"))
        interest = _parse_int(row.get("Zainteresowanie", "0"))
        units_sold = _parse_int(row.get("Liczba sprzedanych sztuk", "0"))
        sales_value = _parse_decimal(row.get("Wartość sprzedaży(PLN)", "0"))

        if offer_id and offer_id not in known_offer_ids:
            if offer_id not in unmatched:
                unmatched.append(offer_id)

        records.append({
            "tenant_id": tenant_id,
            "account_id": account_id,
            "offer_id": offer_id or "",
            "campaign_name": campaign_name or "",
            "ad_group": ad_group or None,
            "ad_date": ad_date,
            "impressions": impressions,
            "clicks": clicks,
            "interest": interest,
            "cpc": cpc,
            "ctr": ctr,
            "cost": cost,
            "roas": roas,
            "units_sold_via_ad": units_sold,
            "sales_value": sales_value,
            "imported_at": _now(),
            "imported_filename": filename,
        })

    return records, unmatched


@router.post("/{account_id}")
def upload_ads_import(
    account_id: int,
    file: UploadFile = File(...),
    scope: TenantScope = Depends(get_scope),
):
    """Upload Allegro Ads stats file (CSV or XLSX) and import per-offer per-day costs."""
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)
    if not account.access_token:
        raise HTTPException(status_code=400, detail="Najpierw połącz właściwe konto Allegro, a potem wgraj plik reklam.")

    filename = file.filename or "unknown"
    content = file.file.read()

    # Parse file
    try:
        if filename.lower().endswith(".xlsx"):
            raw_rows = _parse_rows_from_xlsx(content)
        elif filename.lower().endswith(".csv"):
            raw_rows = _parse_rows_from_csv(content)
        else:
            # Try CSV for any other extension
            raw_rows = _parse_rows_from_csv(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}")

    if not raw_rows:
        raise HTTPException(status_code=400, detail="File is empty or has no data rows")

    # Fetch known offer IDs for this account (for unmatched logging)
    known_offers_rows = scope.db.execute(
        text("SELECT offer_id FROM offers_cache WHERE tenant_id = :tenant_id AND account_id = :aid"),
        {"tenant_id": scope.tenant_id, "aid": account_id},
    ).fetchall()
    known_offer_ids = {r[0] for r in known_offers_rows}

    records, unmatched_offers = _rows_to_records(
        raw_rows,
        account_id=account_id,
        filename=filename,
        known_offer_ids=known_offer_ids,
        tenant_id=scope.tenant_id,
    )

    if not records:
        return {
            "rows_parsed": len(raw_rows),
            "rows_imported": 0,
            "rows_skipped": len(raw_rows),
            "unmatched_offers": unmatched_offers,
            "date_range": None,
            "total_cost": "0.00",
        }

    # Upsert using ON CONFLICT DO UPDATE (idempotent)
    stmt = pg_insert(AllegroAdsImport).values(records)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ads_import_key",
        set_={
            "ad_group": stmt.excluded.ad_group,
            "impressions": stmt.excluded.impressions,
            "clicks": stmt.excluded.clicks,
            "interest": stmt.excluded.interest,
            "cpc": stmt.excluded.cpc,
            "ctr": stmt.excluded.ctr,
            "cost": stmt.excluded.cost,
            "roas": stmt.excluded.roas,
            "units_sold_via_ad": stmt.excluded.units_sold_via_ad,
            "sales_value": stmt.excluded.sales_value,
            "imported_at": stmt.excluded.imported_at,
            "imported_filename": stmt.excluded.imported_filename,
        },
    )
    scope.db.execute(stmt)
    scope.db.commit()

    dates = [r["ad_date"] for r in records]
    total_cost = sum(r["cost"] for r in records)

    logger.info(
        "ads_import: account=%d file=%s rows=%d unmatched=%d cost=%.2f",
        account_id, filename, len(records), len(unmatched_offers), total_cost,
    )

    return {
        "rows_parsed": len(raw_rows),
        "rows_imported": len(records),
        "rows_skipped": len(raw_rows) - len(records),
        "unmatched_offers": unmatched_offers,
        "date_range": {
            "from": str(min(dates)),
            "to": str(max(dates)),
        },
        "total_cost": f"{total_cost:.2f}",
    }


@router.get("/{account_id}/list")
def list_ads_imports(
    account_id: int,
    scope: TenantScope = Depends(get_scope),
):
    """Return summary of imported date ranges grouped by filename and import session."""
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)

    rows = scope.db.execute(
        text("""
            SELECT
                imported_filename,
                MAX(imported_at) AS imported_at,
                MIN(ad_date) AS date_from,
                MAX(ad_date) AS date_to,
                COUNT(*) AS rows_count,
                SUM(cost) AS total_cost
            FROM allegro_ads_imports
            WHERE tenant_id = :tenant_id
              AND account_id = :aid
            GROUP BY imported_filename
            ORDER BY MAX(imported_at) DESC
            LIMIT 50
        """),
        {"tenant_id": scope.tenant_id, "aid": account_id},
    ).mappings().all()

    return [
        {
            "imported_filename": r["imported_filename"],
            "imported_at": r["imported_at"].isoformat() if r["imported_at"] else None,
            "date_from": str(r["date_from"]),
            "date_to": str(r["date_to"]),
            "rows_count": r["rows_count"],
            "total_cost": f"{r['total_cost']:.2f}",
        }
        for r in rows
    ]


@router.delete("/{account_id}")
def delete_ads_import(
    account_id: int,
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    scope: TenantScope = Depends(get_scope),
):
    """Delete imported ads data for a date range (for re-import)."""
    account = scope.db.get(Account, account_id)
    scope.assert_owns(account)

    try:
        df = date.fromisoformat(date_from)
        dt = date.fromisoformat(date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date: {e}")

    result = scope.db.execute(
        text("""
            DELETE FROM allegro_ads_imports
            WHERE tenant_id = :tenant_id
              AND account_id = :aid
              AND ad_date BETWEEN :df AND :dt
        """),
        {"tenant_id": scope.tenant_id, "aid": account_id, "df": df, "dt": dt},
    )
    scope.db.commit()
    return {"deleted": result.rowcount, "date_from": str(df), "date_to": str(dt)}
