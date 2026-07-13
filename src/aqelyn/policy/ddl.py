"""PostgreSQL DDL for Policy Engine persistence (EA-0009 P3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_policy (
    id          text PRIMARY KEY,
    version     int NOT NULL CHECK (version >= 1),
    name        text NOT NULL,
    description text NOT NULL,
    tenant_id   text NULL,
    rules       jsonb NOT NULL DEFAULT '[]',
    standard    text NULL,
    set_by      jsonb NOT NULL,
    set_at      timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_policy_tenant
    ON aq_policy (tenant_id, id);
"""
