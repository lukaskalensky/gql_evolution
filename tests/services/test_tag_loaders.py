import uuid

import pytest

from src.DBDefinitions import TagEntityModel, TagModel, TagTypeModel


@pytest.mark.parametrize(
    'loader_name, model',
    [
        ('TagTypeModel', TagTypeModel),
        ('TagModel', TagModel),
        ('TagEntityModel', TagEntityModel),
    ],
)
def test_loader_map_exposes_typed_tag_loaders(tag_ctx, loader_name, model):
    loader = getattr(tag_ctx.loaders, loader_name)
    assert loader.getModel() is model
    assert tag_ctx.loaders.get_by_name(loader_name) is loader


@pytest.mark.asyncio
async def test_tag_loader_inserts_and_loads_row(tag_ctx):
    tag_id = uuid.uuid4()
    await tag_ctx.loaders.TagModel.insert(TagModel(id=tag_id, name='important', label='Důležité'))

    loaded = await tag_ctx.loaders.TagModel.load(tag_id)

    assert loaded.label == 'Důležité'
