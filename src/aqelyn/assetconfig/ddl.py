"""PostgreSQL DDL for Asset & Configuration Governance stores (EA-0012 A3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_acg_baseline (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    asset_class text NOT NULL,
    version     int NOT NULL CHECK (version >= 1),
    checks      jsonb NOT NULL,
    tenant_id   text NULL,
    set_by      jsonb NOT NULL,
    set_at      timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_acg_baseline_tenant_class
    ON aq_acg_baseline (tenant_id, asset_class, id);

CREATE TABLE IF NOT EXISTS aq_acg_drift_snapshot (
    id            text PRIMARY KEY,
    tenant_id     text NULL,
    run_at        timestamptz NOT NULL,
    scope         jsonb NOT NULL DEFAULT '{}',
    baseline_ids  jsonb NOT NULL DEFAULT '[]',
    overall_score double precision NOT NULL CHECK (overall_score >= 0 AND overall_score <= 1),
    asset_drifts  jsonb NOT NULL DEFAULT '[]',
    coverage_complete boolean NOT NULL DEFAULT false,
    objects_in_scope int NOT NULL DEFAULT 0,
    objects_assessed int NOT NULL DEFAULT 0,
    unassessed_object_ids jsonb NOT NULL DEFAULT '[]',
    coverage_by_object_type jsonb NOT NULL DEFAULT '[]',
    evidence_id   text NULL
);
ALTER TABLE aq_acg_drift_snapshot
    ADD COLUMN IF NOT EXISTS coverage_complete boolean NOT NULL DEFAULT false;
ALTER TABLE aq_acg_drift_snapshot
    ADD COLUMN IF NOT EXISTS objects_in_scope int NOT NULL DEFAULT 0;
ALTER TABLE aq_acg_drift_snapshot
    ADD COLUMN IF NOT EXISTS objects_assessed int NOT NULL DEFAULT 0;
ALTER TABLE aq_acg_drift_snapshot
    ADD COLUMN IF NOT EXISTS unassessed_object_ids jsonb NOT NULL DEFAULT '[]';
ALTER TABLE aq_acg_drift_snapshot
    ADD COLUMN IF NOT EXISTS coverage_by_object_type jsonb NOT NULL DEFAULT '[]';
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_acg_snapshot_coverage_counts'
          AND conrelid = 'aq_acg_drift_snapshot'::regclass
    ) THEN
        ALTER TABLE aq_acg_drift_snapshot
            ADD CONSTRAINT ck_acg_snapshot_coverage_counts CHECK (
                objects_in_scope >= 0
                AND objects_assessed >= 0
                AND objects_assessed <= objects_in_scope
            );
    END IF;
END;
$$;
CREATE INDEX IF NOT EXISTS ix_acg_drift_snapshot_tenant_run
    ON aq_acg_drift_snapshot (tenant_id, run_at DESC, id);

CREATE OR REPLACE FUNCTION aq_acg_drift_snapshot_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'aq_acg_drift_snapshot is append-only' USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_acg_drift_snapshot_no_update_delete
    ON aq_acg_drift_snapshot;
CREATE TRIGGER aq_acg_drift_snapshot_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_acg_drift_snapshot
    FOR EACH ROW EXECUTE FUNCTION aq_acg_drift_snapshot_append_only();
"""
