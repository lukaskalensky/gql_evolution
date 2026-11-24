import strawberry

from .TagTypeGQLModel import TagTypeGQLModel, TagTypeInputFilter, TagTypeMutation, TagTypeQuery
from .TagGQLModel import TagGQLModel, TagInputFilter, TagMutation, TagQuery
from .TagEntityGQLModel import TagEntityGQLModel, TagEntityInputFilter, TagEntityMutation, TagEntityQuery


@strawberry.interface(description='Tag domain queries')
class Query_Domain_Tags(TagTypeQuery, TagQuery, TagEntityQuery):
    pass


@strawberry.interface(description='Tag domain mutations')
class Mutation_Domain_Tags(TagTypeMutation, TagMutation, TagEntityMutation):
    pass


__all__ = [
    'TagTypeGQLModel', 'TagTypeInputFilter',
    'TagGQLModel', 'TagInputFilter',
    'TagEntityGQLModel', 'TagEntityInputFilter',
    'Query_Domain_Tags', 'Mutation_Domain_Tags',
]
