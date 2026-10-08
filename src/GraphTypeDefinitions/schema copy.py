import strawberry
from strawberry.schema.config import StrawberryConfig

from src.GraphTypeDefinitions.ApplicationInfo import ApplicationInfo
from src.GraphTypeDefinitions.default_resolver import gql_default_resolver
from src.GraphTypeDefinitions.mutation import Mutation
from src.GraphTypeDefinitions.query import Query
from src.GraphTypeDefinitions.Domain_UG import UserGQLModel, StateGQLModel

from .BaseGQLModel import Relation

from src.GraphTypeDefinitions.SessionCommitExtension import SessionCommitExtension
from uoishelpers.schema import WhoAmIExtension, ProfilingExtension, PrometheusExtension

from uoishelpers.gqlpermissions.RolePermissionSchemaExtension import RolePermissionSchemaExtension, GraphQLBatchLoader

from strawberry.extensions import ParserCache, ValidationCache

# from uoishelpers.schema.PyInstrumentHtmlExtension import PyInstrumentHtmlExtension


extensions = [
    SessionCommitExtension,
    WhoAmIExtension,

    ProfilingExtension(),
    # PyInstrument(),
    # PrometheusExtension(prefix="gql_evolution"),
    # PyInstrumentHtmlExtension(enabled=True),

    RolePermissionSchemaExtension,
    ParserCache(1000),
    ValidationCache(1000)
]

schema = strawberry.federation.Schema(
    query=Query,
    mutation=Mutation,
    types=[UserGQLModel, StateGQLModel],
    config=StrawberryConfig(
        default_resolver=gql_default_resolver,
        info_class=ApplicationInfo,
    ),

    extensions=extensions,
    schema_directives=[Relation]

)

