"""Výpisy do konzole, pomocné příkazy kokpitu a kontrola dostupnosti serveru."""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from pydantic_ai.messages import ModelMessage
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .common import _extract_tool_info, _is_tool_call, _tool_target, console


def print_tool_audit(new_messages: list[ModelMessage]) -> None:
    """Kompaktní audit reálně spuštěných nástrojů s jejich cíli."""
    for msg in new_messages:
        for part in getattr(msg, "parts", []):
            if not _is_tool_call(part):
                continue
            tool_name, args = _extract_tool_info(part)
            target = (
                _tool_target(args)
                or args.get("command")
                or args.get("pattern")
                or args.get("task")
                or ""
            )
            target_str = (str(target).strip().splitlines() or [""])[0][:90]
            console.print(
                f"  [cyan]⚙️ [bold]{escape(tool_name)}[/bold][/cyan] [dim]->[/dim] [yellow]{escape(target_str)}[/yellow]"
            )


def print_live_tool_call(tool_name: str, args: dict[str, Any], args_valid: Optional[bool] = True) -> None:
    """Okamžitě a přehledně vypíše prováděné volání nástroje na konzoli."""
    # Všechno, co pochází od modelu nebo ze souborového systému, se escapuje:
    # texty jako "[/usr/lib]" nebo regex "[/a-z]+" by jinak Rich bral za značky a spadl.
    path = escape(str(_tool_target(args) or "")) or None
    cmd = args.get("command")
    pattern = args.get("pattern")
    task = args.get("task")

    def first_line(value: Any, limit: int) -> str:
        return escape((str(value).strip().splitlines() or [""])[0][:limit])

    if args_valid is False:
        shown = escape(json.dumps(args, ensure_ascii=False, default=str)[:160])
        console.print(
            f"  [bold red]⚠ Neplatné argumenty nástroje {escape(tool_name)}[/bold red] [dim](model nedodržel schéma)[/dim]: {shown}"
        )
        return

    if tool_name == "read_file":
        console.print(f"  [bold cyan]📖 Čtu soubor:[/bold cyan] [yellow]{path}[/yellow]")
    elif tool_name == "write_file":
        content = args.get("content")
        size = f" [dim]({len(content.splitlines())} řádků)[/dim]" if isinstance(content, str) else ""
        console.print(f"  [bold green]✍️  Zapisuji soubor:[/bold green] [yellow]{path}[/yellow]{size}")
    elif tool_name == "edit_file":
        console.print(f"  [bold yellow]✏️  Upravuji soubor:[/bold yellow] [yellow]{path}[/yellow]")
        print_edit_preview(args)
    elif tool_name == "list_files":
        console.print(f"  [bold blue]📂 Procházím složku:[/bold blue] [yellow]{path or '.'}[/yellow]")
    elif tool_name == "grep":
        console.print(
            f"  [bold magenta]🔍 Hledám v kódu:[/bold magenta] [yellow]'{escape(str(pattern))}'[/yellow] "
            f"v [yellow]{path or '.'}[/yellow]"
        )
    elif tool_name == "shell":
        console.print(f"  [bold red]⚡ Spouštím shell:[/bold red] [bold white]{first_line(cmd, 95)}[/bold white]")
    elif tool_name == "delegate_task":
        console.print(f"  [bold magenta]🤖 Deleguji podúkol:[/bold magenta] [white]{first_line(task, 95)}[/white]")
    else:
        target_str = escape(str(path or cmd or pattern or task or args)[:85])
        console.print(f"  [cyan]⚙️  Nástroj [bold]{escape(tool_name)}[/bold]:[/cyan] [dim]{target_str}[/dim]")


MAX_PREVIEW_LINES = 12


def print_edit_preview(args: dict[str, Any]) -> None:
    """Pod volání edit_file vypíše, co se v souboru mění (odebrané a přidané řádky)."""
    pairs = [args] + [item for item in args.get("replacements") or [] if isinstance(item, dict)]
    body = Text()
    shown = hidden = 0
    for pair in pairs:
        for key, sign, style in (("old_text", "-", "red"), ("new_text", "+", "green")):
            value = pair.get(key)
            if not isinstance(value, str):
                continue
            for line in value.splitlines():
                if shown < MAX_PREVIEW_LINES:
                    body.append(f"    {sign} {line[:140]}\n", style=style)
                    shown += 1
                else:
                    hidden += 1
    if hidden:
        body.append(f"    ... a dalších {hidden} řádků\n", style="dim")
    if shown:
        console.print(body, end="", soft_wrap=True)


def print_live_tool_result(tool_name: str, content: Any) -> None:
    """Okamžitě vypíše stručné shrnutí výsledku dokončeného nástroje na konzoli."""
    text = str(content or "").strip()
    if not text:
        return
    lines = text.splitlines()
    if len(lines) == 1:
        summary = lines[0][:85]
    else:
        summary = f"{lines[0][:65]}... (+ dalších {len(lines) - 1} řádků)"

    color = "red" if "Traceback" in text or "error" in text.lower() else "dim"
    console.print(f"  [{color}]↳ výsledek ({escape(tool_name)}): {escape(summary)}[/{color}]")


def resolve_workspace(explicit_path: Optional[str] = None) -> tuple[Path, bool]:
    """Inteligentně určí kořenový adresář projektu."""
    if explicit_path and explicit_path not in (".", ""):
        return Path(explicit_path).resolve(), False

    cwd = Path.cwd().resolve()

    if (cwd / "src").is_dir() or (cwd / "Dockerfile").exists() or (cwd / ".git").is_dir():
        return cwd, False

    if (cwd.parent / "src").is_dir() or (cwd.parent / "Dockerfile").exists():
        return cwd.parent, True

    script_root = Path(__file__).resolve().parent.parent
    if (script_root / "src").is_dir() or (script_root / "Dockerfile").exists():
        return script_root, True

    return cwd, False


def show_git_diff(workspace_path: Path) -> None:
    """Zobrazí git status a diff v daném workspace."""
    try:
        status_proc = subprocess.run(
            ["git", "status", "-s"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if status_proc.returncode != 0:
            console.print(
                f"[dim]Git není v tomto adresáři inicializován nebo selhal: {escape(status_proc.stderr.strip())}[/dim]"
            )
            return

        diff_proc = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=10,
        )

        status_text = status_proc.stdout.strip() or "Žádné změny (clean workspace)"
        diff_text = diff_proc.stdout.strip() or "Žádný souborový diff"

        body = Text()
        body.append("Git Status:\n", style="bold")
        body.append(status_text + "\n\n")
        body.append("Git Diff Stat:\n", style="bold")
        body.append(diff_text)
        console.print(Panel(body, title="[bold cyan]GIT STAV WORKSPACE[/bold cyan]", border_style="cyan"))
    except Exception as exc:
        console.print(f"[yellow]Nelze načíst git stav:[/yellow] {escape(str(exc))}")


def run_direct_command(workspace_path: Path, command: str) -> None:
    """Spustí přímý příkaz (např. test) ve workspace a zobrazí výstup."""
    console.print(f"[bold dim]Spouštím:[/bold dim] [cyan]{escape(command)}[/cyan]")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = (proc.stdout + proc.stderr).strip()
        color = "green" if proc.returncode == 0 else "red"
        console.print(Panel(
            Syntax(out or "[Žádný výstup]", "bash", theme="monokai", line_numbers=False),
            title=f"[{color}]Kód: {proc.returncode}[/{color}]",
            border_style=color,
        ))
    except Exception as exc:
        console.print(f"[bold red]Chyba při spuštění příkazu:[/bold red] {escape(str(exc))}")


def print_step_usage(requests: int, input_tokens: int, output_tokens: int, seconds: float) -> None:
    """Jednořádkové shrnutí spotřeby kroku."""
    console.print(
        f"[dim]  Spotřeba kroku: {requests} požadavků na model, {input_tokens} vstupních / "
        f"{output_tokens} výstupních tokenů, {seconds:.0f} s[/dim]"
    )


def print_checkpoints(items: list[dict[str, Any]]) -> None:
    """Vypíše seznam git checkpointů."""
    if not items:
        console.print("[dim]Žádné checkpointy (workspace není v git repozitáři, nebo ještě žádný krok neproběhl).[/dim]")
        return
    body = Text()
    for item in items:
        body.append(f"krok #{item['step']:<3} {item['time']}  {item['commit'][:10]}  {item.get('label', '')}\n")
    console.print(Panel(body, title="[bold cyan]CHECKPOINTY (stav PŘED krokem)[/bold cyan]", border_style="cyan"))


def check_endpoint(endpoint: str, api_key: str, model_name: str, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Zeptá se serveru na /models. Vrací (dosažitelný, zpráva). Neexistující model je jen varování,
    protože llama-server název modelu většinou ignoruje.
    """
    url = endpoint.rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # Server odpovídá, jen třeba nemá /models (nebo vyžaduje jiný klíč): je dosažitelný
        return True, f"server odpovídá (HTTP {exc.code} na /models)"
    except Exception as exc:
        return False, f"server na {endpoint} neodpovídá ({type(exc).__name__}: {exc})"

    try:
        ids = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
    except Exception:
        ids = []
    if ids and model_name not in ids:
        shown = ", ".join(ids[:5])
        return True, f"server běží, ale model '{model_name}' v seznamu není (dostupné: {shown})"
    return True, "server odpovídá"
