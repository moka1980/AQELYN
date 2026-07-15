"""PostgreSQL DDL for the Security Data Lake (EA-0019 L2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_lake_dataset (
    name                text NOT NULL,
    tenant_id           text NULL,
    schema              jsonb NOT NULL,
    classifications     jsonb NOT NULL,
    retention_policy_id text NULL,
    indexed_fields      jsonb NOT NULL DEFAULT '[]',
    set_by              jsonb NOT NULL,
    set_at              timestamptz NOT NULL,
    version             int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_lake_dataset_scope_name
    ON aq_lake_dataset (COALESCE(tenant_id, ''), name);
CREATE INDEX IF NOT EXISTS ix_lake_dataset_tenant_name
    ON aq_lake_dataset (tenant_id, name);

CREATE TABLE IF NOT EXISTS aq_lake_record (
    id              text NOT NULL,
    tenant_id       text NULL,
    dataset         text NOT NULL,
    source_id       text NOT NULL,
    occurred_at     timestamptz NOT NULL,
    ingested_at     timestamptz NOT NULL,
    fields          jsonb NOT NULL,
    raw_ref         jsonb NULL,
    schema_version  int NOT NULL CHECK (schema_version >= 1),
    retention_state text NOT NULL CHECK (retention_state IN ('active','archived','expired')),
    legal_hold      boolean NOT NULL DEFAULT false,
    evidence_id     text NULL
) PARTITION BY RANGE (occurred_at);
CREATE TABLE IF NOT EXISTS aq_lake_record_default
    PARTITION OF aq_lake_record DEFAULT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_lake_record_default_id
    ON aq_lake_record_default (id);
CREATE INDEX IF NOT EXISTS ix_lake_record_tenant_dataset_time
    ON aq_lake_record (tenant_id, dataset, occurred_at, id);

CREATE TABLE IF NOT EXISTS aq_lake_quarantine (
    seq         bigserial PRIMARY KEY,
    tenant_id   text NULL,
    source_id   text NOT NULL,
    reason      text NOT NULL,
    received_at timestamptz NOT NULL,
    raw_ref     jsonb NULL
);
CREATE INDEX IF NOT EXISTS ix_lake_quarantine_tenant_time
    ON aq_lake_quarantine (tenant_id, received_at, seq);
"""
