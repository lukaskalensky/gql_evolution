from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import TagTypeModel
from src.ServiceDefinitions.BaseService import ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Tags import ErrorCodes
from src.ServiceDefinitions.Domain_Tags.BaseTagService import BaseTagService
from src.ServiceDefinitions.ServiceContext import ServiceContext


class TagTypeService(BaseTagService[IDLoader[TagTypeModel]]):
    """Číselník typů tagů organizovaný jako strom (parent_id)."""

    NotFoundCode = ErrorCodes.TAG_TYPE_NOT_FOUND
    ConflictCode = ErrorCodes.TAG_TYPE_CONFLICT

    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[TagTypeModel]:
        return ctx.loaders.TagTypeModel

    @classmethod
    async def EnsureValid(cls, ctx: ServiceContext, entity) -> None:
        """Nadřazený typ musí existovat a nesmí vzniknout cyklus (typ pod sebou nebo svým potomkem)."""
        parent_id = getattr(entity, 'parent_id', None)
        if not parent_id:
            return

        visited = set()
        current_id = parent_id
        while current_id and current_id not in visited:
            if current_id == entity.id:
                raise ServiceExceptionWithCode('Tag type tree would contain a cycle', code=ErrorCodes.TAG_TYPE_CYCLE, location='TagTypeService.EnsureValid')
            visited.add(current_id)
            current = await cls.ReadById(ctx=ctx, id=current_id)
            if current is None:
                raise ServiceExceptionWithCode('Parent tag type not found', code=ErrorCodes.TAG_TYPE_PARENT_NOT_FOUND, location='TagTypeService.EnsureValid')
            current_id = current.parent_id

    @classmethod
    async def EnsureCanDelete(cls, ctx: ServiceContext, row) -> None:
        loader = await cls.getLoader(ctx)
        if await cls.SelectBy(loader, parent_id=row.id):
            raise ServiceExceptionWithCode('Tag type has child types', code=ErrorCodes.TAG_TYPE_HAS_CHILDREN, location='TagTypeService.EnsureCanDelete')
        if await cls.SelectBy(ctx.loaders.TagModel, type_id=row.id):
            raise ServiceExceptionWithCode('Tag type is used by tags', code=ErrorCodes.TAG_TYPE_HAS_TAGS, location='TagTypeService.EnsureCanDelete')
