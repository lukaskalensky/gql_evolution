from __future__ import annotations

import contextlib
import dataclasses
import typing

from sqlalchemy.ext.asyncio import AsyncSession

from src.DBDefinitions import ComposeConnectionString, startEngine


@dataclasses.dataclass(frozen=True)
class DatabaseSettings:
    connection_string: str | None = None
    make_drop: bool = False
    make_up: bool = True
    seed_data: bool = True


class DatabaseRuntime:
    """Process-wide database runtime.

    The runtime owns the SQLAlchemy async session maker created during
    application startup. Individual GraphQL requests still get their own
    AsyncSession and LoaderMap; only the engine/session-maker is singleton-like.
    """

    _instance: typing.ClassVar[DatabaseRuntime | None] = None

    def __new__(cls) -> DatabaseRuntime:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._session_maker = None
            cls._instance._settings = None
        return cls._instance

    @property
    def is_started(self) -> bool:
        return self._session_maker is not None

    @property
    def session_maker(self):
        if self._session_maker is None:
            raise RuntimeError('DatabaseRuntime is not started. Call await DatabaseRuntime().start() first.')
        return self._session_maker

    async def start(self, settings: DatabaseSettings | None = None):
        if self._session_maker is not None:
            return self._session_maker

        settings = settings or DatabaseSettings()
        connection_string = settings.connection_string or ComposeConnectionString()
        session_maker = await startEngine(
            connection_string,
            makeDrop=settings.make_drop,
            makeUp=settings.make_up,
        )
        if session_maker is None:
            raise RuntimeError('Unable to create async session maker')

        self._session_maker = session_maker
        self._settings = settings

        if settings.seed_data:
            async with self.session() as session:
                from src.DBDefinitions.seed import init_database_data
                await init_database_data(session)

        return self._session_maker

    @contextlib.asynccontextmanager
    async def session(self) -> typing.AsyncIterator[AsyncSession]:
        maker = self.session_maker
        session: AsyncSession = maker()
        try:
            yield session
        finally:
            await session.close()
            remove = getattr(maker, 'remove', None)
            if remove is not None:
                result = remove()
                if hasattr(result, '__await__'):
                    await result

    async def stop(self) -> None:
        # async_scoped_session has remove(); the underlying engine is owned by
        # SQLAlchemy session factory. startEngine currently does not expose it.
        maker = self._session_maker
        if maker is not None:
            remove = getattr(maker, 'remove', None)
            if remove is not None:
                result = remove()
                if hasattr(result, '__await__'):
                    await result
        self._session_maker = None
        self._settings = None


Database = DatabaseRuntime
