"""PostgreSQL DDL for Identity & Access Governance certifications (EA-0011 I3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_iag_certification (
    id          text PRIMARY KEY,
    tenant_id   text NULL,
    name        text NOT NULL,
    scope       jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL
                CHECK (status IN ('open','in_progress','completed','expired')),
    items       jsonb NOT NULL DEFAULT '[]',
    created_by  jsonb NOT NULL,
    created_at  timestamptz NOT NULL,
    due_at      timestamptz NULL,
    version     int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS ix_iag_certification_tenant_status
    ON aq_iag_certification (tenant_id, status, id);
"""
