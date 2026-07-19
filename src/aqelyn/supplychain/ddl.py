"""PostgreSQL DDL for supply-chain records (EA-0030 Q2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_supplychain_component (
    object_id          text PRIMARY KEY,
    tenant_id          text NULL,
    purl               text NOT NULL CHECK (purl LIKE 'pkg:%'),
    name               text NOT NULL CHECK (length(trim(name)) > 0),
    version            text NOT NULL CHECK (length(trim(version)) > 0),
    component_type     text NOT NULL CHECK (length(trim(component_type)) > 0),
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
    conflicts          jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(conflicts) = 'array'),
    UNIQUE NULLS NOT DISTINCT (tenant_id, purl)
);
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
