"""multi-tenant schema

Revision ID: 20260504_0004
Revises: 20260504_0003
Create Date: 2026-05-04 22:30:00

Adds tenants and tenant_id columns to operational tables. Existing rows are
assigned to tenant 1 ("Operator"). Router-level filtering is intentionally
left for the next PR.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260504_0004"
down_revision: Union[str, None] = "20260504_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERTENANT_TABLES = (
    "accounts",
    "sku_masters",
    "sku_aliases",
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
)


def _add_tenant_column(table_name: str, index_name: str | None = None) -> None:
    op.add_column(
        table_name,
        sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column(table_name, "tenant_id", server_default=None)
    op.create_foreign_key(
        f"fk_{table_name}_tenant",
        table_name,
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(index_name or f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=False)

    op.execute(
        """
        INSERT INTO tenants (id, name, slug, is_active, created_at, updated_at)
        VALUES (1, 'Operator', 'operator', true, NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute("SELECT setval('tenants_id_seq', GREATEST((SELECT MAX(id) FROM tenants), 1), true)")

    _add_tenant_column("accounts", "ix_accounts_tenant")
    for table_name in PERTENANT_TABLES:
        if table_name != "accounts":
            _add_tenant_column(table_name)

    # Denormalized backfills. DEFAULT 1 already handles current single-tenant
    # data; these updates document and preserve the derivation path.
    op.execute(
        """
        UPDATE sku_aliases SET tenant_id = sm.tenant_id
        FROM sku_masters sm WHERE sku_aliases.sku_master_id = sm.id
        """
    )
    op.execute(
        """
        UPDATE encrypted_sku_costs SET tenant_id = sm.tenant_id
        FROM sku_masters sm WHERE encrypted_sku_costs.sku_master_id = sm.id
        """
    )
    op.execute(
        """
        UPDATE encrypted_sku_cost_history SET tenant_id = sm.tenant_id
        FROM sku_masters sm WHERE encrypted_sku_cost_history.sku_master_id = sm.id
        """
    )
    for table_name in (
        "account_import_state",
        "orders_raw",
        "billing_raw",
        "order_events_raw",
        "customer_returns_raw",
        "payment_refunds_raw",
        "offers_cache",
        "allegro_ads_imports",
        "sync_log",
    ):
        op.execute(
            f"""
            UPDATE {table_name} SET tenant_id = accounts.tenant_id
            FROM accounts WHERE {table_name}.account_id = accounts.id
            """
        )
    op.execute(
        """
        UPDATE customer_return_items_raw SET tenant_id = r.tenant_id
        FROM customer_returns_raw r
        WHERE customer_return_items_raw.customer_return_id = r.customer_return_id
        """
    )
    op.execute(
        """
        UPDATE payment_refund_line_items_raw SET tenant_id = r.tenant_id
        FROM payment_refunds_raw r
        WHERE payment_refund_line_items_raw.refund_id = r.refund_id
        """
    )
    op.execute(
        """
        UPDATE stock_levels SET tenant_id = sm.tenant_id
        FROM sku_masters sm WHERE stock_levels.sku_id = sm.id
        """
    )

    op.execute("ALTER TABLE sku_masters DROP CONSTRAINT IF EXISTS sku_masters_sku_key_key")
    op.create_unique_constraint("uq_sku_master_tenant_key", "sku_masters", ["tenant_id", "sku_key"])
    op.create_index("ix_sku_masters_tenant_key", "sku_masters", ["tenant_id", "sku_key"])

    op.execute("ALTER TABLE financial_vaults DROP CONSTRAINT IF EXISTS financial_vaults_scope_key")
    op.create_unique_constraint("uq_financial_vaults_tenant_scope", "financial_vaults", ["tenant_id", "scope"])

    op.execute("ALTER TABLE offers_cache DROP CONSTRAINT IF EXISTS offers_cache_offer_id_key")
    op.create_unique_constraint("uq_offers_cache_account_offer", "offers_cache", ["account_id", "offer_id"])

    op.create_unique_constraint("uq_accounts_allegro_client_id", "accounts", ["allegro_client_id"])

    op.execute("UPDATE users SET tenant_id = 1 WHERE tenant_id IS NULL")
    op.alter_column("users", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_users_tenant",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index("ix_orders_raw_tenant_bought", "orders_raw", ["tenant_id", "bought_at"])
    op.create_index("ix_billing_raw_tenant_occurred", "billing_raw", ["tenant_id", "occurred_at"])
    op.create_index("ix_ads_imports_tenant_date", "allegro_ads_imports", ["tenant_id", "ad_date"])

    op.execute("ALTER TABLE stock_settings DROP CONSTRAINT stock_settings_pkey")
    op.create_primary_key("stock_settings_pkey", "stock_settings", ["tenant_id", "key"])

    op.add_column("waitlist_entries", sa.Column("approved_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported: re-introducing single-tenant schema "
        "would corrupt data after multi-tenant tenants existed."
    )
