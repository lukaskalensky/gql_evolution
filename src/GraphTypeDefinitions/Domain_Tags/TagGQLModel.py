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

TagTypeGQLModel = typing.Annotated['TagTypeGQLModel', strawberry.lazy('.TagTypeGQLModel')]
TagEntityGQLModel = typing.Annotated['TagEntityGQLModel', strawberry.lazy('.TagEntityGQLModel')]
TagEntityInputFilter = typing.Annotated['TagEntityInputFilter', strawberry.lazy('.TagEntityGQLModel')]


@createInputs2
class TagInputFilter:
    id: IDType
    name: str
    label: str
    color: str
    description: str
    type_id: IDType


@strawberry.federation.type(keys=['id'], description='Tag definition which can be assigned to entities')
class TagGQLModel(BaseGQLModel):
    LoaderName = 'TagModel'

    name: typing.Optional[str] = strawberry.field(default=None, description='Internal tag name', permission_classes=[OnlyForAuthentized])
    label: typing.Optional[str] = strawberry.field(default=None, description='Displayed tag label', permission_classes=[OnlyForAuthentized])
    color: typing.Optional[str] = strawberry.field(default=None, description='Tag color', permission_classes=[OnlyForAuthentized])
    description: typing.Optional[str] = strawberry.field(default=None, description='Meaning of the tag', permission_classes=[OnlyForAuthentized])
    type_id: typing.Optional[IDType] = strawberry.field(default=None, description='Tag type id', permission_classes=[OnlyForAuthentized])

    type: typing.Optional[TagTypeGQLModel] = strawberry.field(description='Tag type', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[TagTypeGQLModel](fkey_field_name='type_id'))
    tag_entities: typing.List[TagEntityGQLModel] = strawberry.field(description='Assignments of this tag to entities', permission_classes=[OnlyForAuthentized], resolver=VectorResolver[TagEntityGQLModel](fkey_field_name='tag_id', whereType=TagEntityInputFilter))


@strawberry.interface(description='Tag queries')
class TagQuery:
    tag_by_id: typing.Optional[TagGQLModel] = strawberry.field(description='Get a tag by id', permission_classes=[OnlyForAuthentized], resolver=TagGQLModel.load_with_loader)
    tag_page: typing.List[TagGQLModel] = strawberry.field(description='Get a page of tags', permission_classes=[OnlyForAuthentized], resolver=PageResolver[TagGQLModel](whereType=TagInputFilter))


@strawberry.input(description='Input type for creating a Tag')
class TagInsertGQLModel(InputModelMixin):
    getLoader = TagGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(description='Client generated id', default=None)
    name: typing.Optional[str] = strawberry.field(description='Internal tag name', default=None)
    label: typing.Optional[str] = strawberry.field(description='Displayed tag label', default=None)
    color: typing.Optional[str] = strawberry.field(description='Tag color', default=None)
    description: typing.Optional[str] = strawberry.field(description='Meaning of the tag', default=None)
    type_id: typing.Optional[IDType] = strawberry.field(description='Tag type id', default=None)
    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for updating a Tag')
class TagUpdateGQLModel:
    id: IDType = strawberry.field(description='Tag id')
    lastchange: datetime.datetime = strawberry.field(description='Timestamp')
    name: typing.Optional[str] = strawberry.field(description='Internal tag name', default=strawberry.UNSET)
    label: typing.Optional[str] = strawberry.field(description='Displayed tag label', default=strawberry.UNSET)
    color: typing.Optional[str] = strawberry.field(description='Tag color', default=strawberry.UNSET)
    description: typing.Optional[str] = strawberry.field(description='Meaning of the tag', default=strawberry.UNSET)
    type_id: typing.Optional[IDType] = strawberry.field(description='Tag type id', default=strawberry.UNSET)
    changedby_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for deleting a Tag')
class TagDeleteGQLModel:
    id: IDType = strawberry.field(description='Tag id')
    lastchange: datetime.datetime = strawberry.field(description='Last change')


@strawberry.interface(description='Tag mutations')
class TagMutation:
    @strawberry.mutation(
        description='Insert a Tag',
        permission_classes=[OnlyForAuthentized],
        extensions=[UserAbsoluteAccessControlExtension[InsertError, TagGQLModel](roles=TAG_ADMIN_ROLES)],
    )
    async def tag_insert(self, info: ApplicationInfo, tag: TagInsertGQLModel, user_roles: typing.List[dict]) -> typing.Union[TagGQLModel, InsertError[TagGQLModel]]:
        service = info.ServiceCtx.Services.TagService
        return await service.ExecuteServiceMethod(
            service.Create(ctx=info.ServiceCtx, entity=tag),
            Error=service.CreateErrorCallback(ErrorClass=InsertError[TagGQLModel], code='d7abe3a6-d42c-4dc3-91b2-7095813c03a6', location='tag_insert', _input=tag),
            OK=TagGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Update a Tag',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAbsoluteAccessControlExtension[UpdateError, TagGQLModel](roles=TAG_ADMIN_ROLES),
            LoadDataExtension[UpdateError, TagGQLModel](),
        ],
    )
    async def tag_update(self, info: ApplicationInfo, tag: TagUpdateGQLModel, db_row: typing.Any, user_roles: typing.List[dict]) -> typing.Union[TagGQLModel, UpdateError[TagGQLModel]]:
        service = info.ServiceCtx.Services.TagService
        return await service.ExecuteServiceMethod(
            service.Update(ctx=info.ServiceCtx, entity=tag),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[TagGQLModel], code='debbb893-56df-4ae4-8077-227cfa4efdd8', location='tag_update', _input=tag, _entity=TagGQLModel.from_dataclass(db_row)),
            OK=TagGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Delete a Tag (only when it is not assigned to any entity)',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAbsoluteAccessControlExtension[DeleteError, TagGQLModel](roles=TAG_ADMIN_ROLES),
            LoadDataExtension[DeleteError, TagGQLModel](),
        ],
    )
    async def tag_delete(self, info: ApplicationInfo, tag: TagDeleteGQLModel, db_row: typing.Any, user_roles: typing.List[dict]) -> typing.Optional[DeleteError[TagGQLModel]]:
        service = info.ServiceCtx.Services.TagService
        return await service.ExecuteServiceMethod(
            service.Delete(ctx=info.ServiceCtx, entity=tag),
            Error=service.CreateErrorCallback(ErrorClass=DeleteError[TagGQLModel], code='c1ebd344-fa9f-4f3c-afd8-cf17d0bbfbee', location='tag_delete', _input=tag, _entity=TagGQLModel.from_dataclass(db_row)),
            OK=lambda result: None,
        )
