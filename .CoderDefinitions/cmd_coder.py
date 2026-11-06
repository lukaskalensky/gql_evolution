#!/usr/bin/env python3
"""
Plně autonomní CLI Coder pro libovolný softwarový projekt.
Dynamicky pracuje se zadaným repozitářem/workspace, chrání kontextové okno (VRAM)
pomocí inteligentního ořezávání a zkracování historie, automaticky sleduje stav v PROGRESS.md
a v plánu (PLAN.md), před každým krokem ukládá git checkpoint (příkaz /undo) a nabízí konverzaci
s agentem (výchozí) i plnou autonomii (-t/-y: smyčka do splnění úkolu a ověření testy).

Implementace je v balíčku `coder_lib/`; tento soubor obsahuje jen příkazovou řádku.
"""

import os

# Vypnutí velkého ASCII banneru PydanticAI (musí být před jeho importem)
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from coder_lib.common import console, default_state_paths
from coder_lib.history import DEFAULT_KEEP_RECENT_MESSAGES, DEFAULT_RESULT_CHARS
from coder_lib.runner import RunSettings, run_agent_loop
from coder_lib.ui import resolve_workspace

load_dotenv()


def build_cli_parser() -> argparse.ArgumentParser:
    """Vytvoří a nakonfiguruje parser příkazové řádky."""
    parser = argparse.ArgumentParser(
        description="Plně autonomní programovací CLI agent s ochranou VRAM a sledováním postupu"
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=".",
        help="Cesta k repozitáři/workspace (výchozí: aktuální adresář)",
    )
    parser.add_argument(
        "-t", "--task",
        default=None,
        help="Zadání úkolu pro agenta (pokud je zadáno, agent může běžet plně autonomně)",
    )
    parser.add_argument(
        "-y", "--auto",
        action="store_true",
        help="Spustit v plně autonomním režimu bez čekání na potvrzení mezi kroky",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Zůstat v konverzaci i při zadání úkolu (úkol se provede jako první zpráva)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AI_MODEL", "gemma-4"),
        help="Název LLM modelu (výchozí: $AI_MODEL nebo 'gemma-4')",
    )
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("AI_BASE_URL", "http://127.0.0.1:8080/v1"),
        help="OpenAI API Base URL (výchozí: $AI_BASE_URL nebo http://127.0.0.1:8080/v1)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AI_API_KEY", "local"),
        help="API klíč (výchozí: $AI_API_KEY nebo 'local')",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="Počet zachovaných konverzačních kol v paměti pro ochranu kontextu (výchozí: 20 v konverzaci, 3 v autonomním běhu)",
    )
    parser.add_argument(
        "--step-limit",
        type=int,
        default=None,
        help="Limit požadavků na model v jednom kroku; každé volání nástroje stojí jeden požadavek (výchozí: 100 v konverzaci, 35 v autonomním běhu)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=25,
        help="Maximální počet kroků autonomní smyčky; konverzaci neomezuje (výchozí: 25)",
    )
    parser.add_argument(
        "--result-chars",
        type=int,
        default=DEFAULT_RESULT_CHARS,
        help=f"Starší výstupy nástrojů se v kontextu zkracují nad tento počet znaků; 0 = nezkracovat (výchozí: {DEFAULT_RESULT_CHARS})",
    )
    parser.add_argument(
        "--keep-recent",
        type=int,
        default=DEFAULT_KEEP_RECENT_MESSAGES,
        help=f"Kolik posledních zpráv se nikdy nezkracuje (výchozí: {DEFAULT_KEEP_RECENT_MESSAGES})",
    )
    parser.add_argument(
        "--test-cmd",
        default=None,
        help="Příkaz, kterým harness sám ověřuje práci (např. 'pytest -q'). Spouští se po krocích, "
             "které měnily soubory, a TASK_COMPLETED se přijme jen když projde",
    )
    parser.add_argument(
        "--test-timeout",
        type=int,
        default=300,
        help="Časový limit pro --test-cmd v sekundách (výchozí: 300)",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Nevytvářet git checkpointy před kroky (příkaz undo pak není k dispozici)",
    )
    parser.add_argument(
        "--allow-dangerous",
        action="store_true",
        help="Nechat agenta spouštět i nebezpečné shell příkazy (git push, reset --hard, sudo, rm -r mimo projekt, ...)",
    )
    parser.add_argument(
        "--no-server-check",
        action="store_true",
        help="Nekontrolovat při startu, zda model server odpovídá",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Smazat existující historii, PROGRESS.md a plán (výchozí složka .cmd_coder/) před spuštěním",
    )
    parser.add_argument(
        "--history-file",
        type=Path,
        default=None,
        help="Vlastní cesta k souboru historie (výchozí: <workspace>/.cmd_coder/history.json)",
    )
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="Vlastní cesta k souboru PROGRESS.md (výchozí: <workspace>/.cmd_coder/PROGRESS.md)",
    )
    return parser


async def main() -> bool:
    parser = build_cli_parser()
    args = parser.parse_args()

    workspace_path, workspace_auto = resolve_workspace(args.workspace)

    if args.clear:
        default_hist, default_prog = default_state_paths(workspace_path)
        hist_p = args.history_file or default_hist
        prog_p = args.progress_file or default_prog
        plan_p = default_hist.parent / "PLAN.md"
        for path in (hist_p, prog_p, plan_p):
            if path.exists():
                path.unlink()
        console.print("[green]Historie, PROGRESS.md i plán byly předem smazány (--clear).[/green]")

    # Pokud byl zadán úkol a nebyl vynucen --interactive, běží autonomně
    auto_mode = args.auto or (args.task is not None and not args.interactive)

    settings = RunSettings(
        workspace_path=workspace_path,
        task=args.task,
        model_name=args.model,
        endpoint=args.endpoint,
        api_key=args.api_key,
        turns=args.turns,
        step_limit=args.step_limit,
        max_iterations=args.max_iterations,
        auto_mode=auto_mode,
        history_file=args.history_file,
        progress_file=args.progress_file,
        workspace_auto=workspace_auto,
        test_cmd=args.test_cmd,
        test_timeout=args.test_timeout,
        use_git=not args.no_git,
        allow_dangerous=args.allow_dangerous,
        result_chars=args.result_chars,
        keep_recent=args.keep_recent,
        check_server=not args.no_server_check,
    )
    completed = await run_agent_loop(settings)
    # Kód ukončení má smysl jen v autonomním režimu (skripty, CI): 0 = úkol dokončen
    return completed or not auto_mode


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Vlastní SIGINT handler: asyncio.run() by jinak při Ctrl+C na řádku s promptem (input())
    # první stisk "spolkl" a zareagoval by až po Enteru. S tímto handlerem Ctrl+C přeruší
    # okamžitě (i uprostřed kroku) a smyčka stihne uložit historii a PROGRESS.md.
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    try:
        ok = asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[yellow]Ukončeno (Ctrl+C). Stav je uložen na disk.[/yellow]")
        sys.exit(130)
    sys.exit(0 if ok else 1)
