"""Deployment configuration, deliberately separate from organization business settings."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str

    @model_validator(mode="after")
    def validate_production_database(self) -> "Settings":
        if self.app_env in ("staging", "production") and not self.database_url.startswith(
            "postgresql+psycopg://"
        ):
            raise ValueError("Staging and production require PostgreSQL via psycopg")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
