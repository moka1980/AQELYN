"""PostgreSQL DDL for Risk Intelligence stores (EA-0013 R3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_risk (
    id                  text PRIMARY KEY,
    tenant_id           text NULL,
    correlation_key     text NOT NULL,
    title               text NOT NULL,
    category            text NOT NULL,
    likelihood          double precision NOT NULL CHECK (likelihood >= 0 AND likelihood <= 1),
    impact              double precision NOT NULL CHECK (impact >= 0 AND impact <= 1),
    score               double precision NOT NULL CHECK (score >= 0 AND score <= 100),
    band                text NOT NULL
                        CHECK (band IN ('within_appetite','elevated','over_tolerance')),
    signals             jsonb NOT NULL DEFAULT '[]',
    affected_object_ids jsonb NOT NULL DEFAULT '[]',
    top_mission_id      text NULL,
    lifecycle           text NOT NULL
                        CHECK (lifecycle IN ('identified','assessed','treated','closed')),
    treatment           text NOT NULL
                        CHECK (treatment IN ('none','accept','mitigate','transfer')),
    treatment_note      text NULL,
    treated_by          jsonb NULL,
    reason              text NOT NULL,
    factors             jsonb NOT NULL DEFAULT '{}',
    first_seen_at       timestamptz NOT NULL,
    last_scored_at      timestamptz NOT NULL,
    version             int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_tenant_correlation
    ON aq_risk (tenant_id, correlation_key) NULLS NOT DISTINCT;
CREATE INDEX IF NOT EXISTS ix_risk_tenant_band_score
    ON aq_risk (tenant_id, band, score DESC, id);

CREATE TABLE IF NOT EXISTS aq_risk_snapshot (
    id               text PRIMARY KEY,
    tenant_id        text NULL,
    run_at           timestamptz NOT NULL,
    total            int NOT NULL CHECK (total >= 0),
    band_counts      jsonb NOT NULL DEFAULT '{}',
    top_risks        jsonb NOT NULL DEFAULT '[]',
    overall_exposure double precision NOT NULL CHECK (
        overall_exposure >= 0 AND overall_exposure <= 100
    )
);
CREATE INDEX IF NOT EXISTS ix_risk_snapshot_tenant_run
    ON aq_risk_snapshot (tenant_id, run_at DESC, id);

CREATE OR REPLACE FUNCTION aq_risk_snapshot_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'aq_risk_snapshot is append-only' USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_risk_snapshot_no_update_delete
    ON aq_risk_snapshot;
CREATE TRIGGER aq_risk_snapshot_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_risk_snapshot
    FOR EACH ROW EXECUTE FUNCTION aq_risk_snapshot_append_only();
"""
