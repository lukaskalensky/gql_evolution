"""Průběžně udržovaný přehled stavu repozitáře (PROGRESS.md) a plán modelu (PLAN.md)."""

import re
from pathlib import Path
from typing import Optional

from pydantic_ai.messages import ModelMessage
from rich.markup import escape

from .common import (
    PLAN_FILE_NAME,
    STATE_DIR_NAME,
    _extract_tool_info,
    _is_tool_call,
    _tool_target,
    console,
)

PROGRESS_TITLE = "# AUTOMATICKÝ PŘEHLED STAVU REPOZITÁŘE (PROGRESS)"
_PROGRESS_AUTO_HEADERS = (
    "## Již modifikované",
    "## Již vytvořené",
    "## Již prozkoumané",
    "## Prozkoumané",
    "## Poslední spuštěné ověřovací",
    "## Provedené příkazy",
)
# Řádek typu:  - [x] Přečteno: `cesta`   (cíl je vše mezi první a poslední zpětnou uvozovkou)
_PROGRESS_ENTRY_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s*([^:`]+?)\s*:\s*`(.+)`\s*$")
_MAX_PROGRESS_COMMANDS = 10


def is_state_path(target: str) -> bool:
    """True pro cesty ve stavové složce agenta (.cmd_coder/...): ty se do PROGRESS.md nezapisují."""
    normalized = target.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized == STATE_DIR_NAME or normalized.startswith(STATE_DIR_NAME + "/")


def append_to_progress(progress_file: Path, tool_name: str, target: str) -> None:
    """Okamžitě připíše dotčený soubor do PROGRESS.md během živého streamu."""
    if not target or is_state_path(target):
        return
    try:
        if progress_file.exists():
            content = progress_file.read_text(encoding="utf-8")
        else:
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            content = PROGRESS_TITLE + "\n\n"
            progress_file.write_text(content, encoding="utf-8")

        # Zabráníme vkládání duplicit
        if f"`{target}`" not in content:
            category = "Hotovo/Zapsáno" if any(k in tool_name for k in ("write", "edit", "patch", "create")) else "Přečteno"
            with open(progress_file, "a", encoding="utf-8") as f:
                f.write(f"- [x] {category}: `{target}`\n")
    except Exception as exc:
        console.print(f"[dim]Chyba živého zápisu do PROGRESS: {escape(str(exc))}[/dim]")


def parse_existing_progress(content: str) -> tuple[dict[str, None], dict[str, None], dict[str, None], str]:
    """
    Parsuje stávající PROGRESS.md. Řádky se klasifikují podle svého štítku
    (Přečteno / Hotovo/Zapsáno / Ověřeno / Příkaz), nikoliv podle toho, v jaké sekci leží
    ani podle klíčových slov v obsahu (příkaz `grep ...` není "přečtení souboru").
    Vrací uspořádané množiny (dict) kvůli zachování pořadí.
    """
    reads: dict[str, None] = {}
    writes: dict[str, None] = {}
    commands: dict[str, None] = {}
    custom_lines: list[str] = []

    in_auto_section = False
    for line in content.splitlines():
        trimmed = line.strip()

        match = _PROGRESS_ENTRY_RE.match(line)
        if match:
            tag, target = match.group(1), match.group(2)
            if any(k in tag for k in ("Přečteno", "Prozkoumáno")):
                reads[target] = None
            elif any(k in tag for k in ("Hotovo", "Zapsáno", "Modifikováno")):
                writes[target] = None
            elif any(k in tag for k in ("Příkaz", "Ověřeno")):
                commands[target] = None
            else:
                custom_lines.append(line)
            continue

        if trimmed.startswith(PROGRESS_TITLE):
            continue
        if any(trimmed.startswith(h) for h in _PROGRESS_AUTO_HEADERS):
            in_auto_section = True
            continue
        if trimmed.startswith("#"):
            in_auto_section = False
            custom_lines.append(line)
            continue
        if not in_auto_section:
            custom_lines.append(line)

    custom_text = "\n".join(custom_lines).strip()
    return reads, writes, commands, custom_text


def auto_update_progress_from_messages(messages: list[ModelMessage], progress_file: Path) -> None:
    """Hromadná revize a aktualizace PROGRESS.md po skončení kola."""
    if not messages:
        return

    existing_reads: dict[str, None] = {}
    existing_writes: dict[str, None] = {}
    existing_commands: dict[str, None] = {}
    custom_notes = ""

    if progress_file.exists():
        try:
            content = progress_file.read_text(encoding="utf-8")
            existing_reads, existing_writes, existing_commands, custom_notes = parse_existing_progress(content)
        except Exception as exc:
            console.print(f"[yellow]Varování při čtení PROGRESS.md:[/yellow] {escape(str(exc))}")

    new_reads = dict(existing_reads)
    new_writes = dict(existing_writes)
    new_commands = dict(existing_commands)

    for msg in messages:
        for part in getattr(msg, "parts", []):
            if not _is_tool_call(part):
                continue

            tool_name, args = _extract_tool_info(part)
            if not tool_name:
                continue

            target = _tool_target(args)
            command = args.get("command")
            pattern = args.get("pattern")

            if target and is_state_path(target):
                continue

            if tool_name in ("write_file", "edit_file") or any(k in tool_name for k in ("write", "edit", "patch", "create")):
                if target:
                    new_writes[target] = None
                    # Změněný soubor už není "přečtený": jeho obsah se změnil a model ho smí znovu číst
                    new_reads.pop(target, None)
            elif tool_name in ("read_file", "list_files") or any(k in tool_name for k in ("read", "list", "show")):
                if target:
                    new_reads[target] = None
            elif tool_name == "grep":
                grep_target = f"grep '{pattern}'" if pattern else "grep"
                if target:
                    grep_target += f" in {target}"
                new_reads[grep_target] = None
            elif tool_name == "shell":
                if command:
                    cmd_str = str(command).strip().splitlines()[0][:100]
                    # Znovu spuštěný příkaz se přesune na konec = "naposledy spuštěný"
                    new_commands.pop(cmd_str, None)
                    new_commands[cmd_str] = None
            elif tool_name == "delegate_task":
                task_snippet = str(args.get("task", ""))[:80]
                if task_snippet:
                    key = f"delegate_task: {task_snippet}"
                    new_commands.pop(key, None)
                    new_commands[key] = None

    shown_commands = list(new_commands)[-_MAX_PROGRESS_COMMANDS:]

    if (
        set(new_reads) == set(existing_reads)
        and set(new_writes) == set(existing_writes)
        and shown_commands == list(existing_commands)[-_MAX_PROGRESS_COMMANDS:]
        and progress_file.exists()
    ):
        return

    lines = [PROGRESS_TITLE + "\n"]

    if custom_notes:
        lines.append(custom_notes)
        lines.append("")

    if new_writes:
        lines.append("## Již modifikované / vytvořené soubory:")
        for f in sorted(new_writes):
            lines.append(f"- [x] Hotovo/Zapsáno: `{f}`")
        lines.append("")

    if new_reads:
        lines.append("## Již prozkoumané cesty (NEČÍST ZNOVU ZBYTEČNĚ):")
        for f in sorted(new_reads):
            lines.append(f"- [x] Přečteno: `{f}`")
        lines.append("")

    if shown_commands:
        lines.append("## Poslední spuštěné ověřovací příkazy:")
        for cmd in shown_commands:
            lines.append(f"- [x] Ověřeno / Příkaz: `{cmd}`")
        lines.append("")

    try:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        progress_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    except Exception as exc:
        console.print(f"[bold red]Chyba při zápisu PROGRESS.md:[/bold red] {escape(str(exc))}")


def read_plan(plan_file: Path, max_chars: int = 3000) -> str:
    """Načte plán udržovaný modelem (.cmd_coder/PLAN.md), zkrácený na max_chars."""
    try:
        if plan_file.exists():
            content = plan_file.read_text(encoding="utf-8").strip()
            if len(content) > max_chars:
                content = content[:max_chars].rsplit("\n", 1)[0] + "\n... (zkráceno)"
            return content
    except Exception:
        pass
    return ""


def rebuild_progress(messages: list[ModelMessage], progress_file: Path) -> None:
    """Postaví PROGRESS.md znovu jen z dané historie (po undo), vlastní poznámky uživatele zachová."""
    notes = ""
    try:
        if progress_file.exists():
            _r, _w, _c, notes = parse_existing_progress(progress_file.read_text(encoding="utf-8"))
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        header = PROGRESS_TITLE + "\n"
        progress_file.write_text(header + (("\n" + notes + "\n") if notes else ""), encoding="utf-8")
    except Exception as exc:
        console.print(f"[yellow]Varování při obnově PROGRESS.md:[/yellow] {escape(str(exc))}")
        return
    auto_update_progress_from_messages(messages, progress_file)
