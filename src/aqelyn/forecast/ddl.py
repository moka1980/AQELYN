"""PostgreSQL DDL for Forecasting stores (EA-0021 P2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_forecast (
    id             text PRIMARY KEY,
    tenant_id      text NULL,
    metric         text NOT NULL,
    subject_ref    text NOT NULL,
    method         text NOT NULL,
    model_version  int NOT NULL CHECK (model_version >= 1),
    horizon_days   int NOT NULL CHECK (horizon_days >= 1),
    issued_at      timestamptz NOT NULL,
    resolves_at    timestamptz NOT NULL,
    point          double precision NOT NULL,
    interval       jsonb NOT NULL,
    confidence     double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    basis          jsonb NOT NULL,
    derivation     jsonb NOT NULL,
    advisory       boolean NOT NULL CHECK (advisory = true),
    statement      text NOT NULL,
    outcome        jsonb NULL,
    CHECK (resolves_at > issued_at)
);
CREATE INDEX IF NOT EXISTS ix_forecast_tenant_metric_issued
    ON aq_forecast (tenant_id, metric, issued_at, id);
CREATE INDEX IF NOT EXISTS ix_forecast_due
    ON aq_forecast (tenant_id, resolves_at, id)
    WHERE outcome IS NULL;

CREATE TABLE IF NOT EXISTS aq_prediction_model (
    id           text PRIMARY KEY,
    tenant_key   text NOT NULL,
    tenant_id    text NULL,
    method       text NOT NULL,
    params       jsonb NOT NULL DEFAULT '{}',
    version      int NOT NULL CHECK (version >= 1),
    promoted_by  jsonb NULL,
    promoted_at  timestamptz NULL,
    active       boolean NOT NULL DEFAULT false,
    evidence_id  text NULL,
    UNIQUE (tenant_key, method, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prediction_model_active
    ON aq_prediction_model (tenant_key, method)
    WHERE active = true;
"""
