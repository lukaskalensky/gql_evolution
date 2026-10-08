import strawberry
from src.GraphTypeDefinitions.Domain_Events import Mutation_Domain_Events


@strawberry.type(description='Root mutation')
class Mutation(Mutation_Domain_Events):
    pass
