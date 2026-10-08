"""
Explicit service tests for EventInvitationService.

These tests cover domain methods that cannot be safely generated from the
standard CRUD surface.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from src.DBDefinitions import EventInvitationModel, EventModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Events.EventInvitationService import (
    ACCEPTED_STATE_ID,
    DECLINED_STATE_ID,
    ORGANIZER_STATE_ID,
)
from src.ServiceDefinitions.ServiceContext import ServiceContext
from tests.support.explicit_fixtures import env_uuid, iso_datetime


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_event_invitation_accept_decline_by_invited_user_explicit(
    explicit_service_ctx: ServiceContext,
):
    # invited_user_id = env_uuid("EXPLICIT_TEST_INVITED_USER_ID", required=True)
    invited_user_id = uuid.UUID("51d101a0-81f1-44ca-8366-6cf51432e8d6")  # for local DB with no users table

    explicit_service_ctx.user = {"id": str(invited_user_id)}
    event_service = explicit_service_ctx.Services.EventService
    invitation_service = explicit_service_ctx.Services.EventInvitationService

    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()

    await event_service.Create(
        ctx=explicit_service_ctx,
        entity=EventModel(
            id=event_id,
            name="pytest invitation accept event",
            startdate=datetime.datetime(2023, 1, 1, 0, 0, 0),
            enddate=datetime.datetime(2023, 12, 31, 23, 59, 59),
        ),
    )
    created = await invitation_service.Create(
        ctx=explicit_service_ctx,
        entity=EventInvitationModel(
            id=invitation_id,
            event_id=event_id,
            user_id=invited_user_id,
            state_id=ORGANIZER_STATE_ID,
        ),
    )

    update_entity = EventInvitationModel(
        id=invitation_id,
        lastchange=created.lastchange,
        state_id=ACCEPTED_STATE_ID,
    )
    updated = await invitation_service.AcceptOrDeclineByInvitedUser(
        ctx=explicit_service_ctx,
        entity=update_entity,
    )

    assert updated is not None
    assert updated.id == invitation_id
    assert updated.state_id == ACCEPTED_STATE_ID


@pytest.mark.explicit
@pytest.mark.asyncio
async def test_event_invitation_accept_decline_rejects_different_user_explicit(
    explicit_service_ctx: ServiceContext,
):
    # invited_user_id = env_uuid("EXPLICIT_TEST_INVITED_USER_ID", required=True)
    invited_user_id = uuid.UUID("51d101a0-81f1-44ca-8366-6cf51432e8d6")  # for local DB with no users table

    explicit_service_ctx.user = {"id": str(uuid.uuid4())}
    event_service = explicit_service_ctx.Services.EventService
    invitation_service = explicit_service_ctx.Services.EventInvitationService

    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()

    await event_service.Create(
        ctx=explicit_service_ctx,
        entity=EventModel(
            id=event_id,
            name="pytest invitation reject event",
            startdate=datetime.datetime(2023, 1, 1, 0, 0, 0),
            enddate=datetime.datetime(2023, 12, 31, 23, 59, 59),
        ),
    )
    created = await invitation_service.Create(
        ctx=explicit_service_ctx,
        entity=EventInvitationModel(
            id=invitation_id,
            event_id=event_id,
            user_id=invited_user_id,
            state_id=ORGANIZER_STATE_ID,
        ),
    )

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await invitation_service.AcceptOrDeclineByInvitedUser(
            ctx=explicit_service_ctx,
            entity=EventInvitationModel(
                id=invitation_id,
                lastchange=created.lastchange,
                state_id=DECLINED_STATE_ID,
            ),
        )

    assert exc_info.value.code == "event_invitation_not_invited_user"
