"""PostgreSQL DDL for Evidence (EA-0004 §9)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_evidence (
    id            text PRIMARY KEY,
    tenant_id     text NULL,
    evidence_type text NOT NULL,
    schema_version int NOT NULL,
    subject       jsonb NOT NULL,
    collected_at  timestamptz NOT NULL,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    collector     jsonb NOT NULL,
    source_id     text NOT NULL,
    method        text NOT NULL,
    content       jsonb NULL,
    content_ref   jsonb NULL,
    content_hash  text NOT NULL,
    confidence    double precision NOT NULL DEFAULT 1.0,
    labels        jsonb NOT NULL DEFAULT '{}',
    seq           bigint NOT NULL,
    prev_hash     text NULL,
    record_hash   text NOT NULL,
    signature     jsonb NULL,
    anchor        jsonb NULL,
    CHECK ((content IS NOT NULL) <> (content_ref IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_chain
    ON aq_evidence (COALESCE(tenant_id, ''), seq);
CREATE INDEX IF NOT EXISTS ix_evidence_hash ON aq_evidence (content_hash);
CREATE TABLE IF NOT EXISTS aq_evidence_custody (
    seq         bigserial PRIMARY KEY,
    evidence_id text NOT NULL,
    action      text NOT NULL CHECK (action IN ('read','export','package')),
    actor       jsonb NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    context     jsonb NULL
);
CREATE TABLE IF NOT EXISTS aq_evidence_package (
    id            text PRIMARY KEY,
    tenant_id     text NULL,
    evidence_ids  jsonb NOT NULL,
    manifest_hash text NOT NULL,
    package_hash  text NOT NULL,
    created_by    jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    reason        text NOT NULL
);
"""
