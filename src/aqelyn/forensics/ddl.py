"""PostgreSQL DDL for Digital Forensics artifact store (EA-0016 F2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_forensics_artifact (
    id                text PRIMARY KEY,
    tenant_id         text NULL,
    artifact_type     text NOT NULL,
    acquisition_id    text NOT NULL,
    object_id         text NOT NULL,
    evidence_id       text NOT NULL,
    metadata          jsonb NOT NULL DEFAULT '{}',
    linked_asset_ids  jsonb NOT NULL DEFAULT '[]',
    first_seen_at     timestamptz NOT NULL,
    case_id           text NULL
);
CREATE INDEX IF NOT EXISTS ix_forensics_artifact_tenant_case_seen
    ON aq_forensics_artifact (tenant_id, case_id, first_seen_at, id);
"""
