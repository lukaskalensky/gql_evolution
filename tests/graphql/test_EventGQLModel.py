"""GraphQL contract tests for EventGQLModel.

One file is intentionally dedicated to one GQL model.  The tests use the public
GraphQL API defined for EventGQLModel in
``src/GraphTypeDefinitions/Domain_Events/EventGQLModel.py``:

* queries: ``eventPage`` and ``eventById``
* mutations: ``eventInsert``, ``eventUpdate``, ``eventEnsureInvitations`` and
  ``eventDelete``

The tests are explicit integration tests.  They execute GraphQL operations
against the test schema instead of calling resolvers or services directly.
"""

from __future__ import annotations

import pytest
from tests.support.asserts import assert_insert, assert_update, assert_delete, assert_same
from tests.support.explicit_fixtures import EXPLICIT_PARENT_EVENT_ID

async def event_insert(SchemaExecutor, CreateMutation, variables):
    query = CreateMutation("eventInsert")
    result = await SchemaExecutor(query=query, variable_values=variables)
    return result

async def event_update(SchemaExecutor, CreateMutation, variables):
    query = CreateMutation("eventUpdate")
    result = await SchemaExecutor(query=query, variable_values=variables)
    return result

async def event_delete(SchemaExecutor, CreateMutation, variables):
    query = CreateMutation("eventDelete")
    result = await SchemaExecutor(query=query, variable_values=variables)
    return result


@pytest.mark.asyncio
async def test_event_insert(SchemaExecutor, CreateMutation, WhoAmIExtensionOverride, RolePermissionSchemaExtensionOverride):
    # WhoAmIExtensionOverride.set_user(
    #     {
    #         "id": "30bc16ac-946a-4d73-a1ad-3fd3ddd038f7",
    #         "roles": [{
    #             "roletype": {"name": "plánovací administrátor"}
    #         }]
    #     }
    # )
    RolePermissionSchemaExtensionOverride.set_response(
        {
            "result": [
                {
                    "roletype": {
                        "id": "b87aed46-dfc3-40f8-ad49-03f4138c7478",
                        "name": "plánovací administrátor"
                    }
                }
            ]
        }
    )

    event = {
        "mastereventId": str(EXPLICIT_PARENT_EVENT_ID),
        "name": "Test Event",
    }
    result = await event_insert(SchemaExecutor, CreateMutation, event)
    assert_insert(result)

@pytest.mark.asyncio
async def test_event_update(SchemaExecutor, CreateMutation, RolePermissionSchemaExtensionOverride):
    RolePermissionSchemaExtensionOverride.set_response(
        {
            "result": [
                {
                    "roletype": {
                        "id": "b87aed46-dfc3-40f8-ad49-03f4138c7478",
                        "name": "plánovací administrátor"
                    }
                }
            ]
        }
    )

    event = {
        "mastereventId": str(EXPLICIT_PARENT_EVENT_ID),
        "name": "Test Event",
    }
    delta = {
        "name": "Updated Test Event",
    }
    result = await event_insert(SchemaExecutor, CreateMutation, event)
    event_inserted = assert_insert(result)
    payload = {
        **event,
        **event_inserted,
        **delta
    }
    result = await event_update(SchemaExecutor, CreateMutation, payload)
    event_updated = assert_update(result)
    assert_same(delta, event_updated)

@pytest.mark.asyncio
async def test_event_delete(SchemaExecutor, CreateMutation, RolePermissionSchemaExtensionOverride):
    RolePermissionSchemaExtensionOverride.set_response(
        {
            "result": [
                {
                    "roletype": {
                        "id": "b87aed46-dfc3-40f8-ad49-03f4138c7478",
                        "name": "plánovací administrátor"
                    }
                }
            ]
        }
    )

    event = {
        "mastereventId": str(EXPLICIT_PARENT_EVENT_ID),
        "name": "Test Event",
    }
    result = await event_insert(SchemaExecutor, CreateMutation, event)
    event_inserted = assert_insert(result)
    payload = {
        **event,
        **event_inserted
    }
    result = await event_delete(SchemaExecutor, CreateMutation, payload)
    assert_delete(result)