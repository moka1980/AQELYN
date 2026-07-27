"""PostgreSQL DDL for supply-chain records (EA-0030 Q2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_supplychain_component (
    object_id          text PRIMARY KEY,
    tenant_id          text NULL,
    identity_kind      text NULL,
    purl               text NULL,
    cpe                text NULL,
    name               text NOT NULL CHECK (length(trim(name)) > 0),
    version            text NOT NULL CHECK (length(trim(version)) > 0),
    component_type     text NOT NULL CHECK (length(trim(component_type)) > 0),
    locations          jsonb NOT NULL DEFAULT '[]',
    licenses           jsonb NOT NULL CHECK (jsonb_typeof(licenses) = 'array'),
    supplier           text NULL CHECK (supplier IS NULL OR length(trim(supplier)) > 0),
    hashes             jsonb NOT NULL CHECK (jsonb_typeof(hashes) = 'object'),
    provenance_status  text NOT NULL CHECK (
        provenance_status IN ('verified','unverified','failed')
    ),
    direct             boolean NOT NULL,
    source_id          text NOT NULL,
    observed_at        timestamptz NOT NULL,
    evidence_id        text NOT NULL,
    conflicts          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(conflicts) = 'array')
);

ALTER TABLE aq_supplychain_component
    ADD COLUMN IF NOT EXISTS identity_kind text NULL,
    ADD COLUMN IF NOT EXISTS cpe text NULL,
    ADD COLUMN IF NOT EXISTS locations jsonb;
UPDATE aq_supplychain_component
    SET identity_kind = 'purl'
    WHERE identity_kind IS NULL;
UPDATE aq_supplychain_component
    SET locations = '[]'::jsonb
    WHERE locations IS NULL;
ALTER TABLE aq_supplychain_component
    ALTER COLUMN purl DROP NOT NULL,
    ALTER COLUMN identity_kind SET NOT NULL,
    ALTER COLUMN locations SET DEFAULT '[]'::jsonb,
    ALTER COLUMN locations SET NOT NULL,
    DROP CONSTRAINT IF EXISTS aq_supplychain_component_purl_check,
    DROP CONSTRAINT IF EXISTS aq_supplychain_component_tenant_id_purl_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'aq_supplychain_component'::regclass
          AND conname = 'ck_supplychain_component_identity'
    ) THEN
        ALTER TABLE aq_supplychain_component
            ADD CONSTRAINT ck_supplychain_component_identity CHECK (
                (
                    identity_kind = 'purl'
                    AND purl IS NOT NULL
                    AND purl LIKE 'pkg:%'
                    AND (cpe IS NULL OR cpe LIKE 'cpe:%')
                )
                OR (
                    identity_kind = 'cpe'
                    AND purl IS NULL
                    AND cpe IS NOT NULL
                    AND cpe LIKE 'cpe:%'
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'aq_supplychain_component'::regclass
          AND conname = 'ck_supplychain_component_locations'
    ) THEN
        ALTER TABLE aq_supplychain_component
            ADD CONSTRAINT ck_supplychain_component_locations
            CHECK (jsonb_typeof(locations) = 'array');
    END IF;
END;
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_supplychain_component_purl
    ON aq_supplychain_component (tenant_id, purl) NULLS NOT DISTINCT
    WHERE identity_kind = 'purl';
CREATE UNIQUE INDEX IF NOT EXISTS uq_supplychain_component_cpe
    ON aq_supplychain_component (tenant_id, cpe) NULLS NOT DISTINCT
    WHERE identity_kind = 'cpe';
CREATE INDEX IF NOT EXISTS ix_supplychain_component_tenant_provenance
    ON aq_supplychain_component (tenant_id, provenance_status, object_id);

CREATE TABLE IF NOT EXISTS aq_supplychain_assessment (
    id                     text PRIMARY KEY,
    tenant_id              text NULL,
    run_at                 timestamptz NOT NULL,
    subject_ref            text NOT NULL CHECK (length(trim(subject_ref)) > 0),
    components             integer NOT NULL CHECK (components >= 0),
    direct                 integer NOT NULL CHECK (direct >= 0),
    transitive             integer NOT NULL CHECK (transitive >= 0),
    unverified_provenance  integer NOT NULL CHECK (unverified_provenance >= 0),
    vulnerable_components  integer NOT NULL CHECK (vulnerable_components >= 0),
    assessment_status      text NOT NULL CHECK (
        assessment_status IN ('complete','truncated','pending')
    ),
    evidence_id            text NOT NULL,
    CHECK (direct + transitive <= components),
    CHECK (unverified_provenance <= components),
    CHECK (vulnerable_components <= components),
    CHECK (
        assessment_status <> 'pending'
        OR (
            components = 0 AND direct = 0 AND transitive = 0
            AND unverified_provenance = 0 AND vulnerable_components = 0
        )
    )
);
CREATE INDEX IF NOT EXISTS ix_supplychain_assessment_tenant_run
    ON aq_supplychain_assessment (tenant_id, run_at, id);

CREATE TABLE IF NOT EXISTS aq_supplychain_quarantine (
    doc_id           text PRIMARY KEY,
    tenant_id        text NULL,
    source_id        text NOT NULL,
    observed_at      timestamptz NOT NULL,
    evidence_id      text NULL,
    raw              jsonb NOT NULL CHECK (jsonb_typeof(raw) = 'object'),
    reason           text NOT NULL CHECK (length(trim(reason)) > 0),
    flagged          boolean NOT NULL CHECK (flagged),
    quarantined_at   timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_supplychain_quarantine_tenant_time
    ON aq_supplychain_quarantine (tenant_id, quarantined_at, doc_id);
"""
