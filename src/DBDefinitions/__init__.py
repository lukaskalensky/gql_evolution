import sqlalchemy

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from .BaseModel import BaseDBModel, IDType, UUIDColumn, UUIDFKey
from .Domain_Events import EventModel, EventInvitationModel, EventTypeModel


async def startEngine(connectionstring, makeDrop=False, makeUp=True):
    """Provede nezbytne ukony a vrati asynchronni SessionMaker"""

    from sqlalchemy.ext.asyncio import (
        async_scoped_session,
        async_sessionmaker,
    )
    from asyncio import current_task

    asyncEngine = create_async_engine(connectionstring, pool_pre_ping=True)

 
    async with asyncEngine.begin() as conn:
        if makeDrop:
            await conn.run_sync(BaseDBModel.metadata.drop_all)
            print("BaseDBModel.metadata.drop_all finished")
        if makeUp:
            try:
                await conn.run_sync(BaseDBModel.metadata.create_all)
                print("BaseDBModel.metadata.create_all finished")
            except sqlalchemy.exc.NoReferencedTableError as e:
                print(e)
                print("Unable automaticaly create tables")
                return None

    # async_sessionMaker = sessionmaker(
    #     asyncEngine, expire_on_commit=False, class_=AsyncSession
    # )

    async_session_factory = async_sessionmaker(
        asyncEngine,
        expire_on_commit=False,
        class_=AsyncSession
    )

    async_sessionMaker = async_scoped_session(
        async_session_factory,
        scopefunc=current_task,
    )

    return async_sessionMaker

import os

def ComposeConnectionString():
    """Odvozuje connectionString z promennych prostredi (nebo z Docker Envs, coz je fakticky totez).
    Lze predelat na napr. konfiguracni file.
    """
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "example")
    database = os.environ.get("POSTGRES_DB", "data")
    hostWithPort = os.environ.get("POSTGRES_HOST", "localhost:5432")

    driver = "postgresql+asyncpg"  # "postgresql+psycopg2"
    connectionstring = f"{driver}://{user}:{password}@{hostWithPort}/{database}"
    connectionstring = os.environ.get("CONNECTION_STRING", connectionstring)

    return connectionstring



__all__ = [
    'BaseDBModel', 'IDType', 'UUIDColumn', 'UUIDFKey',
    'EventModel', 'EventInvitationModel', 'EventTypeModel',
    'startEngine', 'ComposeConnectionString', 'EventTypeModel'
]

