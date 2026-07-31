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
