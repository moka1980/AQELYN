"""PostgreSQL DDL for identity (ECR-0116).

Accounts and invites live on the same box as the rest of the platform, loopback-only (arc
decision 2). Email is the global login identifier, so a case-insensitive unique index enforces
the one-account-per-email rule at the database, not only in Python. Every table carries a
non-null ``tenant_id`` and an index that leads with it — the same scoping shape the finding
store uses, so a tenant's rows are always addressable by tenant first.
"""

from __future__ import annotations

DDL = """
CREATE TABLE IF NOT EXISTS aq_account (
    id          text PRIMARY KEY,
    email       text NOT NULL,
    tenant_id   text NOT NULL,
    password    jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('active','disabled')),
    created_at  timestamptz NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS aq_account_email_ci ON aq_account (lower(email));
CREATE INDEX IF NOT EXISTS aq_account_tenant ON aq_account (tenant_id, id);

CREATE TABLE IF NOT EXISTS aq_invite (
    token       text PRIMARY KEY,
    id          text NOT NULL,
    tenant_id   text NOT NULL,
    email       text NULL,
    created_at  timestamptz NOT NULL,
    expires_at  timestamptz NOT NULL,
    redeemed_by text NULL
);
CREATE INDEX IF NOT EXISTS aq_invite_tenant ON aq_invite (tenant_id, token);

-- ECR-0120: sessions live in Postgres so they survive a restart and are shared across
-- workers (the in-memory store is a hard single-worker constraint). tenant_id is bound from
-- the account at start, never from the client, exactly as the in-memory store does.
CREATE TABLE IF NOT EXISTS aq_session (
    token      text PRIMARY KEY,
    account_id text NOT NULL,
    tenant_id  text NOT NULL,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS aq_session_expires ON aq_session (expires_at);
"""
