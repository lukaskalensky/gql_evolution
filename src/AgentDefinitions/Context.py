from dataclasses import dataclass
from typing import Any, Awaitable, Callable


GraphQLExecutor = Callable[
    [str, dict[str, Any] | None],
    Awaitable[Any],
]

def create_execution_context(schema):
    async def execute_gql(query: str, variables: dict = None):
        """Execute a GraphQL query against the Strawberry schema.

        This is a convenience function for testing and debugging.  It does not
        perform any authentication or authorization checks, so it should not be
        used in production code.
        """

        result = await schema.execute(query, variable_values=variables)
        return result
    return execute_gql


@dataclass
class AgentContext:
    """
    Runtime dependencies available to agent tools.

    Later this context can contain:
    - GraphQL client
    - delegated authentication token
    - effective user information
    - federation/subgraph endpoint
    - audit/correlation identifiers
    """

    subgraph_name: str = "demo"
    executor: GraphQLExecutor = None
    user_id: str = None
    authorization_token: str = None