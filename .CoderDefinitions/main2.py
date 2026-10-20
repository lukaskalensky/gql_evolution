import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
from dotenv import load_dotenv

import uvicorn
from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai_harness import Coder

load_dotenv()

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

LLAMA_BASE_URL = os.getenv("LLAMA_BASE_URL", "http://llama-server:8000/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-3.5-turbo")

base_provider = OpenAIProvider(
    base_url=LLAMA_BASE_URL,
    api_key="none",
)
raw_model = OpenAIChatModel(
    MODEL_NAME,
    provider=base_provider,
)

# Pomocný agent bez nástrojů čistě na sumarizaci
summarizer_agent = Agent(
    raw_model,
    instructions="""
Jsi asistent pro kompresi kontextu. Tvým úkolem je vzít dosavadní konverzaci a výstupy nástrojů programátorského agenta a vytvořit stručné shrnutí (max 3 věty) v češtině.
Zaměř se na to, co bylo reálně upraveno a jaký je aktuální stav. Nezmiňuj žádné budoucí kroky.
""",
    model_settings=ModelSettings(temperature=0.0),
)


async def compact_messages(
    messages: list[ModelMessage],
    max_messages: int = 10,
    keep_recent: int = 2,
) -> list[ModelMessage]:
    """Zredukuje dlouhou historii na souhrn + poslední zprávy."""
    if len(messages) <= max_messages:
        return messages

    print(f"\n[INFO] Čistím paměť: ze {len(messages)} zpráv mažu staré a komprimuji...")

    old_messages = messages[:-keep_recent]
    recent_messages = messages[-keep_recent:]

    history_text_blocks = []
    for msg in old_messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if hasattr(part, "content"):
                    history_text_blocks.append(f"User/Tool: {str(part.content)[:500]}")
        elif isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, TextPart):
                    history_text_blocks.append(f"Assistant: {part.content[:500]}")

    full_old_text = "\n---\n".join(history_text_blocks)

    summary_result = await summarizer_agent.run(
        f"Zde je dosavadní historie kódování ke shrnutí:\n\n{full_old_text}"
    )
    summary_text = summary_result.output

    compacted_message = ModelRequest(
        parts=[
            UserPromptPart(
                content=f"[SYSTEM NOTICKA - SHRNUTÍ PŘEDCHOZÍHO KONTEXTU]:\n{summary_text}"
            )
        ]
    )

    print("[INFO] Komprese dokončena.")
    return [compacted_message] + recent_messages


# ==============================================================================
# OPRAVENÝ WRAPPER S ASYNC CONTEXT MANAGEREM
# ==============================================================================
class CompactedChatModel(OpenAIChatModel):
    async def request(self, messages: list[ModelMessage], *args, **kwargs):
        compacted = await compact_messages(messages)
        return await super().request(compacted, *args, **kwargs)

    @asynccontextmanager
    async def request_stream(
        self, messages: list[ModelMessage], *args, **kwargs
    ) -> AsyncIterator:
        compacted = await compact_messages(messages)
        async with super().request_stream(compacted, *args, **kwargs) as stream:
            yield stream


def create_agent() -> Agent:
    wrapped_model = CompactedChatModel(
        MODEL_NAME,
        provider=base_provider,
    )

    return Agent(
        wrapped_model,
        capabilities=[
            LocalWorkspace(REPOSITORY_ROOT),
            Coder(),
        ],
        retries=3,
        model_settings=ModelSettings(
            temperature=0.0,
            max_tokens=2048,
        ),
        instructions=f"""
You are an autonomous coding assistant operating in: {REPOSITORY_ROOT}

CRITICAL EXECUTION PROTOCOL:
1. ONLY call tools when you genuinely need to read or write a file.
2. DO NOT over-verify. Once you have edited the file requested by the user, YOUR JOB IS COMPLETE.
3. NEVER write follow-up plans like "Nyní zkontroluji další soubor..." or "Začínám s čtením...".
4. When you write a text response to the user, you MUST STOP. DO NOT call any more tools in the same turn.
5. If the requested task is done, state briefly what was changed and WAIT for the user's next message.
6. Před každou úpravou nejdříve proveď testy a po úpravě testy znovu vytvoř (pro nové soubory) a spusť znovu
6. Odpovídej vždy česky, stručně a k věci.
""",
    )


def main():
    agent = create_agent()
    app = agent.to_web(allowed_hosts=["*"])

    print("PydanticAI Coder")
    print(f"workspace: {REPOSITORY_ROOT}")
    print(f"model: {MODEL_NAME}")
    print(f"provider: llama-server ({LLAMA_BASE_URL})")
    print("web: http://localhost:7932")

    uvicorn.run(app, host="0.0.0.0", port=7932)


if __name__ == "__main__":
    main()