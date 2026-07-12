"""Structured JSON logging with secret redaction (CONVENTIONS §10)."""

from __future__ import annotations

import json
import logging
from typing import Any

SECRET_KEYS: frozenset[str] = frozenset(
    {"password", "passwd", "secret", "token", "api_key", "apikey", "authorization"}
)
_REDACTED = "***"

# Standard LogRecord attributes we never treat as structured "extra" fields.
_STD = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime", "taskName"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k.lower() in SECRET_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    """Render records as single-line JSON with redacted extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key not in _STD and not key.startswith("_"):
                payload[key] = _REDACTED if key.lower() in SECRET_KEYS else _redact(val)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
