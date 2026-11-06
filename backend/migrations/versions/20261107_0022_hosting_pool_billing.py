"""Add hosting pool billing.

Revision ID: 20261107_0022
Revises: 20261105_0021
"""
from alembic import op
import sqlalchemy as sa

revision = "20261107_0022"
down_revision = "20261105_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("billing_scheme", sa.String(16), nullable=False, server_default="legacy_trial"))
    op.alter_column("tenants", "billing_scheme", server_default="pool_v2")
    op.create_check_constraint("ck_tenants_billing_scheme", "tenants", "billing_scheme IN ('legacy_trial', 'pool_v2')")
    op.add_column("tenants", sa.Column("free_pool_orders", sa.Integer(), nullable=False, server_default="1000"))
    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("tier_code", sa.String(32), nullable=False),
        sa.Column("price_pln", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("terms_version", sa.String(32), nullable=False),
        sa.Column("invoice_number", sa.String(64)),
        sa.Column("ifirma_invoice_id", sa.String(64)),
        sa.Column("invoiced_at", sa.DateTime()),
        sa.Column("paid_at", sa.DateTime()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("marked_paid_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime()),
        sa.CheckConstraint("status IN ('pending_invoice', 'invoiced', 'active', 'expired', 'cancelled')", name="ck_tenant_subscriptions_status"),
    )
    op.create_index("ix_tenant_subscriptions_tenant_id", "tenant_subscriptions", ["tenant_id"])
    op.create_index("uq_tenant_subscriptions_pending", "tenant_subscriptions", ["tenant_id"], unique=True,
                    postgresql_where=sa.text("status IN ('pending_invoice', 'invoiced')"))
    op.create_table(
        "tenant_usage_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("period_key", sa.String(16), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('over_limit', 'upgrade_suggestion', 'renewal_30d', 'renewal_7d', 'expired')", name="ck_tenant_usage_notices_kind"),
        sa.UniqueConstraint("tenant_id", "kind", "period_key", name="uq_tenant_usage_notices_period"),
    )
    op.create_index("ix_tenant_usage_notices_tenant_id", "tenant_usage_notices", ["tenant_id"])


def downgrade():
    op.drop_index("ix_tenant_usage_notices_tenant_id", table_name="tenant_usage_notices")
    op.drop_table("tenant_usage_notices")
    op.drop_index("uq_tenant_subscriptions_pending", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_tenant_id", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")
    op.drop_column("tenants", "free_pool_orders")
    op.drop_constraint("ck_tenants_billing_scheme", "tenants", type_="check")
    op.drop_column("tenants", "billing_scheme")
