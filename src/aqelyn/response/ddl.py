"""PostgreSQL DDL for Response Orchestration persistence (EA-0018 R2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_response_campaign (
    id                text PRIMARY KEY,
    tenant_id         text NULL,
    incident_id       text NULL,
    source_finding_id text NULL,
    phases            jsonb NOT NULL DEFAULT '[]',
    status            text NOT NULL
                      CHECK (status IN ('planned','awaiting_approval','running',
                                        'completed','failed','halted')),
    created_by        jsonb NOT NULL,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL,
    evidence_ids      jsonb NOT NULL DEFAULT '[]',
    version           int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS ix_response_campaign_tenant_status
    ON aq_response_campaign (tenant_id, status, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS aq_response_trigger (
    id          text PRIMARY KEY,
    tenant_id   text NULL,
    name        text NOT NULL,
    condition   jsonb NOT NULL,
    playbook_id text NOT NULL,
    max_effect  text NOT NULL CHECK (max_effect IN ('read_only','reversible')),
    enabled     boolean NOT NULL,
    version     int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE INDEX IF NOT EXISTS ix_response_trigger_tenant_enabled
    ON aq_response_trigger (tenant_id, enabled, id);
"""
