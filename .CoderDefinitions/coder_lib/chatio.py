"""Konverzační vstup a výstup: příkazy kokpitu, řádkový editor a živé vykreslování odpovědi modelu."""

import re
import sys
from pathlib import Path
from typing import Any, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape

from .common import console

COMPLETION_MARKER = "TASK_COMPLETED"

COMMANDS: dict[str, str] = {
    "help": "Zobrazí tuto nápovědu",
    "status": "Zobrazí PROGRESS.md (co agent četl, měnil a spouštěl)",
    "plan": "Zobrazí plán, který si agent vede (PLAN.md)",
    "diff": "Zobrazí git status a diff",
    "test": "/test <příkaz>: spustí příkaz v shellu (totéž co !<příkaz>)",
    "auto": "/auto [N]: autonomní režim na N kroků nebo do dokončení",
    "checkpoints": "Seznam git checkpointů (stav před každým krokem)",
    "undo": "/undo [N]: vrátí soubory i konverzaci před poslední (nebo N-tý) krok",
    "clear": "Smaže historii, PROGRESS.md a plán",
    "exit": "Ukončí program",
}

_ALIASES = {"quit": "exit", "q": "exit", "progress": "status"}
# Bez lomítka platí jen tato přesná slova, cokoli delšího je zpráva pro model
# ("test funkce add je špatně" se nesmí spustit v shellu, "automaticky..." nesmí zapnout autonomii).
_BARE_WORDS = {"help", "status", "plan", "diff", "checkpoints", "clear", "exit", "quit", "q", "progress"}
_BARE_WITH_NUMBER = re.compile(r"^(auto|undo)(?:\s+(\d+))?$", re.IGNORECASE)


def parse_command(text: str) -> Optional[tuple[str, str]]:
    """Vrátí (příkaz, argument), nebo None, pokud je vstup zprávou pro model."""
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("!"):
        return "test", stripped[1:].strip()
    if stripped.startswith("/"):
        pieces = stripped[1:].split(None, 1)
        name = pieces[0].lower() if pieces else ""
        # Cesta k souboru ("/app/x.py je rozbitý") není příkaz
        if not name or "/" in name:
            return None
        name = _ALIASES.get(name, name)
        if name not in COMMANDS:
            return "unknown", pieces[0]
        return name, pieces[1].strip() if len(pieces) > 1 else ""

    lowered = stripped.lower()
    if lowered in _BARE_WORDS:
        return _ALIASES.get(lowered, lowered), ""
    match = _BARE_WITH_NUMBER.match(stripped)
    if match:
        return match.group(1).lower(), match.group(2) or ""
    return None


def strip_completion_marker(text: str) -> str:
    return text.replace(COMPLETION_MARKER, "").strip()


class _SlashCompleter(Completer):
    """Doplňuje příkazy jen na začátku vstupu, běžný text nechává na pokoji."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        for name, description in COMMANDS.items():
            if name.startswith(text[1:].lower()):
                yield Completion(f"/{name}", start_position=-len(text), display_meta=description)


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    # "\n" (c-j) odesílá stejně jako Enter: posílají ho skripty a terminál jím předá i řádky napsané
    # během práce agenta, ty se tak odešlou jako samostatné zprávy, až bude agent hotový.
    @bindings.add("enter")
    @bindings.add("c-j")
    def _submit(event) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    @bindings.add("c-c")
    def _clear_or_quit(event) -> None:
        if event.current_buffer.text:
            event.current_buffer.reset()
        else:
            event.app.exit(exception=KeyboardInterrupt())

    return bindings


class ChatInput:
    """Čtení zpráv uživatele: řádkový editor v terminálu, obyčejné čtení řádků z roury (skripty, testy)."""

    def __init__(self, history_path: Path):
        self._history_path = history_path
        self._session: Optional[PromptSession] = None
        self._quit_armed = False
        self.is_terminal = sys.stdin.isatty() and sys.stdout.isatty()

    def _get_session(self) -> PromptSession:
        if self._session is None:
            self._session = PromptSession(
                history=FileHistory(str(self._history_path)),
                completer=_SlashCompleter(),
                complete_while_typing=True,
                key_bindings=_key_bindings(),
                multiline=True,  # vložený víceřádkový text zůstane jednou zprávou; Enter odesílá
                prompt_continuation="  ",
                style=Style.from_dict({"prompt": "ansicyan bold"}),
            )
        return self._session

    async def read(self, step: int) -> str:
        """Přečte jednu zprávu. Konec vstupu (Ctrl+D, dvakrát Ctrl+C) oznámí výjimkou EOFError."""
        label = f"Krok #{step} ❯ "
        if not self.is_terminal:
            return console.input(f"\n[bold cyan]{label}[/bold cyan]")

        console.print()
        while True:
            try:
                # handle_sigint=False: v editoru je Ctrl+C klávesa a obsluhuje ho _clear_or_quit
                text = await self._get_session().prompt_async([("class:prompt", label)], handle_sigint=False)
            except KeyboardInterrupt:
                if self._quit_armed:
                    raise EOFError from None
                self._quit_armed = True
                console.print("[dim]Dalším Ctrl+C na prázdném řádku se program ukončí.[/dim]")
                continue
            self._quit_armed = False
            return text


async def ask_yes_no(question: str) -> bool:
    """Dotaz a/n v průběhu kroku. Na rozdíl od input() neblokuje smyčku událostí, Ctrl+C znamená ne."""
    session: PromptSession = PromptSession(key_bindings=_key_bindings(), multiline=True)
    try:
        answer = await session.prompt_async(f"{question} (a/n): ", handle_sigint=False)
    except (KeyboardInterrupt, EOFError):
        return False
    return answer.strip().lower() in ("a", "ano", "y", "yes")


class TextStream:
    """
    Vykresluje text modelu průběžně jako Markdown. Rich umí jen jeden živý displej,
    proto se po dobu psaní textu pozastaví spinner.
    """

    def __init__(self, status: Any):
        self._status = status
        self._live: Optional[Live] = None
        self._buffer = ""
        self.last_text = ""

    def feed(self, piece: str) -> None:
        if not piece:
            return
        self._buffer += piece
        shown = strip_completion_marker(self._buffer)
        if not shown:
            return
        if self._live is None:
            self._status.stop()
            self._live = Live(Markdown(shown), console=console, refresh_per_second=6, vertical_overflow="ellipsis")
            self._live.start()
        else:
            self._live.update(Markdown(shown))

    def finish(self) -> None:
        """Ukončí aktuální blok textu (přišlo volání nástroje, konec odpovědi nebo přerušení)."""
        if self._buffer:
            self.last_text = self._buffer
            self._buffer = ""
        if self._live is not None:
            try:
                self._live.stop()
            except Exception as exc:
                console.print(f"[dim]Chyba zobrazení textu: {escape(str(exc))}[/dim]")
            self._live = None
            self._status.start()


def help_text() -> str:
    lines = [f"• [bold cyan]/{name}[/bold cyan]: {escape(text)}" for name, text in COMMANDS.items()]
    lines += [
        "• [bold cyan]!<příkaz>[/bold cyan]: Spustí příkaz přímo v shellu",
        "",
        "[bold]Enter[/bold] odešle zprávu, [bold]Alt+Enter[/bold] vloží nový řádek.",
        "[bold]Ctrl+C[/bold] přeruší práci agenta a vrátí se k zadávání (dosavadní práce zůstane), "
        "[bold]Ctrl+D[/bold] ukončí program.",
        "[bold]Enter[/bold] na prázdném řádku po přerušeném kroku v práci pokračuje.",
    ]
    return "\n".join(lines)
