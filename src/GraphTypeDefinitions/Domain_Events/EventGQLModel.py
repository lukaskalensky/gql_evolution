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
    UpdateError,
    ScalarResolver,
    VectorResolver,
    createInputs2,
)

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.BaseGQLModel import BaseGQLModel, IDType

from .TimeUnit import TimeUnit

EventInvitationGQLModel = typing.Annotated['EventInvitationGQLModel', strawberry.lazy('.EventInvitationGQLModel')]
EventInvitationInputFilter = typing.Annotated['EventInvitationInputFilter', strawberry.lazy('.EventInvitationGQLModel')]
# EventTypeGQLModel = typing.Annotated['EventTypeGQLModel', strawberry.lazy('.EventTypeGQLModel')]

@createInputs2
class EventInputFilter:
    name: str
    name_en: str
    description: str
    startdate: datetime.datetime
    enddate: datetime.datetime
    place: str
    valid: bool
    masterevent_id: IDType
    id: IDType


@strawberry.federation.type(description='Entity representing an Event', keys=['id'])
class EventGQLModel(BaseGQLModel):
    LoaderName = 'EventModel'

    name: typing.Optional[str] = strawberry.field(default=None, description='Event name', permission_classes=[OnlyForAuthentized])
    name_en: typing.Optional[str] = strawberry.field(default=None, description='Event English name', permission_classes=[OnlyForAuthentized])
    description: typing.Optional[str] = strawberry.field(default=None, description='Event description', permission_classes=[OnlyForAuthentized])
    startdate: typing.Optional[datetime.datetime] = strawberry.field(default=None, description='Event start date', permission_classes=[OnlyForAuthentized])
    enddate: typing.Optional[datetime.datetime] = strawberry.field(default=None, description='Event end date', permission_classes=[OnlyForAuthentized])
    place: typing.Optional[str] = strawberry.field(default=None, description='where the event will happen', permission_classes=[OnlyForAuthentized])
    valid: typing.Optional[bool] = strawberry.field(default=None, description='If the event is valid', permission_classes=[OnlyForAuthentized])
    masterevent_id: typing.Optional[IDType] = strawberry.field(default=None, description='Parent event id', permission_classes=[OnlyForAuthentized])

    # event_type: typing.Optional['EventTypeGQLModel'] = strawberry.field(description='Event type', permission_classes=[OnlyForAuthentized], resolver=ScalarResolver['EventTypeGQLModel'](fkey_field_name='type_id'))
    event_type_id: typing.Optional[IDType] = strawberry.field(default=None, description='Event type id', permission_classes=[OnlyForAuthentized])

    subevents: typing.List['EventGQLModel'] = strawberry.field(description='Event children', permission_classes=[OnlyForAuthentized], resolver=VectorResolver['EventGQLModel'](fkey_field_name='masterevent_id', whereType=EventInputFilter))
    user_invitations: typing.List[EventInvitationGQLModel] = strawberry.field(description='Event invitations', permission_classes=[OnlyForAuthentized], resolver=VectorResolver[EventInvitationGQLModel](fkey_field_name='event_id', whereType=EventInvitationInputFilter))

    @strawberry.field(
        name="duration",
        description="""Event duration, implicitly in minutes""",
        permission_classes=[
            OnlyForAuthentized,
            # OnlyForAdmins
        ],
    )
    def _duration(self, unit: TimeUnit=TimeUnit.MINUTES) -> typing.Optional[float]:
        duration = self._dbdata.duration
        if duration is None:
            if self.startdate is None or self.enddate is None:
                return None
            duration = (self.enddate - self.startdate)
        result = duration.total_seconds()
        if unit == TimeUnit.SECONDS:
            return result
        if unit == TimeUnit.MINUTES:
            return result / 60
        if unit == TimeUnit.HOURS:
            return result / 60 / 60
        if unit == TimeUnit.DAYS:
            return result / 60 / 60 / 24
        if unit == TimeUnit.WEEKS:
            return result / 60 / 60 / 24 / 7
        return result / 60


@strawberry.interface(description='Event queries')
class EventQuery:
    event_by_id: typing.Optional[EventGQLModel] = strawberry.field(description='get an event by id', permission_classes=[OnlyForAuthentized], resolver=EventGQLModel.load_with_loader)
    event_page: typing.List[EventGQLModel] = strawberry.field(description='get a page of events', permission_classes=[OnlyForAuthentized], resolver=PageResolver[EventGQLModel](whereType=EventInputFilter))


@strawberry.input(description='Input type for creating an Event')
class EventInsertGQLModel(InputModelMixin):
    getLoader = EventGQLModel.getLoader

    name: typing.Optional[str] = strawberry.field(description='Event name', default=None)
    name_en: typing.Optional[str] = strawberry.field(description='Event English name', default=None)
    description: typing.Optional[str] = strawberry.field(description='Event description', default=None)
    startdate: typing.Optional[datetime.datetime] = strawberry.field(description='Event start date', default=None)
    enddate: typing.Optional[datetime.datetime] = strawberry.field(description='Event end date', default=None)
    place: typing.Optional[str] = strawberry.field(description='where the event will happen', default=None)
    masterevent_id: typing.Optional[IDType] = strawberry.field(description='Parent event id', default=None)
    id: typing.Optional[IDType] = strawberry.field(description='Event id', default=None)
    createdby_id: strawberry.Private[IDType] = None
    rbacobject_id: strawberry.Private[IDType] = None


@strawberry.input(description='Invitation model for batch event invitations')
class EventInvitationInsertModel(InputModelMixin):
    from .EventInvitationGQLModel import EventInvitationGQLModel
    getLoader = EventInvitationGQLModel.getLoader

    id: typing.Optional[IDType] = strawberry.field(description='Invitation id', default=None)
    user_id: IDType = strawberry.field(description='invited user')
    state_id: IDType = strawberry.field(description='invitation state')
    event_id: typing.Optional[IDType] = strawberry.field(description='event inviting to', default=None)
    createdby_id: strawberry.Private[IDType] = None


@strawberry.input(description='Model for batch invitations to the event')
class EventEnsureUserInvitationsModel:
    getLoader = EventGQLModel.getLoader

    id: IDType = strawberry.field(description='Event id')
    user_invitations: typing.Optional[typing.List[EventInvitationInsertModel]] = strawberry.field(description='Invitations to ensure', default_factory=list)


@strawberry.input(description='Input type for updating an Event')
class EventUpdateGQLModel:
    id: IDType = strawberry.field(description='Event id')
    lastchange: datetime.datetime = strawberry.field(description='timestamp')
    name: typing.Optional[str] = strawberry.field(description='Event name', default=strawberry.UNSET)
    name_en: typing.Optional[str] = strawberry.field(description='Event English name', default=strawberry.UNSET)
    description: typing.Optional[str] = strawberry.field(description='Event description', default=strawberry.UNSET)
    startdate: typing.Optional[datetime.datetime] = strawberry.field(description='Event start date', default=strawberry.UNSET)
    enddate: typing.Optional[datetime.datetime] = strawberry.field(description='Event end date', default=strawberry.UNSET)
    place: typing.Optional[str] = strawberry.field(description='where the event will happen', default=strawberry.UNSET)
    changedby_id: strawberry.Private[IDType] = None


@strawberry.input(description='Input type for deleting an Event')
class EventDeleteGQLModel:
    id: IDType = strawberry.field(description='Event id')
    lastchange: datetime.datetime = strawberry.field(description='last change')


@strawberry.interface(description='Event mutations')
class EventMutation:
    @strawberry.mutation(
        description='Insert an Event',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[InsertError, EventGQLModel](roles=['plánovací administrátor']),
            UserRoleProviderExtension[InsertError, EventGQLModel](),
            RbacProviderExtension[InsertError, EventGQLModel](),
            LoadDataExtension[InsertError, EventGQLModel](getLoader=EventGQLModel.getLoader, primary_key_name='masterevent_id'),
        ],
    )
    async def event_insert(self, info: ApplicationInfo, event: EventInsertGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Union[EventGQLModel, InsertError[EventGQLModel]]:
        event.rbacobject_id = rbacobject_id
        service = info.ServiceCtx.Services.EventService
        return await service.ExecuteServiceMethod(
            service.Create(ctx=info.ServiceCtx, entity=event),
            Error=service.CreateErrorCallback(ErrorClass=InsertError[EventGQLModel], code='c2980f1a-eb73-4cd7-960b-94bf16dfa993', location='event_insert', _input=event),
            OK=EventGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Update an Event',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[UpdateError, EventGQLModel](roles=['plánovací administrátor']),
            UserRoleProviderExtension[UpdateError, EventGQLModel](),
            RbacProviderExtension[UpdateError, EventGQLModel](),
            LoadDataExtension[UpdateError, EventGQLModel](),
        ],
    )
    async def event_update(self, info: ApplicationInfo, event: EventUpdateGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Union[EventGQLModel, UpdateError[EventGQLModel]]:
        service = info.ServiceCtx.Services.EventService
        return await service.ExecuteServiceMethod(
            service.Update(ctx=info.ServiceCtx, entity=event),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[EventGQLModel], code='665aecd2-16a4-4560-a828-e043ee61e6d0', location='event_update', _input=event, _entity=EventGQLModel.from_dataclass(db_row)),
            OK=EventGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Ensures multiple invitations and creates missing ones',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[UpdateError, EventGQLModel](roles=['plánovací administrátor']),
            UserRoleProviderExtension[UpdateError, EventGQLModel](),
            RbacProviderExtension[UpdateError, EventGQLModel](),
            LoadDataExtension[UpdateError, EventGQLModel](),
        ],
    )
    async def event_ensure_invitations(self, info: ApplicationInfo, event: EventEnsureUserInvitationsModel, rbacobject_id: IDType, user_roles: typing.List[dict], db_row: typing.Any) -> typing.Union[UpdateError[EventGQLModel], EventGQLModel]:
        service = info.ServiceCtx.Services.EventService
        return await service.ExecuteServiceMethod(
            service.EnsureInvitations(ctx=info.ServiceCtx, entity=event),
            Error=service.CreateErrorCallback(ErrorClass=UpdateError[EventGQLModel], code='738079fc-e737-4da3-b1ad-1795e9d83bec', location='event_ensure_invitations', _input=event, _entity=EventGQLModel.from_dataclass(db_row)),
            OK=EventGQLModel.from_dataclass,
        )

    @strawberry.mutation(
        description='Delete an Event',
        permission_classes=[OnlyForAuthentized],
        extensions=[
            UserAccessControlExtension[DeleteError, EventGQLModel](roles=['plánovací administrátor']),
            UserRoleProviderExtension[DeleteError, EventGQLModel](),
            RbacProviderExtension[DeleteError, EventGQLModel](),
            LoadDataExtension[DeleteError, EventGQLModel](),
        ],
    )
    async def event_delete(self, info: ApplicationInfo, event: EventDeleteGQLModel, db_row: typing.Any, rbacobject_id: IDType, user_roles: typing.List[dict]) -> typing.Optional[DeleteError[EventGQLModel]]:
        service = info.ServiceCtx.Services.EventService
        return await service.ExecuteServiceMethod(
            service.Delete(ctx=info.ServiceCtx, entity=event),
            Error=service.CreateErrorCallback(ErrorClass=DeleteError[EventGQLModel], code='4e9caf74-4dce-4c11-bfe3-278f822c217c', location='event_delete', _input=event, _entity=EventGQLModel.from_dataclass(db_row)),
            OK=lambda result: None,
        )
