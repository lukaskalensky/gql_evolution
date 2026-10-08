from __future__ import annotations

import types
import uuid

import pytest

from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Events.EventInvitationService import (
    ACCEPTED_STATE_ID,
    DECLINED_STATE_ID,
    ORGANIZER_STATE_ID,
    EventInvitationService,
)
from src.ServiceDefinitions.Domain_Events.EventService import EventService


class FakeInvitationLoader:
    def __init__(self, *, invitations_by_id=None, invitations_by_event=None):
        self.invitations_by_id = invitations_by_id or {}
        self.invitations_by_event = invitations_by_event or {}
        self.updated_entities = []
        self.deleted_ids = []

    async def load(self, id_):
        return self.invitations_by_id.get(id_)

    async def filter_by(self, **kwargs):
        event_id = kwargs.get("event_id")
        return list(self.invitations_by_event.get(event_id, []))

    async def update(self, *, entity, **kwargs):
        self.updated_entities.append(entity)
        return entity

    async def delete(self, id_):
        self.deleted_ids.append(id_)
        return None


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


async def _patch_invitation_loader(monkeypatch, loader):
    async def fake_get_loader(cls, ctx):
        return loader

    monkeypatch.setattr(EventInvitationService, "getLoader", classmethod(fake_get_loader))
    return loader


async def _patch_event_loader(monkeypatch, loader):
    async def fake_get_loader(cls, ctx):
        return loader

    monkeypatch.setattr(EventService, "getLoader", classmethod(fake_get_loader))
    return loader


def _ctx(*, user=None, services=None):
    return types.SimpleNamespace(user=user, Services=services or types.SimpleNamespace())


@pytest.mark.asyncio
async def test_event_invitation_ensure_organizer_raises_when_invitation_is_missing(monkeypatch):
    invitation_id = uuid.uuid4()
    loader = FakeInvitationLoader()
    await _patch_invitation_loader(monkeypatch, loader)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventInvitationService.EnsureUserIsOrganizerForInvitation(
            ctx=_ctx(user={"id": str(uuid.uuid4())}),
            invitation_id=invitation_id,
        )

    assert exc_info.value.code == "event_invitation_not_found"


@pytest.mark.asyncio
async def test_event_invitation_ensure_organizer_raises_for_non_organizer_object_user(monkeypatch):
    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    organizer_id = uuid.uuid4()
    current_user_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=event_id, user_id=current_user_id)
    organizer_row = types.SimpleNamespace(
        event_id=event_id,
        user_id=organizer_id,
        state_id=ORGANIZER_STATE_ID,
    )
    loader = FakeInvitationLoader(
        invitations_by_id={invitation_id: invitation},
        invitations_by_event={event_id: [organizer_row]},
    )
    await _patch_invitation_loader(monkeypatch, loader)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventInvitationService.EnsureUserIsOrganizerForInvitation(
            ctx=_ctx(user=types.SimpleNamespace(id=current_user_id)),
            invitation_id=invitation_id,
        )

    assert exc_info.value.code == "event_invitation_not_organizer"


@pytest.mark.asyncio
async def test_event_invitation_ensure_organizer_returns_invitation_for_dict_string_user(monkeypatch):
    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    organizer_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=event_id, user_id=uuid.uuid4())
    organizer_row = types.SimpleNamespace(
        event_id=event_id,
        user_id=organizer_id,
        state_id=ORGANIZER_STATE_ID,
    )
    loader = FakeInvitationLoader(
        invitations_by_id={invitation_id: invitation},
        invitations_by_event={event_id: [organizer_row]},
    )
    await _patch_invitation_loader(monkeypatch, loader)

    result = await EventInvitationService.EnsureUserIsOrganizerForInvitation(
        ctx=_ctx(user={"id": str(organizer_id)}),
        invitation_id=invitation_id,
    )

    assert result is invitation


@pytest.mark.asyncio
async def test_event_invitation_accept_or_decline_raises_when_invitation_is_missing(monkeypatch):
    loader = FakeInvitationLoader()
    await _patch_invitation_loader(monkeypatch, loader)
    entity = types.SimpleNamespace(id=uuid.uuid4(), state_id=ACCEPTED_STATE_ID)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventInvitationService.AcceptOrDeclineByInvitedUser(
            ctx=_ctx(user={"id": str(uuid.uuid4())}),
            entity=entity,
        )

    assert exc_info.value.code == "event_invitation_not_found"


@pytest.mark.asyncio
async def test_event_invitation_accept_or_decline_raises_for_invalid_state(monkeypatch):
    user_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=uuid.uuid4(), user_id=user_id)
    loader = FakeInvitationLoader(invitations_by_id={invitation_id: invitation})
    await _patch_invitation_loader(monkeypatch, loader)
    entity = types.SimpleNamespace(id=invitation_id, state_id=uuid.uuid4())

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await EventInvitationService.AcceptOrDeclineByInvitedUser(
            ctx=_ctx(user={"id": str(user_id)}),
            entity=entity,
        )

    assert exc_info.value.code == "invalid_invitation_state"
    assert loader.updated_entities == []


@pytest.mark.asyncio
async def test_event_invitation_accept_or_decline_updates_for_object_user(monkeypatch):
    user_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=uuid.uuid4(), user_id=user_id)
    loader = FakeInvitationLoader(invitations_by_id={invitation_id: invitation})
    await _patch_invitation_loader(monkeypatch, loader)
    entity = types.SimpleNamespace(id=invitation_id, state_id=DECLINED_STATE_ID)

    result = await EventInvitationService.AcceptOrDeclineByInvitedUser(
        ctx=_ctx(user=types.SimpleNamespace(id=user_id)),
        entity=entity,
    )

    assert result is entity
    assert loader.updated_entities == [entity]


@pytest.mark.asyncio
async def test_event_invitation_update_by_organizer_checks_organizer_and_updates(monkeypatch):
    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    organizer_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=event_id, user_id=uuid.uuid4())
    organizer_row = types.SimpleNamespace(user_id=organizer_id, state_id=ORGANIZER_STATE_ID)
    loader = FakeInvitationLoader(
        invitations_by_id={invitation_id: invitation},
        invitations_by_event={event_id: [organizer_row]},
    )
    await _patch_invitation_loader(monkeypatch, loader)
    entity = types.SimpleNamespace(id=invitation_id, state_id=ACCEPTED_STATE_ID)

    result = await EventInvitationService.UpdateByOrganizer(
        ctx=_ctx(user={"id": str(organizer_id)}),
        entity=entity,
    )

    assert result is entity
    assert loader.updated_entities == [entity]


@pytest.mark.asyncio
async def test_event_invitation_delete_by_organizer_checks_organizer_and_deletes(monkeypatch):
    event_id = uuid.uuid4()
    invitation_id = uuid.uuid4()
    organizer_id = uuid.uuid4()
    invitation = types.SimpleNamespace(id=invitation_id, event_id=event_id, user_id=uuid.uuid4())
    organizer_row = types.SimpleNamespace(user_id=organizer_id, state_id=ORGANIZER_STATE_ID)
    loader = FakeInvitationLoader(
        invitations_by_id={invitation_id: invitation},
        invitations_by_event={event_id: [organizer_row]},
    )
    await _patch_invitation_loader(monkeypatch, loader)
    entity = types.SimpleNamespace(id=invitation_id)

    result = await EventInvitationService.DeleteByOrganizer(
        ctx=_ctx(user={"id": str(organizer_id)}),
        entity=entity,
    )

    assert result is None
    assert loader.deleted_ids == [invitation_id]


@pytest.mark.asyncio
async def test_event_invitation_get_invited_users_returns_user_ids(monkeypatch):
    event_id = uuid.uuid4()
    first_user_id = uuid.uuid4()
    second_user_id = uuid.uuid4()
    loader = FakeInvitationLoader(
        invitations_by_event={
            event_id: [
                types.SimpleNamespace(user_id=first_user_id),
                types.SimpleNamespace(user_id=second_user_id),
            ]
        }
    )
    await _patch_invitation_loader(monkeypatch, loader)

    result = await EventInvitationService.GetInvitedUsers(
        ctx=_ctx(),
        entity=types.SimpleNamespace(id=event_id),
    )

    assert result == [first_user_id, second_user_id]


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
