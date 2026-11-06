"""Add paid plan acceptance audit table.

Revision ID: 20260512_0017
Revises: 20260512_0016
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260512_0017"
down_revision = "20260512_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant_billing_profiles", sa.Column("trial_end_email_sent_at", sa.DateTime(), nullable=True))
    op.create_table(
        "tenant_paid_plan_acceptances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("terms_version", sa.String(length=32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "terms_version", name="uq_tenant_paid_plan_acceptances_tenant_version"),
    )
    op.create_index("ix_tenant_paid_plan_acceptances_tenant", "tenant_paid_plan_acceptances", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_paid_plan_acceptances_tenant_id", "tenant_paid_plan_acceptances", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_paid_plan_acceptances_user_id", "tenant_paid_plan_acceptances", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tenant_paid_plan_acceptances_user_id", table_name="tenant_paid_plan_acceptances")
    op.drop_index("ix_tenant_paid_plan_acceptances_tenant_id", table_name="tenant_paid_plan_acceptances")
    op.drop_index("ix_tenant_paid_plan_acceptances_tenant", table_name="tenant_paid_plan_acceptances")
    op.drop_table("tenant_paid_plan_acceptances")
    op.drop_column("tenant_billing_profiles", "trial_end_email_sent_at")
