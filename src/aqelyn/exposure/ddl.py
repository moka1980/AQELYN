"""PostgreSQL DDL for Exposure records (EA-0023 E2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_exposure_record (
    id             text PRIMARY KEY,
    tenant_id      text NULL,
    asset_ref      jsonb NOT NULL,
    exposure_type  text NOT NULL,
    reachability   text NOT NULL CHECK (reachability IN ('external','internal','unknown')),
    basis          jsonb NOT NULL DEFAULT '[]',
    impact_context jsonb NULL,
    score          double precision NULL CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    confidence     double precision NULL CHECK (
                       confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
                   ),
    derivation     jsonb NULL,
    rationale      text NOT NULL,
    flagged        boolean NOT NULL,
    discovered_at  timestamptz NOT NULL,
    validated_at   timestamptz NULL,
    status         text NOT NULL CHECK (status IN ('open','revalidated','closed')),
    CHECK (reachability <> 'unknown' OR flagged = true),
    CHECK (jsonb_array_length(basis) > 0)
);
ALTER TABLE aq_exposure_record
    ADD COLUMN IF NOT EXISTS impact_context jsonb NULL;
CREATE INDEX IF NOT EXISTS ix_exposure_record_tenant_discovered
    ON aq_exposure_record (tenant_id, discovered_at DESC, id);
CREATE INDEX IF NOT EXISTS ix_exposure_record_tenant_reachability
    ON aq_exposure_record (tenant_id, reachability, flagged, discovered_at DESC, id);
"""
