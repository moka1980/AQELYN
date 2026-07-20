"""12-factor configuration (EA-0001 §8, ADR-0001 D9)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from aqelyn.conventions.errors import ConfigError

DEFAULT_ACG_ASSESSABLE_OBJECT_TYPES = (
    "asset",
    "cloud_compute",
    "cloud_database",
    "cloud_iam",
    "cloud_network",
    "cloud_storage",
    "cloud_unknown",
    "saas_app",
    "saas_unknown",
)


def _default_acg_assessable_object_types() -> list[str]:
    return list(DEFAULT_ACG_ASSESSABLE_OBJECT_TYPES)


def _default_acg_classification_rules() -> list[dict[str, Any]]:
    return [
        {
            "asset_class": object_type,
            "condition": {"op": "eq", "attr": "object_type", "value": object_type},
        }
        for object_type in DEFAULT_ACG_ASSESSABLE_OBJECT_TYPES
        if object_type != "asset"
    ]


def _default_dspm_sensitivity_factors() -> dict[str, float]:
    return {
        "public": 0.0,
        "internal": 0.25,
        "pii": 0.8,
        "secret": 1.0,
    }


class AQELYNConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AQELYN_", extra="ignore")

    env: str = "local"
    log_level: str = "INFO"
    tenant_mode: Literal["local", "enterprise"] = "local"
    backend: Literal["memory", "postgres"] = "memory"
    database_url: str | None = None
    redis_url: str | None = None
    acg_batch_size: int = 100
    acg_assessable_object_types: list[str] = Field(
        default_factory=_default_acg_assessable_object_types
    )
    acg_classification_rules: list[dict[str, Any]] = Field(
        default_factory=_default_acg_classification_rules
    )
    acg_unknown_is_fail: bool = True
    cspm_type_map: dict[str, str] = Field(default_factory=dict)
    cspm_fact_paths: dict[str, dict[str, str]] = Field(default_factory=dict)
    cspm_baseline_ids: list[str] = Field(default_factory=list)
    sspm_type_map: dict[str, str] = Field(default_factory=dict)
    sspm_baseline_ids: list[str] = Field(default_factory=list)
    sspm_sensitive_scopes: list[str] = Field(default_factory=list)
    sspm_batch_size: int = 100
    sspm_integration_max_nodes: int = 10_000
    dspm_classifier_rules: list[dict[str, Any]] = Field(default_factory=list)
    dspm_sensitivity_factors: dict[str, float] = Field(
        default_factory=_default_dspm_sensitivity_factors
    )
    dspm_batch_size: int = 100
    dspm_max_work: int = 5_000
    dspm_max_fields_per_store: int = 1_000
    dspm_max_signals_per_field: int = 100
    supplychain_license_policy_id: str | None = None
    supplychain_sensitive_scopes: list[str] = Field(default_factory=list)
    supplychain_max_depth: int = 6
    supplychain_batch_size: int = 100

    @classmethod
    def load(cls) -> AQELYNConfig:
        try:
            cfg = cls()
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc
        if cfg.backend == "postgres" and not cfg.database_url:
            raise ConfigError("backend=postgres requires AQELYN_DATABASE_URL")
        return cfg
