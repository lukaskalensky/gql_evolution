import uuid
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.DBDefinitions import BaseDBModel, TagModel, TagEntityModel
from src.DBDefinitions.Domain_Tags import TagEntityModel as DomainTagEntityModel
from src.DBDefinitions.Domain_Metadata import TagEntityModel as MetaTagEntityModel
from src.DBDefinitions.main import (
    iter_mapped_classes,
    build_entity_index,
    op_create,
    op_get,
    op_list,
    op_update,
    op_delete,
)


def test_tag_entity_model_structure():
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

    # Verify column properties and foreign keys
    tag_id_col = mapper.columns["tag_id"]
    fk_targets = {fk.target_fullname for fk in tag_id_col.foreign_keys}
    assert "tags.id" in fk_targets

    # owner_id uses UUIDFKey helper representing external user reference
    owner_id_col = mapper.columns["owner_id"]
    assert owner_id_col.comment == "foreign key"
    assert owner_id_col.index is True


def test_tag_entity_model_exports():
    """Verify TagEntityModel exports across modules."""
    assert TagEntityModel is DomainTagEntityModel is MetaTagEntityModel

    mapped = list(iter_mapped_classes())
    assert TagEntityModel in mapped

    index = build_entity_index()
    assert index.get("TagEntityModel") is TagEntityModel
    assert index.get("TagEntity") is TagEntityModel
    assert index.get("tag_entities") is TagEntityModel
    assert index.get("tagentity") is TagEntityModel


@pytest_asyncio.fixture
async def sqlite_session():
    """In-memory SQLite async session for TagEntity tests."""
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
async def test_assign_multiple_tags_to_entity(sqlite_session):
    """
    Test scenario from specification:
    Project A
        → 'Důležité'
        → 'K projednání'
    """
    # Create two tags
    tag_important = TagModel(
        name="important",
        label="Důležité",
        color="#ff0000",
        description="Vysoká priorita",
    )
    tag_review = TagModel(
        name="review",
        label="K projednání",
        color="#ffa500",
        description="Vyžaduje projednání na schůzce",
    )
    sqlite_session.add_all([tag_important, tag_review])
    await sqlite_session.flush()

    # Define Project A
    project_a_id = uuid.uuid4()
    project_type_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    # Assign both tags to Project A
    assignment1 = TagEntityModel(
        entity_id=project_a_id,
        entity_type_id=project_type_id,
        tag_id=tag_important.id,
        owner_id=owner_id,
    )
    assignment2 = TagEntityModel(
        entity_id=project_a_id,
        entity_type_id=project_type_id,
        tag_id=tag_review.id,
        owner_id=owner_id,
    )
    sqlite_session.add_all([assignment1, assignment2])
    await sqlite_session.commit()

    # Query all tag assignments for Project A
    stmt = (
        select(TagEntityModel)
        .where(TagEntityModel.entity_id == project_a_id)
        .options(selectinload(TagEntityModel.tag))
        .order_by(TagEntityModel.created)
    )
    result = await sqlite_session.execute(stmt)
    assignments = result.scalars().all()

    assert len(assignments) == 2
    assigned_tag_labels = {a.tag.label for a in assignments}
    assert assigned_tag_labels == {"Důležité", "K projednání"}

    # Query all entities that have tag 'Důležité'
    stmt_tag = (
        select(TagEntityModel)
        .where(TagEntityModel.tag_id == tag_important.id)
    )
    res_tag = await sqlite_session.execute(stmt_tag)
    tagged_entities = res_tag.scalars().all()
    assert len(tagged_entities) == 1
    assert tagged_entities[0].entity_id == project_a_id
    assert tagged_entities[0].owner_id == owner_id


@pytest.mark.asyncio
async def test_tag_entity_direct_crud(sqlite_session):
    """Test full CRUD lifecycle on TagEntityModel."""
    tag = TagModel(
        name="test_crud_tag",
        label="Testovací štítek",
        color="#123456",
        description="Pro CRUD testy",
    )
    sqlite_session.add(tag)
    await sqlite_session.flush()

    entity_id = uuid.uuid4()
    entity_type_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    te_id = uuid.uuid4()

    # 1. Create
    te = TagEntityModel(
        id=te_id,
        entity_id=entity_id,
        entity_type_id=entity_type_id,
        tag_id=tag.id,
        owner_id=owner_id,
    )
    sqlite_session.add(te)
    await sqlite_session.commit()

    # 2. Read
    loaded = await sqlite_session.get(TagEntityModel, te_id)
    assert loaded is not None
    assert loaded.entity_id == entity_id
    assert loaded.entity_type_id == entity_type_id
    assert loaded.tag_id == tag.id
    assert loaded.owner_id == owner_id

    # 3. Update (e.g. transfer ownership or update metadata)
    new_owner_id = uuid.uuid4()
    loaded.owner_id = new_owner_id
    await sqlite_session.commit()

    updated = await sqlite_session.get(TagEntityModel, te_id)
    assert updated.owner_id == new_owner_id

    # 4. Delete
    await sqlite_session.delete(updated)
    await sqlite_session.commit()

    deleted = await sqlite_session.get(TagEntityModel, te_id)
    assert deleted is None


@pytest.mark.asyncio
async def test_tag_entity_main_cli_operations(sqlite_session):
    """Test op_create, op_get, op_list, op_update, op_delete for TagEntityModel."""
    # Create tag first
    created_tag = await op_create(
        sqlite_session,
        TagModel,
        {
            "name": "cli_tag",
            "label": "CLI Štítek",
            "color": "#654321",
        },
    )
    tag_id = created_tag["id"]

    # 1. op_create TagEntity
    target_entity_id = uuid.uuid4()
    target_entity_type_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    created_te = await op_create(
        sqlite_session,
        TagEntityModel,
        {
            "entity_id": target_entity_id,
            "entity_type_id": target_entity_type_id,
            "tag_id": tag_id,
            "owner_id": owner_id,
        },
    )
    te_id = created_te["id"]
    assert created_te["entity_id"] == target_entity_id
    assert created_te["tag_id"] == tag_id

    # 2. op_get TagEntity with include
    fetched_te = await op_get(
        sqlite_session,
        TagEntityModel,
        {"id": te_id, "include": ["tag"]},
    )
    assert fetched_te["id"] == te_id
    assert fetched_te["tag"]["name"] == "cli_tag"

    # 3. op_list TagEntity
    te_list = await op_list(
        sqlite_session,
        TagEntityModel,
        {"limit": 10},
    )
    assert any(item["id"] == te_id for item in te_list)

    # 4. op_update TagEntity
    new_owner = uuid.uuid4()
    updated_te = await op_update(
        sqlite_session,
        TagEntityModel,
        {
            "id": te_id,
            "lastchange": created_te["lastchange"],
            "owner_id": new_owner,
        },
    )
    assert updated_te["owner_id"] == new_owner

    # 5. op_delete TagEntity
    del_res = await op_delete(
        sqlite_session,
        TagEntityModel,
        {
            "id": te_id,
            "lastchange": updated_te["lastchange"],
        },
    )
    assert del_res["ok"] is True
