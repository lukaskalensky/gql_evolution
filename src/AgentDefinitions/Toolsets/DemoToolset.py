from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from ..Context import AgentContext


def create_demo_toolset() -> FunctionToolset[AgentContext]:
    toolset = FunctionToolset[AgentContext]()

    @toolset.tool
    async def get_subgraph_info(
        ctx: RunContext[AgentContext],
    ) -> str:
        """
        Return basic information about the current GraphQL subgraph.

        Use this tool when you need to know which application
        subgraph you are currently working with.
        """

        return (
            f"This agent is connected to subgraph "
            f"'{ctx.deps.subgraph_name}'."
        )

    @toolset.tool
    async def add_numbers(
        ctx: RunContext[AgentContext],
        a: int,
        b: int,
    ) -> int:
        """
        Add two integer numbers.

        This is a demonstration tool used to verify that
        PydanticAI tool invocation works correctly.
        """

        return a + b

    return toolset