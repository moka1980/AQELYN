"""PostgreSQL DDL for Compliance & Governance snapshots (EA-0010 G3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_compliance_snapshot (
    id               text PRIMARY KEY,
    tenant_id        text NULL,
    run_at           timestamptz NOT NULL,
    scope            jsonb NOT NULL,
    overall_score    double precision NOT NULL CHECK (overall_score >= 0 AND overall_score <= 1),
    control_results  jsonb NOT NULL DEFAULT '[]',
    framework_scores jsonb NOT NULL DEFAULT '{}',
    evidence_id      text NULL
);
CREATE INDEX IF NOT EXISTS ix_compliance_snapshot_tenant_run
    ON aq_compliance_snapshot (tenant_id, run_at DESC, id);
"""
