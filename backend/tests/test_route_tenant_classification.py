"""Every API route must be classified; every tenant-data route must have an isolation test.

Adding a new route without updating ROUTE_CLASSIFICATION (and, for "tenant"
routes, TENANT_ISOLATION_TESTS) fails this test. This keeps contributors from
shipping endpoints that were never checked for cross-tenant access.

Categories:
  public   – no login, no tenant data
  self     – concerns only the logged-in user / session
  operator – SaaS operator panel (require_operator)
  global   – shared reference data, identical for every tenant
  tenant   – company data; MUST have an isolation test
"""
from fastapi.routing import APIRoute

from app.main import app
import tests.test_tenant_isolation_endpoints as isolation

P, S, O, G, T = "public", "self", "operator", "global", "tenant"

ROUTE_CLASSIFICATION: dict[tuple[str, str], str] = {
    ("GET", "/health"): P,
    ("GET", "/api/v1/public/config"): P,
    ("POST", "/api/v1/auth/login"): P,
    ("POST", "/api/v1/auth/refresh"): P,
    ("POST", "/api/v1/auth/totp/enroll"): P,
    ("GET", "/api/v1/auth/activate/{token}"): P,
    ("POST", "/api/v1/auth/activate"): P,
    ("POST", "/api/v1/auth/waitlist"): P,
    ("GET", "/api/v1/app/manifest"): P,
    ("GET", "/api/v1/app/download"): P,
    ("HEAD", "/api/v1/app/download"): P,
    ("GET", "/api/v1/allegro/callback"): P,
    ("GET", "/api/v1/accounts/allegro/callback"): P,
    ("GET", "/api/v1/security/crypto-proof"): P,
    ("POST", "/api/v1/auth/totp/setup"): S,
    ("POST", "/api/v1/auth/totp/disable"): S,
    ("POST", "/api/v1/auth/logout"): S,
    ("POST", "/api/v1/auth/device/logout"): S,
    ("GET", "/api/v1/auth/devices"): S,
    ("DELETE", "/api/v1/auth/devices/{device_id}"): S,
    ("GET", "/api/v1/auth/me"): S,
    ("POST", "/api/v1/auth/me/delete"): S,
    ("GET", "/api/v1/admin/waitlist"): O,
    ("POST", "/api/v1/admin/waitlist/{entry_id}/approve"): O,
    ("POST", "/api/v1/admin/waitlist/{entry_id}/reject"): O,
    ("GET", "/api/v1/admin/subscriptions"): O,
    ("POST", "/api/v1/admin/subscriptions/{subscription_id}/invoice"): O,
    ("POST", "/api/v1/admin/subscriptions/{subscription_id}/manual-invoice"): O,
    ("POST", "/api/v1/admin/subscriptions/{subscription_id}/mark-paid"): O,
    ("POST", "/api/v1/admin/subscriptions/{subscription_id}/cancel"): O,
    ("GET", "/api/v1/admin/tenants"): O,
    ("GET", "/api/v1/admin/revenue"): O,
    ("POST", "/api/v1/admin/tenants/{tenant_id}/deactivate"): O,
    ("POST", "/api/v1/admin/tenants/{tenant_id}/reactivate"): O,
    ("DELETE", "/api/v1/admin/tenants/{tenant_id}"): O,
    ("GET", "/api/v1/admin/system-health"): O,
    ("GET", "/api/v1/billing/types"): G,
    ("POST", "/api/v1/sku-mapping/test"): G,
    ("GET", "/api/v1/accounts/"): T,
    ("POST", "/api/v1/accounts/"): T,
    ("GET", "/api/v1/accounts/{account_id}"): T,
    ("PATCH", "/api/v1/accounts/{account_id}"): T,
    ("DELETE", "/api/v1/accounts/{account_id}"): T,
    ("GET", "/api/v1/app-settings/"): T,
    ("PUT", "/api/v1/app-settings/"): T,
    ("POST", "/api/v1/ads-import/{account_id}"): T,
    ("GET", "/api/v1/ads-import/{account_id}/list"): T,
    ("DELETE", "/api/v1/ads-import/{account_id}"): T,
    ("GET", "/api/v1/sku-masters/"): T,
    ("POST", "/api/v1/sku-masters/"): T,
    ("GET", "/api/v1/sku-masters/{sku_id}"): T,
    ("PATCH", "/api/v1/sku-masters/{sku_id}"): T,
    ("DELETE", "/api/v1/sku-masters/{sku_id}"): T,
    ("GET", "/api/v1/sku-aliases/"): T,
    ("POST", "/api/v1/sku-aliases/"): T,
    ("GET", "/api/v1/sku-aliases/{alias_id}"): T,
    ("PATCH", "/api/v1/sku-aliases/{alias_id}"): T,
    ("DELETE", "/api/v1/sku-aliases/{alias_id}"): T,
    ("GET", "/api/v1/allegro/auth"): T,
    ("GET", "/api/v1/allegro/auth/{account_id}"): T,
    ("GET", "/api/v1/allegro/orders/{account_id}"): T,
    ("GET", "/api/v1/allegro/billing/{account_id}"): T,
    ("GET", "/api/v1/allegro/offers/{account_id}"): T,
    ("GET", "/api/v1/billing/profile"): T,
    ("PUT", "/api/v1/billing/profile"): T,
    ("GET", "/api/v1/billing/vat-lookup/{nip}"): T,
    ("GET", "/api/v1/billing/subscription"): T,
    ("POST", "/api/v1/billing/subscription/request"): T,
    ("POST", "/api/v1/billing/subscription/{subscription_id}/cancel"): T,
    ("POST", "/api/v1/billing/paid-plan/accept"): T,
    ("POST", "/api/v1/import/sync/{account_id}"): T,
    ("GET", "/api/v1/import/status"): T,
    ("POST", "/api/v1/integrations/profit-by-ean"): T,
    ("POST", "/api/v1/sku/auto-import/{account_id}"): T,
    ("GET", "/api/v1/products/"): T,
    ("PATCH", "/api/v1/products/{sku_id}"): T,
    ("POST", "/api/v1/products/{sku_id}/cost-history"): T,
    ("DELETE", "/api/v1/products/{sku_id}/cost-history/{history_id}"): T,
    ("POST", "/api/v1/products/import-costs"): T,
    ("GET", "/api/v1/dashboard/debug/billing-types"): T,
    ("GET", "/api/v1/dashboard/summary"): T,
    ("GET", "/api/v1/dashboard/summary/all"): T,
    ("GET", "/api/v1/dashboard/summary/comparisons"): T,
    ("GET", "/api/v1/dashboard/summary/daily"): T,
    ("GET", "/api/v1/dashboard/product-detail"): T,
    ("GET", "/api/v1/dashboard/products"): T,
    ("GET", "/api/v1/financial-vault/status"): T,
    ("POST", "/api/v1/financial-vault/setup"): T,
    ("GET", "/api/v1/security/encrypted-cost-export/{sku_master_id}"): T,
    ("GET", "/api/v1/stock/settings"): T,
    ("PUT", "/api/v1/stock/settings"): T,
    ("GET", "/api/v1/stock/"): T,
    ("PUT", "/api/v1/stock/{sku_id}"): T,
    ("POST", "/api/v1/stock/auto-import"): T,
    ("GET", "/api/v1/orders/recent"): T,
    ("GET", "/api/v1/sku-mapping/patterns"): T,
    ("POST", "/api/v1/sku-mapping/patterns"): T,
    ("PATCH", "/api/v1/sku-mapping/patterns/{pattern_id}"): T,
    ("DELETE", "/api/v1/sku-mapping/patterns/{pattern_id}"): T,
    ("POST", "/api/v1/sku-mapping/reapply"): T,
    ("GET", "/api/v1/sku-mapping/unmatched-offers"): T,
    ("POST", "/api/v1/support/ticket"): T,
}

# Tenant route -> isolation test(s): "module:function" or a function name in
# tests/test_tenant_isolation_endpoints.py. Empty list = NOT YET COVERED.
TENANT_ISOLATION_TESTS: dict[tuple[str, str], list[str]] = {
    ("GET", "/api/v1/accounts/"): ["test_accounts_list_only_returns_own_tenant"],
    ("POST", "/api/v1/accounts/"): ["test_create_account_belongs_to_current_tenant"],
    ("GET", "/api/v1/accounts/{account_id}"): ["test_account_detail_404_for_foreign_tenant"],
    ("PATCH", "/api/v1/accounts/{account_id}"): ["test_patch_foreign_account_returns_404_and_does_not_modify"],
    ("DELETE", "/api/v1/accounts/{account_id}"): ["test_delete_foreign_account_preserves_database_row"],
    ("GET", "/api/v1/app-settings/"): ["test_settings_read_and_write_are_tenant_scoped"],
    ("PUT", "/api/v1/app-settings/"): ["test_settings_read_and_write_are_tenant_scoped"],
    ("POST", "/api/v1/ads-import/{account_id}"): ["test_ads_upload_foreign_account_rejected_and_unchanged"],
    ("GET", "/api/v1/ads-import/{account_id}/list"): ["test_ads_import_list_foreign_account_returns_404"],
    ("DELETE", "/api/v1/ads-import/{account_id}"): ["test_ads_import_delete_foreign_account_returns_404"],
    ("GET", "/api/v1/sku-masters/"): ["test_sku_masters_list_only_current_tenant"],
    ("POST", "/api/v1/sku-masters/"): ["test_create_sku_master_belongs_to_current_tenant"],
    ("GET", "/api/v1/sku-masters/{sku_id}"): ["test_sku_master_404_for_foreign_tenant"],
    ("PATCH", "/api/v1/sku-masters/{sku_id}"): ["test_patch_foreign_sku_master_returns_404"],
    ("DELETE", "/api/v1/sku-masters/{sku_id}"): ["test_delete_foreign_sku_master_returns_404"],
    ("GET", "/api/v1/sku-aliases/"): ["test_sku_alias_list_only_returns_own_tenant"],
    ("POST", "/api/v1/sku-aliases/"): [
        "test_create_sku_alias_with_foreign_sku_returns_404",
        "test_create_sku_alias_with_foreign_account_returns_404",
    ],
    ("GET", "/api/v1/sku-aliases/{alias_id}"): ["test_foreign_sku_alias_rejected_and_unchanged"],
    ("PATCH", "/api/v1/sku-aliases/{alias_id}"): ["test_foreign_sku_alias_rejected_and_unchanged"],
    ("DELETE", "/api/v1/sku-aliases/{alias_id}"): ["test_foreign_sku_alias_rejected_and_unchanged"],
    ("GET", "/api/v1/allegro/auth"): ["test_allegro_auth_state_uses_current_tenant"],
    ("GET", "/api/v1/allegro/auth/{account_id}"): ["test_allegro_foreign_account_rejected_before_service"],
    ("GET", "/api/v1/allegro/orders/{account_id}"): ["test_allegro_foreign_account_rejected_before_service"],
    ("GET", "/api/v1/allegro/billing/{account_id}"): ["test_allegro_foreign_account_rejected_before_service"],
    ("GET", "/api/v1/allegro/offers/{account_id}"): ["test_allegro_foreign_account_rejected_before_service"],
    ("GET", "/api/v1/billing/profile"): ["test_billing_profile_read_write_is_tenant_scoped"],
    ("PUT", "/api/v1/billing/profile"): ["test_billing_profile_read_write_is_tenant_scoped"],
    ("GET", "/api/v1/billing/vat-lookup/{nip}"): ["test_billing_vat_lookup_does_not_modify_foreign_profile"],
    ("GET", "/api/v1/billing/subscription"): ["test_subscription_excludes_foreign_invoice"],
    ("POST", "/api/v1/billing/subscription/request"): ["test_subscription_request_and_cancel_are_tenant_scoped"],
    ("POST", "/api/v1/billing/subscription/{subscription_id}/cancel"): ["test_subscription_request_and_cancel_are_tenant_scoped"],
    ("POST", "/api/v1/billing/paid-plan/accept"): ["test_paid_plan_acceptance_is_tenant_scoped"],
    ("POST", "/api/v1/import/sync/{account_id}"): ["test_import_sync_foreign_account_returns_404"],
    ("GET", "/api/v1/import/status"): ["test_import_status_only_current_tenant"],
    ("POST", "/api/v1/integrations/profit-by-ean"): ["test_profit_by_ean_rejects_foreign_account"],
    ("POST", "/api/v1/sku/auto-import/{account_id}"): ["test_sku_auto_import_foreign_account_rejected"],
    ("GET", "/api/v1/products/"): ["test_products_list_only_returns_own_tenant"],
    ("PATCH", "/api/v1/products/{sku_id}"): ["test_patch_foreign_product_returns_404"],
    ("POST", "/api/v1/products/{sku_id}/cost-history"): ["test_add_cost_history_rejects_foreign_sku"],
    ("DELETE", "/api/v1/products/{sku_id}/cost-history/{history_id}"): ["test_delete_cost_history_rejects_foreign_sku"],
    ("POST", "/api/v1/products/import-costs"): ["test_import_costs_cannot_modify_foreign_sku"],
    ("GET", "/api/v1/dashboard/debug/billing-types"): ["test_debug_billing_types_excludes_foreign_entries"],
    ("GET", "/api/v1/dashboard/summary"): ["test_dashboard_summary_does_not_aggregate_foreign_orders"],
    ("GET", "/api/v1/dashboard/summary/all"): ["test_dashboard_account_scoped_endpoints_404_for_foreign_account"],
    ("GET", "/api/v1/dashboard/summary/comparisons"): ["test_dashboard_account_scoped_endpoints_404_for_foreign_account"],
    ("GET", "/api/v1/dashboard/summary/daily"): ["test_dashboard_account_scoped_endpoints_404_for_foreign_account"],
    ("GET", "/api/v1/dashboard/product-detail"): ["test_dashboard_product_detail_404_for_foreign_sku"],
    ("GET", "/api/v1/dashboard/products"): ["test_dashboard_products_only_returns_own_tenant_sku"],
    ("GET", "/api/v1/financial-vault/status"): ["test_financial_vault_status_and_setup_are_tenant_scoped"],
    ("POST", "/api/v1/financial-vault/setup"): ["test_financial_vault_status_and_setup_are_tenant_scoped"],
    ("GET", "/api/v1/security/encrypted-cost-export/{sku_master_id}"): ["test_encrypted_cost_export_404_for_foreign_sku"],
    ("GET", "/api/v1/stock/settings"): ["test_settings_read_and_write_are_tenant_scoped"],
    ("PUT", "/api/v1/stock/settings"): ["test_settings_read_and_write_are_tenant_scoped"],
    ("GET", "/api/v1/stock/"): ["test_stock_foreign_account_rejected"],
    ("PUT", "/api/v1/stock/{sku_id}"): ["test_stock_update_foreign_sku_returns_404"],
    ("POST", "/api/v1/stock/auto-import"): ["test_stock_auto_import_only_current_tenant"],
    ("GET", "/api/v1/orders/recent"): [
        "test_orders_recent_only_own_tenant",
        "test_recent_orders_foreign_account_returns_no_orders",
    ],
    ("GET", "/api/v1/sku-mapping/patterns"): ["tests.test_sku_patterns_tenant:test_patterns_are_isolated_and_foreign_mutations_return_404"],
    ("POST", "/api/v1/sku-mapping/patterns"): ["tests.test_sku_patterns_tenant:test_patterns_are_isolated_and_foreign_mutations_return_404"],
    ("PATCH", "/api/v1/sku-mapping/patterns/{pattern_id}"): ["tests.test_sku_patterns_tenant:test_patterns_are_isolated_and_foreign_mutations_return_404"],
    ("DELETE", "/api/v1/sku-mapping/patterns/{pattern_id}"): ["tests.test_sku_patterns_tenant:test_patterns_are_isolated_and_foreign_mutations_return_404"],
    ("POST", "/api/v1/sku-mapping/reapply"): ["tests.test_sku_patterns_tenant:test_reapply_does_not_use_another_tenants_patterns"],
    ("GET", "/api/v1/sku-mapping/unmatched-offers"): ["test_unmatched_offers_only_current_tenant"],
    ("POST", "/api/v1/support/ticket"): ["test_support_ticket_uses_current_tenant_and_user"],
}


def _app_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def _resolve(ref: str):
    import importlib

    if ":" in ref:
        module_name, func = ref.split(":", 1)
        return getattr(importlib.import_module(module_name), func, None)
    return getattr(isolation, ref, None)


def test_every_route_is_classified():
    routes = _app_routes()
    missing = sorted(routes - ROUTE_CLASSIFICATION.keys())
    extra = sorted(ROUTE_CLASSIFICATION.keys() - routes)
    assert not missing, f"Routes without tenant classification: {missing}"
    assert not extra, f"Classified routes that no longer exist: {extra}"


def test_every_tenant_route_has_isolation_test():
    tenant_routes = {k for k, v in ROUTE_CLASSIFICATION.items() if v == T}
    assert tenant_routes == TENANT_ISOLATION_TESTS.keys(), (
        "TENANT_ISOLATION_TESTS must list exactly the tenant routes: "
        f"missing={sorted(tenant_routes - TENANT_ISOLATION_TESTS.keys())} "
        f"extra={sorted(TENANT_ISOLATION_TESTS.keys() - tenant_routes)}"
    )
    uncovered = sorted(k for k, tests in TENANT_ISOLATION_TESTS.items() if not tests)
    assert not uncovered, f"Tenant routes without isolation test: {uncovered}"
    dangling = sorted(
        ref for tests in TENANT_ISOLATION_TESTS.values() for ref in tests if _resolve(ref) is None
    )
    assert not dangling, f"Isolation tests referenced but not found: {dangling}"
