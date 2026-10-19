"""Deployment configuration, deliberately separate from organization business settings."""

from datetime import datetime
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import model_validator
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
