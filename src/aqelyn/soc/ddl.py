"""PostgreSQL DDL for Security Operations persistence (EA-0015 S2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_soc_alert (
    id              text PRIMARY KEY,
    tenant_id       text NULL,
    source_kind     text NOT NULL CHECK (source_kind IN ('finding','threat_match','risk')),
    source_ref      text NOT NULL,
    evidence_id     text NULL,
    severity        text NOT NULL CHECK (severity IN ('info','low','medium','high','critical')),
    state           text NOT NULL CHECK (state IN ('new','triaged','suppressed','escalated')),
    correlation_key text NULL,
    created_at      timestamptz NOT NULL,
    version         int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_soc_alert_tenant_source
    ON aq_soc_alert (tenant_id, source_ref) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS ix_soc_alert_tenant_state
    ON aq_soc_alert (tenant_id, state, id);

CREATE TABLE IF NOT EXISTS aq_soc_incident (
    id                  text PRIMARY KEY,
    tenant_id           text NULL,
    title               text NOT NULL,
    status              text NOT NULL
                        CHECK (status IN ('new','triaged','investigating',
                                          'contained','resolved','closed')),
    priority            double precision NOT NULL CHECK (priority >= 0 AND priority <= 100),
    alert_ids           jsonb NOT NULL DEFAULT '[]',
    affected_object_ids jsonb NOT NULL DEFAULT '[]',
    top_mission_id      text NULL,
    mission_context     jsonb NOT NULL DEFAULT '{
                            "status":"unknown",
                            "factor":null,
                            "top_mission_id":null,
                            "unknown_cause":"input_missing",
                            "reason":"EA-0007 mission context has not been supplied."
                        }',
    risk_score          double precision NULL CHECK (
        risk_score IS NULL OR (risk_score >= 0 AND risk_score <= 100)
    ),
    assignee            jsonb NULL,
    timeline            jsonb NOT NULL DEFAULT '[]',
    created_by          jsonb NOT NULL,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL,
    version             int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
ALTER TABLE aq_soc_incident
    ADD COLUMN IF NOT EXISTS mission_context jsonb NOT NULL DEFAULT '{
        "status":"unknown",
        "factor":null,
        "top_mission_id":null,
        "unknown_cause":"input_missing",
        "reason":"Historical incident did not preserve an EA-0007 mission context."
    }';
CREATE INDEX IF NOT EXISTS ix_soc_incident_tenant_status_priority
    ON aq_soc_incident (tenant_id, status, priority DESC, updated_at DESC, id);
"""
