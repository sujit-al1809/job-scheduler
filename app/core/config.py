"""Application settings, loaded from environment / .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://scheduler:scheduler@localhost:5432/scheduler"
    )
    test_database_url: str = (
        "postgresql+asyncpg://scheduler:scheduler@localhost:5433/scheduler_test"
    )

    # --- Auth ---
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 60

    # --- Worker ---
    worker_concurrency: int = 8
    worker_poll_interval_s: float = 1.0
    worker_claim_batch_size: int = 10
    drain_timeout_s: float = 30.0

    # --- Heartbeats / reaper ---
    heartbeat_interval_s: float = 5.0
    heartbeat_timeout_s: float = 30.0

    # --- Scheduler ---
    scheduler_poll_interval_s: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
