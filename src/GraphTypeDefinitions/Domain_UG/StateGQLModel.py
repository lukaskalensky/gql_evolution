import uuid
import typing
import strawberry

IDType = uuid.UUID


@strawberry.federation.type(
    extend=True, 
    keys=['id'], 
    # description='External state entity from UG subgraph'
)
class StateGQLModel:
    id: IDType = strawberry.federation.field(external=True)
    name: typing.Optional[str] = strawberry.federation.field(external=True, default=None)
