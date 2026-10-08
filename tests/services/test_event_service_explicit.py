"""
Explicit service tests for EventService.

Add tests here manually whenever EventService receives a new business method.
The generic CRUD smoke tests stay in test_servicedefinitions_crud.py; this file
is for domain-specific behavior and named service methods.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from src.DBDefinitions import EventModel
from src.ServiceDefinitions.Domain_Events.EventInvitationService import ORGANIZER_STATE_ID
from src.ServiceDefinitions.ServiceContext import ServiceContext
from tests.support.explicit_fixtures import env_uuid, iso_datetime


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_event_service_create_read_update_delete_explicit(
    explicit_service_ctx: ServiceContext,
):
    """Explicit contract test for the inherited CRUD methods on EventService."""

    service = explicit_service_ctx.Services.EventService
    event_id = uuid.uuid4()

    created = await service.Create(
        ctx=explicit_service_ctx,
        entity=EventModel(
            id=event_id,
            name="pytest explicit service event",
            name_en="pytest explicit service event",
            description="created by explicit EventService test",
            startdate=datetime.datetime(2023, 1, 1, 0, 0, 0),
            enddate=datetime.datetime(2023, 12, 31, 23, 59, 59),
            place="pytest",
        ),
    )

    assert created is not None
    assert created.id == event_id

    loaded = await service.ReadById(ctx=explicit_service_ctx, id=event_id)
    assert loaded is not None
    assert loaded.id == event_id
    assert loaded.name == "pytest explicit service event"

    update_entity = EventModel(
        id=event_id,
        lastchange=loaded.lastchange,
        name="pytest explicit service event updated",
    )
    updated = await service.Update(ctx=explicit_service_ctx, entity=update_entity)
    assert updated is not None
    assert updated.id == event_id
    assert updated.name == "pytest explicit service event updated"

    delete_entity = EventModel(id=event_id, lastchange=updated.lastchange)
    deleted = await service.Delete(ctx=explicit_service_ctx, entity=delete_entity)
    assert deleted is None

    loaded_after_delete = await service.ReadById(ctx=explicit_service_ctx, id=event_id)
    assert loaded_after_delete is None


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_event_service_ensure_invitations_creates_missing_invitations_explicit(
    explicit_service_ctx: ServiceContext,
):
    """Explicit contract test for EventService.EnsureInvitations.

    Requires EXPLICIT_TEST_INVITED_USER_ID when the local DB enforces a real
    users table / FK.  Without that value the test is skipped because the
    correct user id is domain data, not generated test data.
    """

    # invited_user_id = env_uuid("EXPLICIT_TEST_INVITED_USER_ID", required=True)
    invited_user_id = uuid.UUID("51d101a0-81f1-44ca-8366-6cf51432e8d6")  # for local DB with no users table
    service = explicit_service_ctx.Services.EventService
    invitation_service = explicit_service_ctx.Services.EventInvitationService

    event_id = uuid.uuid4()
    await service.Create(
        ctx=explicit_service_ctx,
        entity=EventModel(
            id=event_id,
            name="pytest ensure invitations event",
            startdate=datetime.datetime(2023, 1, 1, 0, 0, 0),
            enddate=datetime.datetime(2023, 12, 31, 23, 59, 59),
        ),
    )

    class InvitationInput:
        id = None
        user_id = invited_user_id
        state_id = ORGANIZER_STATE_ID
        event_id = None
        createdby_id = None
        rbacobject_id = None

    class EnsureInput:
        id = event_id
        user_invitations = [InvitationInput()]

    result = await service.EnsureInvitations(ctx=explicit_service_ctx, event=EnsureInput())
    assert result is not None
    assert result.id == event_id

    invited_users = await invitation_service.GetInvitedUsers(
        ctx=explicit_service_ctx,
        entity=EnsureInput(),
    )
    assert invited_user_id in invited_users


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_event_service_ensure_invitations_is_idempotent_explicit(
    explicit_service_ctx: ServiceContext,
):
    """Calling EnsureInvitations twice must not duplicate existing invitations."""

    # invited_user_id = env_uuid("EXPLICIT_TEST_INVITED_USER_ID", required=True)
    invited_user_id = uuid.UUID("51d101a0-81f1-44ca-8366-6cf51432e8d6")  # for local DB with no users table

    service = explicit_service_ctx.Services.EventService
    invitation_service = explicit_service_ctx.Services.EventInvitationService

    event_id = uuid.uuid4()
    await service.Create(
        ctx=explicit_service_ctx,
        entity=EventModel(
            id=event_id,
            name="pytest idempotent ensure invitations event",
            startdate=datetime.datetime(2023, 1, 1, 0, 0, 0),
            enddate=datetime.datetime(2023, 12, 31, 23, 59, 59),
        ),
    )

    class InvitationInput:
        id = None
        user_id = invited_user_id
        state_id = ORGANIZER_STATE_ID
        event_id = None
        createdby_id = None
        rbacobject_id = None

    class EnsureInput:
        id = event_id
        user_invitations = [InvitationInput()]

    await service.EnsureInvitations(ctx=explicit_service_ctx, event=EnsureInput())
    first = await invitation_service.GetInvitedUsers(ctx=explicit_service_ctx, entity=EnsureInput())

    await service.EnsureInvitations(ctx=explicit_service_ctx, event=EnsureInput())
    second = await invitation_service.GetInvitedUsers(ctx=explicit_service_ctx, entity=EnsureInput())

    assert first.count(invited_user_id) == 1
    assert second.count(invited_user_id) == 1
