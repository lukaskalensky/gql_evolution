import uuid
import strawberry

IDType = uuid.UUID


@strawberry.federation.type(
    extend=True, 
    keys=['id'], 
    # description='External user entity from UG subgraph'
)
class UserGQLModel:
    id: IDType = strawberry.federation.field(external=True)
