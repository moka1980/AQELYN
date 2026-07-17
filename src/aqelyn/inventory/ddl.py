"""PostgreSQL DDL for Inventory stores (EA-0025 N2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_inventory_asset (
    id                 text PRIMARY KEY,
    tenant_id          text NULL,
    asset_type         text NOT NULL CHECK (length(trim(asset_type)) > 0),
    discovery_source   text NOT NULL CHECK (length(trim(discovery_source)) > 0),
    classification     text NULL CHECK (
                           classification IS NULL OR length(trim(classification)) > 0
                       ),
    owner              jsonb NULL,
    lifecycle_state    text NOT NULL CHECK (
                           lifecycle_state IN (
                               'provisioned','active','modified','unreported',
                               'decommissioned','archived'
                           )
                       ),
    confidence         double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    basis              jsonb NOT NULL CHECK (
                           jsonb_typeof(basis) = 'array' AND jsonb_array_length(basis) > 0
                       ),
    conflicts          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(conflicts) = 'array'),
    first_seen_at      timestamptz NOT NULL,
    last_reported_at   timestamptz NOT NULL,
    unreported_since   timestamptz NULL
);
CREATE INDEX IF NOT EXISTS ix_inventory_asset_tenant_lifecycle
    ON aq_inventory_asset (tenant_id, lifecycle_state, first_seen_at, id);
CREATE INDEX IF NOT EXISTS ix_inventory_asset_tenant_source
    ON aq_inventory_asset (tenant_id, discovery_source, last_reported_at DESC, id);

CREATE TABLE IF NOT EXISTS aq_inventory_asset_history (
    seq        bigserial PRIMARY KEY,
    asset_id   text NOT NULL,
    snapshot   jsonb NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_inventory_asset_history_asset
    ON aq_inventory_asset_history (asset_id, seq);

CREATE OR REPLACE FUNCTION aq_inventory_asset_history_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'aq_inventory_asset_history is append-only' USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_inventory_asset_history_no_update_delete
    ON aq_inventory_asset_history;
CREATE TRIGGER aq_inventory_asset_history_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_inventory_asset_history
    FOR EACH ROW EXECUTE FUNCTION aq_inventory_asset_history_append_only();
"""
