import ast
import re
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
API_ROOT = APP_ROOT / "api"
DASHBOARD_ENGINE = APP_ROOT / "services" / "dashboard_engine.py"

PER_TENANT_MODELS = {
    "Account",
    "SkuMaster",
    "SkuAlias",
    "FinancialVault",
    "EncryptedSkuCost",
    "EncryptedSkuCostHistory",
    "OrderRaw",
    "BillingRaw",
    "OfferCache",
    "StockLevel",
    "StockSetting",
    "AllegroAdsImport",
    "SyncLog",
}

PER_TENANT_TABLES = {
    "accounts",
    "sku_masters",
    "sku_aliases",
    "financial_vaults",
    "encrypted_sku_costs",
    "encrypted_sku_cost_history",
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

TENANT_SCOPED_ROUTER_FILES = {
    "accounts.py",
    "ads_import.py",
    "app_settings.py",
    "dashboard.py",
    "financial_vault.py",
    "import_.py",
    "orders.py",
    "products.py",
    "security.py",
    "skus.py",
    "stock.py",
}


def _function_source(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


@pytest.mark.contract
def test_tenant_scoped_routers_use_tenantscope_not_raw_db_dependency():
    offenders: list[str] = []
    for path in sorted(API_ROOT.glob("*.py")):
        if path.name not in TENANT_SCOPED_ROUTER_FILES:
            continue
        source = path.read_text()
        if "Depends(get_db)" in source:
            offenders.append(f"{path.name}: raw Depends(get_db) in tenant-scoped router")
        if "get_scope" not in source:
            offenders.append(f"{path.name}: missing get_scope dependency")
    assert not offenders, "\n".join(offenders)


@pytest.mark.contract
def test_router_db_get_on_pertenant_models_checks_ownership():
    offenders: list[str] = []
    for path in sorted(API_ROOT.glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if path.name == "allegro.py" and node.name == "allegro_callback":
                continue
            body = _function_source(source, node)
            for model in PER_TENANT_MODELS:
                if re.search(rf"(?<!scope\.)\bdb\.get\(\s*{model}\b", body):
                    offenders.append(f"{path.name}:{node.name}: raw db.get({model})")
                if re.search(rf"\bscope\.db\.get\(\s*{model}\b", body):
                    has_ownership_check = "scope.assert_owns(" in body or ".tenant_id" in body
                    if not has_ownership_check:
                        offenders.append(f"{path.name}:{node.name}: scope.db.get({model}) without tenant check")
    assert not offenders, "\n".join(offenders)


@pytest.mark.contract
def test_dashboard_engine_sql_mentions_tenant_filter_near_each_pertenant_table():
    source_lines = DASHBOARD_ENGINE.read_text().splitlines()
    offenders: list[str] = []
    for idx, line in enumerate(source_lines):
        if line.lstrip().startswith("#"):
            continue
        normalized = line.split("#", 1)[0].lower()
        if not any(f"from {table}" in normalized or f"join {table}" in normalized for table in PER_TENANT_TABLES):
            continue
        window = "\n".join(source_lines[idx : idx + 14]).lower()
        if "tenant_id = :tenant_id" not in window and ".tenant_id = :tenant_id" not in window:
            offenders.append(f"{DASHBOARD_ENGINE.name}:{idx + 1}: {line.strip()}")
    assert not offenders, "Per-tenant SQL table references without nearby tenant filter:\n" + "\n".join(offenders)
