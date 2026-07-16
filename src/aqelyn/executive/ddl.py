"""PostgreSQL DDL for Executive Intelligence stores (EA-0022 X2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_kpi_definition (
    id           text PRIMARY KEY,
    kpi_key      text NOT NULL,
    version      int NOT NULL CHECK (version >= 1),
    title        text NOT NULL,
    inputs       jsonb NOT NULL DEFAULT '[]',
    combinator   text NOT NULL,
    unit         text NOT NULL,
    thresholds   jsonb NOT NULL DEFAULT '{}',
    promoted_by  jsonb NULL,
    promoted_at  timestamptz NULL,
    active       boolean NOT NULL DEFAULT false,
    UNIQUE (kpi_key, version)
);
CREATE INDEX IF NOT EXISTS ix_kpi_definition_key_active
    ON aq_kpi_definition (kpi_key, active, version DESC, id);

CREATE TABLE IF NOT EXISTS aq_executive_report (
    id              text PRIMARY KEY,
    tenant_id       text NULL,
    title           text NOT NULL,
    version         int NOT NULL CHECK (version >= 1),
    period          text NOT NULL,
    sections        jsonb NOT NULL DEFAULT '[]',
    exceptions      jsonb NOT NULL DEFAULT '[]',
    approval_status text NOT NULL
                    CHECK (approval_status IN ('draft','pending','approved','published')),
    issued_at       timestamptz NULL,
    issued_by       jsonb NULL,
    content_hash    text NULL,
    frozen          boolean NOT NULL DEFAULT false,
    scope           jsonb NOT NULL DEFAULT '{}',
    excludes        jsonb NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS ix_executive_report_tenant_period
    ON aq_executive_report (tenant_id, period, id);

CREATE OR REPLACE FUNCTION aq_executive_report_frozen_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.frozen = true THEN
        RAISE EXCEPTION 'aq_executive_report row is frozen' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS aq_executive_report_no_frozen_update
    ON aq_executive_report;
CREATE TRIGGER aq_executive_report_no_frozen_update
    BEFORE UPDATE ON aq_executive_report
    FOR EACH ROW EXECUTE FUNCTION aq_executive_report_frozen_guard();
"""
