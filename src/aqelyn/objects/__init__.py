"""Universal Object Model (T2). Implements EA-0002-universal-object-model.spec.md:
AQObject / AQRelationship, ObjectStore (in-memory + Postgres)."""

from aqelyn.objects.memory import InMemoryObjectStore
from aqelyn.objects.models import (
    AQObject,
    AQRelationship,
    NaturalKey,
    ObjectQuery,
    SourceRef,
)
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.objects.store import ObjectEventSink, ObjectStore

__all__ = [
    "AQObject",
    "AQRelationship",
    "InMemoryObjectStore",
    "NaturalKey",
    "ObjectEventSink",
    "ObjectQuery",
    "ObjectStore",
    "ObjectTypeRegistry",
    "SourceRef",
]
