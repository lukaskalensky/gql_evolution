from __future__ import annotations

import types
import uuid

import pytest
import sqlalchemy

from src.ServiceDefinitions.BaseService import (
    BaseService,
    ServiceExceptionWithCode,
    filter_kwargs_for_callable,
    maybe_await,
)


class FakeModel:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeLoader:
    def __init__(self):
        self.insert_calls = []
        self.page_calls = []
        self.update_calls = []
        self.deleted_ids = []
        self.loaded_ids = []

    def getModel(self):
        return FakeModel

    async def insert(self, *, entity, extraAttributes):
        self.insert_calls.append((entity, extraAttributes))
        return {"operation": "insert", "entity": entity, "extraAttributes": extraAttributes}

    async def load(self, id):
        self.loaded_ids.append(id)
        return {"operation": "load", "id": id}

    async def page(self, **kwargs):
        self.page_calls.append(kwargs)
        return [{"operation": "page", **kwargs}]

    async def update(self, *, entity, extraValues):
        self.update_calls.append((entity, extraValues))
        return {"operation": "update", "entity": entity, "extraValues": extraValues}

    async def delete(self, id):
        self.deleted_ids.append(id)
        return {"operation": "delete", "id": id}


class FakeService(BaseService[FakeLoader]):
    loader = FakeLoader()

    @classmethod
    async def getLoader(cls, ctx):
        return cls.loader


class CallbackResult:
    def __init__(self, *, msg=None, code=None, location=None, _entity=None, extra=None):
        self.msg = msg
        self.code = code
        self.location = location
        self.entity = _entity
        self.extra = extra


@pytest.mark.asyncio
async def test_maybe_await_handles_awaitable_and_plain_value():
    async def coro():
        return "awaited"

    assert await maybe_await(coro()) == "awaited"
    assert await maybe_await("plain") == "plain"


def test_filter_kwargs_for_callable_handles_classes_and_var_kwargs():
    class NeedsOnlyA:
        def __init__(self, a):
            self.a = a

    def accepts_var_kwargs(**kwargs):
        return kwargs

    assert filter_kwargs_for_callable(NeedsOnlyA, {"a": 1, "b": 2}) == {"a": 1}
    assert filter_kwargs_for_callable(accepts_var_kwargs, {"a": 1, "b": 2}) == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_base_service_get_loader_must_be_implemented():
    with pytest.raises(NotImplementedError):
        await BaseService.getLoader(ctx=None)


@pytest.mark.asyncio
async def test_standard_methods_delegate_to_loader_and_ensure_id():
    FakeService.loader = FakeLoader()
    ctx = object()

    model = await FakeService.Model(ctx, name="created model", value=3)
    assert isinstance(model, FakeModel)
    assert model.kwargs == {"name": "created model", "value": 3}

    entity = types.SimpleNamespace(id=None)
    created = await FakeService.Create(ctx, entity, extraAttributes={"source": "unit"})
    assert entity.id is not None
    assert isinstance(entity.id, uuid.UUID)
    assert created["operation"] == "insert"
    assert FakeService.loader.insert_calls == [(entity, {"source": "unit"})]

    loaded_id = uuid.uuid4()
    loaded = await FakeService.ReadById(ctx, loaded_id)
    assert loaded == {"operation": "load", "id": loaded_id}

    page = await FakeService.ReadPage(
        ctx,
        skip=2,
        limit=5,
        where="x = y",
        orderby="name",
        desc=True,
        extendedfilter={"active": True},
    )
    assert page[0]["skip"] == 2
    assert page[0]["extendedfilter"] == {"active": True}

    updated = await FakeService.Update(ctx, entity, extraValues={"changed": True})
    assert updated["operation"] == "update"
    assert FakeService.loader.update_calls == [(entity, {"changed": True})]

    deleted = await FakeService.Delete(ctx, entity)
    assert deleted == {"operation": "delete", "id": entity.id}
    assert FakeService.loader.deleted_ids == [entity.id]


@pytest.mark.asyncio
async def test_execute_service_method_success_calls_ok_callback():
    async def operation():
        return {"id": "ok"}

    async def ok(result):
        return {"wrapped": result}

    async def error(**kwargs):  # pragma: no cover - must not be called
        raise AssertionError("error callback should not be called")

    result = await FakeService.ExecuteServiceMethod(operation(), Error=error, OK=ok)
    assert result == {"wrapped": {"id": "ok"}}


@pytest.mark.asyncio
async def test_execute_service_method_maps_sqlalchemy_errors():
    async def operation():
        raise sqlalchemy.exc.SQLAlchemyError("db failed")

    async def error(msg, code, exception):
        return {"msg": msg, "code": code, "exception": exception}

    result = await FakeService.ExecuteServiceMethod(operation(), Error=error)

    assert result["msg"].startswith("Database error: db failed")
    assert result["code"] in (None, "unknown")
    assert isinstance(result["exception"], sqlalchemy.exc.SQLAlchemyError)


@pytest.mark.asyncio
async def test_execute_service_method_maps_service_exception_with_code():
    async def operation():
        raise ServiceExceptionWithCode("business rule failed", code="SERVICE-CODE", location="unit")

    async def error(msg, code, exception):
        return {"msg": msg, "code": code, "exception": exception}

    result = await FakeService.ExecuteServiceMethod(operation(), Error=error)

    assert result["msg"] == "Service error: business rule failed code(SERVICE-CODE)"
    assert result["code"] == "SERVICE-CODE"
    assert isinstance(result["exception"], ServiceExceptionWithCode)


@pytest.mark.asyncio
async def test_execute_service_method_maps_unexpected_exception_with_origin():
    class CodedRuntimeError(RuntimeError):
        code = "RUNTIME-CODE"

    async def operation():
        raise CodedRuntimeError("boom")

    async def error(msg, code, filename, lineno, exception):
        return {
            "msg": msg,
            "code": code,
            "filename": filename,
            "lineno": lineno,
            "exception": exception,
        }

    result = await FakeService.ExecuteServiceMethod(operation(), Error=error)

    assert "CodedRuntimeError: boom code(RUNTIME-CODE)" in result["msg"]
    assert result["code"] == "RUNTIME-CODE"
    assert result["filename"].endswith("test_base_service_unit.py")
    assert isinstance(result["lineno"], int)
    assert isinstance(result["exception"], CodedRuntimeError)


@pytest.mark.asyncio
async def test_create_error_filters_params_resolves_entity_and_formats_location():
    async def entity_factory():
        return {"id": "entity-id"}

    error = await FakeService.CreateError(
        ErrorClass=CallbackResult,
        code="ERROR-CODE",
        location="unit-test",
        msg="failed",
        _input={"ignored_by_callback": True},
        _entity=entity_factory,
        filename="service.py",
        lineno=42,
        extraParams={"extra": "extra-value", "ignored": "ignored-value"},
    )

    assert isinstance(error, CallbackResult)
    assert error.code == "ERROR-CODE"
    assert error.msg == "failed"
    assert error.location == "unit-test (File service.py, line 42)"
    assert error.entity == {"id": "entity-id"}
    assert error.extra == "extra-value"
    assert not hasattr(error, "ignored")


@pytest.mark.asyncio
async def test_create_error_callback_merges_predefined_and_runtime_params():
    callback = FakeService.CreateErrorCallback(
        ErrorClass=CallbackResult,
        code="PREDEFINED-CODE",
        location="callback-location",
        _entity={"id": "entity"},
    )

    result = await callback(
        msg="runtime-message",
        code="RUNTIME-CODE",
        extraParams={"extra": "runtime-extra"},
    )

    assert isinstance(result, CallbackResult)
    assert result.code == "RUNTIME-CODE"
    assert result.msg == "runtime-message"
    assert result.location == "callback-location"
    assert result.entity == {"id": "entity"}
    assert result.extra == "runtime-extra"
