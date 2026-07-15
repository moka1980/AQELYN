"""Safe lake query and redaction helpers (EA-0019 L3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import DatasetNotFound, LakeConfigInvalid
from aqelyn.lake.models import Dataset, LakeConfig, Query, QueryResult, TelemetryRecord
from aqelyn.lake.store import DatasetCatalogStore, TelemetryRecordStore
from aqelyn.policy import Condition, Decision, DecisionRequest, DecisionResource

REDACTED = "***REDACTED***"
_SENSITIVE = {"pii", "secret"}
_FIELD_PREFIX = "fields."
_COLUMN_ATTRS: frozenset[str] = frozenset(
    ("id", "source_id", "retention_state", "schema_version", "legal_hold")
)


class PolicyAuthorizer(Protocol):
    async def authorize(self, request: DecisionRequest) -> Decision: ...


@dataclass(frozen=True)
class SqlPredicate:
    sql: str
    args: tuple[Any, ...]


async def query(
    q: Query,
    *,
    actor: ActorRef,
    catalog: DatasetCatalogStore,
    store: TelemetryRecordStore,
    policy_authorizer: PolicyAuthorizer | None = None,
    config: LakeConfig | None = None,
) -> QueryResult:
    config = config or LakeConfig()
    dataset = await _dataset_for_query(q, catalog)
    fields = _requested_fields(q, dataset)
    limit = min(q.limit, config.max_query_rows)
    total = await store.count(
        dataset=q.dataset,
        tenant_id=q.tenant_id,
        since=q.since,
        until=q.until,
        filter=q.filter,
    )
    records = await store.query(
        dataset=q.dataset,
        tenant_id=q.tenant_id,
        limit=limit,
        since=q.since,
        until=q.until,
        filter=q.filter,
    )
    rows, redacted = await _rows(
        records,
        fields=fields,
        dataset=dataset,
        tenant_id=q.tenant_id,
        actor=actor,
        policy_authorizer=policy_authorizer,
    )
    return QueryResult(
        rows=rows,
        count=total,
        truncated=total > limit,
        redacted_fields=sorted(redacted),
    )


async def count(
    q: Query,
    *,
    catalog: DatasetCatalogStore,
    store: TelemetryRecordStore,
) -> int:
    await _dataset_for_query(q, catalog)
    return await store.count(
        dataset=q.dataset,
        tenant_id=q.tenant_id,
        since=q.since,
        until=q.until,
        filter=q.filter,
    )


def compile_condition(condition: Condition, *, start_index: int = 1) -> SqlPredicate:
    if start_index < 1:
        raise LakeConfigInvalid("start_index must be >= 1")
    args: list[Any] = []
    sql = _compile(condition, args=args, start_index=start_index)
    return SqlPredicate(sql=sql, args=tuple(args))


async def _dataset_for_query(q: Query, catalog: DatasetCatalogStore) -> Dataset:
    dataset = await catalog.get(q.dataset, tenant_id=q.tenant_id)
    if dataset is None:
        raise DatasetNotFound(f"dataset not found: {q.dataset}")
    return dataset


def _requested_fields(q: Query, dataset: Dataset) -> list[str]:
    fields = q.fields or list(dataset.schema_)
    missing = [field for field in fields if field not in dataset.schema_]
    if missing:
        raise LakeConfigInvalid(f"query fields must name dataset schema fields: {missing[0]}")
    return fields


async def _rows(
    records: Sequence[TelemetryRecord],
    *,
    fields: list[str],
    dataset: Dataset,
    tenant_id: str | None,
    actor: ActorRef,
    policy_authorizer: PolicyAuthorizer | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    allowed: dict[str, bool] = {}
    rows: list[dict[str, Any]] = []
    redacted: set[str] = set()
    for record in records:
        row: dict[str, Any] = {}
        for field in fields:
            classification = dataset.classifications[field]
            if classification in _SENSITIVE:
                permitted = allowed.get(field)
                if permitted is None:
                    permitted = await _field_permitted(
                        field,
                        classification=classification,
                        dataset=dataset,
                        tenant_id=tenant_id,
                        actor=actor,
                        policy_authorizer=policy_authorizer,
                    )
                    allowed[field] = permitted
                if not permitted:
                    row[field] = REDACTED
                    redacted.add(field)
                    continue
            row[field] = record.fields.get(field)
        rows.append(row)
    return rows, redacted


async def _field_permitted(
    field: str,
    *,
    classification: str,
    dataset: Dataset,
    tenant_id: str | None,
    actor: ActorRef,
    policy_authorizer: PolicyAuthorizer | None,
) -> bool:
    if policy_authorizer is None:
        return False
    decision = await policy_authorizer.authorize(
        DecisionRequest(
            subject=actor,
            action="lake.query_field",
            resource=DecisionResource(
                id=f"{dataset.name}.{field}",
                type="lake_field",
                tenant_id=tenant_id if tenant_id is not None else dataset.tenant_id,
                attributes={
                    "dataset": dataset.name,
                    "field": field,
                    "classification": classification,
                },
            ),
            context={"dataset": dataset.name, "field": field},
        )
    )
    return decision.effect == "permit"


def _compile(condition: Condition, *, args: list[Any], start_index: int) -> str:
    if condition.op is not None and condition.attr is not None:
        return _compile_leaf(condition, args=args, start_index=start_index)
    if condition.all is not None:
        return (
            "("
            + " AND ".join(
                _compile(item, args=args, start_index=start_index) for item in condition.all
            )
            + ")"
        )
    if condition.any is not None:
        return (
            "("
            + " OR ".join(
                _compile(item, args=args, start_index=start_index) for item in condition.any
            )
            + ")"
        )
    if condition.not_ is not None:
        return f"(NOT {_compile(condition.not_, args=args, start_index=start_index)})"
    raise LakeConfigInvalid("malformed condition")


def _compile_leaf(condition: Condition, *, args: list[Any], start_index: int) -> str:
    assert condition.op is not None
    assert condition.attr is not None
    expr = _attr_expr(condition.attr, args=args, start_index=start_index)
    op = condition.op
    if op == "exists":
        return f"({expr} IS {'NOT ' if _want_exists(condition.value) else ''}NULL)"
    if op == "eq":
        return f"({expr} = {_param(_text_value(condition.value), args, start_index)})"
    if op == "ne":
        return f"({expr} <> {_param(_text_value(condition.value), args, start_index)})"
    if op == "in":
        values = _text_values(condition.value)
        return f"({expr} = ANY({_param(values, args, start_index)}::text[]))"
    if op == "nin":
        values = _text_values(condition.value)
        return f"({expr} <> ALL({_param(values, args, start_index)}::text[]))"
    if op == "contains":
        return (
            f"(POSITION({_param(_text_value(condition.value), args, start_index)} IN {expr}) > 0)"
        )
    if op in {"gt", "gte", "lt", "lte"}:
        operator = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        if isinstance(condition.value, int | float) and not isinstance(condition.value, bool):
            return (
                f"(NULLIF({expr}, '')::numeric {operator} "
                f"{_param(condition.value, args, start_index)}::numeric)"
            )
        return f"({expr} {operator} {_param(_text_value(condition.value), args, start_index)})"
    raise LakeConfigInvalid(f"unsupported condition op: {op!r}")


def _attr_expr(attr: str, *, args: list[Any], start_index: int) -> str:
    if attr.startswith(_FIELD_PREFIX):
        path = attr.removeprefix(_FIELD_PREFIX).split(".")
        if not path or any(not part or part.startswith("__") for part in path):
            raise LakeConfigInvalid("invalid field path")
        return f"(fields #>> {_param(path, args, start_index)}::text[])"
    if attr in _COLUMN_ATTRS:
        return f"({attr})::text"
    raise LakeConfigInvalid(f"unsupported condition attr: {attr!r}")


def _param(value: Any, args: list[Any], start_index: int) -> str:
    args.append(value)
    return f"${start_index + len(args) - 1}"


def _want_exists(value: Any) -> bool:
    return True if value is None else bool(value)


def _text_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _text_values(value: Any) -> list[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        raise LakeConfigInvalid("in/nin condition value must be a list")
    return [_text_value(item) for item in value]
