from __future__ import annotations

import typing

import strawberry
from strawberry.extensions import ParserCache, ValidationCache
from strawberry.schema.config import StrawberryConfig

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.default_resolver import gql_default_resolver
from src.GraphTypeDefinitions.mutation import Mutation
from src.GraphTypeDefinitions.query import Query
from src.GraphTypeDefinitions.Domain_UG import UserGQLModel, StateGQLModel
from src.GraphTypeDefinitions.BaseGQLModel import Relation
from src.GraphTypeDefinitions.SessionCommitExtension import SessionCommitExtension


ExtensionSpec = typing.Any


def get_production_extensions() -> list[ExtensionSpec]:
    """Return production schema extensions.

    Keep this in one place so tests can build the same schema with a fake
    WhoAmI extension instead of calling the external UG microservice.
    """

    from uoishelpers.schema import WhoAmIExtension
    from uoishelpers.gqlpermissions.RolePermissionSchemaExtension import RolePermissionSchemaExtension

    return [
        SessionCommitExtension,
        WhoAmIExtension,
        RolePermissionSchemaExtension,
        lambda:ParserCache(1000),
        lambda:ValidationCache(1000),
    ]


def create_schema(
    *,
    extensions: list[ExtensionSpec] | None = None,
    include_cache_extensions: bool = False,
):
    """Create Strawberry federation schema.

    Parameters
    ----------
    extensions:
        Exact extension list to use.  When omitted, production extensions are
        used, including the real WhoAmIExtension.
    include_cache_extensions:
        Convenience flag for tests that pass their own extension list but still
        want ParserCache and ValidationCache appended.
    """

    selected_extensions = list(extensions) if extensions is not None else get_production_extensions()

    if include_cache_extensions:
        selected_extensions.extend([
            lambda: ParserCache(1000),
            lambda: ValidationCache(1000)
        ])

    return strawberry.federation.Schema(
        query=Query,
        mutation=Mutation,
        types=[UserGQLModel, StateGQLModel],
        config=StrawberryConfig(
            default_resolver=gql_default_resolver,
            info_class=ApplicationInfo,
        ),
        extensions=selected_extensions,
        schema_directives=[Relation],
    )
