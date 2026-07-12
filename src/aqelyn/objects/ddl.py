"""PostgreSQL DDL for the Universal Object Model (EA-0002 §14)."""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_object (
    id              text PRIMARY KEY,
    object_type     text NOT NULL,
    schema_version  int  NOT NULL,
    tenant_id       text NULL,
    display_name    text NOT NULL,
    attributes      jsonb NOT NULL DEFAULT '{}',
    labels          jsonb NOT NULL DEFAULT '{}',
    natural_keys    jsonb NOT NULL DEFAULT '[]',
    sources         jsonb NOT NULL DEFAULT '[]',
    confidence      double precision NOT NULL DEFAULT 1.0
                    CHECK (confidence >= 0 AND confidence <= 1),
    lifecycle_state text NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','archived','merged','deleted')),
    merged_into     text NULL,
    version         int  NOT NULL DEFAULT 1,
    first_seen_at   timestamptz NOT NULL,
    last_seen_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      jsonb NOT NULL,
    updated_by      jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS aq_object_natural_key (
    object_id text NOT NULL REFERENCES aq_object(id),
    tenant_id text NULL,
    namespace text NOT NULL,
    value     text NOT NULL,
    PRIMARY KEY (object_id, namespace, value)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_natural_key_live
    ON aq_object_natural_key (tenant_id, namespace, value);
CREATE TABLE IF NOT EXISTS aq_relationship (
    id              text PRIMARY KEY,
    tenant_id       text NULL,
    from_id         text NOT NULL REFERENCES aq_object(id),
    to_id           text NOT NULL REFERENCES aq_object(id),
    relation_type   text NOT NULL,
    attributes      jsonb NOT NULL DEFAULT '{}',
    sources         jsonb NOT NULL DEFAULT '[]',
    confidence      double precision NOT NULL DEFAULT 1.0,
    lifecycle_state text NOT NULL DEFAULT 'active',
    version         int  NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      jsonb NOT NULL,
    updated_by      jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rel_from ON aq_relationship (from_id, relation_type);
CREATE INDEX IF NOT EXISTS ix_rel_to   ON aq_relationship (to_id, relation_type);
CREATE TABLE IF NOT EXISTS aq_object_history (
    seq        bigserial PRIMARY KEY,
    object_id  text NOT NULL,
    version    int  NOT NULL,
    snapshot   jsonb NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_object ON aq_object_history (object_id, version);
"""
