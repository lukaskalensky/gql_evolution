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

    @classmethod
    async def resolve_reference(cls, info: strawberry.Info, id: IDType, **kwargs):
        """Externí entita: vrací jen referenci {id}, zbytek dodá vlastnický subgraf přes gateway."""
        return None if id is None else cls(id=id)
