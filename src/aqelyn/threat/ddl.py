"""PostgreSQL DDL for Threat Intelligence Fusion stores (EA-0014 T2)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_threat_source (
    source_id   text PRIMARY KEY,
    reliability double precision NOT NULL CHECK (reliability >= 0 AND reliability <= 1),
    meta        jsonb NOT NULL DEFAULT '{}',
    set_by      jsonb NOT NULL,
    set_at      timestamptz NOT NULL,
    version     int NOT NULL DEFAULT 1 CHECK (version >= 1)
);
"""
