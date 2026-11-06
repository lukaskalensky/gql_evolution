"""Sdílené základy: konzole, cesty ke stavu agenta a čtení volání nástrojů ze zpráv."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

# Vypnutí velkého ASCII banneru PydanticAI (musí být nastaveno před jeho importem)
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

from pydantic_ai.messages import ToolCallPart
from rich.console import Console

console = Console()

# Sdílený odkaz na právě běžící spinner (rich Status), aby ho šlo pozastavit při dotazu na uživatele
ui_state = SimpleNamespace(status=None)

# Stav agenta (historie + PROGRESS.md) žije ve SKRYTÉ složce. Důvody: nástroj `grep` agenta
# skrytými složkami neprochází (jinak by každé hledání vracelo zásahy z history.json, což je
# celý přepis konverzace) a `--clear` tak nikdy nesmaže projektový PROGRESS.md.
STATE_DIR_NAME = ".cmd_coder"


def default_state_paths(workspace_path: Path) -> tuple[Path, Path]:
    """Výchozí cesty k souboru historie a PROGRESS.md pro daný workspace."""
    state_dir = workspace_path / STATE_DIR_NAME
    return state_dir / "history.json", state_dir / "PROGRESS.md"


def ensure_state_dir(workspace_path: Path) -> None:
    """Vytvoří stavovou složku a vlastní .gitignore, aby stav nepřišel do commitů."""
    state_dir = workspace_path / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    gitignore = state_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n", encoding="utf-8")


PLAN_FILE_NAME = "PLAN.md"
LOG_FILE_NAME = "run.log"
INPUT_HISTORY_FILE_NAME = "input_history"
CHECKPOINTS_FILE_NAME = "checkpoints.json"


def _is_tool_call(part: Any) -> bool:
    """Rozpozná část zprávy představující volání nástroje."""
    return isinstance(part, ToolCallPart) or getattr(part, "part_kind", "") in ("tool-call", "tool_call")


def _extract_tool_info(part: Any) -> tuple[str, dict[str, Any]]:
    """Extrahuje název nástroje a jeho argumenty z ToolCallPart."""
    tool_name = getattr(part, "tool_name", "") or ""
    args = getattr(part, "args", {})
    if hasattr(args, "model_dump"):
        args = args.model_dump()
    elif hasattr(args, "__dict__"):
        args = args.__dict__
    elif isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return tool_name, args


def _tool_target(args: dict[str, Any]) -> Optional[str]:
    """Najde v argumentech nástroje cílovou cestu (různé nástroje používají různé názvy)."""
    for key in ("file_path", "filepath", "path", "dir_path", "target_file", "file"):
        value = args.get(key)
        if value:
            return str(value)
    return None



def state_file(workspace_path: Path, name: str) -> Path:
    """Cesta k souboru uvnitř stavové složky `.cmd_coder/`."""
    return workspace_path / STATE_DIR_NAME / name
