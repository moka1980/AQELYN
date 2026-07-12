"""12-factor configuration (EA-0001 §8, ADR-0001 D9)."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from aqelyn.conventions.errors import ConfigError


class AQELYNConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AQELYN_", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    tenant_mode: Literal["local", "enterprise"] = "local"
    backend: Literal["memory", "postgres"] = "memory"
    database_url: str | None = None
    redis_url: str | None = None

    @classmethod
    def load(cls) -> AQELYNConfig:
        try:
            cfg = cls()
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc
        if cfg.backend == "postgres" and not cfg.database_url:
            raise ConfigError("backend=postgres requires AQELYN_DATABASE_URL")
        return cfg
