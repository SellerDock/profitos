"""Tests for scripts.export_sku_profit_components (read-only export)."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.account import Account
from app.models.raw_data import OrderRaw
from app.models.sku import EncryptedSkuCost, FinancialVault, SkuMaster
from app.models.tenant import Tenant
from scripts.export_sku_profit_components import main

TENANT_A_SLUG = "export-sku-tenant-a"
TENANT_B_SLUG = "export-sku-tenant-b"
DATE_FROM = "2026-08-01"
DATE_TO = "2026-08-31"
IN_PERIOD = datetime(2026, 8, 15, 12, 0, 0)
OUT_OF_PERIOD = datetime(2026, 6, 1, 12, 0, 0)

_COUNT_TABLES = (
    "orders_raw",
    "billing_raw",
    "encrypted_sku_costs",
    "financial_vaults",
    "sku_masters",
    "accounts",
)


def _cleanup(db) -> None:
    tenant_ids = (
        "SELECT id FROM tenants WHERE slug IN "
        f"('{TENANT_A_SLUG}', '{TENANT_B_SLUG}')"
    )
    db.execute(text(f"DELETE FROM encrypted_sku_cost_history WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM encrypted_sku_costs WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM orders_raw WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM offers_cache WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM sku_aliases WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM financial_vaults WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM sku_masters WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM accounts WHERE tenant_id IN ({tenant_ids})"))
    db.execute(text(f"DELETE FROM tenants WHERE slug IN ('{TENANT_A_SLUG}', '{TENANT_B_SLUG}')"))
    db.commit()


@pytest.fixture
def export_fixture(db_session):
    _cleanup(db_session)

    tenant_a = Tenant(name="Export Tenant A", slug=TENANT_A_SLUG, is_active=True)
    tenant_b = Tenant(name="Export Tenant B", slug=TENANT_B_SLUG, is_active=True)
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    acc_a1 = Account(
        tenant_id=tenant_a.id, name="Export A1",
        allegro_client_id="export-client-a1", allegro_client_secret="s", color="#111111",
    )
    acc_a2 = Account(
        tenant_id=tenant_a.id, name="Export A2",
        allegro_client_id="export-client-a2", allegro_client_secret="s", color="#222222",
    )
    acc_b = Account(
        tenant_id=tenant_b.id, name="Export B",
        allegro_client_id="export-client-b", allegro_client_secret="s", color="#333333",
    )
    db_session.add_all([acc_a1, acc_a2, acc_b])
    db_session.flush()

    vault_a = FinancialVault(
        tenant_id=tenant_a.id, scope="global", kdf="argon2id",
        salt="c2FsdC1h", memory_cost=65536, time_cost=3, parallelism=1,
        verify_nonce="dmVyaWZ5LW5vbmNl", verify_ciphertext="dmVyaWZ5LWN0", key_version=1,
    )
    db_session.add(vault_a)
    db_session.flush()

    sku_a1 = SkuMaster(tenant_id=tenant_a.id, sku_key="EXPORT-A1", name="Export A1 SKU", vat_rate=Decimal("23.00"))
    sku_a2 = SkuMaster(tenant_id=tenant_a.id, sku_key="EXPORT-A2", name="Export A2 SKU", vat_rate=Decimal("23.00"))
    sku_nocost = SkuMaster(tenant_id=tenant_a.id, sku_key="EXPORT-NOCOST", name="Export No Cost SKU", vat_rate=Decimal("23.00"))
    sku_b1 = SkuMaster(tenant_id=tenant_b.id, sku_key="EXPORT-B1", name="Export B1 SKU", vat_rate=Decimal("23.00"))
    db_session.add_all([sku_a1, sku_a2, sku_nocost, sku_b1])
    db_session.flush()

    aad_a1 = f"profitos:sku-cost:{sku_a1.id}:current:v1"
    aad_a2 = f"profitos:sku-cost:{sku_a2.id}:current:v1"
    db_session.add_all([
        EncryptedSkuCost(
            tenant_id=tenant_a.id, sku_master_id=sku_a1.id, vault_id=vault_a.id,
            ciphertext="YTEtY2lwaGVy", nonce="YTEtbm9uY2U=", key_version=1, aad_context=aad_a1,
        ),
        EncryptedSkuCost(
            tenant_id=tenant_a.id, sku_master_id=sku_a2.id, vault_id=vault_a.id,
            ciphertext="YTItY2lwaGVy", nonce="YTItbm9uY2U=", key_version=1, aad_context=aad_a2,
        ),
    ])

    order_specs = [
        ("export-in-a1", acc_a1.id, "EXPORT-A1", 2, "100.00", IN_PERIOD),
        ("export-in-nocost", acc_a1.id, "EXPORT-NOCOST", 1, "50.00", IN_PERIOD),
        ("export-in-a2", acc_a2.id, "EXPORT-A2", 1, "200.00", IN_PERIOD),
        ("export-in-b1", acc_b.id, "EXPORT-B1", 1, "300.00", IN_PERIOD),
        ("export-out-a1", acc_a1.id, "EXPORT-A1", 5, "100.00", OUT_OF_PERIOD),
    ]
    for line_item_id, account_id, sku, qty, price, bought_at in order_specs:
        db_session.add(OrderRaw(
            tenant_id=tenant_a.id if account_id != acc_b.id else tenant_b.id,
            line_item_id=line_item_id,
            order_id=f"{line_item_id}-order",
            account_id=account_id,
            offer_id=f"{line_item_id}-offer",
            sku=sku,
            buyer_login="export-buyer",
            quantity=qty,
            unit_price=Decimal(price),
            delivery_amount=Decimal("0.00"),
            currency="PLN",
            status="READY_FOR_PROCESSING",
            bought_at=bought_at,
        ))
    db_session.commit()

    try:
        yield {
            "db": db_session,
            "tenant_a_id": tenant_a.id,
            "tenant_b_id": tenant_b.id,
            "acc_a1_id": acc_a1.id,
            "acc_a2_id": acc_a2.id,
            "acc_b_id": acc_b.id,
            "sku_a1_id": sku_a1.id,
            "sku_a2_id": sku_a2.id,
            "sku_nocost_id": sku_nocost.id,
            "aad_a1": aad_a1,
            "aad_a2": aad_a2,
        }
    finally:
        _cleanup(db_session)


def _argv(tenant_id: int, account_ids: list[int], date_from: str = DATE_FROM, date_to: str = DATE_TO) -> list[str]:
    argv = ["--tenant-id", str(tenant_id), "--date-from", date_from, "--date-to", date_to]
    for account_id in account_ids:
        argv += ["--account-id", str(account_id)]
    return argv


def test_exports_two_accounts_with_envelopes_and_vault(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"], data["acc_a2_id"]]))
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)

    assert payload["format"] == 1
    assert payload["tenant_id"] == data["tenant_a_id"]
    assert payload["date_from"] == DATE_FROM
    assert payload["date_to"] == DATE_TO
    assert payload["currency"] == "PLN"
    assert isinstance(payload["generated_at"], str)
    assert payload["vault"] == {
        "kdf": "argon2id",
        "salt": "c2FsdC1h",
        "memory_cost": 65536,
        "time_cost": 3,
        "parallelism": 1,
        "verify_nonce": "dmVyaWZ5LW5vbmNl",
        "verify_ciphertext": "dmVyaWZ5LWN0",
        "key_version": 1,
    }

    rows = {(r["account_id"], r["sku_key"]): r for r in payload["rows"]}
    a1 = rows[(data["acc_a1_id"], "EXPORT-A1")]
    assert a1["units_sold"] == 2
    assert a1["encrypted_cost"] == {
        "ciphertext": "YTEtY2lwaGVy",
        "nonce": "YTEtbm9uY2U=",
        "key_version": 1,
        "aad_context": data["aad_a1"],
    }

    db_cost = (
        data["db"].query(EncryptedSkuCost)
        .filter(EncryptedSkuCost.sku_master_id == data["sku_a1_id"])
        .one()
    )
    assert a1["cost_updated_at"] == db_cost.updated_at.isoformat()
    # cogs_units and money fields are decimal strings straight from the engine.
    assert a1["cogs_units"] == "2.00"
    assert isinstance(a1["revenue_net"], str)
    assert isinstance(a1["total_allegro_net"], str)
    assert isinstance(a1["price_adjust_cost"], str)
    assert isinstance(a1["campaign_bonus"], str)
    assert isinstance(a1["refund_commission"], str)
    assert isinstance(a1["commission_refunds_amount"], str)
    assert isinstance(a1["cost_multiplier"], str)

    a2 = rows[(data["acc_a2_id"], "EXPORT-A2")]
    assert a2["units_sold"] == 1
    assert a2["encrypted_cost"]["ciphertext"] == "YTItY2lwaGVy"


def test_account_from_other_tenant_exits_2_with_empty_stdout(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_b_id"]]))
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert "tenant" in captured.err.lower()


def test_unknown_account_exits_2_with_empty_stdout(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [999_999_999]))
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""


def test_date_from_after_date_to_errors(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"]], date_from="2026-09-01", date_to="2026-08-31"))
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""
    assert captured.err != ""


def test_invalid_date_format_errors(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"]], date_from="2026/08/01"))
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == ""


def test_sku_without_cost_has_null_envelope_and_timestamp(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"]]))
    payload = json.loads(capsys.readouterr().out)

    rows = {(r["account_id"], r["sku_key"]): r for r in payload["rows"]}
    nocost = rows[(data["acc_a1_id"], "EXPORT-NOCOST")]
    assert nocost["units_sold"] == 1
    assert nocost["encrypted_cost"] is None
    assert nocost["cost_updated_at"] is None
    # No invented zero: the engine's own decimal string is preserved.
    assert nocost["revenue_net"] == "40.65"


def test_sales_outside_period_are_not_counted(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"]]))
    payload = json.loads(capsys.readouterr().out)

    rows = {(r["account_id"], r["sku_key"]): r for r in payload["rows"]}
    assert rows[(data["acc_a1_id"], "EXPORT-A1")]["units_sold"] == 2


def test_tenant_without_vault_returns_null_vault(export_fixture, capsys):
    data = export_fixture
    code = main(_argv(data["tenant_b_id"], [data["acc_b_id"]]))
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["vault"] is None
    rows = {(r["account_id"], r["sku_key"]): r for r in payload["rows"]}
    assert (data["acc_b_id"], "EXPORT-B1") in rows
    assert rows[(data["acc_b_id"], "EXPORT-B1")]["encrypted_cost"] is None


def test_script_does_not_write_to_database(export_fixture, capsys):
    data = export_fixture
    db = data["db"]

    def snapshot() -> dict:
        counts = {}
        for table in _COUNT_TABLES:
            counts[table] = db.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id IN (:a, :b)"),
                {"a": data["tenant_a_id"], "b": data["tenant_b_id"]},
            ).scalar()
        return counts

    before = snapshot()
    code = main(_argv(data["tenant_a_id"], [data["acc_a1_id"], data["acc_a2_id"]]))
    capsys.readouterr()
    assert code == 0
    assert snapshot() == before
