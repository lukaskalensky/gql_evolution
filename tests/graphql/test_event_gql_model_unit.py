"""Unit tests for Event GraphQL entity helpers and mutation delegates."""

from __future__ import annotations

import datetime
import types
import uuid

import pytest

from src.GraphTypeDefinitions.Domain_Events.EventGQLModel import (
    EventEnsureUserInvitationsModel,
    EventGQLModel,
    EventInvitationInsertModel,
    EventMutation,
)
from src.GraphTypeDefinitions.Domain_Events.TimeUnit import TimeUnit


class FakeExecutableService:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, object, object]] = []
        self.error_callbacks: list[dict] = []

    async def ExecuteServiceMethod(self, service_method, *, Error, OK):
        result = await service_method
        return OK(result)

    def CreateErrorCallback(self, **kwargs):
        self.error_callbacks.append(kwargs)

        def callback(*args, **inner_kwargs):
            return {"args": args, "kwargs": inner_kwargs, "definition": kwargs}

        return callback

    async def EnsureInvitations(self, *, ctx, entity):
        self.calls.append(("EnsureInvitations", ctx, entity))
        return self.result


def _db_row(**overrides):
    data = {
        "id": uuid.uuid4(),
        "lastchange": datetime.datetime.now(datetime.UTC).replace(microsecond=0),
    }
    data.update(overrides)
    return types.SimpleNamespace(**data)


def _info_with_services(*, event_service=None):
    services = types.SimpleNamespace(EventService=event_service)
    service_ctx = types.SimpleNamespace(Services=services)
    return types.SimpleNamespace(ServiceCtx=service_ctx)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (TimeUnit.SECONDS, 2 * 24 * 60 * 60),
        (TimeUnit.MINUTES, 2 * 24 * 60),
        (TimeUnit.HOURS, 48),
        (TimeUnit.DAYS, 2),
        (TimeUnit.WEEKS, 2 / 7),
        (object(), 2 * 24 * 60),
    ],
)
def test_event_duration_calculates_from_start_and_end_for_all_units(unit, expected):
    event = EventGQLModel(
        id=uuid.uuid4(),
        startdate=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        enddate=datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC),
        _dbdata=types.SimpleNamespace(duration=None),
    )

    assert event._duration(unit) == expected


def test_event_duration_returns_none_when_duration_and_dates_are_missing():
    event = EventGQLModel(
        id=uuid.uuid4(),
        startdate=None,
        enddate=None,
        _dbdata=types.SimpleNamespace(duration=None),
    )

    assert event._duration() is None


def test_event_duration_prefers_db_duration_over_explicit_dates():
    event = EventGQLModel(
        id=uuid.uuid4(),
        startdate=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        enddate=datetime.datetime(2026, 1, 30, tzinfo=datetime.UTC),
        _dbdata=types.SimpleNamespace(duration=datetime.timedelta(hours=3)),
    )

    assert event._duration(TimeUnit.HOURS) == 3


@pytest.mark.asyncio
async def test_event_ensure_invitations_delegates_to_event_service():
    result_row = _db_row(name="event")
    service = FakeExecutableService(result_row)
    info = _info_with_services(event_service=service)
    invitation = EventInvitationInsertModel(user_id=uuid.uuid4(), state_id=uuid.uuid4())
    entity = EventEnsureUserInvitationsModel(id=uuid.uuid4(), user_invitations=[invitation])
    loaded_row = _db_row(name="loaded event")

    result = await EventMutation().event_ensure_invitations(
        info=info,
        event=entity,
        rbacobject_id=uuid.uuid4(),
        user_roles=[],
        db_row=loaded_row,
    )

    assert isinstance(result, EventGQLModel)
    assert result.id == result_row.id
    assert service.calls == [("EnsureInvitations", info.ServiceCtx, entity)]
    assert service.error_callbacks[-1]["location"] == "event_ensure_invitations"
    assert service.error_callbacks[-1]["_input"] is entity
    assert isinstance(service.error_callbacks[-1]["_entity"], EventGQLModel)
    assert service.error_callbacks[-1]["_entity"].id == loaded_row.id
