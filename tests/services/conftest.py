"""Sdílené fixtures pro testy služeb nad SQLite v paměti (bez Postgresu)."""

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.Dataloaders import LoaderMap
from src.DBDefinitions import BaseDBModel
from src.ServiceDefinitions.ServiceContext import ServiceContext

TAG_TEST_USER_ID = uuid.UUID('11111111-2222-3333-4444-555555555555')


@pytest_asyncio.fixture
async def tag_ctx():
    """ServiceContext se skutečným LoaderMap nad prázdnou databází a přihlášeným uživatelem."""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(BaseDBModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield ServiceContext(
            loaders=LoaderMap(session),
            user={'id': str(TAG_TEST_USER_ID)},
            session=session,
        )

    await engine.dispose()
