"""PostgreSQL DDL for identity detections (EA-0027 I3)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_identity_detection (
    id                 text PRIMARY KEY,
    tenant_id          text NULL,
    subject_ref        text NOT NULL CHECK (length(trim(subject_ref)) > 0),
    detection_type     text NOT NULL CHECK (
                           detection_type IN (
                               'impossible_travel','credential_reuse','session_hijack',
                               'first_time_privilege_use','dormant_account_use','mfa_anomaly'
                           )
                       ),
    statement          text NOT NULL CHECK (length(trim(statement)) > 0),
    corroboration      jsonb NOT NULL CHECK (
                           jsonb_typeof(corroboration) = 'array'
                           AND jsonb_array_length(corroboration) >= 2
                       ),
    confidence         double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    basis              jsonb NOT NULL CHECK (
                           jsonb_typeof(basis) = 'array' AND jsonb_array_length(basis) > 0
                       ),
    derivation         jsonb NOT NULL CHECK (jsonb_typeof(derivation) = 'object'),
    profile_ref        text NOT NULL,
    entitlement_refs   jsonb NOT NULL DEFAULT '[]' CHECK (
                           jsonb_typeof(entitlement_refs) = 'array'
                       ),
    status             text NOT NULL CHECK (status IN ('open','reviewed','closed')),
    detected_at        timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_identity_detection_tenant_subject
    ON aq_identity_detection (tenant_id, subject_ref, detected_at, id);
CREATE INDEX IF NOT EXISTS ix_identity_detection_tenant_type
    ON aq_identity_detection (tenant_id, detection_type, detected_at, id);

CREATE OR REPLACE FUNCTION aq_identity_detection_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'aq_identity_detection is append-only' USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_identity_detection_no_update_delete
    ON aq_identity_detection;
CREATE TRIGGER aq_identity_detection_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_identity_detection
    FOR EACH ROW EXECUTE FUNCTION aq_identity_detection_append_only();
"""
