import datetime
import typing
import uuid

IDType = uuid.UUID

class EntityProtocol(typing.Protocol):
    id: IDType
    lastchange: datetime.datetime | None
    created: datetime.datetime | None
    createdby_id: IDType | None
    changedby_id: IDType | None
    rbacobject_id: IDType | None

class LoaderProtocol(typing.Protocol):
    def getModel(self) -> type: ...
    async def load(self, id: IDType) -> typing.Any: ...
    async def insert(self, *, entity: typing.Any, extraAttributes: dict | None = None) -> typing.Any: ...
    async def update(self, *, entity: typing.Any, extraValues: dict | None = None) -> typing.Any: ...
    async def delete(self, id: IDType) -> typing.Any: ...
    async def page(self, *, skip: int = 0, limit: int = 10, where: typing.Any = None, orderby: str | None = None, desc: bool | None = None, extendedfilter: dict | None = None) -> list[typing.Any]: ...
    async def filter_by(self, **kwargs) -> list[typing.Any]: ...

class LoaderMapProtocol(typing.Protocol):
    EventModel: LoaderProtocol
    EventInvitationModel: LoaderProtocol

class ServiceContextProtocol(typing.Protocol):
    loaders: LoaderMapProtocol
    user: typing.Any
    Services: typing.Any
