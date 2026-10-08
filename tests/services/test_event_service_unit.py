from __future__ import annotations

import types
import uuid

import pytest

from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Events.EventService import EventService


class FakeEventLoader:
    def __init__(self, result):
        self.result = result
        self.statements = []

    async def execute_select(self, stmt):
        self.statements.append(stmt)
        return self.result


class FakeInvitationServiceForEvent:
    created = []

    @classmethod
    async def Create(cls, ctx, entity):
        cls.created.append(entity)
        return entity


async def _patch_event_loader(monkeypatch, loader):
    async def fake_get_loader(cls, ctx):
        return loader

    monkeypatch.setattr(EventService, "getLoader", classmethod(fake_get_loader))
    return loader


def _ctx(*, user=None, services=None):
    return types.SimpleNamespace(user=user, Services=services or types.SimpleNamespace())


@pytest.mark.asyncio
async def test_event_service_ensure_invitations_raises_when_select_returns_none(monkeypatch):
    loader = FakeEventLoader(result=None)
    await _patch_event_loader(monkeypatch, loader)
    services = types.SimpleNamespace(EventInvitationService=FakeInvitationServiceForEvent)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventService.EnsureInvitations(
            ctx=_ctx(services=services),
            event=types.SimpleNamespace(id=uuid.uuid4(), user_invitations=[]),
        )

    assert exc_info.value.code == "event_not_found"
    assert exc_info.value.location == "EnsureInvitations"


@pytest.mark.asyncio
async def test_event_service_ensure_invitations_raises_when_select_returns_empty(monkeypatch):
    loader = FakeEventLoader(result=[])
    await _patch_event_loader(monkeypatch, loader)
    services = types.SimpleNamespace(EventInvitationService=FakeInvitationServiceForEvent)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventService.EnsureInvitations(
            ctx=_ctx(services=services),
            event=types.SimpleNamespace(id=uuid.uuid4(), user_invitations=[]),
        )

    assert exc_info.value.code == "event_not_found"
    assert exc_info.value.location == "EnsureInvitations"


@pytest.mark.asyncio
async def test_event_service_ensure_invitations_skips_existing_and_creates_missing(monkeypatch):
    existing_user_id = uuid.uuid4()
    new_user_id = uuid.uuid4()
    event_id = uuid.uuid4()
    db_event = types.SimpleNamespace(
        id=event_id,
        user_invitations=[types.SimpleNamespace(user_id=existing_user_id)],
    )
    loader = FakeEventLoader(result=[db_event])
    await _patch_event_loader(monkeypatch, loader)

    FakeInvitationServiceForEvent.created = []
    services = types.SimpleNamespace(EventInvitationService=FakeInvitationServiceForEvent)
    existing_input = types.SimpleNamespace(user_id=existing_user_id, event_id=None)
    new_input = types.SimpleNamespace(user_id=new_user_id, event_id=None)
    input_event = types.SimpleNamespace(
        id=event_id,
        user_invitations=[existing_input, new_input],
    )

    result = await EventService.EnsureInvitations(
        ctx=_ctx(services=services),
        event=input_event,
    )

    assert result is db_event
    assert FakeInvitationServiceForEvent.created == [new_input]
    assert existing_input.event_id is None
    assert new_input.event_id == event_id
