import pytest
from sqlalchemy import inspect, select, text

from app.models.tenant import Tenant


@pytest.fixture(autouse=True)
def _hosted_deployment_mode(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "hosted")


PERTENANT_TABLES = {
    "accounts",
    "sku_masters",
    "sku_aliases",
    "sku_multiplier_patterns",
    "financial_vaults",
    "encrypted_sku_costs",
    "encrypted_sku_cost_history",
    "account_import_state",
    "orders_raw",
    "billing_raw",
    "order_events_raw",
    "customer_returns_raw",
    "customer_return_items_raw",
    "payment_refunds_raw",
    "payment_refund_line_items_raw",
    "offers_cache",
    "stock_levels",
    "stock_settings",
    "allegro_ads_imports",
    "sync_log",
}

GLOBAL_TABLES_WITHOUT_TENANT_ID = {
    "billing_type_labels",
    "tenants",
    "user_sessions",
    "waitlist_entries",
}


@pytest.mark.contract
def test_tenants_table_has_default_operator(db_session):
    """Migration seeds tenant id=1 as the operator tenant."""
    tenants = db_session.execute(select(Tenant)).scalars().all()
    assert any(t.id == 1 and t.slug == "operator" for t in tenants)


@pytest.mark.contract
def test_all_pertenant_tables_have_tenant_id(db_session):
    """Every operational table has a non-null tenant FK."""
    insp = inspect(db_session.get_bind())
    offenders = []

    for table_name in PERTENANT_TABLES:
        cols = {c["name"]: c for c in insp.get_columns(table_name)}
        if "tenant_id" not in cols:
            offenders.append(f"{table_name}: missing tenant_id")
            continue
        if cols["tenant_id"]["nullable"]:
            offenders.append(f"{table_name}: tenant_id is nullable")
        fks = insp.get_foreign_keys(table_name)
        tenant_fk = [fk for fk in fks if fk["referred_table"] == "tenants"]
        if not tenant_fk:
            offenders.append(f"{table_name}: no FK to tenants")

    assert not offenders, "\n".join(offenders)


@pytest.mark.contract
def test_global_tables_have_no_tenant_id(db_session):
    """Shared dictionary/session/waitlist tables are not tenant-scoped."""
    insp = inspect(db_session.get_bind())

    for table_name in GLOBAL_TABLES_WITHOUT_TENANT_ID:
        cols = {c["name"]: c for c in insp.get_columns(table_name)}
        assert "tenant_id" not in cols, f"{table_name} unexpectedly has tenant_id"


@pytest.mark.contract
def test_users_have_required_tenant_fk(db_session):
    """Users are global auth rows, but each user belongs to one tenant."""
    insp = inspect(db_session.get_bind())
    cols = {c["name"]: c for c in insp.get_columns("users")}
    assert "tenant_id" in cols
    assert not cols["tenant_id"]["nullable"]
    fks = insp.get_foreign_keys("users")
    assert any(fk["referred_table"] == "tenants" for fk in fks)


@pytest.mark.contract
def test_all_existing_data_assigned_to_existing_tenants(db_session):
    """Operational rows belong to real tenants after the multi-tenant migration."""
    tables = [
        "accounts",
        "sku_masters",
        "sku_aliases",
        "financial_vaults",
        "encrypted_sku_costs",
        "orders_raw",
        "billing_raw",
    ]

    for table_name in tables:
        orphaned_rows = db_session.execute(
            text(f"""
                SELECT COUNT(*)
                FROM {table_name} r
                LEFT JOIN tenants tenant ON tenant.id = r.tenant_id
                WHERE tenant.id IS NULL
            """)
        ).scalar()
        assert orphaned_rows == 0, f"{table_name}: {orphaned_rows} rows point at missing tenants"
