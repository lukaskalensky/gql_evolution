import os
from pathlib import Path
from dotenv import load_dotenv

import uvicorn
from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai_harness import Coder

# Načte proměnné z .env souboru
load_dotenv()

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

# PydanticAI pro google: provider používá GOOGLE_API_KEY nebo GEMINI_API_KEY
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("Chybí GOOGLE_API_KEY (nebo GEMINI_API_KEY) v .env souboru.")

os.environ["GOOGLE_API_KEY"] = api_key
os.environ["GEMINI_API_KEY"] = api_key

MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.8-flash")


def create_agent() -> Agent:
    return Agent(
        f"google:{MODEL_NAME}",
        capabilities=[
            LocalWorkspace(REPOSITORY_ROOT),
            Coder(),  # Bez argumentu, workspace řeší LocalWorkspace výše
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
    print(f"model: {MODEL_NAME}")
    print("provider: Google AI (native)")
    print("web: http://localhost:7932")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=7932,
    )


if __name__ == "__main__":
    main()