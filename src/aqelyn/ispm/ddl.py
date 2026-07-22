"""PostgreSQL DDL for EA-0033 ISPM records."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_ispm_identity_key (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    provider     text NOT NULL,
    external_id  text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS ix_ispm_identity_key_tenant_provider_id
    ON aq_ispm_identity_key (tenant_id, provider, id);

CREATE TABLE IF NOT EXISTS aq_ispm_identity_revision (
    revision       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id             text NOT NULL REFERENCES aq_ispm_identity_key(id),
    tenant_id      text NULL,
    provider       text NOT NULL,
    identity_kind  text NOT NULL CHECK (
        identity_kind IN (
            'human','service','machine','application','federated','temporary','unknown'
        )
    ),
    record          jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ispm_identity_revision_id_revision
    ON aq_ispm_identity_revision (id, revision DESC);
CREATE INDEX IF NOT EXISTS ix_ispm_identity_revision_tenant_provider_kind_id
    ON aq_ispm_identity_revision (tenant_id, provider, identity_kind, id, revision DESC);

CREATE TABLE IF NOT EXISTS aq_ispm_posture_score (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    subject_ref  text NOT NULL,
    record       jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ispm_posture_score_tenant_subject_id
    ON aq_ispm_posture_score (tenant_id, subject_ref, id);

CREATE TABLE IF NOT EXISTS aq_ispm_baseline_revision (
    revision       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id             text NOT NULL,
    tenant_id      text NULL,
    identity_kind  text NOT NULL CHECK (
        identity_kind IN ('human','service','machine','application','federated','temporary')
    ),
    version         integer NOT NULL CHECK (version > 0),
    record          jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, version)
);
CREATE INDEX IF NOT EXISTS ix_ispm_baseline_revision_tenant_id_version
    ON aq_ispm_baseline_revision (tenant_id, id, version DESC);

CREATE TABLE IF NOT EXISTS aq_ispm_drift_snapshot (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    baseline_id  text NOT NULL,
    record       jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ispm_drift_snapshot_tenant_baseline_id
    ON aq_ispm_drift_snapshot (tenant_id, baseline_id, id);

CREATE TABLE IF NOT EXISTS aq_ispm_assessment (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    status       text NOT NULL CHECK (status IN ('computed','truncated','pending')),
    record       jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ispm_assessment_tenant_status_id
    ON aq_ispm_assessment (tenant_id, status, id);

CREATE OR REPLACE FUNCTION aq_ispm_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'ISPM records are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ispm_identity_key_immutable ON aq_ispm_identity_key;
CREATE TRIGGER trg_ispm_identity_key_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_identity_key
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();

DROP TRIGGER IF EXISTS trg_ispm_identity_revision_immutable ON aq_ispm_identity_revision;
CREATE TRIGGER trg_ispm_identity_revision_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_identity_revision
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();

DROP TRIGGER IF EXISTS trg_ispm_posture_score_immutable ON aq_ispm_posture_score;
CREATE TRIGGER trg_ispm_posture_score_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_posture_score
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();

DROP TRIGGER IF EXISTS trg_ispm_baseline_revision_immutable ON aq_ispm_baseline_revision;
CREATE TRIGGER trg_ispm_baseline_revision_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_baseline_revision
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();

DROP TRIGGER IF EXISTS trg_ispm_drift_snapshot_immutable ON aq_ispm_drift_snapshot;
CREATE TRIGGER trg_ispm_drift_snapshot_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_drift_snapshot
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();

DROP TRIGGER IF EXISTS trg_ispm_assessment_immutable ON aq_ispm_assessment;
CREATE TRIGGER trg_ispm_assessment_immutable
BEFORE UPDATE OR DELETE ON aq_ispm_assessment
FOR EACH ROW EXECUTE FUNCTION aq_ispm_reject_mutation();
"""
