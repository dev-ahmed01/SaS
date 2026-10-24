"""Phase-1 organization, Admin, settings and audit schema.

Financial and sponsor entities arrive in reviewed, versioned migrations in later phases.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settings: Mapped["OrganizationSettings"] = relationship(
        back_populates="organization", cascade="all, delete-orphan", passive_deletes=True
    )


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
        CheckConstraint("inactivity_months = 2", name="ck_settings_inactivity"),
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
        UniqueConstraint(
            "organization_id", "registration_request_id", name="uq_prospect_registration"
        ),
        CheckConstraint("monthly_contribution_paise > 0", name="ck_prospect_amount_positive"),
        CheckConstraint(
            "lifecycle_status IN ('new', 'active', 'inactive')",
            name="ck_prospect_lifecycle_status",
        ),
        Index("ix_prospects_org_status", "organization_id", "lifecycle_status", "archived_at"),
        Index("ix_prospects_org_crm_stage", "organization_id", "crm_stage", "archived_at"),
        Index("ix_prospects_org_pipeline_stage", "organization_id", "pipeline_stage_id"),
        ForeignKeyConstraint(
            ["organization_id", "pipeline_stage_id"],
            ["prospect_stage_definitions.organization_id", "prospect_stage_definitions.id"],
            ondelete="RESTRICT", name="fk_prospect_pipeline_stage_org",
        ),
        CheckConstraint("crm_stage IN ('active','inactive')", name="ck_prospect_crm_stage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(320))
    occupation: Mapped[str | None] = mapped_column(String(120))
    crm_stage: Mapped[str] = mapped_column(
        String(12), nullable=False, default="inactive", server_default="inactive"
    )
    crm_stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_inactive_reason: Mapped[str | None] = mapped_column(String(64))
    crm_inactive_note: Mapped[str | None] = mapped_column(String(500))
    pipeline_stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    mobile_number: Mapped[str] = mapped_column(String(16), nullable=False)
    whatsapp_number: Mapped[str | None] = mapped_column(String(16))
    whatsapp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    area_city: Mapped[str] = mapped_column(String(120), nullable=False)
    monthly_contribution_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    registration_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    registration_payload_hash: Mapped[str | None] = mapped_column(String(64))
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
    start_month: Mapped[date | None] = mapped_column(Date)
    upi_ids: Mapped[list["ProspectUpiIdentifier"]] = relationship(
        back_populates="prospect", cascade="save-update, merge", lazy="selectin"
    )
    stage_transitions: Mapped[list["ProspectStageTransition"]] = relationship(
        back_populates="prospect", lazy="selectin", order_by="ProspectStageTransition.changed_at",
    )
    archive_intervals: Mapped[list["ProspectArchiveInterval"]] = relationship(
        back_populates="prospect", cascade="save-update, merge", lazy="selectin",
        order_by="ProspectArchiveInterval.archived_at",
    )



class SponsorOtpChallenge(Base):
    """Server-generated WhatsApp OTP challenge; no plaintext code or number stored."""

    __tablename__ = "sponsor_otp_challenges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_otp_prospect_org",
        ),
        Index("ix_otp_org_prospect_created", "organization_id", "prospect_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    phone_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProspectFollowUp(Base):
    """Append-only notes from Admin contact activity."""
    __tablename__ = "prospect_followups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"], ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_followup_prospect_org",
        ),
        Index("ix_followups_org_prospect_created", "organization_id", "prospect_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    actor_admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str] = mapped_column(String(500), nullable=False)
    next_followup_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProspectStageDefinition(Base):
    """Admin-configured pipeline stage, separate from CRM active status."""
    __tablename__ = "prospect_stage_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_stage_definition_org_id"),
        UniqueConstraint("organization_id", "name_key", name="uq_stage_definition_org_name"),
        Index("ix_stage_definitions_org_sort", "organization_id", "sort_order", "name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProspectStageTransition(Base):
    """Auditable CRM decisions, separate from payment-derived lifecycle status."""
    __tablename__ = "prospect_stage_transitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"], ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_prospect_stage_same_org",
        ),
        CheckConstraint("from_stage IN ('active','inactive')", name="ck_stage_from"),
        CheckConstraint("to_stage IN ('active','inactive')", name="ck_stage_to"),
        Index("ix_prospect_stage_history", "organization_id", "prospect_id", "changed_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    from_stage: Mapped[str] = mapped_column(String(12), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"),
    )
    prospect: Mapped[Prospect] = relationship(back_populates="stage_transitions")


class ProspectArchiveInterval(Base):
    """Append-only history of when future sponsorship dues were suspended."""

    __tablename__ = "prospect_archive_intervals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_archive_interval_prospect_org",
        ),
        UniqueConstraint(
            "organization_id", "prospect_id", "archived_at",
            name="uq_archive_interval_start",
        ),
        CheckConstraint(
            "restored_at IS NULL OR restored_at >= archived_at",
            name="ck_archive_interval_order",
        ),
        Index("ix_archive_interval_org_prospect", "organization_id", "prospect_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prospect: Mapped[Prospect] = relationship(back_populates="archive_intervals")


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



class Promoter(Base):
    """Volunteer liaison. Activity is an Admin decision, not a financial status."""

    __tablename__ = "promoters"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_promoters_org_id"),
        UniqueConstraint("organization_id", "mobile_number", name="uq_promoters_org_mobile"),
        CheckConstraint("version > 0", name="ck_promoters_version_positive"),
        Index("ix_promoters_org_active", "organization_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(320))
    occupation: Mapped[str | None] = mapped_column(String(120))
    mobile_number: Mapped[str] = mapped_column(String(16), nullable=False)
    whatsapp_number: Mapped[str | None] = mapped_column(String(16))
    area_city: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1500))
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromoterAssignment(Base):
    """One current promoter per prospect. Historical assignments stay auditable."""

    __tablename__ = "promoter_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "promoter_id"],
            ["promoters.organization_id", "promoters.id"],
            ondelete="RESTRICT", name="fk_assignment_promoter_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_assignment_prospect_org",
        ),
        Index(
            "uq_assignment_current_prospect", "organization_id", "prospect_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
        Index("ix_assignments_promoter_current", "promoter_id", "ended_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    promoter_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    ended_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )


class SponsorshipRate(Base):
    """Versioned effective-month contribution rate; historical months are immutable."""

    __tablename__ = "sponsorship_rates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_rate_prospect_same_org",
        ),
        UniqueConstraint(
            "organization_id", "prospect_id", "effective_month",
            name="uq_rate_prospect_month",
        ),
        CheckConstraint("amount_paise > 0", name="ck_rate_positive_amount"),
        CheckConstraint(
            "amount_paise <= 1000000000", name="ck_rate_amount_maximum"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    effective_month: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VerifiedCredit(Base):
    """Immutable bank/manual verification source for later phases.

    Phase 06 provides NO route to create this record. Bank reconciliation and
    manual authorization workflows must enforce matching and evidence provenance.
    """

    __tablename__ = "verified_credits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_credit_prospect_same_org",
        ),
        CheckConstraint("amount_paise > 0", name="ck_credit_positive_amount"),
        CheckConstraint(
            "source_type IN ('bank_reconciled', 'manual_attested')",
            name="ck_credit_source_type",
        ),
        UniqueConstraint(
            "organization_id", "source_key", name="uq_credit_org_source"
        ),
        UniqueConstraint("organization_id", "id", name="uq_credits_org_id"),
        Index(
            "ix_credit_prospect_month",
            "organization_id", "prospect_id", "period_month",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ManualCollection(Base):
    """Admin-attested collection entry: immutable and source-backed for the ledger."""

    __tablename__ = "manual_collections"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_manual_collections_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_manual_collection_prospect_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "verified_credit_id"],
            ["verified_credits.organization_id", "verified_credits.id"],
            ondelete="RESTRICT", name="fk_manual_collection_credit_org",
        ),
        UniqueConstraint(
            "organization_id", "request_id", name="uq_manual_collection_request"
        ),
        UniqueConstraint(
            "organization_id", "reference_digest", name="uq_manual_collection_reference"
        ),
        UniqueConstraint("verified_credit_id", name="uq_manual_collection_credit"),
        CheckConstraint("amount_paise > 0", name="ck_manual_collection_amount"),
        CheckConstraint(
            "payment_method IN ('upi', 'bank_transfer', 'cash')",
            name="ck_manual_collection_method",
        ),
        Index("ix_manual_collection_org_date", "organization_id", "received_on"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    verified_credit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_mask: Mapped[str] = mapped_column(String(16), nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recorded_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessageOutbox(Base):
    """Consent-gated intent only; no network delivery until approved integration."""

    __tablename__ = "message_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_message_prospect_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "collection_id"],
            ["manual_collections.organization_id", "manual_collections.id"],
            ondelete="RESTRICT", name="fk_message_collection_org",
        ),
        UniqueConstraint(
            "organization_id", "collection_id", "event_type",
            name="uq_message_collection_event",
        ),
        UniqueConstraint("organization_id", "id", name="uq_outbox_org_id"),
        CheckConstraint(
            "status IN ('awaiting_integration', 'suppressed')",
            name="ck_message_preintegration_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    prospect_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    collection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    suppress_reason: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ManualCollectionReversal(Base):
    """Immutable void of an incorrectly recorded collection, NOT a cash refund.

    The original collection and credit remain in the database. Accounting
    projections exclude the original credit after a reversal is recorded.
    """

    __tablename__ = "manual_collection_reversals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "collection_id"],
            ["manual_collections.organization_id", "manual_collections.id"],
            ondelete="RESTRICT", name="fk_reversal_collection_same_org",
        ),
        UniqueConstraint(
            "organization_id", "collection_id",
            name="uq_reversal_one_per_collection",
        ),
        UniqueConstraint(
            "organization_id", "request_id", name="uq_reversal_request_org",
        ),
        CheckConstraint(
            "reason_code IN ("
            "'duplicate_entry', 'wrong_sponsor', 'wrong_amount', "
            "'funds_not_received', 'other')",
            name="ck_reversal_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    collection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PayoutPlan(Base):
    """Outgoing commitment, not an execution instruction or payment evidence."""

    __tablename__ = "payout_plans"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_payout_plan_org_id"),
        UniqueConstraint("organization_id", "create_request_id", name="uq_payout_create_request"),
        CheckConstraint(
            "cadence IN ('recurring', 'one_time')", name="ck_payout_plan_cadence",
        ),
        CheckConstraint("amount_paise > 0 AND amount_paise <= 1000000000",
                        name="ck_payout_plan_positive_amount"),
        CheckConstraint(
            "(cadence = 'one_time' AND scheduled_on IS NOT NULL) OR "
            "(cadence = 'recurring' AND scheduled_on IS NULL)",
            name="ck_payout_plan_scheduled_only_once",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    create_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    create_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payee_name: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(240), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(800))
    cadence: Mapped[str] = mapped_column(String(16), nullable=False)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_on: Mapped[date | None] = mapped_column(Date)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PayoutPlanTerm(Base):
    """Monthly effective status; pause/resume never erases past commitments."""

    __tablename__ = "payout_plan_terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            ["payout_plans.organization_id", "payout_plans.id"],
            ondelete="RESTRICT", name="fk_payout_term_plan_org",
        ),
        UniqueConstraint(
            "organization_id", "plan_id", "effective_month",
            name="uq_payout_term_month",
        ),
        UniqueConstraint("organization_id", "request_id", name="uq_payout_term_request"),
        CheckConstraint(
            "status IN ('active', 'paused', 'closed')",
            name="ck_payout_term_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    effective_month: Mapped[date] = mapped_column(Date, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PayoutPayment(Base):
    """Admin-attested actual outgoing payment. This is NOT a bank transfer API."""

    __tablename__ = "payout_payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            ["payout_plans.organization_id", "payout_plans.id"],
            ondelete="RESTRICT", name="fk_payout_payment_plan_org",
        ),
        UniqueConstraint(
            "organization_id", "request_id", name="uq_payout_payment_request",
        ),
        UniqueConstraint(
            "organization_id", "reference_digest", name="uq_payout_payment_reference",
        ),
        UniqueConstraint(
            "organization_id", "plan_id", "period_month",
            name="uq_payout_payment_one_per_period",
        ),
        CheckConstraint(
            "amount_paise > 0 AND amount_paise <= 1000000000",
            name="ck_payout_payment_positive_amount",
        ),
        CheckConstraint(
            "payment_method IN ('upi', 'bank_transfer', 'cash', 'cheque')",
            name="ck_payout_payment_method",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    reference_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_mask: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class CommunicationTemplate(Base):
    """Reusable message copy; provider approval is independent of a saved draft."""

    __tablename__ = "communication_templates"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_comm_template_org_id"),
        UniqueConstraint("organization_id", "name_key", name="uq_comm_template_name"),
        CheckConstraint("channel IN ('whatsapp','email')", name="ck_comm_template_channel"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_key: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(1200), nullable=False)
    provider_template_id: Mapped[str | None] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CommunicationCampaign(Base):
    """Immutable copy snapshot when saved; a schedule is not dispatch authority."""

    __tablename__ = "communication_campaigns"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_comm_campaign_org_id"),
        UniqueConstraint("organization_id", "request_id", name="uq_comm_campaign_request"),
        Index("ix_comm_campaign_org_created", "organization_id", "created_at"),
        CheckConstraint("channel IN ('whatsapp','email')", name="ck_comm_campaign_channel"),
        CheckConstraint(
            "audience IN ('prospects','promoters','both')", name="ck_comm_campaign_audience"
        ),
        CheckConstraint(
            "segment IN ('all','active','inactive','unpaid')", name="ck_comm_campaign_segment"
        ),
        CheckConstraint(
            "status IN ('draft','scheduled','cancelled')", name="ck_comm_campaign_status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("communication_templates.id", ondelete="RESTRICT")
    )
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(1200), nullable=False)
    provider_template_id: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_snapshot: Mapped[int] = mapped_column(nullable=False, default=0)
    candidate_snapshot: Mapped[int] = mapped_column(nullable=False, default=0)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SaasytoCampaignRun(Base):
    """Explicit Admin approval; one run per immutable campaign, no backlog replay."""

    __tablename__ = "saasyto_campaign_runs"
    __table_args__ = (
        UniqueConstraint("organization_id", "campaign_id", name="uq_saasyto_run_campaign"),
        UniqueConstraint("organization_id", "id", name="uq_saasyto_run_org_id"),
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["communication_campaigns.organization_id", "communication_campaigns.id"],
            ondelete="RESTRICT", name="fk_saasyto_run_campaign_org",
        ),
        CheckConstraint("status IN ('approved','cancelled','completed')",
                        name="ck_saasyto_run_status"),
        Index("ix_saasyto_due", "organization_id", "status", "due_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by_admin_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="RESTRICT"), nullable=False,
    )
    eligible_count: Mapped[int] = mapped_column(nullable=False)
    suppressed_count: Mapped[int] = mapped_column(nullable=False)


class SaasytoCampaignRecipient(Base):
    """Unique per-recipient durable queue. Claimed records are never re-sent."""

    __tablename__ = "saasyto_campaign_recipients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "run_id"],
            ["saasyto_campaign_runs.organization_id", "saasyto_campaign_runs.id"],
            ondelete="RESTRICT", name="fk_saasyto_recipient_run_org",
        ),
        UniqueConstraint("run_id", "recipient_kind", "recipient_id",
                         name="uq_saasyto_run_recipient"),
        CheckConstraint("recipient_kind IN ('prospect','promoter')",
                        name="ck_saasyto_recipient_kind"),
        CheckConstraint(
            "status IN ('queued','claimed','accepted_unverified','rejected',"
            "'unknown','suppressed')",
            name="ck_saasyto_recipient_status",
        ),
        Index("ix_saasyto_recipient_queue", "organization_id", "status", "run_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    approved_phone_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommunicationRule(Base):
    """Trigger configuration only. No auto-sender is wired to these definitions."""

    __tablename__ = "communication_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_comm_rule_org_id"),
        UniqueConstraint("organization_id", "name_key", name="uq_comm_rule_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_key: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_kind: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("communication_templates.id", ondelete="RESTRICT"),
        nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CommunicationConsentEvent(Base):
    """Append-only, channel-specific consent/revocation evidence.

    Historical whatsapp_opt_in flags remain intact. An Admin may attest an
    explicit grant with a reference; missing proof never grants email permission.
    """
    __tablename__ = "communication_consent_events"
    __table_args__ = (
        CheckConstraint("recipient_kind IN ('prospect','promoter')",
                        name="ck_comm_consent_kind"),
        CheckConstraint("channel IN ('whatsapp','email')",
                        name="ck_comm_consent_channel"),
        CheckConstraint("decision IN ('opted_in','opted_out')",
                        name="ck_comm_consent_decision"),
        Index("ix_comm_consent_person", "organization_id", "recipient_kind",
              "recipient_id", "channel", "recorded_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    recipient_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    decision: Mapped[str] = mapped_column(String(12), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(160))
    actor_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CommunicationPreparation(Base):
    """One immutable, simulation-only consent check, never a dispatch job."""
    __tablename__ = "communication_preparations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "campaign_id"],
            ["communication_campaigns.organization_id", "communication_campaigns.id"],
            ondelete="RESTRICT", name="fk_comm_prep_campaign_org",
        ),
        UniqueConstraint("organization_id", "id", name="uq_comm_prep_org_id"),
        UniqueConstraint("organization_id", "request_id", name="uq_comm_prep_request"),
        Index("ix_comm_prep_campaign", "organization_id", "campaign_id", "evaluated_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    eligible_count: Mapped[int] = mapped_column(nullable=False)
    suppressed_count: Mapped[int] = mapped_column(nullable=False)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommunicationRecipientSnapshot(Base):
    """Recipient-level review decision; no address/body stored, no delivery state."""
    __tablename__ = "communication_recipient_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "preparation_id"],
            ["communication_preparations.organization_id", "communication_preparations.id"],
            ondelete="RESTRICT", name="fk_comm_recipient_prep_org",
        ),
        UniqueConstraint("preparation_id", "recipient_kind", "recipient_id",
                         name="uq_comm_recipient_once"),
        CheckConstraint("recipient_kind IN ('prospect','promoter')",
                        name="ck_comm_recipient_kind"),
        CheckConstraint("channel IN ('whatsapp','email')",
                        name="ck_comm_recipient_channel"),
        CheckConstraint("status IN ('eligible','suppressed')",
                        name="ck_comm_recipient_state"),
        Index("ix_comm_recipient_org_prep", "organization_id", "preparation_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    preparation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    recipient_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(32))


class ReminderBatch(Base):
    """An Admin-prepared monthly candidate batch; never delivery authorization."""

    __tablename__ = "reminder_batches"
    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="uq_reminder_batch_org_id"),
        UniqueConstraint(
            "organization_id", "kind", "period_month",
            name="uq_reminder_one_batch_kind_month",
        ),
        UniqueConstraint(
            "organization_id", "request_id", name="uq_reminder_batch_request",
        ),
        CheckConstraint(
            "kind IN ('sponsor', 'promoter')", name="ck_reminder_batch_kind",
        ),
        CheckConstraint("recipient_count >= 0", name="ck_reminder_batch_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_on: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_count: Mapped[int] = mapped_column(nullable=False)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReminderIntent(Base):
    """One consent-gated recipient per monthly batch, never sent in Phase 10."""

    __tablename__ = "reminder_intents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "batch_id"],
            ["reminder_batches.organization_id", "reminder_batches.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_batch_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "prospect_id"],
            ["prospects.organization_id", "prospects.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_prospect_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "promoter_id"],
            ["promoters.organization_id", "promoters.id"],
            ondelete="RESTRICT", name="fk_reminder_intent_promoter_org",
        ),
        UniqueConstraint(
            "organization_id", "kind", "prospect_id", "period_month",
            name="uq_reminder_once_sponsor_month",
        ),
        UniqueConstraint(
            "organization_id", "kind", "promoter_id", "period_month",
            name="uq_reminder_once_promoter_month",
        ),
        UniqueConstraint("organization_id", "id", name="uq_reminder_intent_org_id"),
        CheckConstraint(
            "kind IN ('sponsor', 'promoter')",
            name="ck_reminder_intent_kind",
        ),
        CheckConstraint(
            "(kind = 'sponsor' AND prospect_id IS NOT NULL AND promoter_id IS NULL)"
            " OR (kind = 'promoter' AND promoter_id IS NOT NULL AND prospect_id IS NULL)",
            name="ck_reminder_recipient_exclusive",
        ),
        CheckConstraint(
            "status IN ('prepared', 'cancelled')",
            name="ck_reminder_preintegration_state",
        ),
        CheckConstraint(
            "outstanding_paise > 0 AND sponsor_count > 0",
            name="ck_reminder_positive_outstanding",
        ),
        Index(
            "ix_reminder_org_period_kind",
            "organization_id", "period_month", "kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    prospect_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    promoter_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_on: Mapped[date] = mapped_column(Date, nullable=False)
    sponsor_count: Mapped[int] = mapped_column(nullable=False)
    outstanding_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sponsor_snapshot: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="prepared"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MessageDispatch(Base):
    """One durable external dispatch per source. No automatic retry on uncertainty."""

    __tablename__ = "message_dispatches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "outbox_id"],
            ["message_outbox.organization_id", "message_outbox.id"],
            ondelete="RESTRICT", name="fk_dispatch_outbox_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reminder_intent_id"],
            ["reminder_intents.organization_id", "reminder_intents.id"],
            ondelete="RESTRICT", name="fk_dispatch_reminder_org",
        ),
        UniqueConstraint("organization_id", "id", name="uq_dispatch_org_id"),
        UniqueConstraint("organization_id", "outbox_id", name="uq_dispatch_outbox"),
        UniqueConstraint("organization_id", "reminder_intent_id",
                         name="uq_dispatch_reminder"),
        CheckConstraint(
            "(outbox_id IS NOT NULL AND reminder_intent_id IS NULL) OR "
            "(outbox_id IS NULL AND reminder_intent_id IS NOT NULL)",
            name="ck_dispatch_exactly_one_source",
        ),
        CheckConstraint(
            "status IN ('claimed', 'accepted', 'unknown', 'failed', "
            "'cancelled', 'sent', 'delivered')",
            name="ck_dispatch_status",
        ),
        Index("ix_dispatch_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reminder_intent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageDeliveryEvent(Base):
    """Signed provider callback idempotency without recipient PII."""

    __tablename__ = "message_delivery_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "dispatch_id"],
            ["message_dispatches.organization_id", "message_dispatches.id"],
            ondelete="RESTRICT", name="fk_delivery_event_dispatch_org",
        ),
        UniqueConstraint("organization_id", "event_id", name="uq_delivery_callback_event"),
        CheckConstraint("status IN ('sent', 'delivered', 'failed')",
                        name="ck_delivery_callback_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    dispatch_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
