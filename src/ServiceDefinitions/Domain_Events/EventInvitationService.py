import uuid

from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import EventInvitationModel
from src.ServiceDefinitions.BaseService import BaseService, ServiceExceptionWithCode
from src.ServiceDefinitions.ServiceContext import ServiceContext

ORGANIZER_STATE_ID = uuid.UUID('3265a488-bbfa-4c59-946c-7a7b059ee4f0')
ACCEPTED_STATE_ID = uuid.UUID('7d2ef223-b60e-4e6d-b7d5-5fdc1f8e2ec2')
DECLINED_STATE_ID = uuid.UUID('d6a5e9e4-3e47-4c95-a4aa-b194dd2bc3a7')


class EventInvitationService(BaseService[IDLoader[EventInvitationModel]]):
    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[EventInvitationModel]:
        return ctx.loaders.EventInvitationModel

    @classmethod
    async def EnsureUserIsOrganizerForInvitation(cls, ctx: ServiceContext, invitation_id):
        loader = await cls.getLoader(ctx)
        invitation = await loader.load(invitation_id)
        if invitation is None:
            raise ServiceExceptionWithCode('Invitation not found', code='event_invitation_not_found')

        event_invitations = await loader.filter_by(event_id=invitation.event_id)
        user_id = ctx.user.get('id') if isinstance(ctx.user, dict) else getattr(ctx.user, 'id', None)
        user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        is_organizer = any(row.user_id == user_id and row.state_id == ORGANIZER_STATE_ID for row in event_invitations)
        if not is_organizer:
            raise ServiceExceptionWithCode('You are not organizer', code='event_invitation_not_organizer')
        return invitation

    @classmethod
    async def AcceptOrDeclineByInvitedUser(cls, ctx: ServiceContext, entity):
        loader = await cls.getLoader(ctx)
        invitation = await loader.load(entity.id)
        if invitation is None:
            raise ServiceExceptionWithCode('Invitation not found', code='event_invitation_not_found')

        user_id = ctx.user.get('id') if isinstance(ctx.user, dict) else getattr(ctx.user, 'id', None)
        user_id = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        if user_id != invitation.user_id:
            raise ServiceExceptionWithCode('You are not authorized', code='event_invitation_not_invited_user')

        if entity.state_id not in {ACCEPTED_STATE_ID, DECLINED_STATE_ID}:
            raise ServiceExceptionWithCode('Invalid invitation state', code='invalid_invitation_state')
        return await loader.update(entity=entity)

    @classmethod
    async def UpdateByOrganizer(cls, ctx: ServiceContext, entity):
        loader = await cls.getLoader(ctx)
        await cls.EnsureUserIsOrganizerForInvitation(ctx=ctx, invitation_id=entity.id)
        return await loader.update(entity=entity)

    @classmethod
    async def DeleteByOrganizer(cls, ctx: ServiceContext, entity):
        loader = await cls.getLoader(ctx)
        await cls.EnsureUserIsOrganizerForInvitation(ctx=ctx, invitation_id=entity.id)
        return await loader.delete(entity.id)

    @classmethod
    async def GetInvitedUsers(cls, ctx: ServiceContext, entity):
        loader = await cls.getLoader(ctx)
        invitations = await loader.filter_by(event_id=entity.id)
        return [invitation.user_id for invitation in invitations]
