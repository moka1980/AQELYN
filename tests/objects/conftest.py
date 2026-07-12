"""Fixtures: object_store parametrized over in-memory and Postgres."""

import os
from collections.abc import AsyncIterator

import pytest

from aqelyn.objects import InMemoryObjectStore, ObjectTypeRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")


def _registry() -> ObjectTypeRegistry:
    reg = ObjectTypeRegistry()

    def require_hostname(attrs: dict[str, object]) -> None:
        if "hostname" not in attrs:
            from aqelyn.conventions.errors import SchemaValidationError

            raise SchemaValidationError("device requires hostname")

    reg.register("device", 1, require_hostname)
    return reg


@pytest.fixture(params=["inmemory", "postgres"])
async def object_store(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    mode = "local"
    if request.param == "inmemory":
        yield InMemoryObjectStore(registry=_registry(), mode=mode)
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.objects.postgres import PostgresObjectStore

    store = await PostgresObjectStore.connect(PG_URL, registry=_registry(), mode=mode)
    # clean slate
    async with store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_object, aq_relationship, aq_object_natural_key, aq_object_history"
        )
    try:
        yield store
    finally:
        await store.close()
