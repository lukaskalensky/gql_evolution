import strawberry

from .EventGQLModel import EventGQLModel, EventInputFilter, EventMutation, EventQuery
from .EventInvitationGQLModel import EventInvitationGQLModel, EventInvitationInputFilter, EventInvitationMutation, EventInvitationQuery


@strawberry.interface(description='Event domain queries')
class Query_Domain_Events(EventQuery, EventInvitationQuery):
    pass


@strawberry.interface(description='Event domain mutations')
class Mutation_Domain_Events(EventMutation, EventInvitationMutation):
    pass


__all__ = [
    'EventGQLModel', 'EventInputFilter', 'EventInvitationGQLModel', 'EventInvitationInputFilter',
    'Query_Domain_Events', 'Mutation_Domain_Events',
]
