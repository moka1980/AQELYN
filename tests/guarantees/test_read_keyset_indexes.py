"""ECR-0090 static conformance for keyset read indexes."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from aqelyn.exposure.ddl import DDL as EXPOSURE_DDL
from aqelyn.exposure.postgres import PostgresExposureStore
from aqelyn.ispm.ddl import DDL as ISPM_DDL
from aqelyn.ispm.postgres import PostgresISPMStore
from aqelyn.supplychain.ddl import DDL as SUPPLYCHAIN_DDL
from aqelyn.supplychain.postgres import PostgresSBOMStore

_INDEX = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+"
    r"(?P<name>[a-z0-9_]+)\s+ON\s+(?P<table>[a-z0-9_]+)\s*"
    r"\((?P<columns>[^)]+)\)",
    re.IGNORECASE | re.DOTALL,
)
_FROM = re.compile(r"\bFROM\s+([a-z0-9_]+)\b", re.IGNORECASE)
_ORDER_BY = re.compile(r"\bORDER\s+BY\s+(.+?)\s+LIMIT\b", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class _Contract:
    name: str
    table: str
    index_name: str
    order_by: tuple[tuple[str, str], ...]
    ddl: str
    method: Callable[..., object]


_CONTRACTS = (
    _Contract(
        name="exposure",
        table="aq_exposure_record",
        index_name="ix_exposure_record_tenant_discovered_read",
        order_by=(("discovered_at", "ASC"), ("id", "ASC")),
        ddl=EXPOSURE_DDL,
        method=PostgresExposureStore.query_for_read,
    ),
    _Contract(
        name="ispm",
        table="aq_ispm_posture_score",
        index_name="ix_ispm_posture_score_tenant_subject_id",
        order_by=(("subject_ref", "ASC"), ("id", "ASC")),
        ddl=ISPM_DDL,
        method=PostgresISPMStore.query_scores_for_read,
    ),
    _Contract(
        name="supplychain",
        table="aq_supplychain_component",
        index_name="ix_supplychain_component_tenant_provenance",
        order_by=(("provenance_status", "ASC"), ("object_id", "ASC")),
        ddl=SUPPLYCHAIN_DDL,
        method=PostgresSBOMStore.query_components_for_read,
    ),
)


def _sql_shape(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else " "
            for value in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _sql_shape(node.left)
        right = _sql_shape(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _read_query(method: Callable[..., object]) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    candidates: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "fetch":
            continue
        sql = _sql_shape(node.args[0])
        if sql is not None and "ORDER BY" in sql:
            candidates.append(sql)
    if len(candidates) != 1:
        raise AssertionError(f"expected one read query, found {len(candidates)}")
    return " ".join(candidates[0].split())


def _columns(raw: str) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    for entry in raw.split(","):
        parts = entry.strip().split()
        if not parts:
            continue
        direction = parts[1].upper() if len(parts) > 1 else "ASC"
        if direction not in {"ASC", "DESC"}:
            raise AssertionError(f"unsupported index or order direction: {entry.strip()}")
        parsed.append((parts[0].split(".")[-1], direction))
    return tuple(parsed)


def _named_index(ddl: str, name: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    matches = [match for match in _INDEX.finditer(ddl) if match.group("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one definition for {name}, found {len(matches)}")
    match = matches[0]
    return match.group("table"), _columns(match.group("columns"))


@pytest.mark.parametrize("contract", _CONTRACTS, ids=lambda contract: contract.name)
def test_ecr0090_read_order_matches_named_covering_index(contract: _Contract) -> None:
    query = _read_query(contract.method)
    table_match = _FROM.search(query)
    order_match = _ORDER_BY.search(query)
    assert table_match is not None
    assert order_match is not None
    assert table_match.group(1) == contract.table
    assert _columns(order_match.group(1)) == contract.order_by

    index_table, index_columns = _named_index(contract.ddl, contract.index_name)
    assert index_table == contract.table
    expected_prefix = (("tenant_id", "ASC"), *contract.order_by)
    assert index_columns[: len(expected_prefix)] == expected_prefix
