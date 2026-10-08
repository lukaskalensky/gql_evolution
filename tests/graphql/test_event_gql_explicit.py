"""
Explicit GraphQL tests for Event query/mutation contract.

These are intentionally explicit integration tests. They execute a fresh test
schema with the real SessionCommitExtension and local fake WhoAmI/permission
extensions. External UG/WhoAmI communication is not used.
"""

from __future__ import annotations

import os
import uuid

import pytest
import logging

from tests.support.asserts import assert_delete, assert_insert, assert_read, assert_update
from tests.support.explicit_fixtures import EXPLICIT_PARENT_EVENT_ID


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_event_page_explicit(SchemaExecutor):
    result = await SchemaExecutor(
        query="""
        query EventPage($limit: Int!) {
          eventPage(limit: $limit) {
            id
            name
            nameEn
            place
            lastchange
            valid
          }
        }
        """,
        variable_values={"limit": 1000},
    )

    assert result.get("errors") is None
    assert result.get("data") is not None
    assert isinstance(result["data"]["eventPage"], list)


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_event_by_id_explicit(SchemaExecutor):
    result = await SchemaExecutor(
        query="""
        query EventPage($limit: Int!) {
          eventPage(limit: $limit) {
            id
            name
            nameEn
            place
            lastchange
            duration
            valid
          }
        }
        """,
        variable_values={"limit": 5},
    )
    events = result.get("data", {}).get("eventPage", [])
    if not events:
        pytest.skip("No events found for eventById test")
    event_id = events[0]["id"]
    event_id = os.getenv("EXPLICIT_TEST_EVENT_ID", event_id)
    if not event_id:
        pytest.skip("Missing EXPLICIT_TEST_EVENT_ID")

    result = await SchemaExecutor(
        query="""
        query EventById($id: UUID!) {
          eventById(id: $id) {
            __typename
            id
            name
            nameEn
            description
            startdate
            enddate
            place
            lastchange
          }
        }
        """,
        variable_values={"id": event_id},
    )

    entity = assert_read(result)
    assert entity["id"] == event_id


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_event_insert_update_delete_explicit(SchemaExecutor):
    """Atomic GraphQL mutation contract for eventInsert/eventUpdate/eventDelete."""

    event_id = str(uuid.uuid4())
    inserted_name = "pytest explicit gql event"
    updated_name = "pytest explicit gql event updated"

    variable_values={
        "event": {
            "id": event_id,
            "name": inserted_name,
            "nameEn": inserted_name,
            "mastereventId": str(EXPLICIT_PARENT_EVENT_ID),
            "description": "created by explicit GraphQL test",
            "startdate": "2026-01-01T00:00:00", #iso_datetime(1).isoformat(),
            "enddate": "2026-01-02T00:00:00", #iso_datetime(2).isoformat(),
            "place": "pytest",
        }
    }
    insert_result = await SchemaExecutor(
        query="""
        mutation EventInsert($event: EventInsertGQLModel!) {
          eventInsert(event: $event) {
            __typename
            ... on EventGQLModel {
              id
              name
              nameEn
              lastchange
            }
            ... on EventGQLModelInsertError {
              msg
              code
              location
            }
          }
        }
        """,
        variable_values=variable_values,
    )

    inserted = assert_insert(insert_result)
    assert inserted["id"] == event_id
    assert inserted["name"] == inserted_name

    logging.info(f"Inserted event: \n{variable_values}\n{inserted}")

    result = await SchemaExecutor(
        query="""
        query EventById($id: UUID!) {
          eventById(id: $id) {
            __typename
            id
            name
            nameEn
            description
            startdate
            enddate
            place
            lastchange
          }
        }
        """,
        variable_values={"id": event_id},
    )
    entity = assert_read(result)
    assert entity["id"] == event_id
    assert entity["name"] == inserted_name


    update_result = await SchemaExecutor(
        query="""
        mutation EventUpdate($event: EventUpdateGQLModel!) {
          eventUpdate(event: $event) {
            __typename
            ... on EventGQLModel {
              id
              name
              lastchange
            }
            ... on EventGQLModelUpdateError{
              msg
              code
              location
              Entity {
                __typename
                id
                name
              }
            }
          }
        }
        """,
        variable_values={
            "event": {
                "id": event_id,
                "lastchange": inserted["lastchange"],
                "name": updated_name,
            }
        },
    )


    updated = assert_update(update_result)
    assert updated["id"] == event_id
    assert updated["name"] == updated_name

    logging.info(f"Updated event: {updated}")

    delete_result = await SchemaExecutor(
        query="""
        mutation EventDelete($event: EventDeleteGQLModel!) {
          eventDelete(event: $event) {
            __typename
            ... on EventGQLModelDeleteError {
              msg
              code
              location
            }
          }
        }
        """,
        variable_values={
            "event": {
                "id": event_id,
                "lastchange": updated["lastchange"],
            }
        },
    )

    assert_delete(delete_result)


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_gql_event_insert_rollback_on_error_explicit(SchemaExecutor):
    """Failed mutation must not be accepted as another EventGQLModel."""

    event_id = str(uuid.uuid4())

    first = await SchemaExecutor(
        query="""
        mutation EventInsert($event: EventInsertGQLModel!) {
          eventInsert(event: $event) {
            __typename
            ... on EventGQLModel { id name lastchange }
            ... on EventGQLModelInsertError { msg code location }
          }
        }
        """,
        variable_values={
            "event": {
                "id": event_id,
                "name": "pytest rollback gql event",
                "mastereventId": str(EXPLICIT_PARENT_EVENT_ID),
                "startdate": "2023-01-01T00:00:00", #iso_datetime(1).isoformat(),
                "enddate": "2023-12-31T23:59:59", #iso_datetime(2).isoformat(),
            }
        },
    )
    assert_insert(first)

    second = await SchemaExecutor(
        query="""
        mutation EventInsert($event: EventInsertGQLModel!) {
          eventInsert(event: $event) {
            __typename
            ... on EventGQLModel { id name lastchange }
            ... on EventGQLModelInsertError { msg code location }
          }
        }
        """,
        variable_values={
            "event": {
                "id": event_id,
                "name": "pytest duplicate rollback gql event",
            }
        },
    )

    if second.get("errors"):
        assert second["errors"]
    else:
        payload = second["data"]["eventInsert"]
        assert "Error" in payload["__typename"], payload
