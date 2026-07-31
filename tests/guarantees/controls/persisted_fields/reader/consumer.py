"""A source-level reader whose shipped reachability is deliberately not inferred."""

from __future__ import annotations

from guarantees.controls.persisted_fields.writer.memory import ControlRecord


def read_dormant(record: ControlRecord) -> str:
    return record.dormant_probe
