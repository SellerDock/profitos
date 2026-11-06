"""Add beta billing profile and Allegro account claims.

Revision ID: 20260512_0015
Revises: 20260509_0014
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260512_0015"
down_revision = "20260509_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "allegro_account_claims",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allegro_user_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("first_connected_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_connected_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("allegro_user_id"),
    )
    op.create_index("ix_allegro_account_claims_allegro_user_id", "allegro_account_claims", ["allegro_user_id"], unique=False)
    op.create_index("ix_allegro_account_claims_tenant", "allegro_account_claims", ["tenant_id"], unique=False)

    op.create_table(
        "tenant_billing_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("nip", sa.String(length=32), nullable=True),
        sa.Column("regon", sa.String(length=32), nullable=True),
        sa.Column("krs", sa.String(length=32), nullable=True),
        sa.Column("street", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=16), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("invoice_email", sa.String(length=320), nullable=True),
        sa.Column("vat_status", sa.String(length=64), nullable=True),
        sa.Column("fetched_from_vat_api_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_billing_profiles_tenant"),
    )
    op.create_index("ix_tenant_billing_profiles_nip", "tenant_billing_profiles", ["nip"], unique=False)
    op.create_index("ix_tenant_billing_profiles_tenant_id", "tenant_billing_profiles", ["tenant_id"], unique=False)

    op.create_table(
        "tenant_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(length=64), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount_net", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_gross", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pdf_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_tenant_invoices_tenant_number"),
    )
    op.create_index("ix_tenant_invoices_tenant_id", "tenant_invoices", ["tenant_id"], unique=False)
    op.create_index("ix_tenant_invoices_tenant_month", "tenant_invoices", ["tenant_id", "period_month"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tenant_invoices_tenant_month", table_name="tenant_invoices")
    op.drop_index("ix_tenant_invoices_tenant_id", table_name="tenant_invoices")
    op.drop_table("tenant_invoices")
    op.drop_index("ix_tenant_billing_profiles_tenant_id", table_name="tenant_billing_profiles")
    op.drop_index("ix_tenant_billing_profiles_nip", table_name="tenant_billing_profiles")
    op.drop_table("tenant_billing_profiles")
    op.drop_index("ix_allegro_account_claims_tenant", table_name="allegro_account_claims")
    op.drop_index("ix_allegro_account_claims_allegro_user_id", table_name="allegro_account_claims")
    op.drop_table("allegro_account_claims")
