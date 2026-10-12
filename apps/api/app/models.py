"""Phase-1 organization, Admin, settings and audit schema.

Financial and sponsor entities arrive in reviewed, versioned migrations in later phases.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Index,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settings: Mapped["OrganizationSettings"] = relationship(back_populates="organization")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationSettings(Base):
    __tablename__ = "organization_settings"
    __table_args__ = (
        CheckConstraint("default_contribution_paise > 0", name="ck_settings_positive_amount"),
        CheckConstraint("sponsor_reminder_day BETWEEN 1 AND 28", name="ck_settings_sponsor_day"),
        CheckConstraint("promoter_reminder_day BETWEEN 1 AND 28", name="ck_settings_promoter_day"),
        CheckConstraint("inactivity_months BETWEEN 1 AND 24", name="ck_settings_inactivity"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    default_contribution_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sponsor_reminder_day: Mapped[int] = mapped_column(nullable=False)
    promoter_reminder_day: Mapped[int] = mapped_column(nullable=False)
    inactivity_months: Mapped[int] = mapped_column(nullable=False)
    automation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    organization: Mapped[Organization] = relationship(back_populates="settings")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    before_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdminSession(Base):
    """Only a SHA-256 digest of the random browser session token is persisted."""

    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminLoginAttempt(Base):
    """Hashed network/email markers, used to slow online password guessing."""

    __tablename__ = "admin_login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    network_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Prospect(Base):
    """Sponsor candidate. Status is payment-derived in Phase 06, never editable in Phase 04."""

    __tablename__ = "prospects"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_prospects_org_id"),
        CheckConstraint("monthly_contribution_paise > 0", name="ck_prospect_amount_positive"),
        CheckConstraint(
            "lifecycle_status IN ('new', 'active', 'inactive')",
            name="ck_prospect_lifecycle_status",
        ),
        Index("ix_prospects_org_status", "organization_id", "lifecycle_status", "archived_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    mobile_number: Mapped[str] = mapped_column(String(16), nullable=False)
    whatsapp_number: Mapped[str | None] = mapped_column(String(16))
    area_city: Mapped[str] = mapped_column(String(120), nullable=False)
    monthly_contribution_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    next_followup_on: Mapped[date | None] = mapped_column(Date)
    last_contact_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(1500))
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lifecycle_status: Mapped[str] = mapped_column(String(12), nullable=False, default="new")
    last_verified_payment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
        onupdate=func.now(),
    )
    upi_ids: Mapped[list["ProspectUpiIdentifier"]] = relationship(
        back_populates="prospect", cascade="save-update, merge", lazy="selectin"
    )


class ProspectUpiIdentifier(Base):
    """Only a keyed digest and a masked VPA are stored, never its raw value."""

    __tablename__ = "prospect_upi_ids"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="CASCADE",
            name="fk_prospect_upi_same_org",
        ),
        UniqueConstraint("prospect_id", "digest", name="uq_prospect_upi_digest"),
        Index("ix_prospect_upi_org_digest", "organization_id", "digest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_vpa: Mapped[str] = mapped_column(String(130), nullable=False)
    # Always false until a bank/provider verification flow is implemented.
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prospect: Mapped[Prospect] = relationship(back_populates="upi_ids")
