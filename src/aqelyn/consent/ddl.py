"""PostgreSQL DDL for consent and audit (ECR-0117).

Both tables carry a non-null ``tenant_id`` and an index that leads with it, so a tenant's rows
are always addressable by tenant first. ``aq_audit_event`` has no UPDATE or DELETE path in the
store — it is append-only by construction. ``seq`` gives a stable per-insert order for listing.
"""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_consent_record (
    id           text PRIMARY KEY,
    tenant_id    text NOT NULL,
    account_id   text NOT NULL,
    scope        text NOT NULL,
    text_version text NOT NULL,
    granted_at   timestamptz NOT NULL,
    revoked_at   timestamptz NULL
);
CREATE INDEX IF NOT EXISTS aq_consent_tenant_scope
    ON aq_consent_record (tenant_id, scope, granted_at);

CREATE TABLE IF NOT EXISTS aq_audit_event (
    seq              bigserial PRIMARY KEY,
    id               text NOT NULL UNIQUE,
    tenant_id        text NOT NULL,
    actor_account_id text NOT NULL,
    action           text NOT NULL,
    detail           text NOT NULL,
    at               timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS aq_audit_tenant_seq ON aq_audit_event (tenant_id, seq);
"""
