import pytest

ALLOWED_TABLES_WITH_COST_COL = {
    "allegro_ads_imports",
    "orders_raw",
    "billing_raw",
    "customer_return_items_raw",
    "payment_refunds_raw",
    "payment_refund_line_items_raw",
    "offers_cache",
    "financial_vaults",
    "encrypted_sku_costs",
    "encrypted_sku_cost_history",
}

FORBIDDEN_COL_PATTERNS = (
    "cost_per_unit",
    "cogs",
    "profit",
    "margin_value",
    "margin_amount",
    "buy_price",
    "price_purchase",
    "purchase_cost",
    "koszt",
    "marża",
    "zysk",
)


@pytest.mark.contract
def test_no_plaintext_cost_columns():
    import app.models.account  # noqa: F401
    import app.models.raw_data  # noqa: F401
    import app.models.sku  # noqa: F401
    from app.core.database import Base

    offenders = []
    for table_name, table in Base.metadata.tables.items():
        if table_name in ALLOWED_TABLES_WITH_COST_COL:
            continue
        for col in table.columns:
            for pattern in FORBIDDEN_COL_PATTERNS:
                if pattern in col.name.lower():
                    offenders.append(f"{table_name}.{col.name}")

    assert not offenders, (
        "Plaintext cost-derived columns found outside encrypted vault: "
        + ", ".join(offenders)
    )
