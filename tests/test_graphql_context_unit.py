from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.GraphTypeDefinitions.GraphQLContext import GraphQLContext
from src.ServiceDefinitions.ServiceContext import ServiceContext


class DummyDatabase:
    session_maker = object()


class DummyLoaders:
    def __init__(self, session=None):
        self.session = session


class DummyLoaderMap:
    def __call__(self, session):
        return DummyLoaders(session)



def make_service_ctx(**overrides):
    values = {
        "loaders": object(),
        "user": {"id": "service-user"},
        "ug_client": object(),
        "request": object(),
        "session": object(),
    }
    values.update(overrides)
    return ServiceContext(**values)



def test_graphql_context_reads_values_from_service_context_when_extra_is_missing():
    service_ctx = make_service_ctx()
    context = GraphQLContext(ServiceCtx=service_ctx)

    assert context.loaders is service_ctx.loaders
    assert context.user is service_ctx.user
    assert context.session is service_ctx.session
    assert context.ug_client is service_ctx.ug_client

    assert context["ServiceCtx"] is service_ctx
    assert context["service_ctx"] is service_ctx
    assert context["loaders"] is service_ctx.loaders
    assert context["user"] is service_ctx.user
    assert context["session"] is service_ctx.session
    assert context["ug_client"] is service_ctx.ug_client



def test_graphql_context_returns_none_for_optional_values_without_service_context():
    context = GraphQLContext()

    assert context.user is None
    assert context.session is None
    assert context.ug_client is None
    assert "ServiceCtx" not in context
    assert context.get("ServiceCtx", "missing") == "missing"

    with pytest.raises(KeyError):
        _ = context["ServiceCtx"]



def test_graphql_context_setters_keep_service_context_in_sync():
    service_ctx = make_service_ctx()
    context = GraphQLContext(ServiceCtx=service_ctx)

    loaders = object()
    user = {"id": "updated-user"}
    session = object()
    ug_client = object()

    context["loaders"] = loaders
    context["user"] = user
    context["session"] = session
    context["ug_client"] = ug_client

    assert context.loaders is loaders
    assert context.user is user
    assert context.session is session
    assert context.ug_client is ug_client

    assert service_ctx.loaders is loaders
    assert service_ctx.user is user
    assert service_ctx.session is session
    assert service_ctx.ug_client is ug_client



def test_graphql_context_attribute_and_extra_mapping_behaviour():
    request = SimpleNamespace(name="request")
    context = GraphQLContext()

    context["request"] = request
    context["custom"] = 42
    context.update({"alpha": "a"}, beta="b")

    assert context.request is request
    assert context["request"] is request
    assert context["custom"] == 42
    assert context.get("alpha") == "a"
    assert context.get("beta") == "b"
    assert context.get("unknown", "fallback") == "fallback"

    assert context.setdefault("custom", "ignored") == 42
    assert context.setdefault("created", "value") == "value"
    assert context["created"] == "value"



def test_graphql_context_keys_items_and_values_include_dynamic_entries():
    service_ctx = make_service_ctx()
    context = GraphQLContext(ServiceCtx=service_ctx)
    context.update({"custom": 1})
    context["loaders"] = object()
    context["session"] = object()
    context["ug_client"] = object()

    keys = context.keys()
    assert "ServiceCtx" in keys
    assert "service_ctx" in keys
    assert "custom" in keys
    assert "loaders" in keys
    assert "session_maker_factory" in keys

    items = dict(context.items())
    assert items["custom"] == 1
    assert items["ServiceCtx"] is service_ctx
    assert len(context.values()) == len(keys)



def test_graphql_context_resolves_factories_from_attributes_and_extra(monkeypatch):
    session = object()
    session_maker = object()
    loaders = object()

    context = GraphQLContext(
        session_maker_factory=lambda: session_maker,
        loaders_factory=lambda received_session: (received_session, loaders),
    )

    assert context.resolve_session_maker() is session_maker
    assert context.resolve_loaders(session) == (session, loaders)

    extra_session_maker = object()
    extra_loaders = object()
    context = GraphQLContext()
    context["session_maker_factory"] = lambda: extra_session_maker
    context["loaders_factory"] = lambda received_session: (received_session, extra_loaders)

    assert context.resolve_session_maker() is extra_session_maker
    assert context.resolve_loaders(session) == (session, extra_loaders)



def test_graphql_context_resolves_default_database_and_loader_map(monkeypatch):
    import src.GraphTypeDefinitions.GraphQLContext as context_module

    session = object()
    default_session_maker = object()

    monkeypatch.setattr(context_module, "Database", lambda: SimpleNamespace(session_maker=default_session_maker))
    monkeypatch.setattr(context_module, "LoaderMap", lambda received_session: ("loaders", received_session))

    context = GraphQLContext()

    assert context.resolve_session_maker() is default_session_maker
    assert context.resolve_loaders(session) == ("loaders", session)
