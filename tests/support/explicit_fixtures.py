"""
Shared fixtures for explicit, manually maintained tests.

These tests are intentionally not generated. Add one explicit test whenever a
service receives a new business method or a GraphQL query/mutation becomes part
of the public API contract.
"""

from __future__ import annotations

import datetime
import os
import typing
import uuid

import pytest
import pytest_asyncio

from src.Dataloaders import LoaderMap
from src.DBDefinitions import EventModel
from src.DBDefinitions.runtime import Database, DatabaseSettings
from src.GraphTypeDefinitions.GraphQLContext import GraphQLContext
from src.ServiceDefinitions.ServiceContext import ServiceContext

EXPLICIT_PARENT_EVENT_ID = uuid.UUID("a64871f8-2308-48ff-adb2-33fb0b0741f1")


def env_uuid(name: str, *, required: bool = False) -> uuid.UUID | None:
    value = os.getenv(name)
    if not value:
        if required:
            pytest.skip(f"Missing required environment variable {name}")
        return None
    return uuid.UUID(value)


def explicit_user() -> dict[str, typing.Any]:
    """User object used by service and GraphQL permission tests."""

    user_id = os.getenv("EXPLICIT_TEST_USER_ID") or str(uuid.uuid4())
    role_name = os.getenv("EXPLICIT_TEST_ROLE", "plánovací administrátor")
    return {
        "id": user_id,
        "name": os.getenv("EXPLICIT_TEST_USER_NAME", "pytest explicit user"),
        "email": os.getenv("EXPLICIT_TEST_USER_EMAIL", "pytest@example.test"),
        "roles": [
            {
                "name": role_name,
                "roletype": {"name": role_name},
                "valid": True,
            }
        ],
    }


async def explicit_ug_client(*args, **kwargs):
    """Minimal fake UG client for explicit service tests."""

    user = explicit_user()
    return {
        "id": user["id"],
        "roles": user["roles"],
    }


@pytest_asyncio.fixture
async def explicit_database_runtime():
    """Starts DatabaseRuntime for explicit tests.

    Function scope is intentional.  It avoids Windows/pytest-asyncio problems
    where a session-scoped async fixture is created on a different event loop
    than the actual async test.
    """

    settings = DatabaseSettings(
        connection_string=os.getenv("EXPLICIT_TEST_DATABASE_URL") or None,
        make_drop=os.getenv("EXPLICIT_TEST_DB_DROP", "0") == "1",
        make_up=True,
        seed_data=True,
    )
    await Database().start(settings)
    try:
        async with Database().session() as session:
            parent_event = await session.get(EventModel, EXPLICIT_PARENT_EVENT_ID)
            if parent_event is None:
                session.add(
                    EventModel(
                        id=EXPLICIT_PARENT_EVENT_ID,
                        rbacobject_id=EXPLICIT_PARENT_EVENT_ID,
                        name="pytest explicit parent event",
                    )
                )
                await session.commit()
        yield Database()
    finally:
        await Database().stop()


@pytest_asyncio.fixture
async def explicit_session(explicit_database_runtime):
    """Provides one DB session and rolls back after each explicit service test."""

    async with explicit_database_runtime.session() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def explicit_service_ctx(explicit_session):
    user = explicit_user()
    return ServiceContext(
        loaders=LoaderMap(explicit_session),
        user=user,
        ug_client=explicit_ug_client,
        request=None,
        session=explicit_session,
    )


@pytest_asyncio.fixture
async def explicit_gql_context(explicit_database_runtime):
    """GraphQL context consumed by SessionCommitExtension.

    SessionCommitExtension creates the real session and loaders for each GraphQL
    operation. This fixture supplies only request-independent values and factory
    hooks.
    """

    context = GraphQLContext(
        request=None,
        session_maker_factory=lambda: explicit_database_runtime.session_maker,
    )
    user = explicit_user()
    context["test_user"] = user
    context["user"] = user
    context["ug_client"] = explicit_ug_client
    return context


def explicit_permission_response(role_name: str | None = None) -> dict[str, list[dict[str, typing.Any]]]:
    role = role_name or os.getenv("EXPLICIT_TEST_ROLE", "plánovací administrátor")
    return {
        "result": [
            {
                "name": role,
                "roletype": {"name": role},
                "valid": True,
            }
        ]
    }


def iso_datetime(offset_days: int = 0) -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0) + datetime.timedelta(days=offset_days)
