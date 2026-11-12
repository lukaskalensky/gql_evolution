import datetime
import uuid

import pytest

from src.DBDefinitions import TagEntityModel, TagModel, TagTypeModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes


def service(ctx):
    return ctx.Services.TagService


async def create_tag(ctx, **attributes):
    return await service(ctx).Create(ctx=ctx, entity=TagModel(name='important', label='Důležité', **attributes))


async def assert_fails(code, coroutine):
    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await coroutine
    assert exc_info.value.code == code


@pytest.mark.asyncio
async def test_tag_crud_with_existing_type(tag_ctx):
    tag_type = await tag_ctx.Services.TagTypeService.Create(ctx=tag_ctx, entity=TagTypeModel(name='Priorita'))
    tag = await create_tag(tag_ctx, color='#ff0000', type_id=tag_type.id)

    assert (await service(tag_ctx).ReadById(ctx=tag_ctx, id=tag.id)).type_id == tag_type.id
    assert [row.id for row in await service(tag_ctx).ReadPage(ctx=tag_ctx, where={'name': {'_eq': 'important'}})] == [tag.id]

    updated = await service(tag_ctx).Update(
        ctx=tag_ctx,
        entity=TagModel(id=tag.id, lastchange=tag.lastchange, label='Velmi důležité', type_id=tag_type.id),
    )
    assert updated.label == 'Velmi důležité'

    await service(tag_ctx).Delete(ctx=tag_ctx, entity=TagModel(id=tag.id, lastchange=updated.lastchange))
    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=tag.id) is None


@pytest.mark.asyncio
async def test_tag_without_type_is_allowed(tag_ctx):
    tag = await create_tag(tag_ctx)
    assert tag.type_id is None


@pytest.mark.asyncio
async def test_tag_create_and_update_reject_missing_type(tag_ctx):
    await assert_fails(ErrorCodes.TAG_TYPE_REFERENCE_NOT_FOUND, create_tag(tag_ctx, type_id=uuid.uuid4()))

    tag = await create_tag(tag_ctx)
    await assert_fails(
        ErrorCodes.TAG_TYPE_REFERENCE_NOT_FOUND,
        service(tag_ctx).Update(ctx=tag_ctx, entity=TagModel(id=tag.id, lastchange=tag.lastchange, type_id=uuid.uuid4())),
    )


@pytest.mark.asyncio
async def test_tag_update_and_delete_reject_stale_lastchange(tag_ctx):
    tag = await create_tag(tag_ctx)
    stale = tag.lastchange - datetime.timedelta(days=1)

    await assert_fails(ErrorCodes.TAG_CONFLICT, service(tag_ctx).Update(ctx=tag_ctx, entity=TagModel(id=tag.id, lastchange=stale, label='x')))
    await assert_fails(ErrorCodes.TAG_CONFLICT, service(tag_ctx).Delete(ctx=tag_ctx, entity=TagModel(id=tag.id, lastchange=stale)))


@pytest.mark.asyncio
async def test_tag_update_and_delete_reject_unknown_id(tag_ctx):
    unknown = TagModel(id=uuid.uuid4(), lastchange=datetime.datetime.now())

    await assert_fails(ErrorCodes.TAG_NOT_FOUND, service(tag_ctx).Update(ctx=tag_ctx, entity=unknown))
    await assert_fails(ErrorCodes.TAG_NOT_FOUND, service(tag_ctx).Delete(ctx=tag_ctx, entity=unknown))


@pytest.mark.asyncio
async def test_tag_delete_rejects_assigned_tag(tag_ctx):
    tag = await create_tag(tag_ctx)
    await tag_ctx.loaders.TagEntityModel.insert(TagEntityModel(entity_id=uuid.uuid4(), entity_type_id=uuid.uuid4(), tag_id=tag.id))

    await assert_fails(ErrorCodes.TAG_HAS_ASSIGNMENTS, service(tag_ctx).Delete(ctx=tag_ctx, entity=TagModel(id=tag.id)))
    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=tag.id) is not None
