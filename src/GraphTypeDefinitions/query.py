import strawberry
from src.GraphTypeDefinitions.Domain_Events import Query_Domain_Events
from src.GraphTypeDefinitions.Domain_Tags import Query_Domain_Tags


@strawberry.type(description='Root query')
class Query(Query_Domain_Events, Query_Domain_Tags):
    pass
