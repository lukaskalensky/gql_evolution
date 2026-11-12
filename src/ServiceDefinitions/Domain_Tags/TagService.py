from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import TagModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes
from src.ServiceDefinitions.Domain_Tags.BaseTagService import BaseTagService
from src.ServiceDefinitions.ServiceContext import ServiceContext


class TagService(BaseTagService[IDLoader[TagModel]]):
    """Definice tagů (název, popisek, barva, popis a typ z číselníku)."""

    NotFoundCode = ErrorCodes.TAG_NOT_FOUND
    ConflictCode = ErrorCodes.TAG_CONFLICT

    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[TagModel]:
        return ctx.loaders.TagModel

    @classmethod
    async def EnsureValid(cls, ctx: ServiceContext, entity) -> None:
        type_id = getattr(entity, 'type_id', None)
        if type_id and await ctx.loaders.TagTypeModel.load(type_id) is None:
            raise ServiceExceptionWithCode('Tag type not found', code=ErrorCodes.TAG_TYPE_REFERENCE_NOT_FOUND, location='TagService.EnsureValid')

    @classmethod
    async def EnsureCanDelete(cls, ctx: ServiceContext, row) -> None:
        if await cls.SelectBy(ctx.loaders.TagEntityModel, tag_id=row.id):
            raise ServiceExceptionWithCode('Tag is assigned to entities', code=ErrorCodes.TAG_HAS_ASSIGNMENTS, location='TagService.EnsureCanDelete')
