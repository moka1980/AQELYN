"""PostgreSQL DDL for CSPM normalized projections (EA-0028 Y2)."""

from __future__ import annotations

DDL = """
CREATE OR REPLACE FUNCTION aq_jsonb_object_keys_equal(left_value jsonb, right_value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT
        (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(left_value) AS item(key))
        IS NOT DISTINCT FROM
        (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(right_value) AS item(key))
$$;

CREATE TABLE IF NOT EXISTS aq_cloud_normalization (
    object_id          text PRIMARY KEY,
    object_type        text NOT NULL CHECK (length(trim(object_type)) > 0),
    tenant_id          text NULL,
    provider           text NOT NULL CHECK (provider IN ('aws','azure','gcp','oci','other')),
    account            text NOT NULL CHECK (length(trim(account)) > 0),
    region             text NULL CHECK (region IS NULL OR length(trim(region)) > 0),
    native_facts       jsonb NOT NULL CHECK (jsonb_typeof(native_facts) = 'object'),
    field_provenance   jsonb NOT NULL CHECK (jsonb_typeof(field_provenance) = 'object'),
    conflicts          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(conflicts) = 'array'),
    evidence_id        text NOT NULL,
    flagged            boolean NOT NULL DEFAULT false,
    CHECK (aq_jsonb_object_keys_equal(native_facts, field_provenance))
);
CREATE INDEX IF NOT EXISTS ix_cloud_normalization_tenant_provider
    ON aq_cloud_normalization (tenant_id, provider, object_id);
"""
