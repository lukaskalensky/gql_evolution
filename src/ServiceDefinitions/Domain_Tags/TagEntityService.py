import typing
import uuid

from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import TagEntityModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes
from src.ServiceDefinitions.Domain_Tags.BaseTagService import BaseTagService
from src.ServiceDefinitions.ServiceContext import ServiceContext


class TagEntityService(BaseTagService[IDLoader[TagEntityModel]]):
    """Přiřazení tagů k entitám informačního systému; každé přiřazení má svého vlastníka."""

    NotFoundCode = ErrorCodes.TAG_ENTITY_NOT_FOUND
    ConflictCode = ErrorCodes.TAG_ENTITY_CONFLICT

    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[TagEntityModel]:
        return ctx.loaders.TagEntityModel

    @classmethod
    def GetUserId(cls, ctx: ServiceContext) -> uuid.UUID:
        user_id = ctx.user.get('id') if isinstance(ctx.user, dict) else getattr(ctx.user, 'id', None)
        if not user_id:
            raise ServiceExceptionWithCode('User is not authenticated', code=ErrorCodes.TAG_ENTITY_USER_REQUIRED, location='TagEntityService.GetUserId')
        return uuid.UUID(user_id) if isinstance(user_id, str) else user_id

    @classmethod
    async def EnsureValid(cls, ctx: ServiceContext, entity) -> None:
        tag_id = getattr(entity, 'tag_id', None)
        if tag_id and await ctx.loaders.TagModel.load(tag_id) is None:
            raise ServiceExceptionWithCode('Tag not found', code=ErrorCodes.TAG_ENTITY_TAG_NOT_FOUND, location='TagEntityService.EnsureValid')

    @classmethod
    async def AssignTag(cls, ctx: ServiceContext, entity) -> TagEntityModel:
        """Přiřadí tag entitě za přihlášeného uživatele; stejné přiřazení téhož uživatele nezdvojí."""
        owner_id = cls.GetUserId(ctx)
        if not (entity.entity_id and entity.entity_type_id and entity.tag_id):
            raise ServiceExceptionWithCode('entity_id, entity_type_id and tag_id are required', code=ErrorCodes.TAG_ENTITY_INVALID_INPUT, location='TagEntityService.AssignTag')

        loader = await cls.getLoader(ctx)
        existing = await cls.SelectBy(loader, entity_id=entity.entity_id, tag_id=entity.tag_id, owner_id=owner_id)
        if existing:
            return existing[0]
        return await cls.Create(ctx=ctx, entity=entity, extraAttributes={'owner_id': owner_id})

    @classmethod
    async def UnassignTag(cls, ctx: ServiceContext, entity) -> None:
        """Odebere přiřazení tagu; smí pouze jeho vlastník."""
        user_id = cls.GetUserId(ctx)
        row = await cls.EnsureExists(ctx, entity.id)
        if row.owner_id != user_id:
            raise ServiceExceptionWithCode('Only the owner can remove the assignment', code=ErrorCodes.TAG_ENTITY_NOT_OWNER, location='TagEntityService.UnassignTag')
        return await cls.Delete(ctx=ctx, entity=entity)

    @classmethod
    async def ReadByEntity(cls, ctx: ServiceContext, entity_id, entity_type_id=None) -> list[TagEntityModel]:
        """Vrátí přiřazení tagů dané entity, volitelně zúžená na typ entity."""
        filters: dict[str, typing.Any] = {'entity_id': entity_id}
        if entity_type_id:
            filters['entity_type_id'] = entity_type_id
        return await cls.SelectBy(await cls.getLoader(ctx), **filters)

    @classmethod
    async def ReadByTag(cls, ctx: ServiceContext, tag_id) -> list[TagEntityModel]:
        """Vrátí všechna přiřazení daného tagu."""
        return await cls.SelectBy(await cls.getLoader(ctx), tag_id=tag_id)
