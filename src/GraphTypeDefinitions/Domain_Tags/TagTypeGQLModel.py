import datetime
import typing

import strawberry
from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.gqlpermissions.LoadDataExtension import LoadDataExtension
from uoishelpers.gqlpermissions.UserAbsoluteAccessControlExtension import UserAbsoluteAccessControlExtension
from uoishelpers.resolvers import (
    DeleteError,
    InsertError,
    InputModelMixin,
    PageResolver,
    ScalarResolver,
    UpdateError,
    VectorResolver,
    createInputs2,
)

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel, IDType

from .permissions import TAG_ADMIN_ROLES

TagGQLModel = typing.Annotated['TagGQLModel', strawberry.lazy('.TagGQLModel')]
TagInputFilter = typing.Annotated['TagInputFilter', strawberry.lazy('.TagGQLModel')]


@createInputs2
class TagTypeInputFilter:
    id: IDType
    name: str
    name_en: str
    parent_id: IDType


@strawberry.federation.type(keys=['id'], description='Tag type (category) as a tree node, e.g. Priorita -> Vysoká priorita')
class TagTypeGQLModel(BaseGQLModel):
    LoaderName = 'TagTypeModel'

    name: typing.Optional[str] = strawberry.field(default=None, description='Tag type name', permission_classes=[OnlyForAuthentized])
    name_en: typing.Optional[str] = strawberry.field(default=None, description='Tag type English name', permission_classes=[OnlyForAuthentized])
    path: typing.Optional[str] = strawberry.field(default=None, description='Materialized path in the tree of tag types', permission_classes=[OnlyForAuthentized])
    parent_id: typing.Optional[IDType] = strawberry.field(default=None, description='Parent tag type id (root has none)', permission_classes=[OnlyForAuthentized])

    parent: typing.Optional['TagTypeGQLModel'] = strawberry.field(description='Parent tag type', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver['TagTypeGQLModel'](fkey_field_name='parent_id'))
    children: typing.List['TagTypeGQLModel'] = strawberry.field(description='Child tag types', permission_classes=[OnlyForAuthentized], resolver=VectorResolver['TagTypeGQLModel'](fkey_field_name='parent_id', whereType=TagTypeInputFilter))
    tags: typing.List[TagGQLModel] = strawberry.field(description='Tags of this type', permission_classes=[OnlyForAuthentized], resolver=VectorResolver[TagGQLModel](fkey_field_name='type_id', whereType=TagInputFilter))


@strawberry.interface(description='TagType queries')
class TagTypeQuery:
    tag_type_by_id: typing.Optional[TagTypeGQLModel] = strawberry.field(description='Get a tag type by id', permission_classes=[OnlyForAuthentized], resolver=TagTypeGQLModel.load_with_loader)
    tag_type_page: typing.List[TagTypeGQLModel] = strawberry.field(description='Get a page of tag types', permission_classes=[OnlyForAuthentized], resolver=PageResolver[TagTypeGQLModel](whereType=TagTypeInputFilter))


@strawberry.input(description='Input type for creating a TagType')
class TagTypeInsertGQLModel(InputModelMixin):
    getLoader = TagTypeGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(description='Client generated id', default=None)
    name: typing.Optional[str] = strawberry.field(description='Tag type name', default=None)
    name_en: typing.Optional[str] = strawberry.field(description='Tag type English name', default=None)
    parent_id: typing.Optional[IDType] = strawberry.field(description='Parent tag type id', default=None)
    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for updating a TagType')
class TagTypeUpdateGQLModel:
    id: IDType = strawberry.field(description='Tag type id')
    lastchange: datetime.datetime = strawberry.field(description='Timestamp')
    name: typing.Optional[str] = strawberry.field(description='Tag type name', default=strawberry.UNSET)
    name_en: typing.Optional[str] = strawberry.field(description='Tag type English name', default=strawberry.UNSET)
    parent_id: typing.Optional[IDType] = strawberry.field(description='Parent tag type id (null makes it a root)', default=strawberry.UNSET)
    changedby_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for deleting a TagType')
class TagTypeDeleteGQLModel:
    id: IDType = strawberry.field(description='Tag type id')
    lastchange: datetime.datetime = strawberry.field(description='Last change')


@strawberry.interface(description='TagType mutations')
class TagTypeMutation:
    @strawberry.mutation(
        description='Insert a TagType',
        permission_classes=[OnlyForAuthentized],
        extensions=[UserAbsoluteAccessControlExtension[InsertError, TagTypeGQLModel](roles=TAG_ADMIN_ROLES)],
    )
    async def tag_type_insert(self, info: ApplicationInfo, tag_type: TagTypeInsertGQLModel, user_roles: typing.List[dict]) -> typing.Union[TagTypeGQLModel, InsertError[TagTypeGQLModel]]:
        service = info.ServiceCtx.Services.TagTypeService
        return await service.ExecuteServiceMethod(
            service.Create(ctx=info.ServiceCtx, entity=tag_type),
            Error=service.CreateErrorCallback(ErrorClass=InsertError[TagTypeGQLModel], code='25e8f4b5-e3f3-4412-932e-a4740fb66ade', location='tag_type_insert', _input=tag_type),
            OK=TagTypeGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Update a TagType',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAbsoluteAccessControlExtension[UpdateError, TagTypeGQLModel](roles=TAG_ADMIN_ROLES),
            LoadDataExtension[UpdateError, TagTypeGQLModel](),
        ],
    )
    async def tag_type_update(self, info: ApplicationInfo, tag_type: TagTypeUpdateGQLModel, db_row: typing.Any, user_roles: typing.List[dict]) -> typing.Union[TagTypeGQLModel, UpdateError[TagTypeGQLModel]]:
        service = info.ServiceCtx.Services.TagTypeService
        return await service.ExecuteServiceMethod(
            service.Update(ctx=info.ServiceCtx, entity=tag_type),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[TagTypeGQLModel], code='c6f6d999-519b-465f-9d3d-1264426af26c', location='tag_type_update', _input=tag_type, _entity=TagTypeGQLModel.from_dataclass(db_row)),
            OK=TagTypeGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Delete a TagType (only without child types and tags)',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAbsoluteAccessControlExtension[DeleteError, TagTypeGQLModel](roles=TAG_ADMIN_ROLES),
            LoadDataExtension[DeleteError, TagTypeGQLModel](),
        ],
    )
    async def tag_type_delete(self, info: ApplicationInfo, tag_type: TagTypeDeleteGQLModel, db_row: typing.Any, user_roles: typing.List[dict]) -> typing.Optional[DeleteError[TagTypeGQLModel]]:
        service = info.ServiceCtx.Services.TagTypeService
        return await service.ExecuteServiceMethod(
            service.Delete(ctx=info.ServiceCtx, entity=tag_type),
            Error=service.CreateErrorCallback(ErrorClass=DeleteError[TagTypeGQLModel], code='a94e1368-74f7-4a1e-94e2-136ccb7d9852', location='tag_type_delete', _input=tag_type, _entity=TagTypeGQLModel.from_dataclass(db_row)),
            OK=lambda result: None,
        )
