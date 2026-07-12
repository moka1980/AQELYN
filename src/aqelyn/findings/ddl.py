"""PostgreSQL DDL for Findings (Finding-model.spec.md §10)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_finding (
    id                 text PRIMARY KEY,
    tenant_id          text NULL,
    finding_type       text NOT NULL,
    schema_version     int  NOT NULL,
    dedup_key          text NOT NULL,
    title              text NOT NULL,
    severity           text NOT NULL
                       CHECK (severity IN ('info','low','medium','high','critical')),
    severity_score     double precision NOT NULL
                       CHECK (severity_score >= 0 AND severity_score <= 100),
    status             text NOT NULL DEFAULT 'open'
                       CHECK (status IN ('open','acknowledged','in_progress','resolved',
                                         'risk_accepted','false_positive')),
    what_happened      text NOT NULL,
    why_it_matters     text NOT NULL,
    how_determined     text NOT NULL,
    risk_of_inaction   text NOT NULL,
    expert_details     jsonb NULL,
    remediation        jsonb NOT NULL,
    automation         jsonb NOT NULL,
    confidence         double precision NOT NULL DEFAULT 1.0,
    source_engine      text NOT NULL,
    correlation_id     text NULL,
    first_detected_at  timestamptz NOT NULL,
    last_detected_at   timestamptz NOT NULL,
    resolved_at        timestamptz NULL,
    version            int NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_finding_dedup
    ON aq_finding (COALESCE(tenant_id,''), finding_type, dedup_key);
CREATE INDEX IF NOT EXISTS ix_finding_status_sev
    ON aq_finding (tenant_id, status, severity_score DESC);
CREATE TABLE IF NOT EXISTS aq_finding_evidence (
    finding_id  text NOT NULL REFERENCES aq_finding(id),
    evidence_id text NOT NULL,
    PRIMARY KEY (finding_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS aq_finding_asset (
    finding_id text NOT NULL REFERENCES aq_finding(id),
    object_id  text NOT NULL,
    PRIMARY KEY (finding_id, object_id)
);
CREATE TABLE IF NOT EXISTS aq_finding_audit (
    seq         bigserial PRIMARY KEY,
    finding_id  text NOT NULL REFERENCES aq_finding(id),
    at          timestamptz NOT NULL DEFAULT now(),
    actor       jsonb NOT NULL,
    action      text NOT NULL,
    from_status text NULL,
    to_status   text NULL,
    note        text NULL
);
CREATE INDEX IF NOT EXISTS ix_finding_audit_finding
    ON aq_finding_audit (finding_id, seq);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aq_finding' AND column_name = 'evidence_ids'
    ) THEN
        INSERT INTO aq_finding_evidence (finding_id, evidence_id)
        SELECT id, evidence_id
        FROM aq_finding
        CROSS JOIN LATERAL jsonb_array_elements_text(evidence_ids) AS evidence_id
        ON CONFLICT DO NOTHING;
        ALTER TABLE aq_finding DROP COLUMN evidence_ids;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aq_finding' AND column_name = 'affected_object_ids'
    ) THEN
        INSERT INTO aq_finding_asset (finding_id, object_id)
        SELECT id, object_id
        FROM aq_finding
        CROSS JOIN LATERAL jsonb_array_elements_text(affected_object_ids) AS object_id
        ON CONFLICT DO NOTHING;
        ALTER TABLE aq_finding DROP COLUMN affected_object_ids;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'aq_finding' AND column_name = 'audit'
    ) THEN
        INSERT INTO aq_finding_audit (
            finding_id, at, actor, action, from_status, to_status, note
        )
        SELECT
            id,
            COALESCE((entry ->> 'at')::timestamptz, now()),
            entry -> 'actor',
            entry ->> 'action',
            entry ->> 'from_status',
            entry ->> 'to_status',
            entry ->> 'note'
        FROM aq_finding
        CROSS JOIN LATERAL jsonb_array_elements(audit) WITH ORDINALITY AS e(entry, ord)
        ORDER BY id, ord;
        ALTER TABLE aq_finding DROP COLUMN audit;
    END IF;
END $$;
"""
