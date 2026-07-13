"""PostgreSQL DDL for Workflow Engine run persistence (EA-0008 W2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_workflow_run (
    id                text PRIMARY KEY,
    playbook_id       text NOT NULL,
    playbook_version  int NOT NULL CHECK (playbook_version >= 1),
    tenant_id         text NULL,
    status            text NOT NULL
                      CHECK (status IN ('proposed','simulated','awaiting_approval',
                                        'approved','running','completed','failed','halted')),
    source_finding_id text NULL,
    results           jsonb NOT NULL DEFAULT '[]',
    approvals         jsonb NOT NULL DEFAULT '[]',
    created_by        jsonb NOT NULL,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL,
    version           int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS ix_workflow_run_tenant
    ON aq_workflow_run (tenant_id, id);
"""
