import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .Context import AgentContext
from .Toolsets import create_demo_toolset

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run PydanticAI subgraph agent."
    )

    parser.add_argument(
        "--env-file",
        type=Path,
        help="Path to .env file.",
    )

    return parser.parse_args()

def load_configuration():
    args = parse_args()

    if args.env_file:
        print(f"Loading environment variables from {args.env_file}")
        load_dotenv(args.env_file)

    result = {
        "AI_MODEL": os.getenv("AI_MODEL"),
        "AI_BASE_URL": os.getenv("AI_BASE_URL"),
        "AI_API_KEY": os.getenv("AI_API_KEY"),
    }
    return result

def create_agent(base_url: str, api_key: str, model_name: str) -> Agent[AgentContext]:
    
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=api_key,
    )

    model = OpenAIChatModel(
        model_name,
        provider=provider,
    )

    return Agent(
        model,
        deps_type=AgentContext,
        toolsets=[
            create_demo_toolset(),
        ],
        instructions="""
You are an assistant for a GraphQL federation subgraph.

This is an educational system demonstrating an architecture
close to a real deployable system.

Use available tools to access authoritative application data.
Do not invent identifiers or application data.

All future data operations must respect the identity and
permissions of the effective user.
""",
    )


def main():

    config = load_configuration()

    if not config["AI_MODEL"]:
        raise RuntimeError("AI_MODEL is not configured.")

    if not config["AI_BASE_URL"]:
        raise RuntimeError("AI_BASE_URL is not configured.")

    if not config["AI_API_KEY"]:
        raise RuntimeError("AI_API_KEY is not configured.")
        
    model_name = config.get(
        "AI_MODEL",
        "gpt-5.4-nano",
    )

    base_url = config.get(
        "AI_BASE_URL",
        "http://localhost:4000/v1",
    )

    api_key = config.get("AI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Environment variable AI_API_KEY is not set."
        )


    agent = create_agent(base_url, api_key, model_name)

    print("PydanticAI subgraph agent")
    print(f"model: {model_name}")
    print(f"endpoint: {base_url}")
    print()

    agent.to_cli_sync()


if __name__ == "__main__":
    main()