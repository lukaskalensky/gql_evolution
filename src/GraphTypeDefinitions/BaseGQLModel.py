import datetime
import typing
import uuid

import strawberry
from strawberry.federation.schema_directive import Location, schema_directive
from strawberry.directive import DirectiveLocation
from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.resolvers import getLoadersFromInfo

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.common.protocols import EntityProtocol

IDType = uuid.UUID


@schema_directive(
    repeatable=True,
    compose=True,
    description='Description for foreign keys',
    locations=[Location.INPUT_FIELD_DEFINITION, Location.FIELD_DEFINITION, DirectiveLocation.FIELD],
)
class Relation:
    to: str
    field: str = 'id'


@strawberry.federation.interface(description='Entity representing an interface')
class BaseGQLModel:
    LoaderName: typing.ClassVar[str | None] = None
    _dbdata: strawberry.Private[EntityProtocol | None] = None

    id: IDType = strawberry.field(description='primary key', permission_classes=[OnlyForAuthentized])
    lastchange: typing.Optional[datetime.datetime] = strawberry.field(default=None, description='timestamp', permission_classes=[OnlyForAuthentized])
    created: typing.Optional[datetime.datetime] = strawberry.field(default=None, description='date & time of entity creation', permission_classes=[OnlyForAuthentized])
    createdby_id: typing.Optional[IDType] = strawberry.field(default=None, description='who created this entity', permission_classes=[OnlyForAuthentized])
    changedby_id: typing.Optional[IDType] = strawberry.field(default=None, description='who changed this entity', permission_classes=[OnlyForAuthentized])
    rbacobject_id: typing.Optional[IDType] = strawberry.field(default=None, description='rbac ruling object', permission_classes=[OnlyForAuthentized])

    @classmethod
    def getLoader(cls, info: ApplicationInfo) -> typing.Any:
        if cls.LoaderName is None:
            raise NotImplementedError(f'{cls.__name__}.LoaderName is not defined')
        loaders = getLoadersFromInfo(info)
        loaders = info.loaders
        return getattr(loaders, cls.LoaderName)

    @classmethod
    def from_dataclass(cls, db_row):
        return cls.from_db(db_row)

    @classmethod
    def from_db(cls, db_row):
        if db_row is None:
            return None
        return cls(id=db_row.id, _dbdata=db_row)

    @classmethod
    async def load_with_loader(cls, info: ApplicationInfo, id: IDType):
        _id = IDType(id) if isinstance(id, str) else id
        if _id is None:
            return None
        db_row = await cls.getLoader(info).load(_id)
        return cls.from_db(db_row) if db_row is not None else cls(id=_id)

    @classmethod
    async def resolve_reference(cls, info: ApplicationInfo, id: IDType, **otherData):
        loaded = await cls.load_with_loader(info=info, id=id)
        if loaded is None:
            return None
        for key, value in otherData.items():
            setattr(loaded, key, value)
        return loaded

    def get_db_value(self, field_name: str, default=None):
        explicit_value = getattr(self, field_name, None)
        if explicit_value is not None:
            return explicit_value
        if self._dbdata is not None and hasattr(self._dbdata, field_name):
            return getattr(self._dbdata, field_name)
        return default
