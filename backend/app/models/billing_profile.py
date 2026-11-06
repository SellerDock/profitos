from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantBillingProfile(Base):
    __tablename__ = "tenant_billing_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_billing_profiles_tenant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    nip: Mapped[str | None] = mapped_column(String(32), index=True)
    regon: Mapped[str | None] = mapped_column(String(32))
    krs: Mapped[str | None] = mapped_column(String(32))
    street: Mapped[str | None] = mapped_column(String(255))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(2), default="PL", nullable=False)
    invoice_email: Mapped[str | None] = mapped_column(String(320))
    vat_status: Mapped[str | None] = mapped_column(String(64))
    fetched_from_vat_api_at: Mapped[datetime | None] = mapped_column(DateTime)
    trial_end_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TenantInvoice(Base):
    __tablename__ = "tenant_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_tenant_invoices_tenant_number"),
        Index("ix_tenant_invoices_tenant_month", "tenant_id", "period_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    amount_net: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    amount_gross: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="PLN", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TenantPaidPlanAcceptance(Base):
    __tablename__ = "tenant_paid_plan_acceptances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "terms_version", name="uq_tenant_paid_plan_acceptances_tenant_version"),
        Index("ix_tenant_paid_plan_acceptances_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    terms_version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"
    __table_args__ = (
        CheckConstraint("status IN ('pending_invoice', 'invoiced', 'active', 'expired', 'cancelled')", name="ck_tenant_subscriptions_status"),
        Index("uq_tenant_subscriptions_pending", "tenant_id", unique=True,
              postgresql_where=text("status IN ('pending_invoice', 'invoiced')"), sqlite_where=text("status IN ('pending_invoice', 'invoiced')")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    tier_code: Mapped[str] = mapped_column(String(32), nullable=False)
    price_pln: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    terms_version: Mapped[str] = mapped_column(String(32), nullable=False)
    invoice_number: Mapped[str | None] = mapped_column(String(64))
    ifirma_invoice_id: Mapped[str | None] = mapped_column(String(64))
    invoiced_at: Mapped[datetime | None] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    marked_paid_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)


class TenantUsageNotice(Base):
    __tablename__ = "tenant_usage_notices"
    __table_args__ = (
        CheckConstraint("kind IN ('over_limit', 'upgrade_suggestion', 'renewal_30d', 'renewal_7d', 'expired')", name="ck_tenant_usage_notices_kind"),
        UniqueConstraint("tenant_id", "kind", "period_key", name="uq_tenant_usage_notices_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    period_key: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
