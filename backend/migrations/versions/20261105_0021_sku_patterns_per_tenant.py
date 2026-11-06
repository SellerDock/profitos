"""Scope SKU multiplier patterns to tenants.

Revision ID: 20261105_0021
Revises: 20260726_0020
"""
from alembic import op
import sqlalchemy as sa

revision = "20261105_0021"
down_revision = "20260726_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sku_multiplier_patterns", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.drop_constraint("sku_multiplier_patterns_pattern_regex_key", "sku_multiplier_patterns", type_="unique")
    op.execute("""
        INSERT INTO sku_multiplier_patterns
            (tenant_id, pattern_regex, multiplier, description, priority, enabled, created_at, updated_at)
        SELECT t.id, p.pattern_regex, p.multiplier, p.description, p.priority,
               p.enabled, p.created_at, p.updated_at
        FROM sku_multiplier_patterns p CROSS JOIN tenants t
        WHERE p.tenant_id IS NULL
    """)
    op.execute("DELETE FROM sku_multiplier_patterns WHERE tenant_id IS NULL")
    op.alter_column("sku_multiplier_patterns", "tenant_id", nullable=False)
    op.create_foreign_key("fk_sku_multiplier_patterns_tenant_id", "sku_multiplier_patterns", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_sku_multiplier_patterns_tenant_id", "sku_multiplier_patterns", ["tenant_id"])
    op.create_unique_constraint("uq_sku_patterns_tenant_regex", "sku_multiplier_patterns", ["tenant_id", "pattern_regex"])


def downgrade():
    op.execute("""
        DELETE FROM sku_multiplier_patterns p
        USING sku_multiplier_patterns keep
        WHERE p.pattern_regex = keep.pattern_regex AND p.id > keep.id
    """)
    op.drop_constraint("uq_sku_patterns_tenant_regex", "sku_multiplier_patterns", type_="unique")
    op.drop_index("ix_sku_multiplier_patterns_tenant_id", table_name="sku_multiplier_patterns")
    op.drop_constraint("fk_sku_multiplier_patterns_tenant_id", "sku_multiplier_patterns", type_="foreignkey")
    op.drop_column("sku_multiplier_patterns", "tenant_id")
    op.create_unique_constraint("sku_multiplier_patterns_pattern_regex_key", "sku_multiplier_patterns", ["pattern_regex"])
