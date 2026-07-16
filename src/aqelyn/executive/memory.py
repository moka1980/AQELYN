"""In-memory Executive Intelligence stores (EA-0022 X2)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import FrozenReportMutation
from aqelyn.executive.definitions import InMemoryKPIDefinitionStore
from aqelyn.executive.models import ExecutiveReport
from aqelyn.executive.store import (
    validate_period,
    validate_query_limit,
    validate_report,
    validate_report_id,
    validate_tenant,
)


class InMemoryReportStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._reports: dict[str, ExecutiveReport] = {}

    async def put(self, report: ExecutiveReport) -> ExecutiveReport:
        stored = validate_report(report)
        existing = self._reports.get(stored.id)
        if existing is not None and existing.frozen:
            raise FrozenReportMutation(f"frozen report cannot be mutated: {stored.id}")
        self._reports[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, report_id: str, *, tenant_id: str | None = None) -> ExecutiveReport | None:
        validate_report_id(report_id)
        tenant_id = validate_tenant(tenant_id)
        report = self._reports.get(report_id)
        if report is None or not self._visible(report.tenant_id, tenant_id):
            return None
        return copy.deepcopy(report)

    async def query(
        self, *, tenant_id: str | None, period: str | None = None, limit: int = 100
    ) -> list[ExecutiveReport]:
        tenant_id = validate_tenant(tenant_id)
        period = validate_period(period)
        validate_query_limit(limit)
        rows = [
            copy.deepcopy(report)
            for report in self._reports.values()
            if self._visible(report.tenant_id, tenant_id)
            and (period is None or report.period == period)
        ]
        rows.sort(key=lambda report: (report.period, report.id))
        return rows[:limit]

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id


__all__ = ["InMemoryKPIDefinitionStore", "InMemoryReportStore"]
