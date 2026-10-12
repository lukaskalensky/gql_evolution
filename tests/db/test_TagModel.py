import uuid
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.DBDefinitions import BaseDBModel, TagModel, TagEntityModel
from src.DBDefinitions.Domain_Tags import TagModel as DomainTagModel, TagEntityModel as DomainTagEntityModel
from src.DBDefinitions.Domain_Metadata import TagModel as MetaTagModel, TagEntityModel as MetaTagEntityModel
from src.DBDefinitions.main import (
    iter_mapped_classes,
    build_entity_index,
    op_create,
    op_get,
    op_list,
    op_update,
    op_delete,
)


def test_tag_model_attributes():
    """Verify TagModel table name, columns, and properties."""
    mapper = inspect(TagModel)
    assert mapper.local_table.name == "tags"

    column_names = {col.key for col in mapper.column_attrs}
    expected_columns = {
        "id",
        "created",
        "lastchange",
        "createdby_id",
        "changedby_id",
        "rbacobject_id",
        "name",
        "label",
        "color",
        "description",
    }
    assert expected_columns.issubset(column_names)

    relationships = {rel.key for rel in mapper.relationships}
    assert "tag_entities" in relationships


def test_tag_entity_model_attributes():
    """Verify TagEntityModel table name, columns, and properties."""
    mapper = inspect(TagEntityModel)
    assert mapper.local_table.name == "tag_entities"

    column_names = {col.key for col in mapper.column_attrs}
    expected_columns = {
        "id",
        "created",
        "lastchange",
        "createdby_id",
        "changedby_id",
        "rbacobject_id",
        "entity_id",
        "entity_type_id",
        "tag_id",
        "owner_id",
    }
    assert expected_columns.issubset(column_names)

    relationships = {rel.key for rel in mapper.relationships}
    assert "tag" in relationships


def test_imports_and_registry_consistency():
    """Verify export consistency across domain and root modules."""
    assert TagModel is DomainTagModel is MetaTagModel
    assert TagEntityModel is DomainTagEntityModel is MetaTagEntityModel

    mapped = list(iter_mapped_classes())
    assert TagModel in mapped
    assert TagEntityModel in mapped

    index = build_entity_index()
    assert index.get("TagModel") is TagModel
    assert index.get("Tag") is TagModel
    assert index.get("tags") is TagModel
    assert index.get("TagEntityModel") is TagEntityModel
    assert index.get("TagEntity") is TagEntityModel
    assert index.get("tag_entities") is TagEntityModel


@pytest_asyncio.fixture
async def sqlite_session():
    """In-memory SQLite async session for DB unit tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(BaseDBModel.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_tag_model_direct_crud(sqlite_session):
    """Test direct insert, select, update, and delete on TagModel."""
    tag_id = uuid.uuid4()
    tag = TagModel(
        id=tag_id,
        name="important",
        label="Důležité",
        color="#ff0000",
        description="Vysoká priorita",
    )
    sqlite_session.add(tag)
    await sqlite_session.commit()

    # Read
    loaded = await sqlite_session.get(TagModel, tag_id)
    assert loaded is not None
    assert loaded.name == "important"
    assert loaded.label == "Důležité"
    assert loaded.color == "#ff0000"
    assert loaded.description == "Vysoká priorita"

    # Update
    loaded.color = "#00ff00"
    loaded.label = "Velmi důležité"
    await sqlite_session.commit()

    updated = await sqlite_session.get(TagModel, tag_id)
    assert updated.color == "#00ff00"
    assert updated.label == "Velmi důležité"

    # Delete
    await sqlite_session.delete(updated)
    await sqlite_session.commit()

    deleted = await sqlite_session.get(TagModel, tag_id)
    assert deleted is None


@pytest.mark.asyncio
async def test_tag_entity_relationship(sqlite_session):
    """Test relationship between TagModel and TagEntityModel."""
    tag = TagModel(
        name="review",
        label="K projednání",
        color="#0000ff",
        description="Vyžaduje projednání",
    )
    sqlite_session.add(tag)
    await sqlite_session.flush()

    entity_id = uuid.uuid4()
    entity_type_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    tag_entity = TagEntityModel(
        entity_id=entity_id,
        entity_type_id=entity_type_id,
        tag_id=tag.id,
        owner_id=owner_id,
    )
    sqlite_session.add(tag_entity)
    await sqlite_session.commit()

    # Verify relation from TagEntity to Tag
    stmt = (
        select(TagEntityModel)
        .where(TagEntityModel.id == tag_entity.id)
        .options(selectinload(TagEntityModel.tag))
    )
    result = await sqlite_session.execute(stmt)
    loaded_te = result.scalar_one()
    assert loaded_te.tag is not None
    assert loaded_te.tag.id == tag.id
    assert loaded_te.tag.name == "review"

    # Verify relation from Tag to TagEntities
    stmt2 = (
        select(TagModel)
        .where(TagModel.id == tag.id)
        .options(selectinload(TagModel.tag_entities))
    )
    result2 = await sqlite_session.execute(stmt2)
    loaded_tag = result2.scalar_one()
    assert len(loaded_tag.tag_entities) == 1
    assert loaded_tag.tag_entities[0].entity_id == entity_id
    assert loaded_tag.tag_entities[0].owner_id == owner_id


@pytest.mark.asyncio
async def test_main_cli_operations_with_tags(sqlite_session):
    """Test DBDefinitions.main CRUD functions on TagModel and TagEntityModel."""
    # 1. op_create Tag
    tag_payload = {
        "name": "project_tag",
        "label": "Projektový štítek",
        "color": "#e0e0e0",
        "description": "Štítek pro projekty",
    }
    created_tag = await op_create(sqlite_session, TagModel, tag_payload)
    tag_id = created_tag["id"]
    assert created_tag["name"] == "project_tag"

    # 2. op_get Tag
    fetched_tag = await op_get(sqlite_session, TagModel, {"id": tag_id})
    assert fetched_tag["id"] == tag_id
    assert fetched_tag["label"] == "Projektový štítek"

    # 3. op_list Tag
    tag_list = await op_list(sqlite_session, TagModel, {"limit": 10})
    assert any(t["id"] == tag_id for t in tag_list)

    # 4. op_update Tag
    update_res = await op_update(
        sqlite_session,
        TagModel,
        {
            "id": tag_id,
            "lastchange": fetched_tag["lastchange"],
            "label": "Aktualizovaný štítek",
        },
    )
    assert update_res["label"] == "Aktualizovaný štítek"

    # 5. op_create TagEntity
    target_entity_id = uuid.uuid4()
    tag_entity_payload = {
        "entity_id": target_entity_id,
        "entity_type_id": uuid.uuid4(),
        "tag_id": tag_id,
        "owner_id": uuid.uuid4(),
    }
    created_te = await op_create(sqlite_session, TagEntityModel, tag_entity_payload)
    te_id = created_te["id"]
    assert created_te["tag_id"] == tag_id

    # 6. op_get with include
    fetched_tag_with_include = await op_get(
        sqlite_session,
        TagModel,
        {"id": tag_id, "include": ["tag_entities"]},
    )
    assert "tag_entities" in fetched_tag_with_include
    assert len(fetched_tag_with_include["tag_entities"]) == 1

    fetched_te_with_include = await op_get(
        sqlite_session,
        TagEntityModel,
        {"id": te_id, "include": ["tag"]},
    )
    assert "tag" in fetched_te_with_include
    assert fetched_te_with_include["tag"]["id"] == tag_id

    # 7. op_delete
    del_te = await op_delete(
        sqlite_session,
        TagEntityModel,
        {"id": te_id, "lastchange": created_te["lastchange"]},
    )
    assert del_te["ok"] is True

    del_tag = await op_delete(
        sqlite_session,
        TagModel,
        {"id": tag_id, "lastchange": update_res["lastchange"]},
    )
    assert del_tag["ok"] is True


@pytest.mark.asyncio
async def test_database_seed_with_10_tags_and_entities(sqlite_session):
    """Verify that systemdata.json seeds 10 tags and 10 tag entity assignments."""
    from src.DBDefinitions.seed import init_database_data

    await init_database_data(sqlite_session)

    # 1. Verify 10 Tags
    res_tags = await sqlite_session.execute(select(TagModel))
    tags = res_tags.scalars().all()
    assert len(tags) == 10
    tag_names = {t.name for t in tags}
    expected_tag_names = {
        "important",
        "review",
        "in_progress",
        "completed",
        "archive",
        "project_a",
        "project_b",
        "urgent",
        "idea",
        "bug",
    }
    assert tag_names == expected_tag_names

    # 2. Verify 10 TagEntities
    res_entities = await sqlite_session.execute(select(TagEntityModel))
    entities = res_entities.scalars().all()
    assert len(entities) == 10

    # 3. Verify Project A assignments
    project_a_id = uuid.UUID("11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    stmt = (
        select(TagEntityModel)
        .where(TagEntityModel.entity_id == project_a_id)
        .options(selectinload(TagEntityModel.tag))
    )
    res_project_a = await sqlite_session.execute(stmt)
    project_a_tags = {te.tag.label for te in res_project_a.scalars().all()}
    assert "Důležité" in project_a_tags
    assert "K projednání" in project_a_tags
    assert "V řešení" in project_a_tags

