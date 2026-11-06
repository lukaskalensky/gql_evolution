"""Tovární funkce autonomního agenta a jeho instrukce."""

from pathlib import Path
from typing import Callable, Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import LocalWorkspace, ProcessHistory
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai_harness import Coder

from .guards import ConfirmFn, ShellGuard, ToolArgsNormalizer
from .history import compact_old_messages
from .progress import read_plan

# Pravidla společná pro oba režimy (práce s nástroji a kontextem).
COMMON_CODER_INSTRUCTIONS = """
You are a Senior Software Engineering Agent working directly inside a local repository.

TOOL CALLING RULES (STRICT SCHEMA REQUIREMENTS):
- All paths are relative to the workspace root (e.g. "src/app/main.py"). NEVER omit `path`.
- `write_file(path, content)`: BOTH parameters are required. Creates a file or replaces its WHOLE content.
  The parent directory must already exist (create it with `shell`: mkdir -p).
- `edit_file(path, old_text, new_text)`: exact string replacement. `old_text` must appear EXACTLY ONCE
  in the file (include surrounding lines for uniqueness). For several changes in one call pass
  `replacements` (a JSON ARRAY of {old_text, new_text} objects, not a string) instead.
  `edit_file` has NO `content` parameter.
- `read_file` prefixes every line with its number and a TAB ("     3<TAB>code"). That prefix is NOT part
  of the file: copy only the code after the TAB into `old_text`, keeping its exact indentation.
- If one `edit_file` fails with "old_text not found", do NOT retry from memory: `read_file` the
  relevant lines again and copy them exactly. For small files or large rewrites use `write_file`.
- `read_file(path)`, `list_files(path, glob)`, `grep(pattern, path)`, `shell(command)`.
- Dangerous shell commands (git push, git reset --hard, sudo, rm -r outside the project, ...) are
  blocked by the harness. Do not try to work around the block; choose a safer approach.

CONTEXT RULES:
- `.cmd_coder/PLAN.md` is the ONLY file inside `.cmd_coder/` you may touch; never read, search or edit
  `history.json`, `PROGRESS.md` or the other files there. The folder already exists.
- Older tool outputs in the conversation may be shortened (marked "...[zkráceno ...]"). If you need
  the exact text again (for example for `edit_file`), read the file again instead of guessing.
- When requested to compare versions (e.g. v3 vs v3_1 vs v4) or synthesize architecture, inspect all relevant directories.
- Respect existing architectural conventions and guidelines.
"""

# Interaktivní konverzace: tah končí odpovědí uživateli, žádná značka dokončení.
CHAT_MODE_INSTRUCTIONS = """
YOU ARE IN A LIVE CONVERSATION WITH THE USER (pair programming):
- Your reply is shown to the user. Always answer in plain words, in the user's language.
- Question about the code: read what you need, then give the actual answer in your reply. Do not edit
  files or run tests for a question unless the user asks.
- Request to change something: do exactly that, without unrelated changes. Then verify it (run the relevant
  tests, or the changed code) and report briefly what changed and what the verification showed, including failures.
- If you hit a bug or a test failure while working, analyze it and fix it yourself. Ask the user only when
  the request is genuinely ambiguous or a decision is theirs, and then ask one short question.
- When you have answered or finished, stop and wait for the next message. Never write the word TASK_COMPLETED.
- For large multi-step work keep a checklist in `.cmd_coder/PLAN.md` (`- [ ]` / `- [x]`). Skip it for small tasks.
- Files may change between messages because the user edits them too: read a file again before relying on
  an old copy of it.
"""

# Autonomní běh bez člověka: smyčka končí značkou, kterou ověřuje harness.
AUTONOMOUS_MODE_INSTRUCTIONS = """
YOU ARE RUNNING AUTONOMOUSLY, no user is available to answer:
1. ATOMIC EXECUTION & AUTONOMY:
   - Take action immediately using your tools (read, write, edit, shell, delegate_task).
   - If you encounter a bug, syntax error, or test failure, do NOT give up or ask the user for help.
     Analyze the error traceback, formulate a fix, apply it, and re-test.

2. PROGRESS, PLAN & CACHE DISCIPLINE:
   - Check the provided SYSTEM STATE REMINDER (PROGRESS.md and PLAN) before acting.
   - Keep a short plan in `.cmd_coder/PLAN.md` (use `write_file`): a checklist with `- [ ]` / `- [x]` items
     plus a few lines of notes (decisions, findings, what remains). Update it after each major step. It is
     shown to you at the start of every step, so it is how you remember work across steps.
   - Do NOT redundantly re-read files marked as read in PROGRESS.md. A file you EDITED after reading is
     no longer listed as read; read it again if you need its current content.

3. TEST-DRIVEN VERIFICATION:
   - Before modifying code: inspect relevant files and existing tests.
   - After writing or editing code: ALWAYS run the relevant test suite or linters using the `shell` tool.
   - Never declare a task complete without executing verification commands. The harness REJECTS
     TASK_COMPLETED unless tests/linters ran successfully after your last edit (or its own test
     command passes).

4. TERMINATION PROTOCOL:
   - When the assigned task is fully implemented, verified, and all tests pass with zero regressions:
     Provide a brief summary of all completed work and conclude your response with:
     'TASK_COMPLETED'
"""

# Horní mez velikosti připomínky stavu vstřikované do každého požadavku (ochrana kontextu).
MAX_REMINDER_CHARS = 6000
MAX_PLAN_CHARS = 3000

# Limit opakování pro ostatní nástroje (shell, delegate_task). Souborové nástroje (read_file,
# edit_file, ...) mají v knihovně vlastní pevný limit 5 po sobě jdoucích chyb schématu; ten tu
# změnit nejde. Proto je tu ToolArgsNormalizer (předchází chybám) a obnova po vyčerpání limitu
# (viz MAX_CONSECUTIVE_PROBLEMS v runneru). Chyba "old_text not found" se do limitu nepočítá.
TOOL_RETRIES = 8


def create_generic_agent(
    workspace_path: Path,
    base_url: str,
    api_key: str,
    model_name: str,
    progress_file: Optional[Path] = None,
    plan_file: Optional[Path] = None,
    allow_dangerous: bool = False,
    confirm: Optional[ConfirmFn] = None,
    on_denied=None,
    keep_recent: int = 10,
    result_chars: int = 1200,
    is_autonomous: Callable[[], bool] = lambda: True,
) -> Agent:
    """
    Vytvoří agenta vybaveného workspace nástroji a dynamickým systémovým kontextem.
    `is_autonomous` se ptá před každým požadavkem, takže se režim může v průběhu relace měnit (/auto).
    """
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=api_key,
    )
    base_model = OpenAIChatModel(
        model_name,
        provider=provider,
    )

    capabilities = [
        LocalWorkspace(workspace_path),
        Coder(),
        ToolArgsNormalizer(),
        ShellGuard(allow_dangerous=allow_dangerous, confirm=confirm, on_denied=on_denied),
    ]
    if result_chars > 0:
        # Zkracuje staré výsledky nástrojů PŘED KAŽDÝM požadavkem na model, tedy i uvnitř jednoho
        # dlouhého kroku (35 volání nástrojů). Změna se projeví i v ukládané historii; proto se
        # zachovává začátek i konec výstupu (návratový kód a shrnutí testů jsou na konci).
        capabilities.append(
            ProcessHistory(lambda messages: compact_old_messages(messages, keep_recent, result_chars))
        )

    agent = Agent(
        base_model,
        capabilities=capabilities,
        instructions=COMMON_CODER_INSTRUCTIONS,
        retries={"tools": TOOL_RETRIES},
    )

    # Dynamické injektování aktuálního PROGRESS.md a plánu.
    # DŮLEŽITÉ: musí to být `instructions`, ne `system_prompt`. Obyčejný system_prompt se vyhodnotí
    # jen jednou, při prvním běhu bez historie, a pak zůstane zmrazený ve staré historii -
    # model by nikdy neviděl aktuální stav. Instructions se přepočítají při každém běhu.
    @agent.instructions
    def state_reminder(ctx: RunContext) -> str:
        autonomous = is_autonomous()
        sections: list[str] = [AUTONOMOUS_MODE_INSTRUCTIONS if autonomous else CHAT_MODE_INSTRUCTIONS]

        # PROGRESS.md říká "tohle už nečti znovu". To pomáhá autonomní smyčce, ale v konverzaci
        # by model spoléhal na zastaralé kopie souborů, které mezitím mohl změnit uživatel.
        if autonomous and progress_file and progress_file.exists():
            try:
                content = progress_file.read_text(encoding="utf-8").strip()
                if content:
                    if len(content) > MAX_REMINDER_CHARS:
                        content = (
                            content[:MAX_REMINDER_CHARS].rsplit("\n", 1)[0]
                            + "\n... (zkráceno; úplný stav je v PROGRESS.md)"
                        )
                    sections.append(
                        "[SYSTEM STATE REMINDER - CURRENT REPOSITORY PROGRESS (PROGRESS.md)]:\n"
                        f"{content}\n\n"
                        "[OPERATIONAL GUIDANCE]: The list above indicates previously examined or touched files. "
                        "When comparing architectures, analyzing diffs between versions, or refactoring, "
                        "you ARE permitted to re-inspect and compare files across folders to ensure complete accuracy."
                    )
            except Exception:
                pass

        if plan_file is not None:
            plan = read_plan(plan_file, MAX_PLAN_CHARS)
            if plan and autonomous:
                sections.append(f"[YOUR PLAN AND NOTES (.cmd_coder/PLAN.md)]:\n{plan}")
            elif plan:
                sections.append(
                    "[YOUR PLAN AND NOTES (.cmd_coder/PLAN.md), ignore it if it is unrelated to the user's "
                    f"current request]:\n{plan}"
                )
            elif autonomous:
                sections.append(
                    "[PLAN]: No plan exists yet. If the task has several steps, create `.cmd_coder/PLAN.md` "
                    "now with a short checklist."
                )

        return "\n\n".join(sections)

    return agent
