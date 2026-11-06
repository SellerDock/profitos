"""Add ADS service date to billing entries.

Revision ID: 20260509_0014
Revises: 20260509_0013
Create Date: 2026-05-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260509_0014"
down_revision = "20260509_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("billing_raw", sa.Column("ads_service_date", sa.Date(), nullable=True))
    op.create_index("ix_billing_raw_ads_service_date", "billing_raw", ["ads_service_date"])


def downgrade() -> None:
    op.drop_index("ix_billing_raw_ads_service_date", table_name="billing_raw")
    op.drop_column("billing_raw", "ads_service_date")
