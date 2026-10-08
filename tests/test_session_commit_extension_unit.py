from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.GraphTypeDefinitions.GraphQLContext import GraphQLContext
from src.GraphTypeDefinitions.SessionCommitExtension import SessionCommitExtension, _maybe_await
from src.ServiceDefinitions.ServiceContext import ServiceContext


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeSessionContextManager:
    def __init__(self, session: FakeSession):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.session.closed = True
        return False


class FakeSessionMaker:
    def __init__(self, session: FakeSession):
        self.session = session
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return FakeSessionContextManager(self.session)


class FakeOperationType:
    def __init__(self, value):
        self.value = value


class FakeContext(dict):
    pass


async def async_identity(value):
    return value


@pytest.mark.asyncio
async def test_maybe_await_handles_plain_values_and_awaitables():
    assert await _maybe_await("plain") == "plain"
    assert await _maybe_await(async_identity("async")) == "async"


@pytest.mark.asyncio
async def test_get_session_maker_prefers_context_resolver_and_awaits_it():
    maker = object()

    class Context:
        async def resolve_session_maker(self):
            return maker

    extension = SessionCommitExtension()
    assert await extension._get_session_maker(Context()) is maker


@pytest.mark.asyncio
async def test_get_session_maker_uses_context_factory_and_database_fallback(monkeypatch):
    import src.GraphTypeDefinitions.SessionCommitExtension as extension_module

    maker_from_factory = object()
    context = {"session_maker_factory": lambda: maker_from_factory}
    extension = SessionCommitExtension()

    assert await extension._get_session_maker(context) is maker_from_factory

    default_maker = object()
    monkeypatch.setattr(extension_module, "Database", lambda: SimpleNamespace(session_maker=default_maker))
    assert await extension._get_session_maker({}) is default_maker


@pytest.mark.asyncio
async def test_create_loaders_prefers_context_resolver_factory_and_fallback(monkeypatch):
    import src.GraphTypeDefinitions.SessionCommitExtension as extension_module

    session = object()
    loaders_from_resolver = object()

    class ContextWithResolver:
        async def resolve_loaders(self, received_session):
            assert received_session is session
            return loaders_from_resolver

    extension = SessionCommitExtension()
    assert await extension._create_loaders(ContextWithResolver(), session) is loaders_from_resolver

    loaders_from_factory = object()
    context = {"loaders_factory": lambda received_session: (received_session, loaders_from_factory)}
    assert await extension._create_loaders(context, session) == (session, loaders_from_factory)

    monkeypatch.setattr(extension_module, "LoaderMap", lambda received_session: ("default", received_session))
    assert await extension._create_loaders({}, session) == ("default", session)


@pytest.mark.parametrize(
    "operation, expected",
    [
        (None, None),
        (SimpleNamespace(operation=None), None),
        (SimpleNamespace(operation=FakeOperationType("mutation")), "mutation"),
        (SimpleNamespace(operation="query"), "query"),
    ],
)
def test_get_operation_type_handles_missing_enum_and_plain_string(operation, expected):
    extension = SessionCommitExtension()
    extension.execution_context = SimpleNamespace(operation=operation)

    assert extension._get_operation_type() == expected


async def drive_successful_operation(extension: SessionCommitExtension):
    operation = extension.on_operation()
    await operation.__anext__()
    with pytest.raises(StopAsyncIteration):
        await operation.__anext__()


@pytest.mark.asyncio
async def test_on_operation_commits_mutation_and_injects_service_context():
    session = FakeSession()
    maker = FakeSessionMaker(session)
    loaders = object()
    user = {"id": "user-id"}
    ug_client = object()
    request = SimpleNamespace(state=SimpleNamespace(user={"id": "state-user"}))

    context = GraphQLContext(
        request=request,
        session_maker_factory=lambda: maker,
        loaders_factory=lambda received_session: loaders,
    )
    context["user"] = user
    context["ug_client"] = ug_client

    extension = SessionCommitExtension()
    extension.execution_context = SimpleNamespace(
        context=context,
        operation=SimpleNamespace(operation=FakeOperationType("mutation")),
    )

    await drive_successful_operation(extension)

    assert maker.calls == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True
    assert context["session"] is session
    assert context["loaders"] is loaders
    assert isinstance(context["ServiceCtx"], ServiceContext)
    assert context["ServiceCtx"].user is user
    assert context["ServiceCtx"].ug_client is ug_client
    assert context["ServiceCtx"].session is session


@pytest.mark.asyncio
async def test_on_operation_rolls_back_query_without_errors():
    session = FakeSession()
    maker = FakeSessionMaker(session)
    context = GraphQLContext(
        session_maker_factory=lambda: maker,
        loaders_factory=lambda received_session: object(),
    )

    extension = SessionCommitExtension()
    extension.execution_context = SimpleNamespace(
        context=context,
        operation=SimpleNamespace(operation=FakeOperationType("query")),
    )

    await drive_successful_operation(extension)

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_on_operation_rolls_back_when_context_has_errors():
    session = FakeSession()
    maker = FakeSessionMaker(session)
    context = GraphQLContext(
        session_maker_factory=lambda: maker,
        loaders_factory=lambda received_session: object(),
    )

    extension = SessionCommitExtension()
    extension.execution_context = SimpleNamespace(
        context=context,
        operation=SimpleNamespace(operation=FakeOperationType("mutation")),
    )

    operation = extension.on_operation()
    await operation.__anext__()
    context["errors"].append({"msg": "business error"})
    with pytest.raises(StopAsyncIteration):
        await operation.__anext__()

    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_on_operation_rolls_back_and_appends_error_on_exception():
    session = FakeSession()
    maker = FakeSessionMaker(session)
    context = GraphQLContext(
        session_maker_factory=lambda: maker,
        loaders_factory=lambda received_session: object(),
    )

    extension = SessionCommitExtension()
    extension.execution_context = SimpleNamespace(
        context=context,
        operation=SimpleNamespace(operation=FakeOperationType("mutation")),
    )

    operation = extension.on_operation()
    await operation.__anext__()

    with pytest.raises(RuntimeError):
        await operation.athrow(RuntimeError("boom"))

    assert session.commits == 0
    assert session.rollbacks == 1
    assert context["errors"]
    assert context["errors"][0]["code"] == "43b027da-d073-4fac-8881-3353609f2bcd"
    assert "boom" in context["errors"][0]["msg"]
