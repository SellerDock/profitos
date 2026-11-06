from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class SkuMaster(Base):
    __tablename__ = "sku_masters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku_key", name="uq_sku_master_tenant_key"),
        Index("ix_sku_masters_tenant_key", "tenant_id", "sku_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    sku_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(255))
    product_type: Mapped[str | None] = mapped_column(String(255))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=23)
    target_margin_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    aliases: Mapped[list["SkuAlias"]] = relationship(
        "SkuAlias", back_populates="sku_master", cascade="all, delete-orphan"
    )

class SkuAlias(Base):
    __tablename__ = "sku_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    sku_master_id: Mapped[int] = mapped_column(ForeignKey("sku_masters.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=1.0)

    sku_master: Mapped["SkuMaster"] = relationship("SkuMaster", back_populates="aliases")


class FinancialVault(Base):
    """Client-side encrypted financial vault metadata.

    The backend stores Argon2id parameters and a verifier payload only. The
    password-derived key normally lives only in the browser: it never persists
    on the server. The authenticated integration endpoint
    (POST /api/v1/integrations/profit-by-ean) is disabled by default and works
    only when the installation administrator enables VAULT_SERVER_DECRYPTION_ENABLED.
    A client may opt in to server-side
    decryption by supplying the vault code in each request; the code, the
    derived key and any decrypted costs then live only in the memory of that
    single request and are never persisted or logged.
    """
    __tablename__ = "financial_vaults"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", name="uq_financial_vaults_tenant_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, default="global")
    kdf: Mapped[str] = mapped_column(String(32), nullable=False, default="argon2id")
    salt: Mapped[str] = mapped_column(Text, nullable=False)
    memory_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    time_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    parallelism: Mapped[int] = mapped_column(Integer, nullable=False)
    verify_nonce: Mapped[str] = mapped_column(Text, nullable=False)
    verify_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EncryptedSkuCost(Base):
    """Current encrypted purchase cost per SKU."""
    __tablename__ = "encrypted_sku_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    sku_master_id: Mapped[int] = mapped_column(ForeignKey("sku_masters.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    vault_id: Mapped[int] = mapped_column(ForeignKey("financial_vaults.id", ondelete="CASCADE"), nullable=False, index=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aad_context: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EncryptedSkuCostHistory(Base):
    """Encrypted purchase cost history per SKU."""
    __tablename__ = "encrypted_sku_cost_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1, index=True)
    sku_master_id: Mapped[int] = mapped_column(ForeignKey("sku_masters.id", ondelete="CASCADE"), nullable=False, index=True)
    vault_id: Mapped[int] = mapped_column(ForeignKey("financial_vaults.id", ondelete="CASCADE"), nullable=False, index=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aad_context: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SkuMultiplierPattern(Base):
    """Regex patterns that detect multi-unit offers and assign a cost multiplier."""
    __tablename__ = "sku_multiplier_patterns"
    __table_args__ = (UniqueConstraint("tenant_id", "pattern_regex", name="uq_sku_patterns_tenant_regex"),)

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    pattern_regex: Mapped[str] = mapped_column(String(500), nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
