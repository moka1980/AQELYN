"""Memory writes that distinguish GC-004's population and reader states."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ControlRecord:
    dormant_probe: str = ""
    memory_only: str = ""
    owner_only: str = ""
    unconsumed_probe: str = ""


class InMemoryControlStore:
    def __init__(self) -> None:
        self._records: dict[str, ControlRecord] = {}

    def put(self, key: str, record: ControlRecord, value: str) -> None:
        record.dormant_probe = value
        record.memory_only = value
        record.owner_only = value
        record.unconsumed_probe = value
        self._records[key] = record

    def owner_read(self, record: ControlRecord) -> str:
        return record.owner_only


@dataclass
class ConformingRecord:
    conforming_only: str = ""


class InMemoryWholeRecordStore:
    def __init__(self) -> None:
        self._records: dict[str, ConformingRecord] = {}

    def put(self, key: str, record: ConformingRecord) -> None:
        self._records[key] = record


@dataclass
class BareRecord:
    bare_only: str = ""


class ProbeLog:
    """A whole-record writer with no naming convention for discovery to lean on."""

    def __init__(self) -> None:
        self._log: list[BareRecord] = []

    def append(self, record: BareRecord) -> None:
        self._log.append(record)


@dataclass
class CapacityRecord:
    capacity_only: str = ""


class TypedCapacity:
    """A model annotation without a write site must not enter the census."""

    def __init__(self) -> None:
        self._records: list[CapacityRecord] = []


@dataclass
class DirectMutationRecord:
    direct_only: str = ""


class InMemoryDirectMutationStore:
    def __init__(self) -> None:
        self._record: DirectMutationRecord | None = None

    def put(self, record: DirectMutationRecord, value: str) -> None:
        record.direct_only = value
        self._record = record


@dataclass
class AliasLeft:
    alias_left: str = ""


@dataclass
class AliasRight:
    alias_right: str = ""


RecordAlias = AliasLeft | AliasRight


class AliasLog:
    def __init__(self) -> None:
        self._log: list[RecordAlias] = []

    def append(self, record: RecordAlias) -> None:
        self._log.append(record)
