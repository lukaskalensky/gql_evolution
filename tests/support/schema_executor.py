from __future__ import annotations

import logging

import pytest
import pytest_asyncio
import json
import logging
from graphql import parse

from tests.support.explicit_fixtures import explicit_permission_response, explicit_user
from tests.support.explicit_schema import create_explicit_test_schema
from tests.support.fake_permissions_extension import FakeRolePermissionSchemaExtension
from tests.support.fake_whoami_extension import FakeWhoAmIExtension


@pytest.fixture
def WhoAmIExtensionOverride():
    """Compatibility fixture matching the older test suite naming."""

    FakeWhoAmIExtension.reset()
    FakeWhoAmIExtension.set_user(explicit_user())
    return FakeWhoAmIExtension


@pytest.fixture
def RolePermissionSchemaExtensionOverride():
    """Compatibility fixture matching the older test suite naming."""

    FakeRolePermissionSchemaExtension.reset()
    FakeRolePermissionSchemaExtension.set_response(explicit_permission_response())
    return FakeRolePermissionSchemaExtension


@pytest.fixture
def ExplicitSchema(WhoAmIExtensionOverride, RolePermissionSchemaExtensionOverride):
    """Fresh schema per test, without mutating production ``schema.extensions``."""

    return create_explicit_test_schema()


@pytest_asyncio.fixture
async def SchemaExecutor(
    explicit_gql_context,
    ExplicitSchema,
    WhoAmIExtensionOverride,
    RolePermissionSchemaExtensionOverride,
):
    """Execute GraphQL against explicit test schema and return dict result.

    This mirrors the older ``SchemaExecutor`` pattern, but uses GraphQLContext
    and SessionCommitExtension instead of manually creating sessions in the
    context fixture.
    """

    user = explicit_gql_context.get("test_user") or explicit_user()
    WhoAmIExtensionOverride.set_user(user)
    RolePermissionSchemaExtensionOverride.set_response(explicit_permission_response())

    async def execute(query: str, variable_values: dict | None = None):
        result = await ExplicitSchema.execute(
            query=query,
            variable_values=variable_values or {},
            context_value=explicit_gql_context,
        )
        value = {"data": result.data}
        if result.errors:
            value["errors"] = result.errors
        variable_values_json = json.dumps(variable_values, default=str, indent=2) if variable_values else None
        value_json = json.dumps(value, default=str, indent=2)
        logging.info(f"Executed query: \n{query}\nwith variables: \n{variable_values_json}\nResult: \n{value_json}")
        return value

    return execute


@pytest_asyncio.fixture
async def Sdl(SchemaExecutor):
    service_sdl_query = """
      query {
        _service {
          sdl
        }
      }
    """
    sdl_json_result = await SchemaExecutor(query=service_sdl_query)
    data = sdl_json_result.get("data", {})
    sdl_str = data["_service"]["sdl"]
    # assert False
    return parse(sdl_str)


@pytest_asyncio.fixture
async def CreateMutation(Sdl):
    from tests.support.utils_sdl import build_expanded_mutation

    def create_mutation(name: str) -> str:
        query = build_expanded_mutation(Sdl, name)
        logging.info("mutation %s\n%s", name, query)
        assert query is not None, f"Failed to build mutation for {name}"
        return query

    return create_mutation


@pytest_asyncio.fixture
async def CreateQuery(Sdl):
    from tests.support.utils_sdl import build_query_page, build_query_scalar

    def create_query(name: str) -> str:
        query = build_query_scalar(Sdl, name)
        if not query:
            query = build_query_page(Sdl, name)
        logging.info("query %s\n%s", name, query)
        assert query is not None, f"Failed to build query for {name}"
        return query

    return create_query
