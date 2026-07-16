"""PostgreSQL DDL for AI Decision Intelligence stores (EA-0020 E2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_decision_recommendation (
    id            text PRIMARY KEY,
    tenant_id     text NULL,
    subject_ref   text NOT NULL,
    statement     text NOT NULL,
    action_hint   jsonb NULL,
    confidence    double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    derivation    jsonb NOT NULL,
    advisory      boolean NOT NULL CHECK (advisory = true),
    created_at    timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decision_recommendation_tenant_created
    ON aq_decision_recommendation (tenant_id, created_at, id);

CREATE TABLE IF NOT EXISTS aq_decision_model_version (
    tenant_key   text NOT NULL,
    tenant_id    text NULL,
    version      int NOT NULL CHECK (version >= 1),
    params       jsonb NOT NULL DEFAULT '{}',
    promoted_by  jsonb NULL,
    promoted_at  timestamptz NULL,
    active       boolean NOT NULL DEFAULT false,
    evidence_id  text NULL,
    PRIMARY KEY (tenant_key, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_model_version_active
    ON aq_decision_model_version (tenant_key)
    WHERE active = true;
"""
