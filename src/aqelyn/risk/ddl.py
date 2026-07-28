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
    mission_context     jsonb NOT NULL DEFAULT '{
                            "status":"unknown",
                            "factor":null,
                            "top_mission_id":null,
                            "unknown_cause":"input_missing",
                            "reason":"EA-0007 mission context has not been supplied."
                        }',
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
ALTER TABLE aq_risk
    ADD COLUMN IF NOT EXISTS mission_context jsonb NULL;
UPDATE aq_risk
SET mission_context = CASE
    WHEN top_mission_id IS NOT NULL AND factors ? 'mission_factor' THEN
        jsonb_build_object(
            'status', 'known',
            'factor', factors->'mission_factor',
            'top_mission_id', top_mission_id,
            'unknown_cause', NULL,
            'reason', 'Migrated from the historically persisted EA-0007 mission factor.'
        )
    ELSE
        jsonb_build_object(
            'status', 'unknown',
            'factor', NULL,
            'top_mission_id', NULL,
            'unknown_cause', 'input_missing',
            'reason', 'Historical risk did not preserve a known EA-0007 mission context.'
        )
END
WHERE mission_context IS NULL;
ALTER TABLE aq_risk
    ALTER COLUMN mission_context SET DEFAULT '{
        "status":"unknown",
        "factor":null,
        "top_mission_id":null,
        "unknown_cause":"input_missing",
        "reason":"EA-0007 mission context has not been supplied."
    }'::jsonb,
    ALTER COLUMN mission_context SET NOT NULL;
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
