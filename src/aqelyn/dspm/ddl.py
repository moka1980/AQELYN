"""PostgreSQL DDL for append-only DSPM records (EA-0031 P2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_dspm_asset_key (
    tenant_key  text NOT NULL,
    tenant_id   text NULL,
    store_id    text NOT NULL CHECK (length(trim(store_id)) > 0),
    asset_id    text NOT NULL UNIQUE,
    PRIMARY KEY (tenant_key, store_id)
);

CREATE TABLE IF NOT EXISTS aq_dspm_asset (
    id                  text NOT NULL,
    version             integer NOT NULL CHECK (version >= 1),
    tenant_id           text NULL,
    store_id            text NOT NULL CHECK (length(trim(store_id)) > 0),
    store_type          text NOT NULL CHECK (length(trim(store_type)) > 0),
    classification      text NULL CHECK (
        classification IS NULL OR classification IN ('public','internal','pii','secret')
    ),
    classification_status text NOT NULL CHECK (
        classification_status IN ('complete','partial','unknown','conflict')
    ),
    flagged             boolean NOT NULL,
    payload             jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (id, version)
);
CREATE INDEX IF NOT EXISTS ix_dspm_asset_query
    ON aq_dspm_asset (tenant_id, id, version DESC);

CREATE TABLE IF NOT EXISTS aq_dspm_exposure (
    id          text PRIMARY KEY,
    tenant_id   text NULL,
    payload     jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE IF NOT EXISTS aq_dspm_assessment (
    id          text PRIMARY KEY,
    tenant_id   text NULL,
    payload     jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object')
);

CREATE OR REPLACE FUNCTION aq_dspm_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_dspm_asset_no_update_delete ON aq_dspm_asset;
CREATE TRIGGER aq_dspm_asset_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_dspm_asset
    FOR EACH ROW EXECUTE FUNCTION aq_dspm_append_only();

DROP TRIGGER IF EXISTS aq_dspm_asset_key_no_update_delete ON aq_dspm_asset_key;
CREATE TRIGGER aq_dspm_asset_key_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_dspm_asset_key
    FOR EACH ROW EXECUTE FUNCTION aq_dspm_append_only();

DROP TRIGGER IF EXISTS aq_dspm_exposure_no_update_delete ON aq_dspm_exposure;
CREATE TRIGGER aq_dspm_exposure_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_dspm_exposure
    FOR EACH ROW EXECUTE FUNCTION aq_dspm_append_only();

DROP TRIGGER IF EXISTS aq_dspm_assessment_no_update_delete ON aq_dspm_assessment;
CREATE TRIGGER aq_dspm_assessment_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_dspm_assessment
    FOR EACH ROW EXECUTE FUNCTION aq_dspm_append_only();
"""
