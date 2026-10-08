import datetime
import inspect
import logging
import typing
import uuid

import sqlalchemy
from uoishelpers.dataloaders.IDLoader import IDLoader

T = typing.TypeVar('T', bound=IDLoader)
logger = logging.getLogger(__name__)


class ServiceExceptionWithCode(Exception):
    def __init__(self, msg: str, code: typing.Union[str, int] = 'unknown', location: str | None = None):
        super().__init__(msg)
        self.code = code
        self.location = location


class BaseCreateProtocol(typing.Protocol):
    id: uuid.UUID | None
    rbacobject_id: uuid.UUID | None
    createdby_id: uuid.UUID | None


class BaseUpdateProtocol(typing.Protocol):
    id: uuid.UUID
    lastchange: datetime.datetime
    rbacobject_id: uuid.UUID | None
    changedby_id: uuid.UUID | None


class BaseDeleteProtocol(typing.Protocol):
    id: uuid.UUID
    lastchange: datetime.datetime
    rbacobject_id: uuid.UUID | None


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def filter_kwargs_for_callable(callable_, kwargs: dict):
    target = callable_
    if inspect.isclass(callable_):
        target = callable_.__init__

    signature = inspect.signature(target)
    parameters = signature.parameters
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    if accepts_kwargs:
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


class BaseService(typing.Generic[T]):
    @classmethod
    async def getLoader(cls, ctx) -> T:
        raise NotImplementedError('getLoader method must be implemented by subclass of BaseService')

    @classmethod
    def EnsureId(cls, ctx, entity: BaseCreateProtocol) -> BaseCreateProtocol:
        if entity.id is None:
            entity.id = uuid.uuid4()
        return entity

    @classmethod
    async def Model(cls, ctx, **attributes) -> typing.Any:
        loader = await cls.getLoader(ctx)
        model = loader.getModel()(**attributes)
        return model

    @classmethod
    async def Create(cls, ctx, entity, extraAttributes=None) -> typing.Any:
        extraAttributes = extraAttributes or {}
        loader = await cls.getLoader(ctx)
        entity_with_id = cls.EnsureId(ctx, entity)
        return await loader.insert(entity=entity_with_id, extraAttributes=extraAttributes)

    @classmethod
    async def ReadById(cls, ctx, id) -> typing.Any:
        loader = await cls.getLoader(ctx)
        return await loader.load(id)

    @classmethod
    async def ReadPage(cls, ctx, skip: int = 0, limit: int = 10, where: typing.Any = None, orderby: str = None, desc: bool = None, extendedfilter: dict = None) -> list[typing.Any]:
        loader = await cls.getLoader(ctx)
        return await loader.page(skip=skip, limit=limit, where=where, orderby=orderby, desc=desc, extendedfilter=extendedfilter)

    @classmethod
    async def Update(cls, ctx, entity, extraValues=None) -> typing.Any:
        extraValues = extraValues or {}
        loader = await cls.getLoader(ctx)
        return await loader.update(entity=entity, extraValues=extraValues)

    @classmethod
    async def Delete(cls, ctx, entity) -> typing.Any:
        loader = await cls.getLoader(ctx)
        return await loader.delete(entity.id)

    @classmethod
    async def ExecuteServiceMethod(cls, coroutine, *, Error, OK=lambda result: result):
        result = None
        try:
            result = await coroutine
            return await cls.call_callback(OK, result)

        except sqlalchemy.exc.SQLAlchemyError as e:
            logger.exception("Database service operation failed")
            return await cls.call_callback(
                Error,
                msg=f"Database error: {e} code({getattr(e, 'code', 'unknown')})",
                exception=e,
                code=getattr(e, 'code', 'unknown'),
            )

        except ServiceExceptionWithCode as e:
            return await cls.call_callback(
                Error,
                msg=f"Service error: {e} code({e.code})",
                exception=e,
                code=e.code,
            )

        except Exception as e:
            code = getattr(e, 'code', 'unknown')
            logger.exception("Unexpected service operation failure (code=%s)", code)
            return await cls.call_callback(
                Error,
                msg="Unexpected service error",
                code=code,
            )

    @classmethod
    async def call_callback(cls, callback, *args, **kwargs):
        safe_kwargs = filter_kwargs_for_callable(callback, kwargs)
        result = callback(*args, **safe_kwargs)
        return await maybe_await(result)

    @classmethod
    async def CreateError(cls, *, ErrorClass, code, location, msg, _input=None, _entity=None, exception=None, filename=None, lineno=None, extraParams=None):
        _entity = await maybe_await(_entity() if callable(_entity) else _entity)
        location_text = location if filename is None or lineno is None else f'{location} (File {filename}, line {lineno})'
        params = {
            'code': code,
            'location': location_text,
            'msg': msg,
            '_input': _input,
            '_entity': _entity,
            **(extraParams or {}),
        }
        safe_params = filter_kwargs_for_callable(ErrorClass, params)
        return ErrorClass(**safe_params)

    @classmethod
    def CreateErrorCallback(cls, *, ErrorClass, **predefinedParams):
        async def result(**args):
            allParams = {**predefinedParams, **args}
            return await cls.CreateError(ErrorClass=ErrorClass, **allParams)
        return result
