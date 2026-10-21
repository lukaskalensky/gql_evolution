import os
from pathlib import Path

import uvicorn

from pydantic_ai import Agent
from pydantic_ai_harness import Coder
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.capabilities import LocalWorkspace
from dotenv import load_dotenv

load_dotenv()

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def create_model() -> OpenAIChatModel:
    provider = OpenAIProvider(
        base_url=os.environ["AI_BASE_URL"],
        api_key=os.environ["AI_API_KEY"],
    )

    return OpenAIChatModel(
        os.environ["AI_MODEL"],
        provider=provider,
    )


def create_agent() -> Agent:
    return Agent(
        create_model(),
        capabilities=[
            LocalWorkspace(REPOSITORY_ROOT),
            Coder(REPOSITORY_ROOT),
        ],
        instructions="""
You are a coding agent working on this repository.

Read AGENTS.md before making architectural changes.

Respect the existing architecture.

Before modifying code:
- inspect relevant files,
- inspect relevant tests.

After modifying code:
- run relevant tests,
- run linting if configured,
- inspect git diff.

Do not modify .CoderDefinitions or .devcontainer
unless explicitly requested.
""",
    )


def main():
    agent = create_agent()

    app = agent.to_web(
        allowed_hosts=["*"],
    )

    print("PydanticAI Coder")
    print(f"workspace: {REPOSITORY_ROOT}")
    print(f"model: {os.environ['AI_MODEL']}")
    print(f"endpoint: {os.environ['AI_BASE_URL']}")
    print("web: http://localhost:7932")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7932,
    )


if __name__ == "__main__":
    main()