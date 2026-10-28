"""Deployment configuration, deliberately separate from organization business settings."""

from datetime import datetime
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str
    auth_secret: str | None = None
    upi_match_secret: str | None = None
    # Never enable for staging/production; local ephemeral DB only.
    local_demo_login_enabled: bool = False

    # Global kill switch, independent of organization settings.
    messaging_delivery_enabled: bool = False
    messaging_sender_approved: bool = False
    messaging_enable_after: datetime | None = None
    messaging_runner_secret: str | None = None
    messaging_callback_secret: str | None = None
    pabbly_webhook_url: str | None = None
    pabbly_signature_secret: str | None = None
    whatsapp_template_payment: str | None = None
    whatsapp_template_sponsor: str | None = None
    whatsapp_template_promoter: str | None = None
    promoter_disclosure_approved: bool = False
    # Saasyto account/API connector. Separate from the existing Pabbly reminder
    # transport and Meta Cloud OTP adapter. Default OFF, even with credentials.
    saasyto_delivery_enabled: bool = False
    saasyto_sender_approved: bool = False
    saasyto_instance_id: str | None = None
    saasyto_access_token: SecretStr | None = None
    saasyto_enable_after: datetime | None = None
    saasyto_runner_secret: SecretStr | None = None
    # Bounded campaign dispatch. 10 requests/minute is a conservative
    # engineering default, NOT a verified Saasyto API capacity. Raising this
    # requires provider confirmation and a controlled production pilot.
    saasyto_campaign_batch_size: int = Field(default=10, ge=1, le=15)
    saasyto_campaign_max_per_minute: int = Field(default=10, ge=1, le=60)
    # Conservative default for a QR-linked/personal WhatsApp sender. Saasyto
    # publicly recommends a 90-120s interval for its personal-account UI.
    # The direct-send API has no confirmed numeric quota. An independently
    # approved official/API sender may explicitly configure a smaller gap.
    saasyto_campaign_min_interval_seconds: int = Field(default=90, ge=0, le=300)
    # Explicit 429 pauses future queued recipients; the rejected attempt
    # remains terminal to avoid unsafe replay without provider idempotency.
    saasyto_rate_limit_pause_minutes: int = Field(default=15, ge=5, le=60)

    # One-recipient, opt-in local pilot. This is deliberately NOT a generic
    # development-mode bypass of the normal production sending restriction.
    saasyto_local_test_enabled: bool = False
    # Explicit localhost-only rehearsal with dynamic CRM recipients, never
    # an implicit bypass or a setting for the production environment.
    saasyto_local_dynamic_enabled: bool = False
    saasyto_local_test_phone: str | None = None
    # Optional second explicitly authorized recipient for an isolated local test.
    saasyto_local_test_phone_2: str | None = None

    # Separate from reminder messaging. Explicitly OFF unless Meta OTP is provisioned.
    otp_delivery_enabled: bool = False
    # Single allowlisted WhatsApp pilot, never a production OTP sender.
    otp_local_pilot_enabled: bool = False
    # Explicit Saasyto OTP transport for selected registered prospects.
    # Allowed on approved production sender or protected dynamic localhost demo;
    # separate from the allowlisted pilot and optional Meta transport.
    otp_saasyto_enabled: bool = False
    # Optional one-time Saasyto acknowledgement after successful OTP activation.
    otp_activation_notice_enabled: bool = False
    otp_secret: str | None = None
    otp_meta_access_token: str | None = None
    otp_meta_phone_number_id: str | None = None
    otp_meta_template_name: str | None = None
    otp_meta_template_language: str = "en_US"
    otp_meta_graph_version: str = "v23.0"


    @model_validator(mode="after")
    def validate_production_database(self) -> "Settings":
        if self.local_demo_login_enabled:
            parsed = urlsplit(self.database_url)
            if not (
                self.app_env == "development"
                and parsed.scheme == "postgresql+psycopg"
                and parsed.hostname in ("127.0.0.1", "localhost")
                and parsed.port == 5432
                and parsed.username == "sas_dev"
                and parsed.path == "/sas_dev"
                and not parsed.query
            ):
                raise ValueError(
                    "Local demo credentials require the loopback-only sas_dev PostgreSQL database"
                )
        if self.app_env in ("staging", "production") and not self.database_url.startswith(
            "postgresql+psycopg://"
        ):
            raise ValueError("Staging and production require PostgreSQL via psycopg")
        if self.app_env in ("staging", "production") and (
            not self.auth_secret or len(self.auth_secret) < 32
        ):
            raise ValueError("Staging and production require AUTH_SECRET of at least 32 characters")
        if self.app_env in ("staging", "production") and (
            not self.upi_match_secret or len(self.upi_match_secret) < 32
        ):
            raise ValueError("Staging and production require UPI_MATCH_SECRET of 32+ characters")
        if self.app_env in ("staging", "production"):
            parsed_db = urlsplit(self.database_url)
            tls_options = parse_qs(parsed_db.query, keep_blank_values=True)
            modes = tls_options.get("sslmode", [])
            if (
                not parsed_db.hostname
                or len(modes) != 1
                or modes[0] not in {"require", "verify-ca", "verify-full"}
            ):
                raise ValueError(
                    "Staging and production DATABASE_URL must enable PostgreSQL TLS "
                    "with sslmode=require, verify-ca or verify-full"
                )
        if self.saasyto_local_dynamic_enabled:
            if not (self.app_env == "development" and self.local_demo_login_enabled):
                raise ValueError("Dynamic Saasyto local sending requires loopback demo mode")
            if self.saasyto_local_test_enabled or self.otp_local_pilot_enabled:
                raise ValueError("Dynamic local sending cannot combine with allowlisted pilot")
            if self.saasyto_local_test_phone or self.saasyto_local_test_phone_2:
                raise ValueError("Dynamic local mode cannot configure recipient phone numbers")
        if self.saasyto_local_test_enabled:
            import re

            if not (self.app_env == "development" and self.local_demo_login_enabled):
                raise ValueError("Saasyto local test requires protected loopback demo mode")
            # The local-demo validator above already enforces exactly
            # sas_dev@127.0.0.1:5432/sas_dev, no extra query parameters.
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", self.saasyto_local_test_phone or ""):
                raise ValueError("Saasyto local test requires an E.164 +country-code phone")
            if self.saasyto_local_test_phone_2 is not None:
                if not re.fullmatch(r"\+[1-9][0-9]{7,14}", self.saasyto_local_test_phone_2):
                    raise ValueError("Second local Saasyto recipient must be an E.164 phone")
                if self.saasyto_local_test_phone_2 == self.saasyto_local_test_phone:
                    raise ValueError("Local Saasyto pilot phones must be distinct")
        elif self.saasyto_local_test_phone_2:
            raise ValueError("Second local Saasyto phone requires guarded local test mode")
        if self.saasyto_delivery_enabled:
            import re

            local_pilot = self.app_env == "development" and (
                self.saasyto_local_test_enabled or self.saasyto_local_dynamic_enabled
            )
            if self.app_env not in ("production", "test") and not local_pilot:
                raise ValueError("Saasyto delivery requires approved production or local pilot")
            if not self.saasyto_enable_after or not self.saasyto_enable_after.tzinfo:
                raise ValueError("Saasyto enable-after cutoff must include a timezone")
            runner = (
                self.saasyto_runner_secret.get_secret_value()
                if self.saasyto_runner_secret else ""
            )
            if len(runner) < 32:
                raise ValueError("Saasyto runner secret must be 32+ characters")
            if not self.saasyto_sender_approved:
                raise ValueError("Saasyto sender and recipient-permission approval required")
            if not re.fullmatch(r"[a-zA-Z0-9_-]{6,80}", self.saasyto_instance_id or ""):
                raise ValueError("Configured Saasyto instance ID required")
            token = (
                self.saasyto_access_token.get_secret_value()
                if self.saasyto_access_token else ""
            )
            if len(token) < 12 or any(ch.isspace() for ch in token):
                raise ValueError("Valid Saasyto access token required")
        if self.otp_local_pilot_enabled:
            if not (
                self.app_env == "development"
                and self.local_demo_login_enabled
                and self.saasyto_local_test_enabled
                and self.saasyto_delivery_enabled
                and self.saasyto_sender_approved
                and not self.otp_delivery_enabled
            ):
                raise ValueError("Local OTP requires approved guarded Saasyto pilot only")
            if not self.otp_secret or len(self.otp_secret) < 32:
                raise ValueError("OTP_SECRET of 32+ characters is required")
        if self.otp_saasyto_enabled:
            if (
                (self.app_env != "production" and not self.saasyto_local_dynamic_enabled)
                or self.saasyto_local_test_enabled
                or self.otp_local_pilot_enabled
                or self.otp_delivery_enabled
                or not self.saasyto_delivery_enabled
                or not self.saasyto_sender_approved
            ):
                raise ValueError(
                    "Saasyto production OTP requires an approved production sender, "
                    "delivery enabled, and all local/Meta OTP modes disabled"
                )
            if not self.otp_secret or len(self.otp_secret) < 32:
                raise ValueError("OTP_SECRET of 32+ characters is required")
        if self.otp_activation_notice_enabled and not (
            self.saasyto_delivery_enabled
            and self.saasyto_sender_approved
            and (
                self.otp_delivery_enabled
                or self.otp_local_pilot_enabled
                or self.otp_saasyto_enabled
            )
        ):
            raise ValueError(
                "Activation notice requires approved Saasyto sending and enabled OTP"
            )
        if self.otp_delivery_enabled:
            import re

            if self.app_env not in ("production", "test"):
                raise ValueError("WhatsApp OTP delivery is restricted to approved production")
            if not self.otp_secret or len(self.otp_secret) < 32:
                raise ValueError("OTP_SECRET of 32+ characters is required")
            if not self.otp_meta_access_token or len(self.otp_meta_access_token) < 20:
                raise ValueError("Meta WhatsApp OTP access token required")
            if not re.fullmatch(r"[0-9]{5,25}", self.otp_meta_phone_number_id or ""):
                raise ValueError("Meta WhatsApp sender phone ID required")
            if not re.fullmatch(r"[a-z0-9_]{2,160}", self.otp_meta_template_name or ""):
                raise ValueError("Approved WhatsApp authentication template name required")
            if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", self.otp_meta_template_language):
                raise ValueError("Invalid WhatsApp authentication template language")
            if not re.fullmatch(r"v[0-9]{1,2}\.0", self.otp_meta_graph_version):
                raise ValueError("Unsupported Meta Graph API version")
        if self.messaging_delivery_enabled:
            if self.app_env not in ("test", "production"):
                raise ValueError("Messaging dispatch is restricted to approved production")
            if not self.messaging_sender_approved:
                raise ValueError("Messaging sender business approval is required")
            if (
                self.messaging_enable_after is None
                or self.messaging_enable_after.tzinfo is None
            ):
                raise ValueError("Messaging requires a timezone-aware enable-after cutoff")
            for label, secret in (
                ("runner", self.messaging_runner_secret),
                ("callback", self.messaging_callback_secret),
                ("Pabbly signature", self.pabbly_signature_secret),
            ):
                if secret is None or len(secret) < 32:
                    raise ValueError(f"Messaging {label} secret must be 32+ characters")
            url = urlsplit(self.pabbly_webhook_url or "")
            if (
                url.scheme != "https"
                or url.hostname != "connect.pabbly.com"
                or url.username or url.password or url.fragment
                or not url.path.startswith("/workflow/")
            ):
                raise ValueError("Use a configured HTTPS Pabbly Connect workflow webhook")
            if not all((
                self.whatsapp_template_payment,
                self.whatsapp_template_sponsor,
                self.whatsapp_template_promoter,
            )):
                raise ValueError("All approved WhatsApp template identifiers are required")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
