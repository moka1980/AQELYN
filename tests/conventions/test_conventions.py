"""T1 acceptance tests for CONVENTIONS.spec.md (§12)."""

import io
import json
import logging

import pytest

from aqelyn.conventions import (
    ALL_ERROR_CODES,
    canonical_json,
    configure_logging,
    is_valid,
    new_id,
    parse_id,
    sha256_hex,
    to_rfc3339,
    utc_now,
)
from aqelyn.conventions.errors import _all_error_classes
from aqelyn.conventions.logging import JsonFormatter


def test_conv_id_roundtrip() -> None:
    oid = new_id("obj")
    prefix, hexpart = parse_id(oid)
    assert prefix == "obj"
    assert len(hexpart) == 32
    assert is_valid(oid, "obj")
    assert not is_valid(oid, "evt")
    assert not is_valid("obj_notvalid")
    with pytest.raises(ValueError, match="UUIDv7"):
        parse_id("obj_0123456789abcdef0123456789abcdef")


def test_conv_canonical_json_stable() -> None:
    a = {"b": 1, "a": 2, "nested": {"y": [3, 2], "x": 1}}
    b = {"nested": {"x": 1, "y": [3, 2]}, "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_hex(a) == sha256_hex(b)
    assert canonical_json({"k": "v"}) == b'{"k":"v"}'


def test_conv_error_codes_unique() -> None:
    codes = [c.code for c in _all_error_classes()]
    assert len(codes) == len(set(codes))
    assert "OptimisticConcurrencyConflict" in ALL_ERROR_CODES
    assert "EvidenceRequired" in ALL_ERROR_CODES


def test_conv_logging_redaction() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.redact")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("INFO")
    logger.propagate = False
    tenant_id = "018f0000-0000-7000-8000-000000000001"
    logger.info("login", extra={"password": "hunter2", "tenant_id": tenant_id})
    record = json.loads(stream.getvalue())
    assert record["password"] == "***"
    assert record["tenant_id"] == tenant_id
    assert record["msg"] == "login"


def test_conv_timestamp_format() -> None:
    s = to_rfc3339(utc_now())
    assert s.endswith("+00:00")
    assert "." in s  # microseconds present
    # configure_logging is importable and runs without error
    configure_logging("INFO")
