from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_tenant", "tenant_id"),
        Index("ix_accounts_tenant_allegro_user_id", "tenant_id", "allegro_user_id"),
        UniqueConstraint("tenant_id", "allegro_user_id", name="uq_accounts_tenant_allegro_user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    allegro_client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    allegro_client_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    allegro_user_id: Mapped[str | None] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class AllegroAccountClaim(Base):
    """Global Allegro account claim used to prevent trial/account reuse."""

    __tablename__ = "allegro_account_claims"
    __table_args__ = (
        Index("ix_allegro_account_claims_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    allegro_user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"))
    account_name: Mapped[str | None] = mapped_column(String(255))
    first_connected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_connected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AllegroOAuthTransaction(Base):
    """One-time Allegro OAuth transaction bound to the browser that started it.

    Only the SHA-256 of the nonce is stored; the nonce itself travels in the
    signed OAuth state and in an httponly cookie of the initiating browser.
    """

    __tablename__ = "allegro_oauth_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
