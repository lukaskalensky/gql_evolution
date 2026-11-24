import datetime
import typing

import strawberry
from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.gqlpermissions.LoadDataExtension import LoadDataExtension
from uoishelpers.resolvers import (
    DeleteError,
    InsertError,
    InputModelMixin,
    PageResolver,
    ScalarResolver,
    createInputs2,
)

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel, IDType

TagGQLModel = typing.Annotated['TagGQLModel', strawberry.lazy('.TagGQLModel')]
UserGQLModel = typing.Annotated['UserGQLModel', strawberry.lazy('src.GraphTypeDefinitions.Domain_UG.UserGQLModel')]


@createInputs2
class TagEntityInputFilter:
    id: IDType
    entity_id: IDType
    entity_type_id: IDType
    tag_id: IDType
    owner_id: IDType


@strawberry.federation.type(keys=['id'], description='Assignment of a tag to an entity of the information system, owned by the user who assigned it')
class TagEntityGQLModel(BaseGQLModel):
    LoaderName = 'TagEntityModel'

    entity_id: typing.Optional[IDType] = strawberry.field(default=None, description='Tagged entity id', permission_classes=[OnlyForAuthentized])
    entity_type_id: typing.Optional[IDType] = strawberry.field(default=None, description='Tagged entity type id', permission_classes=[OnlyForAuthentized])
    tag_id: typing.Optional[IDType] = strawberry.field(default=None, description='Assigned tag id', permission_classes=[OnlyForAuthentized])
    owner_id: typing.Optional[IDType] = strawberry.field(default=None, description='Owner of the assignment', permission_classes=[OnlyForAuthentized])

    tag: typing.Optional[TagGQLModel] = strawberry.field(description='Assigned tag', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[TagGQLModel](fkey_field_name='tag_id'))
    owner: typing.Optional[UserGQLModel] = strawberry.field(description='Owner of the assignment', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[UserGQLModel](fkey_field_name='owner_id'))


@strawberry.interface(description='TagEntity queries')
class TagEntityQuery:
    tag_entity_by_id: typing.Optional[TagEntityGQLModel] = strawberry.field(description='Get a tag assignment by id', permission_classes=[OnlyForAuthentized], resolver=TagEntityGQLModel.load_with_loader)
    tag_entity_page: typing.List[TagEntityGQLModel] = strawberry.field(description='Get a page of tag assignments (filter by entityId to get tags of an entity)', permission_classes=[OnlyForAuthentized], resolver=PageResolver[TagEntityGQLModel](whereType=TagEntityInputFilter))


@strawberry.input(description='Input type for assigning a tag to an entity; owner is the current user')
class TagEntityInsertGQLModel(InputModelMixin):
    getLoader = TagEntityGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(description='Client generated id', default=None)
    entity_id: IDType = strawberry.field(description='Tagged entity id')
    entity_type_id: IDType = strawberry.field(description='Tagged entity type id')
    tag_id: IDType = strawberry.field(description='Assigned tag id')
    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for removing a tag assignment')
class TagEntityDeleteGQLModel:
    id: IDType = strawberry.field(description='Tag assignment id')
    lastchange: datetime.datetime = strawberry.field(description='Last change')


@strawberry.interface(description='TagEntity mutations')
class TagEntityMutation:
    @strawberry.mutation(
        description='Assign a tag to an entity on behalf of the current user (idempotent for the same user)',
        permission_classes=[OnlyForAuthentized],
    )
    async def tag_entity_assign(self, info: ApplicationInfo, tag_entity: TagEntityInsertGQLModel) -> typing.Union[TagEntityGQLModel, InsertError[TagEntityGQLModel]]:
        service = info.ServiceCtx.Services.TagEntityService
        return await service.ExecuteServiceMethod(
            service.AssignTag(ctx=info.ServiceCtx, entity=tag_entity),
            Error=service.CreateErrorCallback(ErrorClass=InsertError[TagEntityGQLModel], code='97ff685e-7a05-4cc4-8095-b519e932dc33', location='tag_entity_assign', _input=tag_entity),
            OK=TagEntityGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Remove a tag assignment; allowed only for its owner',
        permission_classes=[OnlyForAuthentized],
        extensions=[LoadDataExtension[DeleteError, TagEntityGQLModel]()],
    )
    async def tag_entity_unassign(self, info: ApplicationInfo, tag_entity: TagEntityDeleteGQLModel, db_row: typing.Any) -> typing.Optional[DeleteError[TagEntityGQLModel]]:
        service = info.ServiceCtx.Services.TagEntityService
        return await service.ExecuteServiceMethod(
            service.UnassignTag(ctx=info.ServiceCtx, entity=tag_entity),
            Error=service.CreateErrorCallback(ErrorClass=DeleteError[TagEntityGQLModel], code='ee72e16e-0300-4f92-afb3-616acffa5b47', location='tag_entity_unassign', _input=tag_entity, _entity=TagEntityGQLModel.from_dataclass(db_row)),
            OK=lambda result: None,
        )
