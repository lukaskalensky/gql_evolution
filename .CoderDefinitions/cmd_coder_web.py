#!/usr/bin/env python3
"""
Webové rozhraní Coderu: konverzace s agentem v prohlížeči.
Používá stejného agenta a stejný stav (.cmd_coder/) jako terminálový cmd_coder.py.
Nespouštějte obě rozhraní nad jedním workspace současně, přepisovala by si historii.
"""

import os

# Vypnutí velkého ASCII banneru PydanticAI (musí být před jeho importem)
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

import argparse
import ipaddress
import secrets
import sys

import uvicorn
from dotenv import load_dotenv

from coder_lib.common import console
from coder_lib.history import DEFAULT_KEEP_RECENT_MESSAGES, DEFAULT_RESULT_CHARS
from coder_lib.ui import check_endpoint, resolve_workspace
from coder_lib.web import WebSettings, create_app

load_dotenv()


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Webové rozhraní programovacího agenta")
    parser.add_argument("workspace", nargs="?", default=".", help="Cesta k projektu (výchozí: aktuální adresář)")
    parser.add_argument("--host", default="127.0.0.1", help="Adresa serveru (výchozí: 127.0.0.1, jen tento počítač)")
    parser.add_argument("--port", type=int, default=8765, help="Port serveru (výchozí: 8765)")
    parser.add_argument(
        "--token",
        default=os.environ.get("CODER_WEB_TOKEN"),
        help="Přístupový token (výchozí: $CODER_WEB_TOKEN, jinak se při každém startu vygeneruje nový)",
    )
    parser.add_argument("--model", default=os.environ.get("AI_MODEL", "gemma-4"), help="Název modelu")
    parser.add_argument("--endpoint", default=os.environ.get("AI_BASE_URL", "http://127.0.0.1:8080/v1"), help="OpenAI API Base URL")
    parser.add_argument("--api-key", default=os.environ.get("AI_API_KEY", "local"), help="API klíč modelu")
    parser.add_argument("--turns", type=int, default=None, help="Kolik kol konverzace si model pamatuje (výchozí: 20)")
    parser.add_argument("--step-limit", type=int, default=None, help="Limit požadavků na model v jednom kroku (výchozí: 100)")
    parser.add_argument("--result-chars", type=int, default=DEFAULT_RESULT_CHARS, help="Délka, na kterou se zkracují starší výstupy nástrojů")
    parser.add_argument("--keep-recent", type=int, default=DEFAULT_KEEP_RECENT_MESSAGES, help="Kolik posledních zpráv se nikdy nezkracuje")
    parser.add_argument("--no-git", action="store_true", help="Nevytvářet git checkpointy (návrat změn pak není k dispozici)")
    parser.add_argument("--allow-dangerous", action="store_true", help="Spouštět i nebezpečné příkazy bez potvrzení")
    return parser


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> int:
    args = build_cli_parser().parse_args()
    workspace, _ = resolve_workspace(args.workspace)
    if not workspace.is_dir():
        console.print(f"[bold red]Zadaná cesta není adresář:[/bold red] {workspace}", markup=True)
        return 1

    reachable, server_message = check_endpoint(args.endpoint, args.api_key, args.model)
    token = args.token or secrets.token_urlsafe(24)
    app = create_app(WebSettings(
        workspace_path=workspace,
        token=token,
        model_name=args.model,
        endpoint=args.endpoint,
        api_key=args.api_key,
        turns=args.turns,
        step_limit=args.step_limit,
        use_git=not args.no_git,
        allow_dangerous=args.allow_dangerous,
        result_chars=args.result_chars,
        keep_recent=args.keep_recent,
        startup_warning="" if reachable else server_message,
    ))

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    console.print(f"Workspace: {workspace}", markup=False, highlight=False)
    if not reachable:
        console.print(server_message, style="yellow", markup=False)
    if not _is_loopback(args.host):
        console.print(
            f"POZOR: server poslouchá na {args.host} bez šifrování. Kdokoli s tokenem může spouštět "
            "příkazy na tomto počítači a token jde po síti čitelně.",
            style="bold red",
            markup=False,
        )
    console.print("\nOtevřete v prohlížeči (odkaz obsahuje přístupový token, nesdílejte ho):", markup=False)
    # print místo console.print: odkaz se nesmí zalomit, jinak by nešel zkopírovat
    print(f"  http://{shown_host}:{args.port}/#token={token}\n", flush=True)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=3,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
