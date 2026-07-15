"""PostgreSQL DDL for Threat Detection stores (EA-0017 D2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_detection_rule (
    id             text NOT NULL,
    version        int NOT NULL CHECK (version >= 1),
    name           text NOT NULL,
    description    text NOT NULL,
    kind           text NOT NULL,
    condition      jsonb NOT NULL,
    subject_type   text NOT NULL,
    technique_ids  jsonb NOT NULL DEFAULT '[]',
    severity       text NOT NULL,
    enabled        boolean NOT NULL,
    tenant_id      text NULL,
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS ix_detection_rule_tenant_enabled
    ON aq_detection_rule (tenant_id, enabled, id, version DESC);

CREATE TABLE IF NOT EXISTS aq_behavior_profile (
    id                 text NOT NULL,
    version            int NOT NULL CHECK (version >= 1),
    tenant_id          text NULL,
    subject_ref        text NOT NULL,
    metric             text NOT NULL,
    window_days        int NOT NULL CHECK (window_days >= 1),
    baseline           jsonb NOT NULL DEFAULT '{}',
    computed_at        timestamptz NOT NULL,
    insufficient_data  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS ix_behavior_profile_latest
    ON aq_behavior_profile (tenant_id, subject_ref, metric, version DESC);
"""
