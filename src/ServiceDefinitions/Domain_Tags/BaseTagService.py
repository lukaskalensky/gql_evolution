import typing

from sqlalchemy import select

from src.ServiceDefinitions.BaseService import BaseService, T, ServiceExceptionWithCode
from src.ServiceDefinitions.ServiceContext import ServiceContext


class BaseTagService(BaseService[T]):
    """Společný základ služeb domény Tags: kódované chyby, kontrola lastchange a doménová pravidla."""

    NotFoundCode: str = None
    ConflictCode: str = None

    @classmethod
    async def SelectBy(cls, loader, **filters) -> list[typing.Any]:
        """Vrátí vždy čerstvé řádky; filter_by s jedním klíčem by vracel výsledky z cache session."""
        return await loader.execute_select(select(loader.getModel()).filter_by(**filters))

    @classmethod
    async def EnsureExists(cls, ctx: ServiceContext, id) -> typing.Any:
        row = await cls.ReadById(ctx=ctx, id=id)
        if row is None:
            raise ServiceExceptionWithCode('Entity not found', code=cls.NotFoundCode, location=cls.__name__)
        return row

    @classmethod
    async def EnsureValid(cls, ctx: ServiceContext, entity) -> None:
        """Doménová kontrola vstupu před zápisem; potomci ji podle potřeby přepisují."""

    @classmethod
    async def EnsureCanDelete(cls, ctx: ServiceContext, row) -> None:
        """Doménová kontrola před smazáním; potomci ji podle potřeby přepisují."""

    @classmethod
    async def Create(cls, ctx: ServiceContext, entity, extraAttributes=None) -> typing.Any:
        await cls.EnsureValid(ctx, entity)
        return await super().Create(ctx=ctx, entity=entity, extraAttributes=extraAttributes)

    @classmethod
    async def Update(cls, ctx: ServiceContext, entity, extraValues=None) -> typing.Any:
        await cls.EnsureExists(ctx, entity.id)
        await cls.EnsureValid(ctx, entity)
        result = await super().Update(ctx=ctx, entity=entity, extraValues=extraValues)
        if result is None:
            raise ServiceExceptionWithCode('Entity was changed by someone else', code=cls.ConflictCode, location=cls.__name__)
        return result

    @classmethod
    async def Delete(cls, ctx: ServiceContext, entity) -> typing.Any:
        """Smaže entitu; lastchange se porovnává, pokud ho volající předal (GraphQL vstup ho vyžaduje)."""
        row = await cls.EnsureExists(ctx, entity.id)
        lastchange = getattr(entity, 'lastchange', None)
        if lastchange is not None and lastchange != row.lastchange:
            raise ServiceExceptionWithCode('Entity was changed by someone else', code=cls.ConflictCode, location=cls.__name__)
        await cls.EnsureCanDelete(ctx, row)
        return await super().Delete(ctx=ctx, entity=entity)
