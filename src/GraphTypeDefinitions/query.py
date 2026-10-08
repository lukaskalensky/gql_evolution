import strawberry
from src.GraphTypeDefinitions.Domain_Events import Query_Domain_Events


@strawberry.type(description='Root query')
class Query(Query_Domain_Events):
    pass
