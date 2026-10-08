import datetime
import typing

import strawberry
from uoishelpers.gqlpermissions import OnlyForAuthentized
from uoishelpers.gqlpermissions.LoadDataExtension import LoadDataExtension
from uoishelpers.gqlpermissions.RbacProviderExtension import RbacProviderExtension
from uoishelpers.gqlpermissions.UserAccessControlExtension import UserAccessControlExtension
from uoishelpers.gqlpermissions.UserRoleProviderExtension import UserRoleProviderExtension
from uoishelpers.resolvers import (
    DeleteError,
    InsertError,
    InputModelMixin,
    PageResolver,
    ScalarResolver,
    UpdateError,
    createInputs2,
)

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel, IDType

EventGQLModel = typing.Annotated['EventGQLModel', strawberry.lazy('.EventGQLModel')]
EventInputFilter = typing.Annotated['EventInputFilter', strawberry.lazy('.EventGQLModel')]
UserGQLModel = typing.Annotated['UserGQLModel', strawberry.lazy('src.GraphTypeDefinitions.Domain_UG.UserGQLModel')]
StateGQLModel = typing.Annotated['StateGQLModel', strawberry.lazy('src.GraphTypeDefinitions.Domain_UG.StateGQLModel')]


@createInputs2
class EventInvitationInputFilter:
    id: IDType
    event_id: IDType
    user_id: IDType
    state_id: IDType


@strawberry.federation.type(keys=['id'], description='Entity representing an invitation to an event and user presence state')
class EventInvitationGQLModel(BaseGQLModel):
    LoaderName = 'EventInvitationModel'

    event_id: typing.Optional[IDType] = strawberry.field(default=None, description='Event assigned to the invitation', permission_classes=[OnlyForAuthentized])
    user_id: typing.Optional[IDType] = strawberry.field(default=None, description='User assigned to the invitation', permission_classes=[OnlyForAuthentized])
    state_id: typing.Optional[IDType] = strawberry.field(default=None, description='State assigned to the invitation', permission_classes=[OnlyForAuthentized])

    event: typing.Optional[EventGQLModel] = strawberry.field(description='Event assigned to the invitation', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[EventGQLModel](fkey_field_name='event_id'))
    user: typing.Optional[UserGQLModel] = strawberry.field(description='User assigned to the invitation', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[UserGQLModel](fkey_field_name='user_id'))
    state: typing.Optional[StateGQLModel] = strawberry.field(description='State assigned to the invitation', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver[StateGQLModel](fkey_field_name='state_id'))


@strawberry.interface(description='EventInvitation queries')
class EventInvitationQuery:
    event_invitation_by_id: typing.Optional[EventInvitationGQLModel] = strawberry.field(description='Invitation by id', permission_classes=[OnlyForAuthentized], resolver=EventInvitationGQLModel.load_with_loader)
    event_invitation_page: typing.List[EventInvitationGQLModel] = strawberry.field(description='Selected invitations to events', permission_classes=[OnlyForAuthentized], resolver=PageResolver[EventInvitationGQLModel](whereType=EventInvitationInputFilter))


@strawberry.input(description='EventInvitation insert mutation')
class EventInvitationInsertGQLModel(InputModelMixin):
    getLoader = EventInvitationGQLModel.getLoader

    event_id: typing.Optional[IDType] = strawberry.field(description='event id to which invitation is sent', default=None)
    user_id: typing.Optional[IDType] = strawberry.field(description='user id who receives invitation', default=None)
    state_id: typing.Optional[IDType] = strawberry.field(description='invitation state', default=None)
    id: typing.Optional[IDType] = strawberry.field(description='client generated id', default=None)
    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description='EventInvitation update mutation')
class EventInvitationUpdateGQLModel:
    id: IDType = strawberry.field(description='id')
    lastchange: datetime.datetime = strawberry.field(description='timestamp')
    state_id: typing.Optional[IDType] = strawberry.field(description='invitation kind and presence type', default=None)
    changedby_id: strawberry.Private[IDType] = None


@strawberry.input(description='EventInvitation delete mutation')
class EventInvitationDeleteGQLModel:
    id: IDType = strawberry.field(description='EventInvitation id')
    lastchange: datetime.datetime = strawberry.field(description='EventInvitation lastchange')


@strawberry.interface(description='EventInvitation mutations')
class EventInvitationMutation:
    from .EventGQLModel import EventGQLModel

    @strawberry.mutation(
        description='Insert an EventInvitation',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[InsertError, EventInvitationGQLModel](roles=['plánovací administrátor']),
            UserRoleProviderExtension[InsertError, EventInvitationGQLModel](),
            RbacProviderExtension[InsertError, EventInvitationGQLModel](),
            LoadDataExtension[InsertError, EventInvitationGQLModel](getLoader=EventGQLModel.getLoader, primary_key_name='event_id'),
        ],
    )
    async def event_invitation_insert(self, info: ApplicationInfo, invitation: EventInvitationInsertGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Union[EventInvitationGQLModel, InsertError[EventInvitationGQLModel]]:
        invitation.rbacobject_id = rbacobject_id
        service = info.ServiceCtx.Services.EventInvitationService
        return await service.ExecuteServiceMethod(
            service.Create(ctx=info.ServiceCtx, entity=invitation),
            Error=service.CreateErrorCallback(ErrorClass=InsertError[EventInvitationGQLModel], code='c7a19df1-df70-4394-a7c4-6ec54c75efb8', location='event_invitation_insert', _input=invitation),
            OK=EventInvitationGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Allows invited user to accept or decline the invitation',
        permission_classes=[OnlyForAuthentized],
        extensions=[UserRoleProviderExtension[UpdateError, EventInvitationGQLModel](), RbacProviderExtension[UpdateError, EventInvitationGQLModel](), LoadDataExtension[UpdateError, EventInvitationGQLModel]()],
    )
    async def event_invitation_accept_decline(self, info: ApplicationInfo, invitation: EventInvitationUpdateGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Union[EventInvitationGQLModel, UpdateError[EventInvitationGQLModel]]:
        service = info.ServiceCtx.Services.EventInvitationService
        return await service.ExecuteServiceMethod(
            service.AcceptOrDeclineByInvitedUser(ctx=info.ServiceCtx, entity=invitation),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[EventInvitationGQLModel], code='48f0a626-f31a-4429-9e53-819ca865786d', location='event_invitation_accept_decline', _input=invitation, _entity=EventInvitationGQLModel.from_dataclass(db_row)),
            OK=EventInvitationGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Update the EventInvitation, caller must be organizer of the event',
        permission_classes=[OnlyForAuthentized],
        extensions=[UserRoleProviderExtension[UpdateError, EventInvitationGQLModel](), RbacProviderExtension[UpdateError, EventInvitationGQLModel](), LoadDataExtension[UpdateError, EventInvitationGQLModel]()],
    )
    async def event_invitation_update(self, info: ApplicationInfo, invitation: EventInvitationUpdateGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Union[EventInvitationGQLModel, UpdateError[EventInvitationGQLModel]]:
        service = info.ServiceCtx.Services.EventInvitationService
        return await service.ExecuteServiceMethod(
            service.UpdateByOrganizer(ctx=info.ServiceCtx, entity=invitation),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[EventInvitationGQLModel], code='ae30e32b-94ec-4d59-9c1e-7eca3b75701e', location='event_invitation_update', _input=invitation, _entity=EventInvitationGQLModel.from_dataclass(db_row)),
            OK=EventInvitationGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Delete an EventInvitation',
        permission_classes=[OnlyForAuthentized],
        extensions=[UserRoleProviderExtension[DeleteError, EventInvitationGQLModel](), RbacProviderExtension[DeleteError, EventInvitationGQLModel](), LoadDataExtension[DeleteError, EventInvitationGQLModel]()],
    )
    async def event_invitation_delete(self, info: ApplicationInfo, invitation: EventInvitationDeleteGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Optional[DeleteError[EventInvitationGQLModel]]:
        service = info.ServiceCtx.Services.EventInvitationService
        return await service.ExecuteServiceMethod(
            service.DeleteByOrganizer(ctx=info.ServiceCtx, entity=invitation),
            Error=service.CreateErrorCallback(ErrorClass=DeleteError[EventInvitationGQLModel], code='ae30e32b-94ec-4d59-9c1e-7eca3b75701e', location='event_invitation_delete', _input=invitation, _entity=EventInvitationGQLModel.from_dataclass(db_row)),
            OK=lambda result: None,
        )
