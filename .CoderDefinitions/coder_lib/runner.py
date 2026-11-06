"""Provedení jednoho kroku agenta a hlavní běhová smyčka (autonomní režim i interaktivní kokpit)."""

import asyncio
import signal
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelMessage, TextPartDelta
from pydantic_ai.usage import UsageLimits
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from . import gitsafe
from .agent import create_generic_agent
from .chatio import ChatInput, TextStream, ask_yes_no, help_text, parse_command, strip_completion_marker
from .common import (
    LOG_FILE_NAME,
    PLAN_FILE_NAME,
    INPUT_HISTORY_FILE_NAME,
    STATE_DIR_NAME,
    _extract_tool_info,
    _tool_target,
    console,
    default_state_paths,
    ensure_state_dir,
    state_file,
    ui_state,
)
from .guards import LoopMonitor
from .history import (
    DEFAULT_KEEP_RECENT_MESSAGES,
    DEFAULT_RESULT_CHARS,
    finalize_partial_history,
    load_history_from_disk,
    safe_trim_history,
    save_history_to_disk,
)
from .progress import (
    append_to_progress,
    auto_update_progress_from_messages,
    read_plan,
    rebuild_progress,
)
from .runlog import RunLog
from .ui import (
    check_endpoint,
    print_checkpoints,
    print_live_tool_call,
    print_live_tool_result,
    print_step_usage,
    run_direct_command,
    show_git_diff,
)
from .verify import (
    MAX_GATE_REJECTIONS,
    analyze_activity,
    completion_hint_without_tests,
    format_test_report,
    run_test_command,
)

CONTINUE_PROMPT_AUTO = (
    "Zkontroluj SYSTEM STATE REMINDER / PROGRESS.md a svůj plán. "
    "Pokračuj dalším logickým nehotovým krokem v implementaci nebo ověřování (testech). "
    "Pokud narazíš na chybu, oprav ji a znovu otestuj. "
    "Pokud je úkol kompletně hotový a všechny testy procházejí, odpověz 'TASK_COMPLETED'."
)
CONTINUE_PROMPT_INTERACTIVE = (
    "Předchozí krok nebyl dokončen. Pokračuj v rozdělané práci od místa, kde skončila. "
    "Až bude hotová a ověřená, stručně shrň výsledek."
)

# Kolikrát po sobě smí krok skončit problémem (vyčerpaný limit opakování nástroje, zacyklení),
# než se běh zastaví.
MAX_CONSECUTIVE_PROBLEMS = 3
# S --test-cmd: kolikrát smí harness odmítnout TASK_COMPLETED kvůli selhávajícím testům
MAX_TEST_REJECTIONS = 4
# Výchozí hodnoty podle režimu: v konverzaci je krok celý tah a paměť musí držet její průběh
# (zkracování starých výstupů a strop délky historie v safe_trim_history hlídají kontextové okno).
DEFAULT_TURNS = {"auto": 3, "chat": 20}
DEFAULT_STEP_LIMIT = {"auto": 35, "chat": 100}
# Jak často (s) se nanejvýš překresluje text spinneru
_STATUS_REFRESH = 0.3


@dataclass
class RunSettings:
    """Všechna nastavení běhu agenta na jednom místě."""

    workspace_path: Path
    task: Optional[str] = None
    model_name: str = "gemma-4"
    endpoint: str = "http://127.0.0.1:8080/v1"
    api_key: str = "local"
    turns: Optional[int] = None  # None = výchozí hodnota podle režimu (DEFAULT_TURNS)
    step_limit: Optional[int] = None  # None = výchozí hodnota podle režimu (DEFAULT_STEP_LIMIT)
    max_iterations: int = 25
    auto_mode: bool = False
    history_file: Optional[Path] = None
    progress_file: Optional[Path] = None
    workspace_auto: bool = False
    test_cmd: Optional[str] = None
    test_timeout: int = 300
    use_git: bool = True
    allow_dangerous: bool = False
    result_chars: int = DEFAULT_RESULT_CHARS
    keep_recent: int = DEFAULT_KEEP_RECENT_MESSAGES
    check_server: bool = True


class StepOutcome:
    """Výsledek jednoho kroku agenta."""

    def __init__(
        self,
        output: Optional[str] = None,
        error: Optional[str] = None,
        limit_hit: bool = False,
        tool_failure: bool = False,
        loop_detected: Optional[str] = None,
        usage: tuple[int, int, int] = (0, 0, 0),
        seconds: float = 0.0,
        interrupted: bool = False,
        streamed_text: str = "",
    ):
        self.output = output
        self.error = error
        self.limit_hit = limit_hit
        # Model opakovaně volal nástroj se špatnými argumenty a vyčerpal limit opakování
        self.tool_failure = tool_failure
        # Popis zacyklení (None = nezacyklil se)
        self.loop_detected = loop_detected
        self.usage = usage  # (požadavky, vstupní tokeny, výstupní tokeny)
        self.seconds = seconds
        # Uživatel krok přerušil (Ctrl+C), dosavadní práce je v historii
        self.interrupted = interrupted
        # Text odpovědi, který už uživatel viděl průběžně
        self.streamed_text = streamed_text


def is_task_completed(text: str) -> bool:
    """Úkol je hotový, pokud značka TASK_COMPLETED stojí na posledním neprázdném řádku odpovědi."""
    for line in reversed(text.strip().splitlines()):
        if line.strip():
            return "TASK_COMPLETED" in line
    return False


def _read_usage(source: Any) -> tuple[int, int, int]:
    """Spotřebu čte z výsledku běhu nebo ze streamu (v různých verzích knihovny je to vlastnost či metoda)."""
    try:
        usage = source.usage
        # Novější verze knihovny: `usage` je vlastnost (volání jako metody je zastaralé a vypisuje varování)
        if not hasattr(usage, "requests") and callable(usage):
            usage = usage()
        return (
            int(getattr(usage, "requests", 0) or 0),
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
        )
    except Exception:
        return (0, 0, 0)


class ConsoleStepView:
    """Zobrazení běžícího kroku v terminálu: spinner, živý text a výpisy nástrojů."""

    def __enter__(self) -> "ConsoleStepView":
        self._context = console.status(
            "[bold green]⏳ Llama-server vyhodnocuje prompt a generuje odpověď...[/bold green]",
            spinner="dots",
        )
        self._status = self._context.__enter__()
        ui_state.status = self._status
        self._stream = TextStream(self._status)
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        self._stream.finish()
        ui_state.status = None
        return self._context.__exit__(*exc_info)

    def text(self, piece: str) -> None:
        self._stream.feed(piece)

    def end_text(self) -> None:
        self._stream.finish()

    def tool_call(self, part: Any, tool_name: str, args: dict[str, Any], valid: Optional[bool]) -> None:
        print_live_tool_call(tool_name, args, valid)

    def tool_result(self, part: Any) -> None:
        print_live_tool_result(getattr(part, "tool_name", ""), getattr(part, "content", ""))

    def tick(self, tools: int, chars: int, seconds: float) -> None:
        self._status.update(
            "[bold green]⏳ Model pracuje...[/bold green] "
            f"[dim]nástrojů: {tools} | vygenerováno ~{chars} znaků | {seconds:.0f} s[/dim]"
        )

    @property
    def streamed_text(self) -> str:
        return self._stream.last_text


def handle_stream_event(
    ev: Any,
    progress_path: Path,
    runlog: RunLog,
    monitor: LoopMonitor,
    step_no: int,
    counters: dict[str, int],
    view: Any,
) -> bool:
    """Předá událost zobrazení a zaloguje ji. Vrací True, pokud se model právě zacyklil."""
    if isinstance(ev, PartStartEvent) and isinstance(ev.part, TextPart):
        view.text(ev.part.content)
        counters["chars"] += len(ev.part.content)
        return False
    if isinstance(getattr(ev, "delta", None), TextPartDelta):
        view.text(ev.delta.content_delta)
        counters["chars"] += len(ev.delta.content_delta)
        return False
    if isinstance(ev, (PartEndEvent, PartStartEvent, FunctionToolCallEvent, FunctionToolResultEvent)):
        view.end_text()

    if isinstance(ev, FunctionToolCallEvent):
        tool_name, args = _extract_tool_info(ev.part)
        valid = getattr(ev, "args_valid", True)
        view.tool_call(ev.part, tool_name, args, valid)
        runlog.write("tool_call", step=step_no, tool=tool_name, args=args, args_valid=valid)
        counters["tools"] += 1

        # Živý zápis operace ihned - chrání proti ztrátě dat při pádu modelu
        target = _tool_target(args)
        if target and valid is not False:
            append_to_progress(progress_path, tool_name, target)
        return monitor.observe(tool_name, args)

    if isinstance(ev, FunctionToolResultEvent):
        tool_name = getattr(ev.part, "tool_name", "")
        content = getattr(ev.part, "content", "")
        view.tool_result(ev.part)
        runlog.write("tool_result", step=step_no, tool=tool_name, result=str(content))
        return False

    # Průběžný text / argumenty z modelu: jen počítáme znaky kvůli živému ukazateli
    delta = getattr(ev, "delta", None)
    if delta is not None:
        piece = getattr(delta, "content_delta", None) or getattr(delta, "args_delta", None) or ""
        if isinstance(piece, str):
            counters["chars"] += len(piece)
    return False


async def execute_step(
    agent: Agent,
    prompt: str,
    history: list[ModelMessage],
    trimmed_history: list[ModelMessage],
    round_limits: UsageLimits,
    progress_path: Path,
    runlog: Optional[RunLog] = None,
    step_no: int = 0,
    view: Any = None,
) -> StepOutcome:
    """
    Spustí jeden krok agenta. Zprávy z běhu se do `history` přidají VŽDY, i když běh skončí
    limitem požadavků, chybou serveru, zacyklením nebo Ctrl+C - jinak by se zahodila veškerá práce
    kroku a agent by ji příští krok dělal znovu.
    """
    runlog = runlog or RunLog(None)
    result = None
    events = None
    error: Optional[str] = None
    limit_hit = False
    tool_failure = False
    loop_desc: Optional[str] = None
    reason = "Krok byl přerušen uživatelem"
    monitor = LoopMonitor()
    counters = {"tools": 0, "chars": 0}
    started = time.monotonic()
    last_refresh = 0.0
    view = view if view is not None else ConsoleStepView()

    try:
        with view:
            async with agent.run_stream_events(
                prompt,
                message_history=trimmed_history,
                usage_limits=round_limits,
            ) as events:
                async for ev in events:
                    if isinstance(ev, AgentRunResultEvent):
                        result = ev.result
                        continue
                    try:
                        looped = handle_stream_event(ev, progress_path, runlog, monitor, step_no, counters, view)
                    except Exception as display_err:
                        # Kosmetická chyba výpisu nesmí zabít běh agenta
                        looped = False
                        console.print(f"[dim]Chyba zobrazení události: {escape(str(display_err))}[/dim]")
                    if looped:
                        loop_desc = monitor.last_description
                        error = f"Zacyklení: {loop_desc}"
                        reason = f"Krok byl přerušen kvůli zacyklení ({loop_desc})"
                        break

                    now = time.monotonic()
                    if now - last_refresh >= _STATUS_REFRESH:
                        last_refresh = now
                        view.tick(counters["tools"], counters["chars"], now - started)
    except UsageLimitExceeded as exc:
        limit_hit = True
        error = str(exc)
        reason = "Krok vyčerpal limit požadavků na model"
    except UnexpectedModelBehavior as exc:
        # Typicky "Tool 'edit_file' exceeded max retries": model opakovaně posílal neplatné argumenty
        tool_failure = True
        error = f"{type(exc).__name__}: {exc}"
        reason = "Model opakovaně volal nástroj s neplatnými argumenty"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        reason = f"Krok selhal ({type(exc).__name__})"
        runlog.write("exception", step=step_no, error=error, traceback=traceback.format_exc())
    finally:
        new_messages: list[ModelMessage] = []
        usage = (0, 0, 0)
        if result is not None:
            new_messages = list(result.new_messages())
            usage = _read_usage(result)
        elif events is not None:
            usage = _read_usage(events)
            try:
                new_messages = finalize_partial_history(events.new_messages(), reason)
            except Exception:
                new_messages = []
        history.extend(new_messages)

    seconds = time.monotonic() - started
    streamed_text = view.streamed_text
    if result is not None:
        output = getattr(result, "output", None)
        if output is None:
            output = getattr(result, "data", "")
        return StepOutcome(output=str(output), usage=usage, seconds=seconds, streamed_text=streamed_text)
    return StepOutcome(
        error=error,
        limit_hit=limit_hit,
        tool_failure=tool_failure,
        loop_detected=loop_desc,
        usage=usage,
        seconds=seconds,
        streamed_text=streamed_text,
    )


async def run_interruptible(coro: Any) -> Optional[StepOutcome]:
    """
    Spustí krok tak, že Ctrl+C zruší jen tento krok a relace pokračuje. Vrací None, pokud byl krok
    přerušen. Zprávy z přerušeného kroku uloží do historie sám `execute_step`.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(coro)
    previous_handler = signal.getsignal(signal.SIGINT)
    try:
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        installed = True
    except (NotImplementedError, RuntimeError, ValueError):
        installed = False  # mimo hlavní vlákno: Ctrl+C se obslouží jako výjimka v hlavní smyčce
    try:
        return await task
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise  # zrušení přišlo zvenčí, ne od uživatele
        return None
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGINT)
            signal.signal(signal.SIGINT, previous_handler)


def _tool_failure_hint(error: str) -> str:
    return (
        "POZOR: v předchozím kroku jsi opakovaně volal nástroj se špatnými argumenty "
        f"({error[:200]}). Před úpravou soubor znovu přečti `read_file` a zkopíruj "
        "`old_text` přesně (bez čísel řádků a tabulátoru z výpisu). Při větší změně nebo u malého "
        "souboru použij `write_file` s celým obsahem. `replacements` musí být pole objektů, ne řetězec."
    )


def _loop_hint(description: str) -> str:
    return (
        f"POZOR: v předchozím kroku ses zacyklil ({description}), proto byl krok přerušen. "
        "Nezkoušej totéž znovu: znovu si přečti aktuální stav souborů, změň přístup (jiný nástroj, "
        "jiná úprava, nebo `write_file` s celým obsahem) a zapiš si do plánu, co nefunguje."
    )


# ==============================================================================
# HLAVNÍ BĚHOVÁ SMYČKA AGENTA
# ==============================================================================

async def run_agent_loop(settings: RunSettings) -> bool:
    """Spustí autonomní běhovou smyčku programovacího agenta. Vrací True, pokud byl úkol dokončen."""
    workspace_path = settings.workspace_path.resolve()
    auto_mode = settings.auto_mode
    max_iterations = settings.max_iterations
    mode_key = "auto" if auto_mode else "chat"
    step_limit = settings.step_limit if settings.step_limit is not None else DEFAULT_STEP_LIMIT[mode_key]
    turns = settings.turns if settings.turns is not None else DEFAULT_TURNS[mode_key]
    task = settings.task

    if not workspace_path.is_dir():
        console.print(f"[bold red]Chyba: Zadaná cesta není adresář:[/bold red] {escape(str(workspace_path))}")
        return False

    default_history, default_progress = default_state_paths(workspace_path)
    history_path = settings.history_file or default_history
    progress_path = settings.progress_file or default_progress
    plan_path = state_file(workspace_path, PLAN_FILE_NAME)
    try:
        ensure_state_dir(workspace_path)
    except Exception as exc:
        console.print(f"[yellow]Nelze vytvořit stavovou složku {STATE_DIR_NAME}:[/yellow] {escape(str(exc))}")
    runlog = RunLog(state_file(workspace_path, LOG_FILE_NAME))

    # Git checkpointy jen tehdy, když workspace je v git repozitáři
    git_enabled = settings.use_git and gitsafe.repo_root(workspace_path) is not None

    # Banner
    mode_str = "[bold green]PLNĚ AUTONOMNÍ (AUTO)[/bold green]" if auto_mode else "[bold cyan]KONVERZACE[/bold cyan]"
    task_str = f"[bold white]Úkol:[/bold white] [green]{escape(task)}[/green]\n" if task else ""
    ws_note = " [dim](auto-detekován kořen projektu z podsložky)[/dim]" if settings.workspace_auto else ""
    test_str = f"[bold white]Testy:[/bold white] [yellow]{escape(settings.test_cmd)}[/yellow]\n" if settings.test_cmd else ""
    git_str = "zapnuté" if git_enabled else "vypnuté (mimo git repozitář nebo --no-git)"

    console.print(Panel(
        f"[bold white]Workspace:[/bold white] [green]{escape(str(workspace_path))}[/green]{ws_note}\n"
        f"[bold white]Režim:[/bold white] {mode_str}\n"
        f"{task_str}"
        f"{test_str}"
        f"[bold white]Model:[/bold white] [yellow]{escape(settings.model_name)}[/yellow] @ [dim]{escape(settings.endpoint)}[/dim]\n"
        f"[bold white]Limity:[/bold white] "
        + (f"Max kroků: {max_iterations}, " if auto_mode else "")
        + f"Požadavků na model v kroku: {step_limit}, Paměť: {turns} kol\n"
        f"[bold white]Git checkpointy:[/bold white] {git_str}\n"
        + ("" if auto_mode else "[dim]/help = příkazy, Alt+Enter = nový řádek, Ctrl+C = přerušit agenta, Ctrl+D = konec[/dim]"),
        title="[bold cyan]CODER[/bold cyan]",
        border_style="cyan",
    ))

    # Kontrola, že model server odpovídá (jinak by se chyba objevila až uprostřed prvního kroku)
    if settings.check_server:
        reachable, message = check_endpoint(settings.endpoint, settings.api_key, settings.model_name)
        if not reachable:
            console.print(Panel(
                Text(message + "\nZkontrolujte, že llama-server běží a že --endpoint / $AI_BASE_URL je správně."),
                title="[bold red]SERVER NEODPOVÍDÁ[/bold red]",
                border_style="red",
            ))
            if auto_mode:
                return False
        elif message != "server odpovídá":
            console.print(f"[yellow]⚠ {escape(message)}[/yellow]")

    # --- zpětná vazba pro nebezpečné příkazy ---
    def on_denied(command: str, reason: str) -> None:
        first = (command.strip().splitlines() or [""])[0][:90]
        console.print(f"  [bold yellow]🛡 Zablokován nebezpečný příkaz:[/bold yellow] {escape(first)} [dim]({escape(reason)})[/dim]")
        runlog.write("denied_command", command=command, reason=reason)

    async def confirm_dangerous(command: str, reason: str) -> bool:
        if auto_mode or not sys.stdin.isatty():
            return False
        status = ui_state.status
        if status is not None:
            status.stop()
        try:
            console.print(Panel(
                Text(command),
                title=f"[bold red]NEBEZPEČNÝ PŘÍKAZ: {escape(reason)}[/bold red]",
                border_style="red",
            ))
            return await ask_yes_no("Povolit tento příkaz?")
        finally:
            if status is not None:
                status.start()

    # Režim se může během relace měnit (/auto), agent se na něj ptá před každým požadavkem
    autonomous_step = auto_mode

    agent = create_generic_agent(
        workspace_path,
        settings.endpoint,
        settings.api_key,
        settings.model_name,
        progress_path,
        plan_file=plan_path,
        allow_dangerous=settings.allow_dangerous,
        confirm=confirm_dangerous,
        on_denied=on_denied,
        keep_recent=settings.keep_recent,
        result_chars=settings.result_chars,
        is_autonomous=lambda: autonomous_step,
    )

    # Historie z disku může končit nedokončeným krokem (např. po pádu) - opravíme ji
    history: list[ModelMessage] = finalize_partial_history(
        load_history_from_disk(history_path), "Předchozí relace byla ukončena uprostřed kroku"
    )
    if history:
        restart_hint = "" if auto_mode else " Novou konverzaci začnete příkazem /clear."
        console.print(f"[dim]Načtena existující historie: {len(history)} zpráv z {escape(history_path.name)}.{restart_hint}[/dim]")

    round_limits = UsageLimits(request_limit=step_limit)
    step_counter = 1
    auto_remaining = max_iterations if auto_mode else 0
    pending_task = task  # zadání se odešle vždy jako první krok (i v interaktivním režimu)
    hints: list[str] = []  # upozornění pro model, která se přidají k promptu dalšího kroku
    consecutive_problems = 0
    completion_rejections = 0
    tested_write_count = analyze_activity(history).write_count  # zápisy, které už harness otestoval
    completed = False
    can_continue = False  # předchozí krok nedoběhl: Enter na prázdném řádku v něm pokračuje
    chat_input = ChatInput(state_file(workspace_path, INPUT_HISTORY_FILE_NAME))

    # Limit kroků platí jen pro autonomní běh, konverzace končí, až když ji ukončí uživatel
    while not auto_mode or step_counter <= max_iterations:
        try:
            # 1. Zadaný úkol, autonomní pokračování, nebo uživatelský vstup
            autonomous_step = auto_mode or auto_remaining > 0
            if pending_task is not None:
                prompt = pending_task
                pending_task = None
                if auto_remaining > 0:
                    auto_remaining -= 1
                console.print(f"\n[bold magenta]🤖 Krok #{step_counter}: zadaný úkol[/bold magenta]")
            elif auto_remaining > 0:
                prompt = CONTINUE_PROMPT_AUTO
                auto_remaining -= 1
                console.print(
                    f"\n[bold magenta]🤖 Autonomní krok #{step_counter}[/bold magenta] "
                    f"[dim](zbývá {auto_remaining} auto-kroků)[/dim]"
                )
            else:
                try:
                    user_input = (await chat_input.read(step_counter)).strip()
                except EOFError:
                    console.print("[yellow]Konec vstupu. Stav je bezpečně uložen na disk.[/yellow]")
                    return completed

                if not user_input and not can_continue:
                    continue

                command, argument = parse_command(user_input) or (None, "")

                if command == "unknown":
                    console.print(f"[yellow]Neznámý příkaz /{escape(argument)}. Seznam příkazů: /help[/yellow]")
                    continue

                if command == "exit":
                    console.print("[yellow]Ukončuji relaci. Stav je bezpečně uložen na disk.[/yellow]")
                    return completed

                if command == "clear":
                    history = []
                    pending_task = None
                    hints.clear()
                    for path in (history_path, progress_path, plan_path):
                        if path.exists():
                            path.unlink()
                    console.print("[green]Historie, PROGRESS.md i plán byly smazány. Začínáme s čistým štítem.[/green]")
                    step_counter = 1
                    tested_write_count = 0
                    can_continue = False
                    continue

                if command == "status":
                    if progress_path.exists():
                        # Text(...) místo řetězce: jinak by Rich zpracoval "[x]" jako značku a zmizelo by
                        console.print(Panel(
                            Text(progress_path.read_text(encoding="utf-8")),
                            title="[bold green]PROGRESS.md[/bold green]",
                            border_style="green",
                        ))
                    else:
                        console.print("[dim]PROGRESS.md zatím neexistuje.[/dim]")
                    continue

                if command == "plan":
                    plan_text = read_plan(plan_path, max_chars=20000)
                    if plan_text:
                        console.print(Panel(Text(plan_text), title="[bold green]PLAN.md[/bold green]", border_style="green"))
                    else:
                        console.print("[dim]Plán zatím neexistuje (agent ho vytvoří sám).[/dim]")
                    continue

                if command == "diff":
                    show_git_diff(workspace_path)
                    continue

                if command == "checkpoints":
                    print_checkpoints(gitsafe.list_checkpoints(workspace_path))
                    continue

                if command == "undo":
                    items = gitsafe.list_checkpoints(workspace_path)
                    if not items:
                        console.print("[dim]Není k dispozici žádný checkpoint.[/dim]")
                        continue
                    chosen = items[-1]
                    if argument.isdigit():
                        matches = [i for i in items if i["step"] == int(argument)]
                        if not matches:
                            console.print(f"[yellow]Checkpoint kroku #{escape(argument)} neexistuje (příkaz /checkpoints).[/yellow]")
                            continue
                        chosen = matches[-1]
                    try:
                        changes = gitsafe.describe_changes(workspace_path, chosen)
                    except gitsafe.GitError as exc:
                        console.print(f"[bold red]Undo nelze provést:[/bold red] {escape(str(exc))}")
                        continue
                    if not changes:
                        console.print("[dim]Od tohoto checkpointu se soubory nezměnily; vracím jen historii konverzace.[/dim]")
                    else:
                        shown = "\n".join(f"  {action}: {path}" for action, path in changes[:25])
                        more = f"\n  ... a dalších {len(changes) - 25}" if len(changes) > 25 else ""
                        console.print(Panel(
                            Text(shown + more),
                            title=f"[bold yellow]UNDO: návrat do stavu před krokem #{chosen['step']}[/bold yellow]",
                            border_style="yellow",
                        ))
                    answer = Prompt.ask("[yellow]Provést? Změny z těchto kroků budou ztraceny (a/n)[/yellow]", default="n")
                    if answer.strip().lower() not in ("a", "ano", "y", "yes"):
                        console.print("[dim]Zrušeno.[/dim]")
                        continue
                    try:
                        counts = gitsafe.restore_checkpoint(workspace_path, chosen)
                    except gitsafe.GitError as exc:
                        console.print(f"[bold red]Undo selhalo:[/bold red] {escape(str(exc))}")
                        continue
                    gitsafe.drop_checkpoints_from(workspace_path, chosen)
                    history = history[: int(chosen.get("history_len", 0))]
                    save_history_to_disk(history, history_path)
                    rebuild_progress(history, progress_path)
                    hints.clear()
                    step_counter = int(chosen["step"])
                    tested_write_count = analyze_activity(history).write_count
                    can_continue = False
                    runlog.write("undo", to_step=chosen["step"], **counts)
                    console.print(
                        f"[green]Hotovo: obnoveno {counts['restored']} souborů, smazáno {counts['deleted']}. "
                        f"Konverzace vrácena před krok #{chosen['step']}.[/green]"
                    )
                    continue

                if command == "test":
                    if argument:
                        run_direct_command(workspace_path, argument)
                    else:
                        console.print("[yellow]Zadejte příkaz, např. /test pytest -q nebo !pytest -q[/yellow]")
                    continue

                if command == "auto":
                    auto_remaining = int(argument) if argument.isdigit() else max_iterations
                    console.print(f"[bold green]Přepnuto do autonomního režimu na {auto_remaining} kroků.[/bold green]")
                    continue

                if command == "help":
                    console.print(Panel(help_text(), title="[bold cyan]Nápověda k příkazům[/bold cyan]", border_style="cyan"))
                    continue

                prompt = user_input if user_input else CONTINUE_PROMPT_INTERACTIVE

            if hints:
                prompt = prompt + "\n\n" + "\n\n".join(hints)
                hints.clear()

            # 2. Git checkpoint stavu PŘED krokem (undo se vrací právě sem)
            if git_enabled:
                try:
                    checkpoint = gitsafe.create_checkpoint(workspace_path, step_counter, len(history), prompt[:80])
                    console.print(f"[dim]  Checkpoint před krokem #{step_counter}: {checkpoint['commit'][:10]}[/dim]")
                except gitsafe.GitError as exc:
                    git_enabled = False
                    console.print(f"[yellow]⚠ Checkpoint se nepodařilo vytvořit, další už nebudou: {escape(str(exc))}[/yellow]")

            # 3. Bezpečné ořezání historie pro ochranu VRAM / kontextového okna (zkracování starých
            #    výsledků nástrojů dělá capability ProcessHistory přímo před každým požadavkem na model)
            #    V konverzaci se první zpráva nedrží napořád: nemusí už s aktuální prací souviset.
            trimmed_history = safe_trim_history(history, keep_turns=turns, preserve_initial=autonomous_step)

            # 4. Spuštění agenta s okamžitým živým reportováním prováděných akcí
            console.print(
                f"\n[bold magenta]🤖 Agent zahájil práci na kroku #{step_counter}...[/bold magenta] "
                f"[dim](analyzuje kód a volá nástroje)[/dim]"
            )
            runlog.write("step_start", step=step_counter, prompt=prompt)
            step = execute_step(
                agent, prompt, history, trimmed_history, round_limits, progress_path, runlog, step_counter
            )
            # Autonomní běh Ctrl+C ukončí celý (skripty, CI), v konverzaci přeruší jen tento krok
            if auto_mode:
                outcome = await step
            else:
                outcome = await run_interruptible(step) or StepOutcome(
                    error="Přerušeno uživatelem", interrupted=True
                )

            # 5. Uložení stavu na disk a aktualizace PROGRESS.md (Záchranné uložení se provede VŽDY)
            save_history_to_disk(history, history_path)
            auto_update_progress_from_messages(history, progress_path)
            requests, tokens_in, tokens_out = outcome.usage
            if requests:
                print_step_usage(requests, tokens_in, tokens_out, outcome.seconds)
            runlog.write(
                "step_end",
                step=step_counter,
                ok=outcome.error is None,
                error=outcome.error,
                loop=outcome.loop_detected,
                usage=list(outcome.usage),
                seconds=round(outcome.seconds, 1),
            )

            # 6. Vyhodnocení výsledku
            problem = False
            step_accepted = False
            can_continue = outcome.error is not None
            if outcome.interrupted:
                auto_remaining = 0
                console.print(
                    "[yellow]Přerušeno. Dosavadní práce je uložena; napište další zprávu, "
                    "nebo Enterem pokračujte.[/yellow]"
                )

            elif outcome.error is None:
                output_text = outcome.output or ""
                visible_text = strip_completion_marker(output_text)
                # Text, který běžel živě na obrazovce, se podruhé nevypisuje
                if visible_text and outcome.streamed_text.strip() != output_text.strip():
                    console.print(Markdown(visible_text))
                elif not visible_text and not autonomous_step:
                    console.print("[yellow]Model skončil bez textové odpovědi. Zkuste dotaz zopakovat nebo upřesnit.[/yellow]")
                consecutive_problems = 0

                # V konverzaci tah končí odpovědí; značku a její bránu má jen autonomní běh
                if autonomous_step and is_task_completed(output_text):
                    accepted = True

                    if settings.test_cmd:
                        with console.status("[bold green]Spouštím testy...[/bold green]", spinner="dots"):
                            test_result = run_test_command(workspace_path, settings.test_cmd, settings.test_timeout)
                        tested_write_count = analyze_activity(history).write_count
                        color = "green" if test_result.ok else "red"
                        console.print(Panel(
                            Text(test_result.output.strip()[-2500:] or "(bez výstupu)"),
                            title=f"[{color}]Testy harnessu: {escape(settings.test_cmd)} -> kód {test_result.returncode}[/{color}]",
                            border_style=color,
                        ))
                        if not test_result.ok:
                            accepted = False
                            completion_rejections += 1
                            hints.append(
                                "TASK_COMPLETED NEBYLO PŘIJATO: testy spuštěné harnessem selhaly. "
                                "Oprav příčinu a nepiš TASK_COMPLETED, dokud neprojdou.\n"
                                + format_test_report(test_result)
                            )
                            if completion_rejections > MAX_TEST_REJECTIONS:
                                console.print(Panel(
                                    f"Agent {completion_rejections}× prohlásil úkol za hotový, ale testy dál selhávají. Běh zastaven.",
                                    title="[bold red]TESTY STÁLE SELHÁVAJÍ[/bold red]",
                                    border_style="red",
                                ))
                                return False
                    else:
                        hint = completion_hint_without_tests(analyze_activity(history))
                        if hint:
                            if completion_rejections < MAX_GATE_REJECTIONS:
                                accepted = False
                                completion_rejections += 1
                                hints.append(hint)
                            else:
                                console.print(Panel(
                                    "Agent opakovaně prohlásil úkol za hotový bez rozpoznaného ověření (testy/linter). "
                                    "Dokončení se přijímá, ale výsledek si ověřte sami (nebo použijte --test-cmd).",
                                    title="[bold yellow]DOKONČENO BEZ OVĚŘENÍ[/bold yellow]",
                                    border_style="yellow",
                                ))

                    if accepted:
                        console.print(Panel(
                            "[bold green]🎉 ÚKOL BYL ÚSPĚŠNĚ DOKONČEN A OVĚŘEN! (TASK_COMPLETED)[/bold green]\n"
                            f"Celkem kroků: {step_counter}\n"
                            f"Aktualizovaný stav: {escape(str(progress_path))}",
                            title="[bold green]DOKONČENO[/bold green]",
                            border_style="green",
                        ))
                        completed = True
                        step_accepted = True
                        if auto_mode:
                            return True
                        # V interaktivním kokpitu dokončení úkolu jen zastaví autonomní běh
                        auto_remaining = 0
                    else:
                        console.print(
                            "[yellow]⚠ TASK_COMPLETED nebylo přijato, agent dostane pokyn pokračovat.[/yellow]"
                        )

            elif outcome.loop_detected:
                problem = True
                consecutive_problems += 1
                console.print(Panel(
                    Text(
                        f"Model se zacyklil: {outcome.loop_detected}.\n"
                        "Krok byl přerušen, dosavadní práce je uložena. Další krok dostane pokyn změnit přístup."
                    ),
                    title=f"[bold yellow]ZACYKLENÍ (krok #{step_counter})[/bold yellow]",
                    border_style="yellow",
                ))
                hints.append(_loop_hint(outcome.loop_detected))

            elif outcome.tool_failure:
                problem = True
                consecutive_problems += 1
                give_up = consecutive_problems >= MAX_CONSECUTIVE_PROBLEMS
                console.print(Panel(
                    Text(
                        (outcome.error or "")
                        + "\n\nModel opakovaně volal nástroj s neplatnými argumenty. Dosavadní práce je uložena."
                        + (
                            f"\nOpakovaná selhání ({consecutive_problems}×) - běh zastaven."
                            if give_up
                            else "\nDalší krok naváže a dostane nápovědu ke správnému volání nástrojů."
                        )
                    ),
                    title=f"[bold yellow]SELHÁNÍ NÁSTROJE (krok #{step_counter})[/bold yellow]",
                    border_style="yellow",
                ))
                hints.append(_tool_failure_hint(outcome.error or ""))

            elif outcome.limit_hit:
                # Limit požadavků na krok není chyba: práce je uložena, další krok na ni naváže
                console.print(Panel(
                    f"Krok vyčerpal limit {step_limit} požadavků na model.\n"
                    "Dosavadní práce je uložena v historii a PROGRESS.md, další krok na ni naváže.",
                    title=f"[bold yellow]LIMIT POŽADAVKŮ (krok #{step_counter})[/bold yellow]",
                    border_style="yellow",
                ))

            else:
                console.print(Panel(
                    Text(outcome.error or "Neznámá chyba"),
                    title=f"[bold red]CHYBA KROKU #{step_counter}[/bold red]",
                    border_style="red",
                ))
                console.print("[dim]Dosavadní práce kroku je uložena. Autonomní běh byl zastaven.[/dim]")
                auto_remaining = 0
                if auto_mode:
                    return False

            if problem and consecutive_problems >= MAX_CONSECUTIVE_PROBLEMS:
                console.print(Panel(
                    f"{consecutive_problems} kroky po sobě skončily problémem (zacyklení / neplatné volání nástrojů). Běh zastaven.",
                    title="[bold red]BĚH ZASTAVEN[/bold red]",
                    border_style="red",
                ))
                auto_remaining = 0
                if auto_mode:
                    return False

            # 7. Testy harnessu po kroku, který měnil soubory (výsledek uvidí model v dalším kroku)
            if settings.test_cmd and not step_accepted and not outcome.interrupted:
                write_count = analyze_activity(history).write_count
                if write_count > tested_write_count:
                    with console.status("[bold green]Spouštím testy...[/bold green]", spinner="dots"):
                        test_result = run_test_command(workspace_path, settings.test_cmd, settings.test_timeout)
                    tested_write_count = write_count
                    color = "green" if test_result.ok else "red"
                    console.print(
                        f"[{color}]  Testy harnessu po kroku #{step_counter}: "
                        f"{'PROŠLY' if test_result.ok else 'SELHALY'} (kód {test_result.returncode})[/{color}]"
                    )
                    runlog.write("harness_tests", step=step_counter, ok=test_result.ok, code=test_result.returncode)
                    hints.append(format_test_report(test_result))

            step_counter += 1

        except (KeyboardInterrupt, asyncio.CancelledError) as exc:
            console.print("\n[yellow]Přerušeno uživatelem (Ctrl+C). Ukládám stav...[/yellow]")
            save_history_to_disk(history, history_path)
            auto_update_progress_from_messages(history, progress_path)
            if auto_mode or not isinstance(exc, KeyboardInterrupt):
                raise
            # V konverzaci (např. Ctrl+C během testů harnessu nebo dotazu) se jen vrátíme k zadávání
            auto_remaining = 0

        except Exception as exc:
            console.print(f"\n[bold red]❌ Chyba běhu (Neočekávaná výjimka):[/bold red] {escape(str(exc))}")
            runlog.write("exception", step=step_counter, error=str(exc), traceback=traceback.format_exc())
            auto_remaining = 0

            # Záchranné uložení při pádu chyby (FAILSAFE)
            save_history_to_disk(history, history_path)
            auto_update_progress_from_messages(history, progress_path)

            if not sys.stdin.isatty() or auto_mode:
                break
            try:
                continue_after_err = Prompt.ask("[yellow]Chcete pokračovat v relaci i přes chybu? (a/n)[/yellow]", default="n")
                if continue_after_err.lower() not in ("a", "ano", "y", "yes"):
                    break
            except Exception:
                break

    if auto_mode and step_counter > max_iterations:
        console.print(Panel(
            f"[bold yellow]⚠️ Dosažen maximální limit {max_iterations} kroků.[/bold yellow]\n"
            "Stav je uložen na disk. Pro pokračování spusťte agenta znovu nebo zvyšte --max-iterations.",
            title="[bold yellow]LIMIT KROKŮ[/bold yellow]",
            border_style="yellow",
        ))

    return completed
