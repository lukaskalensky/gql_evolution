import datetime
import uuid

import pytest
import strawberry

from src.DBDefinitions import TagModel, TagTypeModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes


def service(ctx):
    return ctx.Services.TagTypeService


async def create_type(ctx, name='Priorita', parent_id=None):
    return await service(ctx).Create(ctx=ctx, entity=TagTypeModel(name=name, parent_id=parent_id))


async def assert_fails(code, coroutine):
    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await coroutine
    assert exc_info.value.code == code


@pytest.mark.asyncio
async def test_tag_type_crud(tag_ctx):
    root = await create_type(tag_ctx, 'Tagy')
    child = await create_type(tag_ctx, 'Priorita', parent_id=root.id)

    assert (await service(tag_ctx).ReadById(ctx=tag_ctx, id=child.id)).parent_id == root.id
    page = await service(tag_ctx).ReadPage(ctx=tag_ctx, where={'name': {'_eq': 'Priorita'}})
    assert [row.id for row in page] == [child.id]

    updated = await service(tag_ctx).Update(
        ctx=tag_ctx,
        entity=TagTypeModel(id=child.id, lastchange=child.lastchange, name='Důležitost', parent_id=root.id),
    )
    assert updated.name == 'Důležitost'

    await service(tag_ctx).Delete(ctx=tag_ctx, entity=TagTypeModel(id=child.id, lastchange=updated.lastchange))
    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=child.id) is None


@pytest.mark.asyncio
async def test_tag_type_create_rejects_missing_parent(tag_ctx):
    await assert_fails(ErrorCodes.TAG_TYPE_PARENT_NOT_FOUND, create_type(tag_ctx, parent_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_tag_type_update_rejects_self_as_parent(tag_ctx):
    row = await create_type(tag_ctx)

    await assert_fails(
        ErrorCodes.TAG_TYPE_CYCLE,
        service(tag_ctx).Update(ctx=tag_ctx, entity=TagTypeModel(id=row.id, lastchange=row.lastchange, parent_id=row.id)),
    )


@pytest.mark.asyncio
async def test_tag_type_update_rejects_descendant_as_parent(tag_ctx):
    root = await create_type(tag_ctx, 'Tagy')
    child = await create_type(tag_ctx, 'Priorita', parent_id=root.id)
    grandchild = await create_type(tag_ctx, 'Vysoká', parent_id=child.id)

    await assert_fails(
        ErrorCodes.TAG_TYPE_CYCLE,
        service(tag_ctx).Update(ctx=tag_ctx, entity=TagTypeModel(id=root.id, lastchange=root.lastchange, parent_id=grandchild.id)),
    )


@pytest.mark.asyncio
async def test_tag_type_update_keeps_parent_when_unset(tag_ctx):
    root = await create_type(tag_ctx, 'Tagy')
    child = await create_type(tag_ctx, 'Priorita', parent_id=root.id)

    class PatchInput:
        id = child.id
        lastchange = child.lastchange
        name = 'Důležitost'
        parent_id = strawberry.UNSET

    updated = await service(tag_ctx).Update(ctx=tag_ctx, entity=PatchInput())

    assert updated.name == 'Důležitost'
    assert updated.parent_id == root.id


@pytest.mark.asyncio
async def test_tag_type_update_rejects_stale_lastchange(tag_ctx):
    row = await create_type(tag_ctx)
    stale = row.lastchange - datetime.timedelta(days=1)

    await assert_fails(
        ErrorCodes.TAG_TYPE_CONFLICT,
        service(tag_ctx).Update(ctx=tag_ctx, entity=TagTypeModel(id=row.id, lastchange=stale, name='x')),
    )


@pytest.mark.asyncio
async def test_tag_type_update_and_delete_reject_unknown_id(tag_ctx):
    unknown = TagTypeModel(id=uuid.uuid4(), lastchange=datetime.datetime.now())

    await assert_fails(ErrorCodes.TAG_TYPE_NOT_FOUND, service(tag_ctx).Update(ctx=tag_ctx, entity=unknown))
    await assert_fails(ErrorCodes.TAG_TYPE_NOT_FOUND, service(tag_ctx).Delete(ctx=tag_ctx, entity=unknown))


@pytest.mark.asyncio
async def test_tag_type_delete_rejects_stale_lastchange(tag_ctx):
    row = await create_type(tag_ctx)
    stale = row.lastchange - datetime.timedelta(days=1)

    await assert_fails(ErrorCodes.TAG_TYPE_CONFLICT, service(tag_ctx).Delete(ctx=tag_ctx, entity=TagTypeModel(id=row.id, lastchange=stale)))
    assert await service(tag_ctx).ReadById(ctx=tag_ctx, id=row.id) is not None


@pytest.mark.asyncio
async def test_tag_type_delete_rejects_type_with_children(tag_ctx):
    root = await create_type(tag_ctx, 'Tagy')
    await create_type(tag_ctx, 'Priorita', parent_id=root.id)

    await assert_fails(ErrorCodes.TAG_TYPE_HAS_CHILDREN, service(tag_ctx).Delete(ctx=tag_ctx, entity=TagTypeModel(id=root.id)))


@pytest.mark.asyncio
async def test_tag_type_delete_rejects_type_used_by_tags(tag_ctx):
    row = await create_type(tag_ctx)
    await tag_ctx.loaders.TagModel.insert(TagModel(name='urgent', type_id=row.id))

    await assert_fails(ErrorCodes.TAG_TYPE_HAS_TAGS, service(tag_ctx).Delete(ctx=tag_ctx, entity=TagTypeModel(id=row.id)))
