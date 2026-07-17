"""PostgreSQL DDL for Vulnerability Intelligence stores (EA-0024 V2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_vuln_record (
    id            text PRIMARY KEY,
    tenant_id     text NULL,
    cve_id        text NOT NULL CHECK (length(trim(cve_id)) > 0),
    scanner       text NOT NULL CHECK (length(trim(scanner)) > 0),
    asset_ref     jsonb NOT NULL,
    severity      text NOT NULL CHECK (severity IN ('critical','high','medium','low','none')),
    cvss          jsonb NOT NULL,
    epss          jsonb NULL,
    confidence    double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    basis         jsonb NOT NULL CHECK (
        jsonb_typeof(basis) = 'array' AND jsonb_array_length(basis) > 0
    ),
    disposition   jsonb NULL,
    discovered_at timestamptz NOT NULL,
    status        text NOT NULL CHECK (status IN ('open','reasserted','closed'))
);
CREATE INDEX IF NOT EXISTS ix_vuln_record_tenant_cve
    ON aq_vuln_record (tenant_id, cve_id, id);
CREATE INDEX IF NOT EXISTS ix_vuln_record_tenant_scanner
    ON aq_vuln_record (tenant_id, scanner, id);

CREATE TABLE IF NOT EXISTS aq_vuln_history (
    seq              bigserial PRIMARY KEY,
    vulnerability_id text NOT NULL,
    snapshot         jsonb NOT NULL,
    changed_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vuln_history_vulnerability
    ON aq_vuln_history (vulnerability_id, seq);

CREATE OR REPLACE FUNCTION aq_vuln_history_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'aq_vuln_history is append-only' USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS aq_vuln_history_no_update_delete
    ON aq_vuln_history;
CREATE TRIGGER aq_vuln_history_no_update_delete
    BEFORE UPDATE OR DELETE ON aq_vuln_history
    FOR EACH ROW EXECUTE FUNCTION aq_vuln_history_append_only();
"""
