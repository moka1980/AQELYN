"""PostgreSQL DDL for EA-0032 crypto records."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_crypto_asset_identity (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    kind         text NOT NULL CHECK (kind IN ('secret','key','certificate')),
    fingerprint  text NOT NULL CHECK (fingerprint ~ '^hmac-sha256:[0-9a-f]{64}$'),
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (tenant_id, kind, fingerprint)
);
CREATE INDEX IF NOT EXISTS ix_crypto_identity_tenant_kind_id
    ON aq_crypto_asset_identity (tenant_id, kind, id);

CREATE TABLE IF NOT EXISTS aq_crypto_asset_revision (
    revision     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id           text NOT NULL REFERENCES aq_crypto_asset_identity(id),
    tenant_id    text NULL,
    kind         text NOT NULL CHECK (kind IN ('secret','key','certificate')),
    fingerprint  text NOT NULL CHECK (fingerprint ~ '^hmac-sha256:[0-9a-f]{64}$'),
    record       jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crypto_revision_id_revision
    ON aq_crypto_asset_revision (id, revision DESC);
CREATE INDEX IF NOT EXISTS ix_crypto_revision_tenant_kind_id
    ON aq_crypto_asset_revision (tenant_id, kind, id, revision DESC);

CREATE TABLE IF NOT EXISTS aq_crypto_assessment (
    id           text PRIMARY KEY,
    tenant_id    text NULL,
    record       jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crypto_assessment_tenant_id
    ON aq_crypto_assessment (tenant_id, id);

CREATE OR REPLACE FUNCTION aq_crypto_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'crypto records are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_crypto_identity_immutable ON aq_crypto_asset_identity;
CREATE TRIGGER trg_crypto_identity_immutable
BEFORE UPDATE OR DELETE ON aq_crypto_asset_identity
FOR EACH ROW EXECUTE FUNCTION aq_crypto_reject_mutation();

DROP TRIGGER IF EXISTS trg_crypto_revision_immutable ON aq_crypto_asset_revision;
CREATE TRIGGER trg_crypto_revision_immutable
BEFORE UPDATE OR DELETE ON aq_crypto_asset_revision
FOR EACH ROW EXECUTE FUNCTION aq_crypto_reject_mutation();

DROP TRIGGER IF EXISTS trg_crypto_assessment_immutable ON aq_crypto_assessment;
CREATE TRIGGER trg_crypto_assessment_immutable
BEFORE UPDATE OR DELETE ON aq_crypto_assessment
FOR EACH ROW EXECUTE FUNCTION aq_crypto_reject_mutation();
"""
