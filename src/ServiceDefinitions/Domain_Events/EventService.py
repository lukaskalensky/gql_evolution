import typing
import uuid

from sqlalchemy import select

import sqlalchemy
from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import EventModel
from src.ServiceDefinitions.BaseService import BaseService, ServiceExceptionWithCode
from src.ServiceDefinitions.ServiceContext import ServiceContext


class EventService(BaseService[IDLoader[EventModel]]):
    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[EventModel]:
        return ctx.loaders.EventModel

    @classmethod
    async def EnsureInvitations(cls, ctx: ServiceContext, event) -> typing.Optional[EventModel]:
        invitation_service = ctx.Services.EventInvitationService
        loader = await cls.getLoader(ctx)

        stmt = (
            select(EventModel)
            .where(EventModel.id == event.id)
            .options(
                sqlalchemy.orm.selectinload(EventModel.user_invitations))
            )

        result = await loader.execute_select(stmt)
        if result is None:
            raise ServiceExceptionWithCode('the event does not exist', code='event_not_found', location='EnsureInvitations')
        if len(result) == 0:
            raise ServiceExceptionWithCode('the event does not exist', code='event_not_found', location='EnsureInvitations')
        result = result[0]
        user_invitations = result.user_invitations
        related_user_ids = {invitation.user_id for invitation in user_invitations}
        # related_user_ids = set(await invitation_service.GetInvitedUsers(ctx=ctx, entity=event))
        for invitation in event.user_invitations:
            if invitation.user_id in related_user_ids:
                continue
            invitation.event_id = event.id
            await invitation_service.Create(ctx=ctx, entity=invitation)
        return result
