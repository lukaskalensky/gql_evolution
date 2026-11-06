"""Ověřování práce agenta: analýza historie, spouštění testů harnessem a brána pro TASK_COMPLETED."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic_ai.messages import ModelMessage, ToolReturnPart

from .common import _extract_tool_info, _is_tool_call, _tool_target
from .progress import is_state_path

WRITE_TOOLS = ("write_file", "edit_file")

# Příkazy, které se počítají jako "ověření" (testy, linter, kontrola syntaxe, build)
_VERIFY_RE = re.compile(
    r"\b(pytest|unittest|tox|nox|nosetests|ruff|flake8|pylint|mypy|pyright|pyflakes|black\s+--check|"
    r"eslint|tsc|jest|vitest|mocha|phpunit|rspec|"
    r"py_compile|compileall|"
    r"python[\d.]*\s+(?:\S*/)?(?:test_\w+|\w+_test)\.py|"
    r"go\s+(test|vet|build)|cargo\s+(test|check|build|clippy)|dotnet\s+(test|build)|"
    r"mvn|gradle|ctest|"
    r"(npm|yarn|pnpm)\s+(run\s+)?(test|lint|build|check|typecheck)|"
    r"make(\s+\w+)?\s*$|make\s+(test|check|lint|build))\b"
)

_EXIT_CODE_RE = re.compile(r'"exit_code"\s*:\s*(-?\d+)')


def parse_exit_code(content: object) -> Optional[int]:
    """Z výsledku shell nástroje vytáhne návratový kód (poslední řádek je JSON se stavem)."""
    matches = _EXIT_CODE_RE.findall(str(content))
    return int(matches[-1]) if matches else None


def is_verification_command(command: str) -> bool:
    return bool(_VERIFY_RE.search(command or ""))


@dataclass
class Activity:
    """Co agent v historii udělal z hlediska ověřování."""

    write_count: int = 0                 # kolik zápisů souborů (mimo stavovou složku) proběhlo
    verified_since_last_write: bool = False  # proběhl po posledním zápisu úspěšný ověřovací příkaz?
    last_verify_failed: bool = False     # poslední ověřovací příkaz po zápisu skončil chybou


def analyze_activity(messages: list[ModelMessage]) -> Activity:
    """Projde historii v pořadí a zjistí, zda byla práce po posledním zápisu ověřena."""
    calls: dict[str, tuple[str, dict]] = {}
    act = Activity()

    for msg in messages:
        for part in getattr(msg, "parts", []):
            if _is_tool_call(part):
                name, args = _extract_tool_info(part)
                call_id = getattr(part, "tool_call_id", None)
                if call_id:
                    calls[call_id] = (name, args)
            elif isinstance(part, ToolReturnPart):
                name, args = calls.get(part.tool_call_id, (part.tool_name, {}))
                if name in WRITE_TOOLS:
                    target = _tool_target(args) or ""
                    if target and is_state_path(target):
                        continue
                    text = str(part.content).lower()
                    if "not found" in text or "denied" in text or "failed" in text:
                        continue  # neúspěšná úprava nic nezměnila
                    act.write_count += 1
                    act.verified_since_last_write = False
                    act.last_verify_failed = False
                elif name == "shell":
                    command = str(args.get("command", ""))
                    if is_verification_command(command):
                        code = parse_exit_code(part.content)
                        if code == 0:
                            act.verified_since_last_write = True
                            act.last_verify_failed = False
                        elif code is not None:
                            act.verified_since_last_write = False
                            act.last_verify_failed = True
    return act


@dataclass
class TestResult:
    __test__ = False  # pytest nemá tuto třídu sbírat jako test

    command: str
    returncode: int
    output: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def run_test_command(workspace: Path, command: str, timeout: int = 300) -> TestResult:
    """Spustí testovací příkaz ve workspace (stdout i stderr dohromady)."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return TestResult(command, proc.returncode, proc.stdout or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return TestResult(command, -1, out, timed_out=True)
    except Exception as exc:
        return TestResult(command, -1, f"Nelze spustit příkaz: {exc}")


def format_test_report(result: TestResult, max_chars: int = 3000) -> str:
    """Zpráva pro model: stav testů a KONEC výstupu (tam bývají chyby)."""
    output = result.output.strip()
    if len(output) > max_chars:
        output = "...[začátek výstupu vynechán]\n" + output[-max_chars:]
    if result.timed_out:
        status = "PŘEKROČEN ČASOVÝ LIMIT"
    elif result.ok:
        status = "PROŠLY"
    else:
        status = f"SELHALY (kód {result.returncode})"
    return f"[VÝSLEDEK TESTŮ spuštěných harnessem: `{result.command}` -> {status}]\n{output}"


MAX_GATE_REJECTIONS = 2  # bez --test-cmd: kolikrát smí brána odmítnout TASK_COMPLETED, než se přijme s varováním


def completion_hint_without_tests(act: Activity) -> Optional[str]:
    """
    Bez --test-cmd: když agent psal soubory a po posledním zápisu nic neověřil, vrátí pokyn pro model.
    Vrací None, pokud je dokončení v pořádku.
    """
    if act.write_count == 0:
        return None  # úkol bez změn souborů (analýza, vysvětlení): není co ověřovat
    if act.verified_since_last_write:
        return None
    if act.last_verify_failed:
        return (
            "TASK_COMPLETED NEBYLO PŘIJATO: poslední ověřovací příkaz po tvých úpravách selhal. "
            "Oprav chybu a spusť ověření znovu; dokud neprojde, úkol není hotový."
        )
    return (
        "TASK_COMPLETED NEBYLO PŘIJATO: po posledních úpravách souborů jsi nespustil žádné ověření. "
        "Spusť přes `shell` relevantní testy / linter / kontrolu syntaxe, a až projdou, napiš TASK_COMPLETED."
    )
