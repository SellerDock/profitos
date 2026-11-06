from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, Index, String, Integer, Numeric, DateTime, Text, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class BillingTypeLabel(Base):
    """Official Allegro billing type codes with Polish names, fetched via API."""
    __tablename__ = "billing_type_labels"

    type_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_pl: Mapped[str] = mapped_column(String(255), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AccountImportState(Base):
    """Lightweight per-account cursors for incremental Allegro imports."""
    __tablename__ = "account_import_state"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    latest_order_event_id: Mapped[str | None] = mapped_column(String(64))
    latest_order_event_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class OrderRaw(Base):
    """One row per line item in an Allegro checkout form."""
    __tablename__ = "orders_raw"
    __table_args__ = (Index("ix_orders_raw_tenant_bought", "tenant_id", "bought_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    line_item_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    offer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sku: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer_login: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    delivery_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    status: Mapped[str | None] = mapped_column(String(64))
    bought_at: Mapped[datetime | None] = mapped_column(DateTime)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BillingRaw(Base):
    """One row per Allegro billing entry."""
    __tablename__ = "billing_raw"
    __table_args__ = (Index("ix_billing_raw_tenant_occurred", "tenant_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    entry_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    offer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    type: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    ads_service_date: Mapped[date | None] = mapped_column(Date, index=True)
    shipping_is_smart: Mapped[bool | None] = mapped_column(Boolean)
    shipping_order_is_smart: Mapped[bool | None] = mapped_column(Boolean)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OrderEventRaw(Base):
    """Raw order events from GET /order/events."""
    __tablename__ = "order_events_raw"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checkout_form_revision: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomerReturnRaw(Base):
    """One row per Allegro customer return."""
    __tablename__ = "customer_returns_raw"

    customer_return_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reference_number: Mapped[str | None] = mapped_column(String(128))
    buyer_login: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer_email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(64), index=True)
    marketplace_id: Mapped[str | None] = mapped_column(String(64))
    is_fulfillment: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomerReturnItemRaw(Base):
    """Returned items inside a customer return."""
    __tablename__ = "customer_return_items_raw"
    __table_args__ = (
        UniqueConstraint("customer_return_id", "item_index", name="uq_customer_return_item_idx"),
        Index("ix_customer_return_items_offer_id", "offer_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    customer_return_id: Mapped[str] = mapped_column(
        ForeignKey("customer_returns_raw.customer_return_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    offer_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    reason_type: Mapped[str | None] = mapped_column(String(64))
    reason_user_comment: Mapped[str | None] = mapped_column(Text)


class PaymentRefundRaw(Base):
    """One row per Allegro payment refund."""
    __tablename__ = "payment_refunds_raw"

    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reason: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    delivery_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    overpaid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    additional_services_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    inserted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PaymentRefundLineItemRaw(Base):
    """Refunded line items inside a payment refund."""
    __tablename__ = "payment_refund_line_items_raw"
    __table_args__ = (
        UniqueConstraint("refund_id", "item_index", name="uq_payment_refund_item_idx"),
        Index("ix_payment_refund_items_line_item_id", "line_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    refund_id: Mapped[str] = mapped_column(
        ForeignKey("payment_refunds_raw.refund_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    line_item_id: Mapped[str | None] = mapped_column(String(64))
    refund_type: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int | None] = mapped_column(Integer)
    value_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    value_currency: Mapped[str | None] = mapped_column(String(3))


class OfferCache(Base):
    """Cached snapshot of Allegro offers."""
    __tablename__ = "offers_cache"
    __table_args__ = (
        UniqueConstraint("account_id", "offer_id", name="uq_offers_cache_account_offer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    stock_available: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="PLN")
    ean: Mapped[str | None] = mapped_column(String(64))
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class StockLevel(Base):
    """Current stock quantity per SKU (base products only, not bundles)."""
    __tablename__ = "stock_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku_masters.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str] = mapped_column(String(20), default="manual")
    sync_from_allegro: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class StockSetting(Base):
    """Key-value stock and app settings stored as integer flags/values."""
    __tablename__ = "stock_settings"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), primary_key=True, default=1)
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class AllegroAdsImport(Base):
    """One row per (account, offer, date, campaign) imported from Allegro Ads stats XLSX/CSV."""
    __tablename__ = "allegro_ads_imports"
    __table_args__ = (
        UniqueConstraint("account_id", "offer_id", "ad_date", "campaign_name", name="uq_ads_import_key"),
        Index("ix_ads_imports_account_date", "account_id", "ad_date"),
        Index("ix_ads_imports_tenant_date", "tenant_id", "ad_date"),
        Index("ix_ads_imports_offer_id", "offer_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ad_group: Mapped[str | None] = mapped_column(String(255))
    ad_date: Mapped[date] = mapped_column(Date, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    interest: Mapped[int] = mapped_column(Integer, default=0)
    cpc: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    ctr: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    roas: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    units_sold_via_ad: Mapped[int] = mapped_column(Integer, default=0)
    sales_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    imported_filename: Mapped[str | None] = mapped_column(String(255))


class SyncLog(Base):
    """Record of each synchronisation run."""
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    days_fetched: Mapped[int] = mapped_column(Integer, default=90)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    billing_count: Mapped[int] = mapped_column(Integer, default=0)
    offers_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
