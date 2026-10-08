from __future__ import annotations

import dataclasses
import typing

from strawberry.fastapi.context import BaseContext

from src.Dataloaders import LoaderMap
from src.DBDefinitions.runtime import Database
from src.ServiceDefinitions.ServiceContext import ServiceContext


@dataclasses.dataclass
class GraphQLContext(BaseContext):
    """Strawberry/FastAPI context for one GraphQL operation.

    The object must inherit from Strawberry BaseContext, but uoishelpers also
    treats the context as a mutable dict. Therefore this class intentionally
    supports both attribute-style and dict-style access.

    Session, LoaderMap and ServiceContext are normally injected by
    SessionCommitExtension during the GraphQL operation lifecycle.
    """

    ServiceCtx: ServiceContext | None = None

    request: typing.Any = None
    response: typing.Any = None
    background_tasks: typing.Any = None

    # Optional hooks used by SessionCommitExtension. They are provided here so
    # the extension can have a no-argument constructor and still stay decoupled.
    session_maker_factory: typing.Callable[[], typing.Any] | None = None
    loaders_factory: typing.Callable[[typing.Any], typing.Any] | None = None

    _extra: dict[str, typing.Any] = dataclasses.field(default_factory=dict)

    @property
    def loaders(self) -> LoaderMap:
        if self.ServiceCtx is not None:
            return self.ServiceCtx.loaders
        return self._extra['loaders']

    @loaders.setter
    def loaders(self, value: LoaderMap) -> None:
        self._extra['loaders'] = value
        if self.ServiceCtx is not None:
            self.ServiceCtx.loaders = value

    @property
    def user(self) -> typing.Any:
        if 'user' in self._extra:
            return self._extra['user']
        if self.ServiceCtx is not None:
            return self.ServiceCtx.user
        return None

    @user.setter
    def user(self, value: typing.Any) -> None:
        self._extra['user'] = value
        if self.ServiceCtx is not None:
            self.ServiceCtx.user = value

    @property
    def session(self) -> typing.Any:
        if 'session' in self._extra:
            return self._extra['session']
        if self.ServiceCtx is not None:
            return getattr(self.ServiceCtx, 'session', None)
        return None

    @session.setter
    def session(self, value: typing.Any) -> None:
        self._extra['session'] = value
        if self.ServiceCtx is not None:
            self.ServiceCtx.session = value

    @property
    def ug_client(self):
        if 'ug_client' in self._extra:
            return self._extra['ug_client']
        if self.ServiceCtx is not None:
            return self.ServiceCtx.ug_client
        return None

    @ug_client.setter
    def ug_client(self, value) -> None:
        self._extra['ug_client'] = value
        if self.ServiceCtx is not None:
            self.ServiceCtx.ug_client = value

    def resolve_session_maker(self):
        factory = self.session_maker_factory or self._extra.get('session_maker_factory')
        if factory is not None:
            return factory()
        return Database().session_maker

    def resolve_loaders(self, session):
        factory = self.loaders_factory or self._extra.get('loaders_factory')
        if factory is not None:
            return factory(session)
        return LoaderMap(session)

    def __getitem__(self, key: str) -> typing.Any:
        if key in {'ServiceCtx', 'service_ctx'}:
            if self.ServiceCtx is None:
                raise KeyError(key)
            return self.ServiceCtx

        if key == 'loaders':
            return self.loaders

        if key == 'user':
            return self.user

        if key == 'session':
            return self.session

        if key == 'ug_client':
            return self.ug_client

        if key in self._extra:
            return self._extra[key]

        return getattr(self, key)

    def __setitem__(self, key: str, value: typing.Any) -> None:
        if key in {'ServiceCtx', 'service_ctx'}:
            self.ServiceCtx = value
            return

        if key == 'loaders':
            self.loaders = value
            return

        if key == 'user':
            self.user = value
            return

        if key == 'session':
            self.session = value
            return

        if key == 'ug_client':
            self.ug_client = value
            return

        if hasattr(self, key):
            setattr(self, key, value)
            return

        self._extra[key] = value

    def __contains__(self, key: str) -> bool:
        if key in {'ServiceCtx', 'service_ctx'}:
            return self.ServiceCtx is not None
        if key in {'loaders', 'user', 'session', 'ug_client'}:
            return True
        return key in self._extra or hasattr(self, key)

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        try:
            return self[key]
        except (AttributeError, KeyError):
            return default

    def setdefault(self, key: str, default: typing.Any = None) -> typing.Any:
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, values: dict[str, typing.Any] | None = None, **kwargs: typing.Any) -> None:
        if values:
            for key, value in values.items():
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def keys(self):
        keys = {
            'request',
            'response',
            'background_tasks',
            'loaders',
            'user',
            'session',
            'ug_client',
            'session_maker_factory',
            'loaders_factory',
        }
        if self.ServiceCtx is not None:
            keys |= {'ServiceCtx', 'service_ctx'}
        return keys | set(self._extra.keys())

    def items(self):
        return [(key, self[key]) for key in self.keys()]

    def values(self):
        return [self[key] for key in self.keys()]
