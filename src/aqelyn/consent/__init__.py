"""Consent + audit path (ECR-0117, Charter UX-005).

A ``ConsentRecord`` is a tenant's standing agreement to store scans under a named scope; the
``AuditEvent`` log is the append-only record of who did what. Both are tenant-scoped and follow
the identity backend pattern — ``InMemory*`` for local/tests, ``Postgres*`` for production,
selected by ``build_consent_stores``. ECR-0118's upload path requires an active consent before it
writes, and audits every write.
"""

from aqelyn.consent.factory import ConsentStores, build_consent_stores
from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.consent.models import (
    AuditAction,
    AuditEvent,
    ConsentRecord,
    ConsentScope,
)
from aqelyn.consent.store import AuditLog, ConsentError, ConsentStore

__all__ = [
    "AuditAction",
    "AuditEvent",
    "AuditLog",
    "ConsentError",
    "ConsentRecord",
    "ConsentScope",
    "ConsentStore",
    "ConsentStores",
    "InMemoryAuditLog",
    "InMemoryConsentStore",
    "build_consent_stores",
]
