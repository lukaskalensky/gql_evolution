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

    @classmethod
    async def resolve_reference(cls, info: strawberry.Info, id: IDType, **kwargs):
        """Externí entita: vrací jen referenci {id}, zbytek dodá vlastnický subgraf přes gateway."""
        return None if id is None else cls(id=id)
