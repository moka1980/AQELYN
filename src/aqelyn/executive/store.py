"""Executive report persistence protocol and validation helpers (EA-0022 X2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ExecutiveConfigInvalid
from aqelyn.executive.models import ExecutiveReport, validate_limit


class ReportStore(Protocol):
    async def put(self, report: ExecutiveReport) -> ExecutiveReport: ...

    async def get(
        self, report_id: str, *, tenant_id: str | None = None
    ) -> ExecutiveReport | None: ...

    async def query(
        self, *, tenant_id: str | None, period: str | None = None, limit: int = 100
    ) -> list[ExecutiveReport]: ...


def validate_report_id(value: str, *, field: str = "report_id") -> str:
    return require_typed_id(value, "rpt", field=field)


def validate_report(report: ExecutiveReport) -> ExecutiveReport:
    return ExecutiveReport.model_validate(report.model_dump(mode="json"))


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_period(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise ExecutiveConfigInvalid("period must not be empty")
    return value


def validate_query_limit(value: int) -> int:
    return validate_limit(value)
