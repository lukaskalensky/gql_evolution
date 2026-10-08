from __future__ import annotations

import types
import uuid

import pytest

from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel


class FakeLoader:
    def __init__(self, row=None):
        self.row = row
        self.loaded_ids = []

    async def load(self, id):
        self.loaded_ids.append(id)
        return self.row


class FakeLoaders:
    def __init__(self, loader):
        self.entity_loader = loader


class FakeInfo:
    def __init__(self, loaders):
        self.loaders = loaders
        self.context = {"loaders": loaders}


class ConcreteGQLModel(BaseGQLModel):
    LoaderName = "entity_loader"


class NoLoaderNameGQLModel(BaseGQLModel):
    LoaderName = None


def test_get_loader_requires_loader_name():
    info = FakeInfo(FakeLoaders(FakeLoader()))

    with pytest.raises(NotImplementedError) as exc_info:
        NoLoaderNameGQLModel.getLoader(info)

    assert "NoLoaderNameGQLModel.LoaderName is not defined" in str(exc_info.value)


def test_get_loader_returns_named_loader_from_info_loaders():
    loader = FakeLoader()
    info = FakeInfo(FakeLoaders(loader))

    assert ConcreteGQLModel.getLoader(info) is loader


def test_from_db_and_from_dataclass_handle_none_and_wrap_db_row():
    assert ConcreteGQLModel.from_db(None) is None
    assert ConcreteGQLModel.from_dataclass(None) is None

    entity_id = uuid.uuid4()
    db_row = types.SimpleNamespace(id=entity_id, name="stored name")

    gql_model = ConcreteGQLModel.from_db(db_row)

    assert isinstance(gql_model, ConcreteGQLModel)
    assert gql_model.id == entity_id
    assert gql_model._dbdata is db_row


@pytest.mark.asyncio
async def test_load_with_loader_returns_none_for_none_id_without_calling_loader():
    loader = FakeLoader()
    info = FakeInfo(FakeLoaders(loader))

    result = await ConcreteGQLModel.load_with_loader(info, None)

    assert result is None
    assert loader.loaded_ids == []


@pytest.mark.asyncio
async def test_load_with_loader_converts_string_id_and_wraps_loaded_row():
    entity_id = uuid.uuid4()
    db_row = types.SimpleNamespace(id=entity_id, name="loaded")
    loader = FakeLoader(row=db_row)
    info = FakeInfo(FakeLoaders(loader))

    result = await ConcreteGQLModel.load_with_loader(info, str(entity_id))

    assert isinstance(result, ConcreteGQLModel)
    assert result.id == entity_id
    assert result._dbdata is db_row
    assert loader.loaded_ids == [entity_id]


@pytest.mark.asyncio
async def test_load_with_loader_returns_reference_shell_when_loader_misses():
    entity_id = uuid.uuid4()
    loader = FakeLoader(row=None)
    info = FakeInfo(FakeLoaders(loader))

    result = await ConcreteGQLModel.load_with_loader(info, entity_id)

    assert isinstance(result, ConcreteGQLModel)
    assert result.id == entity_id
    assert result._dbdata is None
    assert loader.loaded_ids == [entity_id]


@pytest.mark.asyncio
async def test_resolve_reference_returns_none_when_missing_id():
    info = FakeInfo(FakeLoaders(FakeLoader()))

    result = await ConcreteGQLModel.resolve_reference(info, None, name="ignored")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_reference_applies_other_data_to_loaded_or_shell_model():
    entity_id = uuid.uuid4()
    loader = FakeLoader(row=None)
    info = FakeInfo(FakeLoaders(loader))

    result = await ConcreteGQLModel.resolve_reference(
        info,
        entity_id,
        name="federated name",
        extra_value=42,
    )

    assert isinstance(result, ConcreteGQLModel)
    assert result.id == entity_id
    assert result.name == "federated name"
    assert result.extra_value == 42


# def test_get_db_value_prefers_explicit_value_then_dbdata_then_default():
#     model_id = uuid.uuid4()
#     db_row = types.SimpleNamespace(name="db name", missing_none=None)

#     model = ConcreteGQLModel(id=model_id, _dbdata=db_row)
#     model.name = "explicit name"

#     assert model.get_db_value("name", default="default") == "explicit name"
#     assert model.get_db_value("missing_none", default="default") == "default"
#     assert model.get_db_value("unknown", default="default") == "default"

#     delattr(model, "name")
#     assert model.get_db_value("name", default="default") == "db name"
