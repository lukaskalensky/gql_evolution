import dataclasses
import datetime
import types
import uuid

import pytest
import pytest_asyncio

from src.DBDefinitions import TagEntityModel, TagModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes
from tests.services.conftest import TAG_TEST_USER_ID


def service(ctx):
    return ctx.Services.TagEntityService


def assignment(tag_id, entity_id=None, entity_type_id=None):
    return TagEntityModel(entity_id=entity_id or uuid.uuid4(), entity_type_id=entity_type_id or uuid.uuid4(), tag_id=tag_id)


async def assert_fails(code, coroutine):
    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await coroutine
    assert exc_info.value.code == code


@pytest_asyncio.fixture
async def tag(tag_ctx):
    return await tag_ctx.Services.TagService.Create(ctx=tag_ctx, entity=TagModel(name='important', label='Důležité'))


@pytest.mark.asyncio
async def test_project_a_gets_two_tags(tag_ctx, tag):
    """Scénář ze zadání: Project A -> Důležité, K projednání."""
    review = await tag_ctx.Services.TagService.Create(ctx=tag_ctx, entity=TagModel(name='review', label='K projednání'))
    project_a, project_type = uuid.uuid4(), uuid.uuid4()

    await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id, project_a, project_type))
    await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(review.id, project_a, project_type))

    rows = await service(tag_ctx).ReadByEntity(ctx=tag_ctx, entity_id=project_a)
    assert {row.tag_id for row in rows} == {tag.id, review.id}
    assert {row.owner_id for row in rows} == {TAG_TEST_USER_ID}


@pytest.mark.asyncio
async def test_assign_is_idempotent_for_the_same_owner(tag_ctx, tag):
    entity_id, entity_type_id = uuid.uuid4(), uuid.uuid4()

    first = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id, entity_id, entity_type_id))
    second = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id, entity_id, entity_type_id))

    assert first.id == second.id
    assert len(await service(tag_ctx).ReadByEntity(ctx=tag_ctx, entity_id=entity_id)) == 1


@pytest.mark.asyncio
async def test_two_users_can_assign_the_same_tag(tag_ctx, tag):
    entity_id, entity_type_id = uuid.uuid4(), uuid.uuid4()
    other_ctx = dataclasses.replace(tag_ctx, user=types.SimpleNamespace(id=uuid.uuid4()))

    await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id, entity_id, entity_type_id))
    await service(tag_ctx).AssignTag(ctx=other_ctx, entity=assignment(tag.id, entity_id, entity_type_id))

    assert len(await service(tag_ctx).ReadByEntity(ctx=tag_ctx, entity_id=entity_id)) == 2


@pytest.mark.asyncio
async def test_assign_overrides_owner_supplied_by_caller(tag_ctx, tag):
    entity = assignment(tag.id)
    entity.owner_id = uuid.uuid4()

    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=entity)

    assert created.owner_id == TAG_TEST_USER_ID


@pytest.mark.asyncio
async def test_assign_requires_user(tag_ctx, tag):
    anonymous = dataclasses.replace(tag_ctx, user=None)

    await assert_fails(ErrorCodes.TAG_ENTITY_USER_REQUIRED, service(tag_ctx).AssignTag(ctx=anonymous, entity=assignment(tag.id)))


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['entity_id', 'entity_type_id', 'tag_id'])
async def test_assign_requires_all_identifiers(tag_ctx, tag, missing):
    entity = assignment(tag.id)
    setattr(entity, missing, None)

    await assert_fails(ErrorCodes.TAG_ENTITY_INVALID_INPUT, service(tag_ctx).AssignTag(ctx=tag_ctx, entity=entity))


@pytest.mark.asyncio
async def test_assign_rejects_missing_tag(tag_ctx):
    await assert_fails(ErrorCodes.TAG_ENTITY_TAG_NOT_FOUND, service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(uuid.uuid4())))


@pytest.mark.asyncio
async def test_unassign_by_owner(tag_ctx, tag):
    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id))

    await service(tag_ctx).UnassignTag(ctx=tag_ctx, entity=TagEntityModel(id=created.id, lastchange=created.lastchange))

    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=created.id) is None


@pytest.mark.asyncio
async def test_unassign_rejects_other_user(tag_ctx, tag):
    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id))
    other_ctx = dataclasses.replace(tag_ctx, user={'id': str(uuid.uuid4())})

    await assert_fails(ErrorCodes.TAG_ENTITY_NOT_OWNER, service(tag_ctx).UnassignTag(ctx=other_ctx, entity=TagEntityModel(id=created.id)))
    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=created.id) is not None


@pytest.mark.asyncio
async def test_unassign_rejects_stale_lastchange(tag_ctx, tag):
    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id))
    stale = created.lastchange - datetime.timedelta(days=1)

    await assert_fails(ErrorCodes.TAG_ENTITY_CONFLICT, service(tag_ctx).UnassignTag(ctx=tag_ctx, entity=TagEntityModel(id=created.id, lastchange=stale)))


@pytest.mark.asyncio
async def test_unassign_rejects_unknown_id(tag_ctx):
    await assert_fails(ErrorCodes.TAG_ENTITY_NOT_FOUND, service(tag_ctx).UnassignTag(ctx=tag_ctx, entity=TagEntityModel(id=uuid.uuid4())))


@pytest.mark.asyncio
async def test_read_by_entity_filters_by_entity_type(tag_ctx, tag):
    entity_id, wanted_type = uuid.uuid4(), uuid.uuid4()
    wanted = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id, entity_id, wanted_type))
    await service(tag_ctx).Create(ctx=tag_ctx, entity=assignment(tag.id, entity_id, uuid.uuid4()))

    rows = await service(tag_ctx).ReadByEntity(ctx=tag_ctx, entity_id=entity_id, entity_type_id=wanted_type)

    assert [row.id for row in rows] == [wanted.id]


@pytest.mark.asyncio
async def test_read_by_tag_sees_assignment_created_in_same_session(tag_ctx, tag):
    assert await service(tag_ctx).ReadByTag(ctx=tag_ctx, tag_id=tag.id) == []

    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id))

    assert [row.id for row in await service(tag_ctx).ReadByTag(ctx=tag_ctx, tag_id=tag.id)] == [created.id]


@pytest.mark.asyncio
async def test_update_moves_assignment_to_existing_tag_only(tag_ctx, tag):
    review = await tag_ctx.Services.TagService.Create(ctx=tag_ctx, entity=TagModel(name='review'))
    created = await service(tag_ctx).AssignTag(ctx=tag_ctx, entity=assignment(tag.id))

    class PatchInput:
        id = created.id
        lastchange = created.lastchange
        tag_id = uuid.uuid4()

    await assert_fails(ErrorCodes.TAG_ENTITY_TAG_NOT_FOUND, service(tag_ctx).Update(ctx=tag_ctx, entity=PatchInput()))

    PatchInput.tag_id = review.id
    updated = await service(tag_ctx).Update(ctx=tag_ctx, entity=PatchInput())
    assert updated.tag_id == review.id
