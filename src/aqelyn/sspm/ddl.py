"""PostgreSQL DDL for SSPM normalized projections (EA-0029 Z2)."""

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

CREATE OR REPLACE FUNCTION aq_jsonb_array_nonempty(value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT jsonb_typeof(value) = 'array' AND jsonb_array_length(value) > 0
$$;

CREATE TABLE IF NOT EXISTS aq_saas_normalization (
    object_id          text PRIMARY KEY,
    tenant_id          text NULL,
    object_type        text NOT NULL CHECK (length(trim(object_type)) > 0),
    provider           text NOT NULL CHECK (length(trim(provider)) > 0),
    provider_tenant    text NOT NULL CHECK (length(trim(provider_tenant)) > 0),
    native_facts       jsonb NOT NULL CHECK (jsonb_typeof(native_facts) = 'object'),
    field_provenance   jsonb NOT NULL CHECK (jsonb_typeof(field_provenance) = 'object'),
    conflicts          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(conflicts) = 'array'),
    evidence_id        text NOT NULL,
    flagged            boolean NOT NULL DEFAULT false,
    CHECK (aq_jsonb_object_keys_equal(native_facts, field_provenance))
);
CREATE INDEX IF NOT EXISTS ix_saas_normalization_tenant_provider
    ON aq_saas_normalization (tenant_id, provider, object_id);

CREATE TABLE IF NOT EXISTS aq_saas_integration (
    object_id             text PRIMARY KEY,
    tenant_id             text NULL,
    integration_id        text NOT NULL CHECK (length(trim(integration_id)) > 0),
    grantor_ref           text NOT NULL,
    grantor_kind          text NOT NULL CHECK (grantor_kind IN ('api','identity')),
    third_party_app       text NOT NULL,
    third_party_external  boolean NOT NULL,
    scopes                jsonb NOT NULL CHECK (jsonb_typeof(scopes) = 'array'),
    over_scoped           text NOT NULL CHECK (
        over_scoped IN ('over_scoped','within_scope','unknown')
    ),
    reachable_object_ids  jsonb NOT NULL CHECK (
        jsonb_typeof(reachable_object_ids) = 'array'
    ),
    reach_status          text NOT NULL CHECK (
        reach_status IN ('computed','truncated','pending')
    ),
    known_surface_ref     text NULL,
    claim_confidence      double precision NOT NULL CHECK (
        claim_confidence >= 0.0 AND claim_confidence <= 1.0
    ),
    evidence_id           text NOT NULL,
    observed_at           timestamptz NOT NULL,
    reason                text NOT NULL CHECK (length(trim(reason)) > 0),
    CHECK (reach_status <> 'pending' OR jsonb_array_length(reachable_object_ids) = 0),
    CHECK (reach_status <> 'truncated' OR aq_jsonb_array_nonempty(reachable_object_ids)),
    CHECK (
        (over_scoped = 'over_scoped' AND third_party_external
            AND known_surface_ref = object_id)
        OR (over_scoped <> 'over_scoped' AND known_surface_ref IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_saas_integration_tenant_scope
    ON aq_saas_integration (tenant_id, over_scoped, object_id);
"""
