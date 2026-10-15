import uuid
import pytest
import pytest_asyncio
from sqlalchemy import inspect, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from src.DBDefinitions import BaseDBModel, TagTypeModel, TagModel, TagEntityModel
from src.DBDefinitions.Domain_Tags import TagTypeModel as DomainTagTypeModel
from src.DBDefinitions.Domain_Metadata import TagTypeModel as MetaTagTypeModel
from src.DBDefinitions.main import iter_mapped_classes, build_entity_index


def test_tag_type_model_structure():
    """Verify TagTypeModel table name, columns, tree relationships and FK from TagModel."""
    mapper = inspect(TagTypeModel)
    assert mapper.local_table.name == "tagtypes"

    column_names = {col.key for col in mapper.column_attrs}
    assert {"id", "lastchange", "path", "name", "name_en", "parent_id"}.issubset(column_names)

    relationships = {rel.key for rel in mapper.relationships}
    assert {"parent", "children", "tags"}.issubset(relationships)

    parent_fk = {fk.target_fullname for fk in mapper.columns["parent_id"].foreign_keys}
    assert parent_fk == {"tagtypes.id"}

    tag_mapper = inspect(TagModel)
    type_fk = {fk.target_fullname for fk in tag_mapper.columns["type_id"].foreign_keys}
    assert type_fk == {"tagtypes.id"}
    assert "type" in {rel.key for rel in tag_mapper.relationships}


def test_tag_type_model_exports():
    """Verify TagTypeModel exports and registry discovery."""
    assert TagTypeModel is DomainTagTypeModel is MetaTagTypeModel
    assert TagTypeModel in list(iter_mapped_classes())
    assert build_entity_index().get("tagtypes") is TagTypeModel


@pytest_asyncio.fixture
async def sqlite_session():
    """In-memory SQLite async session for TagType tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(BaseDBModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_tag_type_tree_and_tags(sqlite_session):
    """Build tree Tagy -> Priorita and attach a tag to the leaf type."""
    root = TagTypeModel(name="Tagy", name_en="Tags")
    sqlite_session.add(root)
    await sqlite_session.flush()

    priority = TagTypeModel(name="Priorita", name_en="Priority", parent_id=root.id)
    sqlite_session.add(priority)
    await sqlite_session.flush()

    tag = TagModel(name="important", label="Důležité", type_id=priority.id)
    sqlite_session.add(tag)
    await sqlite_session.commit()

    stmt = (
        select(TagTypeModel)
        .where(TagTypeModel.id == root.id)
        .options(selectinload(TagTypeModel.children).selectinload(TagTypeModel.tags))
    )
    loaded_root = (await sqlite_session.execute(stmt)).scalar_one()
    assert loaded_root.parent_id is None
    assert [c.name for c in loaded_root.children] == ["Priorita"]
    assert [t.name for t in loaded_root.children[0].tags] == ["important"]

    stmt = (
        select(TagModel)
        .where(TagModel.id == tag.id)
        .options(selectinload(TagModel.type).selectinload(TagTypeModel.parent))
    )
    loaded_tag = (await sqlite_session.execute(stmt)).scalar_one()
    assert loaded_tag.type.name == "Priorita"
    assert loaded_tag.type.parent.name == "Tagy"


@pytest.mark.asyncio
async def test_seed_without_demodata_imports_only_type_catalog(sqlite_session, monkeypatch):
    """Without DEMODATA only *TypeModel catalogs (tagtypes) are seeded, not tags."""
    from src.DBDefinitions.seed import init_database_data

    monkeypatch.delenv("DEMODATA", raising=False)
    await init_database_data(sqlite_session)

    tag_types = (await sqlite_session.execute(select(TagTypeModel))).scalars().all()
    assert len(tag_types) == 5
    roots = [t for t in tag_types if t.parent_id is None]
    assert [r.name for r in roots] == ["Tagy"]

    assert (await sqlite_session.execute(select(TagModel))).scalars().all() == []
    assert (await sqlite_session.execute(select(TagEntityModel))).scalars().all() == []


@pytest.mark.asyncio
async def test_seed_with_demodata_links_tags_to_types(sqlite_session, monkeypatch):
    """With DEMODATA every seeded tag points to an existing tag type."""
    from src.DBDefinitions.seed import init_database_data

    monkeypatch.setenv("DEMODATA", "True")
    await init_database_data(sqlite_session)

    type_ids = {t.id for t in (await sqlite_session.execute(select(TagTypeModel))).scalars().all()}
    tags = (await sqlite_session.execute(select(TagModel))).scalars().all()
    assert len(tags) == 10
    assert all(t.type_id in type_ids for t in tags)

    important = next(t for t in tags if t.name == "important")
    assert important.type_id == uuid.UUID("a0000000-0000-0000-0000-000000000002")
