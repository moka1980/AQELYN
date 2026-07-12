"""G1 acceptance tests for Knowledge Graph types and validation."""

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import GraphQueryInvalid, ObjectNotFound, SchemaValidationError
from aqelyn.graph import (
    MAX_DEPTH,
    MAX_NODES,
    MAX_WORK,
    EdgeView,
    NodeView,
    normalize_limits,
    require_node,
    validate_direction,
    validate_max_paths,
    validate_max_work,
    validate_within_hops,
)
from aqelyn.objects import InMemoryObjectStore


async def test_kg_invalid_params() -> None:
    with pytest.raises(GraphQueryInvalid, match="direction"):
        validate_direction("sideways")
    with pytest.raises(GraphQueryInvalid, match="max_depth"):
        normalize_limits(max_depth=0)
    with pytest.raises(GraphQueryInvalid, match="max_nodes"):
        normalize_limits(max_nodes=0)
    with pytest.raises(GraphQueryInvalid, match="within_hops"):
        validate_within_hops(0)
    with pytest.raises(GraphQueryInvalid, match="max_paths"):
        validate_max_paths(0)
    with pytest.raises(GraphQueryInvalid, match="max_work"):
        validate_max_work(0)

    capped = normalize_limits(max_depth=999, max_nodes=999_999)
    assert capped.max_depth == MAX_DEPTH
    assert capped.max_nodes == MAX_NODES
    assert validate_within_hops(999) == MAX_DEPTH
    assert validate_max_work(MAX_WORK + 1) == MAX_WORK

    with pytest.raises(SchemaValidationError, match="valid obj_ typed id"):
        NodeView(id="obj_not-a-uuid", object_type="generic", display_name="bad")
    with pytest.raises(SchemaValidationError, match="UUID string"):
        NodeView(id=new_id("obj"), object_type="generic", display_name="bad", tenant_id="t1")
    with pytest.raises(SchemaValidationError, match="rel_ prefix"):
        EdgeView(
            id=new_id("obj"),
            from_id=new_id("obj"),
            to_id=new_id("obj"),
            relation_type="depends_on",
        )

    with pytest.raises(ObjectNotFound):
        await require_node(InMemoryObjectStore(), new_id("obj"))
