"""
Tests for Allegro Ads import: parsing, upsert, dashboard COALESCE logic.

test_parse_csv_basic              — parse 5 synthetic CSV rows, verify values
test_parse_xlsx_basic             — parse XLSX built in-memory, verify values
test_parse_cp1250_fallback        — CSV encoded as cp1250 with Polish chars decodes correctly
test_idempotent_reimport          — same file imported twice → no duplicate DB rows
test_dashboard_uses_imported      — imported data → summary ads_cost reflects it, source="imported"
test_dashboard_falls_back_to_nsp  — no imports → summary ads_cost uses NSP billing, source="billing"
test_unmatched_offer_logged       — offer_id not in offers_cache still imports, appears in unmatched_offers
"""
import io
import os
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from tests.tenant_helpers import operator_scope

_DB_URL = (
    f"postgresql+psycopg2://"
    f"{os.environ.get('POSTGRES_USER', 'apos_user')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'apos_pass')}@"
    f"{os.environ.get('POSTGRES_HOST', 'apos-db')}/"
    f"{os.environ.get('POSTGRES_DB', 'apos_db')}"
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _engine():
    return create_engine(_DB_URL)


def _make_csv_bytes(rows: list[dict], encoding: str = "utf-8") -> bytes:
    """Build a CSV bytes object from list of dicts matching the Allegro Ads format."""
    import csv as _csv_mod

    fieldnames = [
        "Nazwa kampanii", "Nazwa grupy reklam", "Tytuł klikniętej oferty",
        "Numer klikniętej oferty", "Wyświetlenia", "Kliknięcia", "Zainteresowanie",
        "CPC(PLN)", "CTR", "Koszt(PLN)", "ROAS(PLN)", "Liczba sprzedanych sztuk",
        "Wartość sprzedaży(PLN)", "Okres",
    ]
    buf = io.StringIO()
    writer = _csv_mod.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "Nazwa kampanii": r.get("campaign", "TestCampaign"),
            "Nazwa grupy reklam": r.get("group", "TestGroup"),
            "Tytuł klikniętej oferty": r.get("title", "Test Offer"),
            "Numer klikniętej oferty": r.get("offer_id", "12345678"),
            "Wyświetlenia": r.get("impressions", 100),
            "Kliknięcia": r.get("clicks", 10),
            "Zainteresowanie": r.get("interest", 5),
            "CPC(PLN)": r.get("cpc", "0,50 PLN"),
            "CTR": r.get("ctr", "10,00%"),
            "Koszt(PLN)": r.get("cost", "5,00 PLN"),
            "ROAS(PLN)": r.get("roas", "25,00 PLN"),
            "Liczba sprzedanych sztuk": r.get("units", 2),
            "Wartość sprzedaży(PLN)": r.get("sales", "125,00 PLN"),
            "Okres": r.get("period", "21-04-2026"),
        })
    return buf.getvalue().encode(encoding)


def _synthetic_rows() -> list[dict]:
    return [
        {"offer_id": "11111111", "cost": "1,15 PLN", "period": "01-04-2026", "impressions": 200, "clicks": 20},
        {"offer_id": "22222222", "cost": "2,50 PLN", "period": "02-04-2026", "impressions": 300, "clicks": 30},
        {"offer_id": "33333333", "cost": "0,80 PLN", "period": "01-04-2026", "impressions": 50,  "clicks": 5},
        {"offer_id": "44444444", "cost": "3,00 PLN", "period": "03-04-2026", "impressions": 400, "clicks": 40},
        {"offer_id": "55555555", "cost": "0,55 PLN", "period": "04-04-2026", "impressions": 100, "clicks": 10},
    ]


# ── Pure parsing tests (no DB) ─────────────────────────────────────────────────

def test_parse_csv_basic():
    """5 synthetic CSV rows are parsed with correct field values."""
    from app.api.ads_import import _parse_rows_from_csv, _rows_to_records

    rows_data = _synthetic_rows()
    csv_bytes = _make_csv_bytes(rows_data)
    raw_rows = _parse_rows_from_csv(csv_bytes)
    assert len(raw_rows) == 5

    records, unmatched = _rows_to_records(raw_rows, account_id=1, filename="test.csv", known_offer_ids=set())

    assert len(records) == 5
    assert records[0]["offer_id"] == "11111111"
    assert records[0]["cost"] == Decimal("1.15")
    assert records[0]["ad_date"] == date(2026, 4, 1)
    assert records[0]["impressions"] == 200
    assert records[0]["clicks"] == 20

    assert records[1]["offer_id"] == "22222222"
    assert records[1]["cost"] == Decimal("2.50")

    # All offer_ids not in known set → all unmatched
    assert set(unmatched) == {"11111111", "22222222", "33333333", "44444444", "55555555"}


def test_parse_xlsx_basic():
    """XLSX built in-memory with openpyxl is parsed with correct values."""
    from app.api.ads_import import _parse_rows_from_xlsx, _rows_to_records

    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [
        "Nazwa kampanii", "Nazwa grupy reklam", "Tytuł klikniętej oferty",
        "Numer klikniętej oferty", "Wyświetlenia", "Kliknięcia", "Zainteresowanie",
        "CPC(PLN)", "CTR", "Koszt(PLN)", "ROAS(PLN)", "Liczba sprzedanych sztuk",
        "Wartość sprzedaży(PLN)", "Okres",
    ]
    ws.append(headers)
    ws.append([
        "CampaignA", "GroupA", "Offer Title",
        "99887766", 150, 15, 7,
        "0,30 PLN", "10,00%", "4,50 PLN", "30,00 PLN", 3,
        "135,00 PLN", "15-04-2026",
    ])
    ws.append([
        "CampaignB", "GroupB", "Another Offer",
        "11223344", 50, 5, 2,
        "0,80 PLN", "10,00%", "4,00 PLN", "20,00 PLN", 1,
        "80,00 PLN", "16-04-2026",
    ])

    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    raw_rows = _parse_rows_from_xlsx(xlsx_bytes)
    assert len(raw_rows) == 2

    records, _ = _rows_to_records(raw_rows, account_id=1, filename="test.xlsx", known_offer_ids={"99887766", "11223344"})
    assert len(records) == 2
    assert records[0]["offer_id"] == "99887766"
    assert records[0]["cost"] == Decimal("4.50")
    assert records[0]["ad_date"] == date(2026, 4, 15)
    assert records[1]["offer_id"] == "11223344"
    assert records[1]["cost"] == Decimal("4.00")
    assert records[1]["ad_date"] == date(2026, 4, 16)


def test_parse_xlsx_accepts_excel_date_cell():
    """XLSX rows with a native Excel date in Okres are imported, not silently skipped."""
    from app.api.ads_import import _parse_rows_from_xlsx, _rows_to_records

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Nazwa kampanii", "Nazwa grupy reklam", "Tytuł klikniętej oferty",
        "Numer klikniętej oferty", "Wyświetlenia", "Kliknięcia", "Zainteresowanie",
        "CPC(PLN)", "CTR", "Koszt(PLN)", "ROAS(PLN)", "Liczba sprzedanych sztuk",
        "Wartość sprzedaży(PLN)", "Okres",
    ])
    ws.append([
        "CampaignDate", "GroupDate", "Offer Date",
        "DATE001", 10, 1, 0,
        "1,00 PLN", "10,00%", "1,00 PLN", "0,00 PLN", 0,
        "0,00 PLN", date(2026, 4, 17),
    ])

    buf = io.BytesIO()
    wb.save(buf)

    raw_rows = _parse_rows_from_xlsx(buf.getvalue())
    records, _ = _rows_to_records(raw_rows, account_id=1, filename="date-cell.xlsx", known_offer_ids={"DATE001"})

    assert len(records) == 1
    assert records[0]["offer_id"] == "DATE001"
    assert records[0]["ad_date"] == date(2026, 4, 17)


def test_parse_xlsx_scans_all_sheets_for_offer_stats():
    """Multi-sheet exports are accepted even when the active sheet has no ads headers."""
    from app.api.ads_import import _parse_rows_from_xlsx, _rows_to_records

    wb = openpyxl.Workbook()
    ws_blank = wb.active
    ws_blank.title = "Podsumowanie"
    ws_blank.append(["To nie jest tabela statystyk"])

    ws = wb.create_sheet("Statystyki ofert")
    ws.append([
        "Nazwa kampanii", "Nazwa grupy reklam", "Tytuł klikniętej oferty",
        "Numer klikniętej oferty", "Wyświetlenia", "Kliknięcia", "Zainteresowanie",
        "CPC(PLN)", "CTR", "Koszt(PLN)", "ROAS(PLN)", "Liczba sprzedanych sztuk",
        "Wartość sprzedaży(PLN)", "Okres",
    ])
    ws.append([
        "CampaignSheet", "GroupSheet", "Offer Sheet",
        "SHEET001", 19, 1, 1,
        "0,99 PLN", "5,26%", "0,99 PLN", "85,85 PLN", 1,
        "84,99 PLN", "19-04-2026",
    ])

    buf = io.BytesIO()
    wb.save(buf)

    raw_rows = _parse_rows_from_xlsx(buf.getvalue())
    records, _ = _rows_to_records(raw_rows, account_id=1, filename="multi-sheet.xlsx", known_offer_ids={"SHEET001"})

    assert len(records) == 1
    assert records[0]["offer_id"] == "SHEET001"
    assert records[0]["cost"] == Decimal("0.99")
    assert records[0]["ad_date"] == date(2026, 4, 19)


def test_parse_cp1250_fallback():
    """CSV encoded as cp1250 with Polish characters decodes correctly via fallback."""
    from app.api.ads_import import _parse_rows_from_csv, _rows_to_records

    rows_data = [{"offer_id": "99990001", "cost": "2,00 PLN", "period": "10-04-2026",
                  "campaign": "Kampania Wiosenna", "title": "Oferta Łódź"}]
    csv_bytes = _make_csv_bytes(rows_data, encoding="cp1250")

    # Should NOT raise even though it's not UTF-8
    raw_rows = _parse_rows_from_csv(csv_bytes)
    assert len(raw_rows) == 1

    records, _ = _rows_to_records(raw_rows, account_id=1, filename="test_cp1250.csv", known_offer_ids=set())
    assert len(records) == 1
    assert records[0]["offer_id"] == "99990001"
    assert records[0]["cost"] == Decimal("2.00")
    assert records[0]["ad_date"] == date(2026, 4, 10)
    # Campaign name with Polish chars should be present
    assert "Kampania" in records[0]["campaign_name"]


def test_parse_prefers_gross_cost_column_from_new_allegro_export():
    """New Allegro exports use 'Koszt brutto'; store that gross value for VAT-mode display."""
    from app.api.ads_import import _rows_to_records

    rows = [{
        "Nazwa kampanii": "CampaignGross",
        "Nazwa grupy reklam": "GroupGross",
        "Tytuł klikniętej oferty": "Offer Gross",
        "Numer klikniętej oferty": "GROSS001",
        "Wyświetlenia": "10",
        "Kliknięcia": "2",
        "Koszt brutto": "12,30 PLN",
        "Koszt netto": "10,00 PLN",
        "Okres": "20-05-2026",
    }]

    records, unmatched = _rows_to_records(
        rows,
        account_id=1,
        filename="gross.xlsx",
        known_offer_ids={"GROSS001"},
    )

    assert unmatched == []
    assert records[0]["cost"] == Decimal("12.30")
    assert records[0]["offer_id"] == "GROSS001"


def test_parse_gross_cost_column_with_currency_suffix_and_whitespace():
    """Header matching tolerates Allegro XLSX variants like 'Koszt brutto (PLN)'."""
    from app.api.ads_import import _rows_to_records

    rows = [{
        "Nazwa kampanii": "CampaignGross",
        "Numer klikniętej oferty": "GROSS002",
        "Koszt\u00a0brutto (PLN)": "24,60",
        "Koszt netto (PLN)": "20,00",
        "Okres": "20-05-2026",
    }]

    records, _ = _rows_to_records(
        rows,
        account_id=1,
        filename="gross-variant.xlsx",
        known_offer_ids={"GROSS002"},
    )

    assert records[0]["cost"] == Decimal("24.60")


def test_unmatched_offer_logged_but_imported():
    """Offer_id not in offers_cache is still imported; it appears in unmatched_offers list."""
    from app.api.ads_import import _parse_rows_from_csv, _rows_to_records

    rows_data = [
        {"offer_id": "KNOWN001", "cost": "1,00 PLN", "period": "05-04-2026"},
        {"offer_id": "UNKNOWN999", "cost": "2,00 PLN", "period": "05-04-2026"},
    ]
    csv_bytes = _make_csv_bytes(rows_data)
    raw_rows = _parse_rows_from_csv(csv_bytes)
    records, unmatched = _rows_to_records(
        raw_rows, account_id=1, filename="test.csv", known_offer_ids={"KNOWN001"}
    )

    # Both rows should be imported
    assert len(records) == 2
    # Only the unknown one is in the unmatched list
    assert "UNKNOWN999" in unmatched
    assert "KNOWN001" not in unmatched


# ── DB-dependent tests ─────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db():
    engine = _engine()
    with Session(engine) as session:
        yield session


def _ensure_test_account(db: Session) -> int:
    """Return account id=1 or insert a dummy if missing."""
    db.execute(text("""
        INSERT INTO tenants (id, name, slug, is_active)
        VALUES (1, 'Operator', 'operator', true)
        ON CONFLICT (id) DO NOTHING
    """))
    row = db.execute(text("SELECT id FROM accounts WHERE id = 1")).fetchone()
    if row:
        db.commit()
        return 1
    db.execute(text("""
        INSERT INTO accounts (id, tenant_id, name, allegro_client_id, allegro_client_secret, color)
        VALUES (1, 1, 'Test Account', 'dummy_id', 'dummy_secret', '#6366f1')
        ON CONFLICT (id) DO NOTHING
    """))
    db.commit()
    return 1


def _cleanup_ads_imports(db: Session, account_id: int):
    db.execute(text("DELETE FROM allegro_ads_imports WHERE account_id = :aid"), {"aid": account_id})
    db.execute(text("DELETE FROM billing_raw WHERE entry_id = 'ads-import-adjustment-nsp'"))
    db.commit()


def test_idempotent_reimport(db: Session):
    """Importing the same file twice results in no duplicate rows."""
    from app.api.ads_import import _parse_rows_from_csv, _rows_to_records
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.raw_data import AllegroAdsImport

    account_id = _ensure_test_account(db)
    _cleanup_ads_imports(db, account_id)

    rows_data = [
        {"offer_id": "IDEM001", "cost": "1,00 PLN", "period": "06-04-2026", "campaign": "CampaignX"},
        {"offer_id": "IDEM002", "cost": "2,00 PLN", "period": "06-04-2026", "campaign": "CampaignX"},
    ]
    csv_bytes = _make_csv_bytes(rows_data)

    def _do_import():
        raw_rows = _parse_rows_from_csv(csv_bytes)
        records, _ = _rows_to_records(raw_rows, account_id=account_id, filename="idem.csv", known_offer_ids=set())
        stmt = pg_insert(AllegroAdsImport).values(records)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ads_import_key",
            set_={
                "cost": stmt.excluded.cost,
                "imported_at": stmt.excluded.imported_at,
                "imported_filename": stmt.excluded.imported_filename,
            },
        )
        db.execute(stmt)
        db.commit()

    _do_import()
    _do_import()  # second time should not add rows

    count = db.execute(
        text("SELECT COUNT(*) FROM allegro_ads_imports WHERE account_id = :aid AND offer_id LIKE 'IDEM%'"),
        {"aid": account_id},
    ).scalar()
    assert count == 2, f"Expected 2 rows, got {count}"

    _cleanup_ads_imports(db, account_id)


def test_dashboard_uses_imported_when_available(db: Session):
    """When imported data exists for date range, summary.ads_cost reflects it and source='imported'."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.raw_data import AllegroAdsImport
    from app.services.dashboard_engine import DashboardEngine, get_custom_period

    account_id = _ensure_test_account(db)
    _cleanup_ads_imports(db, account_id)

    # Insert a synthetic imported row for 2026-04-07
    test_cost = Decimal("12.34")
    stmt = pg_insert(AllegroAdsImport).values([{
        "tenant_id": 1,
        "account_id": account_id,
        "offer_id": "DASH001",
        "campaign_name": "TestCampaign",
        "ad_group": None,
        "ad_date": date(2026, 4, 7),
        "impressions": 100,
        "clicks": 10,
        "interest": 5,
        "cpc": Decimal("0.50"),
        "ctr": Decimal("0.10"),
        "cost": test_cost,
        "roas": Decimal("10.00"),
        "units_sold_via_ad": 2,
        "sales_value": Decimal("50.00"),
        "imported_at": datetime.utcnow(),
        "imported_filename": "test_dash.csv",
    }])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ads_import_key",
        set_={"cost": stmt.excluded.cost, "imported_at": stmt.excluded.imported_at},
    )
    db.execute(stmt)
    db.commit()

    period = get_custom_period("2026-04-07", "2026-04-07")
    summary = DashboardEngine(operator_scope(db)).summary(period, account_id=account_id)

    assert summary.ads_cost_source == "imported", f"Expected 'imported', got '{summary.ads_cost_source}'"
    imported_ads = Decimal(summary.ads_cost)
    assert imported_ads == test_cost, f"Expected {test_cost}, got {imported_ads}"

    _cleanup_ads_imports(db, account_id)


def test_dashboard_splits_imported_ads_and_nsp_adjustment(db: Session):
    """Imported offer Ads are shown separately and NSP becomes the billing reconciliation."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models.raw_data import AllegroAdsImport, BillingRaw
    from app.services.dashboard_engine import DashboardEngine, get_custom_period

    account_id = _ensure_test_account(db)
    _cleanup_ads_imports(db, account_id)
    db.execute(text("DELETE FROM billing_raw WHERE entry_id = 'ads-import-adjustment-nsp'"))

    db.add(BillingRaw(
        tenant_id=1,
        entry_id="ads-import-adjustment-nsp",
        account_id=account_id,
        offer_id=None,
        order_id=None,
        type="NSP",
        amount=Decimal("-12.34"),
        currency="PLN",
        occurred_at=datetime(2026, 4, 10, 3, 0, 0),
        ads_service_date=date(2026, 4, 7),
    ))
    stmt = pg_insert(AllegroAdsImport).values([{
        "tenant_id": 1,
        "account_id": account_id,
        "offer_id": "DASH-IMP-001",
        "campaign_name": "TestCampaign",
        "ad_group": None,
        "ad_date": date(2026, 4, 7),
        "impressions": 100,
        "clicks": 10,
        "interest": 5,
        "cpc": Decimal("0.50"),
        "ctr": Decimal("0.10"),
        "cost": Decimal("10.00"),
        "roas": Decimal("10.00"),
        "units_sold_via_ad": 2,
        "sales_value": Decimal("50.00"),
        "imported_at": datetime.utcnow(),
        "imported_filename": "test_dash.csv",
    }])
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ads_import_key",
        set_={"cost": stmt.excluded.cost, "imported_at": stmt.excluded.imported_at},
    )
    db.execute(stmt)
    db.commit()

    period = get_custom_period("2026-04-07", "2026-04-07")
    summary = DashboardEngine(operator_scope(db)).summary(period, account_id=account_id)

    assert summary.ads_cost == "12.34"
    assert summary.ads_imported_cost == "10.00"
    assert summary.ads_nsp_adjustment_cost == "2.34"
    assert summary.ads_cost_source == "mixed"

    db.execute(text("DELETE FROM billing_raw WHERE entry_id = 'ads-import-adjustment-nsp'"))
    _cleanup_ads_imports(db, account_id)


def test_dashboard_falls_back_to_nsp_when_no_imports(db: Session):
    """When no imported data, summary uses NSP billing (source='billing')."""
    from app.services.dashboard_engine import DashboardEngine, get_custom_period

    account_id = _ensure_test_account(db)
    _cleanup_ads_imports(db, account_id)

    # Date range with no imported data
    period = get_custom_period("2020-01-01", "2020-01-01")
    summary = DashboardEngine(operator_scope(db)).summary(period, account_id=account_id)

    assert summary.ads_cost_source == "billing", f"Expected 'billing', got '{summary.ads_cost_source}'"


def test_upload_rejects_file_over_limit():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from fastapi import HTTPException, UploadFile
    from app.api.ads_import import upload_ads_import
    scope = SimpleNamespace(db=MagicMock(), assert_owns=MagicMock())
    scope.db.get.return_value = SimpleNamespace(access_token="token")
    upload = UploadFile(file=io.BytesIO(b"x" * (10 * 1024 * 1024 + 1)), filename="ads.csv")
    with pytest.raises(HTTPException) as error:
        upload_ads_import(1, upload, scope)
    assert error.value.status_code == 413
