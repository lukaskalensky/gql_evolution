"""Webové rozhraní: lokální server s jednou konverzací nad stejným agentem a stavem jako terminál."""

import asyncio
import contextlib
import json
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from pydantic_ai.messages import (
    ModelMessage,
    RetryPromptPart,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import gitsafe
from .agent import create_generic_agent
from .chatio import strip_completion_marker
from .common import (
    LOG_FILE_NAME,
    PLAN_FILE_NAME,
    _extract_tool_info,
    _is_tool_call,
    _tool_target,
    default_state_paths,
    ensure_state_dir,
    state_file,
)
from .history import (
    DEFAULT_KEEP_RECENT_MESSAGES,
    DEFAULT_RESULT_CHARS,
    finalize_partial_history,
    load_history_from_disk,
    safe_trim_history,
    save_history_to_disk,
    truncate_text,
)
from .progress import auto_update_progress_from_messages, read_plan, rebuild_progress
from .runlog import RunLog
from .runner import (
    CONTINUE_PROMPT_AUTO,
    CONTINUE_PROMPT_INTERACTIVE,
    DEFAULT_STEP_LIMIT,
    DEFAULT_TURNS,
    _loop_hint,
    _tool_failure_hint,
    execute_step,
)
from .verify import parse_exit_code

STATIC_DIR = Path(__file__).parent / "web_static"

# Výstup modelu je nedůvěryhodný: HTML se escapuje a obrázky jsou vypnuté, protože načtení
# obrázku z cizí adresy by mohlo vynést data z projektu (např. po prompt injection ze souboru).
_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"]).disable("image")

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

MAX_TOOL_TEXT = 4000
MAX_PANEL_CHARS = 200_000
MAX_REPLAY_EVENTS = 400
TEXT_UPDATE_SECONDS = 0.12
CONFIRM_TIMEOUT_SECONDS = 600
AUTH_TIMEOUT_SECONDS = 10
CLOSE_UNAUTHORIZED = 4401


# Patička, kterou knihovna přidává k výstupu shellu (PID, cesty k logům, stav). Je určená modelu.
_SHELL_FOOTER = re.compile(
    r"(?:^|\n)PID: \d+ \(supervisor[^\n]*(?:\n(?:Output|Stdout|Stderr|Status): [^\n]*)*(?:\n\{\"pid\"[^\n]*)?\s*$"
)
# Pokyny, které harness přidává ke zprávám pro model; uživatel je nenapsal, a tak je nezobrazujeme
_INTERNAL_PROMPTS = (CONTINUE_PROMPT_INTERACTIVE, CONTINUE_PROMPT_AUTO)
_HINT_MARKER = "\n\nPOZOR: v předchozím kroku"


def render_markdown(text: str) -> str:
    return _markdown.render(strip_completion_marker(text))


def _first_line(value: Any, limit: int = 300) -> str:
    return (str(value).strip().splitlines() or [""])[0][:limit]


def tool_call_event(part: Any, tool_name: str, args: dict[str, Any], valid: Optional[bool]) -> dict[str, Any]:
    target = _tool_target(args) or args.get("command") or args.get("pattern") or args.get("task") or ""
    event: dict[str, Any] = {
        "type": "tool_call",
        "id": getattr(part, "tool_call_id", None),
        "name": tool_name,
        "valid": valid is not False,
        "target": _first_line(target),
    }
    if tool_name == "shell" and args.get("command"):
        event["command"] = truncate_text(str(args["command"]), MAX_TOOL_TEXT)
    if tool_name == "write_file" and isinstance(args.get("content"), str):
        event["content"] = truncate_text(args["content"], MAX_TOOL_TEXT)
    if tool_name == "edit_file":
        pairs = [args] + [item for item in args.get("replacements") or [] if isinstance(item, dict)]
        event["edits"] = [
            {
                "old": truncate_text(str(pair.get("old_text", "")), MAX_TOOL_TEXT),
                "new": truncate_text(str(pair.get("new_text", "")), MAX_TOOL_TEXT),
            }
            for pair in pairs
            if "old_text" in pair or "new_text" in pair
        ]
    return event


def tool_result_event(part: Any) -> dict[str, Any]:
    name = getattr(part, "tool_name", "") or ""
    content = getattr(part, "content", "")
    failed = isinstance(part, RetryPromptPart)
    exit_code = None
    if not isinstance(content, str):
        with contextlib.suppress(TypeError, ValueError):
            content = json.dumps(content, ensure_ascii=False, default=str)
    text = str(content)
    if name == "shell" and not failed:
        exit_code = parse_exit_code(text)
        failed = exit_code is not None and exit_code != 0
        text = _SHELL_FOOTER.sub("", text)
    return {
        "type": "tool_result",
        "id": getattr(part, "tool_call_id", None),
        "name": name,
        "text": truncate_text(text.strip(), MAX_TOOL_TEXT),
        "failed": failed,
        "denied": text.startswith("DENIED by harness"),
        "exit_code": exit_code,
    }


def visible_user_text(content: str) -> str:
    """Část zprávy, kterou opravdu napsal uživatel (bez pokynů přidaných harnessem)."""
    text = content.split(_HINT_MARKER, 1)[0]
    return "" if text in _INTERNAL_PROMPTS else text


def history_to_events(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    """Převede uloženou historii na události, ze kterých stránka po načtení vykreslí konverzaci."""
    events: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        for position, part in enumerate(getattr(message, "parts", [])):
            if isinstance(part, UserPromptPart):
                content = part.content if isinstance(part.content, str) else " ".join(
                    item for item in part.content if isinstance(item, str)
                )
                shown = visible_user_text(content)
                if shown:
                    events.append({"type": "user", "text": shown})
            elif isinstance(part, TextPart):
                if strip_completion_marker(part.content):
                    events.append({"type": "text", "id": f"h{index}-{position}", "html": render_markdown(part.content)})
            elif _is_tool_call(part):
                name, args = _extract_tool_info(part)
                events.append(tool_call_event(part, name, args, True))
            elif isinstance(part, (ToolReturnPart, RetryPromptPart)):
                events.append(tool_result_event(part))
    return events[-MAX_REPLAY_EVENTS:]


class WebStepView:
    """Zobrazení běžícího kroku v prohlížeči: stejné rozhraní jako ConsoleStepView v terminálu."""

    def __init__(self, session: "WebSession"):
        self._session = session
        self._buffer = ""
        self._block: Optional[str] = None
        self._last_update = 0.0
        self.streamed_text = ""

    def __enter__(self) -> "WebStepView":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.end_text()

    def _send_text(self) -> None:
        self._last_update = time.monotonic()
        self._session.emit({"type": "text", "id": self._block, "html": render_markdown(self._buffer)})

    def text(self, piece: str) -> None:
        if not piece:
            return
        if self._block is None:
            self._block = self._session.new_block_id()
        self._buffer += piece
        # Celý blok se vykresluje znovu, proto jen několikrát za sekundu
        if time.monotonic() - self._last_update >= TEXT_UPDATE_SECONDS:
            self._send_text()

    def end_text(self) -> None:
        if self._buffer:
            self._send_text()
            self.streamed_text = self._buffer
        self._buffer = ""
        self._block = None

    def tool_call(self, part: Any, tool_name: str, args: dict[str, Any], valid: Optional[bool]) -> None:
        self._session.emit(tool_call_event(part, tool_name, args, valid))

    def tool_result(self, part: Any) -> None:
        self._session.emit(tool_result_event(part))

    def tick(self, tools: int, chars: int, seconds: float) -> None:
        self._session.emit({"type": "tick", "tools": tools, "chars": chars}, replay=False)


@dataclass
class WebSettings:
    workspace_path: Path
    token: str
    model_name: str
    endpoint: str
    api_key: str
    turns: Optional[int] = None
    step_limit: Optional[int] = None
    use_git: bool = True
    allow_dangerous: bool = False
    result_chars: int = DEFAULT_RESULT_CHARS
    keep_recent: int = DEFAULT_KEEP_RECENT_MESSAGES
    startup_warning: str = ""


class WebSession:
    """Jedna konverzace a její běžící krok. Všechny otevřené záložky vidí totéž."""

    def __init__(self, settings: WebSettings):
        self.settings = settings
        self.workspace = settings.workspace_path.resolve()
        ensure_state_dir(self.workspace)
        self.history_path, self.progress_path = default_state_paths(self.workspace)
        self.plan_path = state_file(self.workspace, PLAN_FILE_NAME)
        self.runlog = RunLog(state_file(self.workspace, LOG_FILE_NAME))
        self.git_enabled = settings.use_git and gitsafe.repo_root(self.workspace) is not None
        self.turns = settings.turns if settings.turns is not None else DEFAULT_TURNS["chat"]
        step_limit = settings.step_limit if settings.step_limit is not None else DEFAULT_STEP_LIMIT["chat"]
        self.limits = UsageLimits(request_limit=step_limit)

        self.history: list[ModelMessage] = finalize_partial_history(
            load_history_from_disk(self.history_path), "Předchozí relace byla ukončena uprostřed kroku"
        )
        self.clients: set[asyncio.Queue] = set()
        self.task: Optional[asyncio.Task] = None
        self.started_at = 0.0
        self.live_events: list[dict[str, Any]] = []
        self.pending_confirms: dict[str, tuple[asyncio.Future, dict[str, Any]]] = {}
        self.hints: list[str] = []
        self.can_continue = False
        self.step = self._next_step_number()
        self._block_counter = 0

        self.agent = create_generic_agent(
            self.workspace,
            settings.endpoint,
            settings.api_key,
            settings.model_name,
            self.progress_path,
            plan_file=self.plan_path,
            allow_dangerous=settings.allow_dangerous,
            confirm=self._confirm_dangerous,
            on_denied=self._on_denied,
            keep_recent=settings.keep_recent,
            result_chars=settings.result_chars,
            is_autonomous=lambda: False,
        )

    # --- události pro prohlížeč ---------------------------------------------------------

    def new_block_id(self) -> str:
        self._block_counter += 1
        return f"live-{self._block_counter}"

    def emit(self, event: dict[str, Any], replay: bool = True) -> None:
        """Pošle událost všem záložkám a u běžícího kroku si ji drží pro záložky otevřené později."""
        if replay and self.running:
            last = self.live_events[-1] if self.live_events else None
            if event["type"] == "text" and last and last["type"] == "text" and last["id"] == event["id"]:
                self.live_events[-1] = event
            else:
                self.live_events.append(event)
        for queue in self.clients:
            queue.put_nowait(event)

    def notice(self, level: str, text: str) -> None:
        self.emit({"type": "notice", "level": level, "text": text})

    @property
    def running(self) -> bool:
        return self.task is not None

    def state_event(self) -> dict[str, Any]:
        return {
            "type": "state",
            "running": self.running,
            "can_continue": self.can_continue,
            "git": self.git_enabled,
            "elapsed": time.monotonic() - self.started_at if self.running else 0,
        }

    def snapshot(self) -> dict[str, Any]:
        """Úplný stav pro nově připojenou záložku."""
        events = history_to_events(self.history) + list(self.live_events)
        return {
            "type": "init",
            "workspace": str(self.workspace),
            "model": self.settings.model_name,
            "warning": self.settings.startup_warning,
            "events": events,
            "confirms": [event for _, event in self.pending_confirms.values()],
            "state": self.state_event(),
        }

    def _broadcast_snapshot(self) -> None:
        snapshot = self.snapshot()
        for queue in self.clients:
            queue.put_nowait(snapshot)

    # --- nebezpečné příkazy --------------------------------------------------------------

    async def _confirm_dangerous(self, command: str, reason: str) -> bool:
        confirm_id = secrets.token_hex(8)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        event = {"type": "confirm", "id": confirm_id, "command": command, "reason": reason}
        self.pending_confirms[confirm_id] = (future, event)
        self.emit(event, replay=False)
        try:
            return await asyncio.wait_for(future, CONFIRM_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending_confirms.pop(confirm_id, None)
            self.emit({"type": "confirm_done", "id": confirm_id}, replay=False)

    def _on_denied(self, command: str, reason: str) -> None:
        self.runlog.write("denied_command", command=command, reason=reason)
        self.notice("warning", f"Zablokován nebezpečný příkaz: {_first_line(command, 120)} ({reason})")

    # --- krok agenta ---------------------------------------------------------------------

    def _next_step_number(self) -> int:
        return max((int(item["step"]) for item in gitsafe.list_checkpoints(self.workspace)), default=0) + 1

    def start_step(self, text: str) -> None:
        prompt = text if text else CONTINUE_PROMPT_INTERACTIVE
        if self.hints:
            prompt = prompt + "\n\n" + "\n\n".join(self.hints)
            self.hints.clear()
        self.live_events = []
        self.started_at = time.monotonic()
        self.task = asyncio.create_task(self._run_step(prompt))
        if text:
            self.emit({"type": "user", "text": text})
        self.emit(self.state_event(), replay=False)

    async def _run_step(self, prompt: str) -> None:
        outcome = None
        try:
            if self.git_enabled:
                try:
                    await asyncio.to_thread(
                        gitsafe.create_checkpoint, self.workspace, self.step, len(self.history), prompt[:80]
                    )
                except gitsafe.GitError as exc:
                    self.git_enabled = False
                    self.notice("warning", f"Checkpoint se nepodařilo vytvořit, další už nebudou: {exc}")

            trimmed = safe_trim_history(self.history, keep_turns=self.turns, preserve_initial=False)
            self.runlog.write("step_start", step=self.step, prompt=prompt)
            outcome = await execute_step(
                self.agent,
                prompt,
                self.history,
                trimmed,
                self.limits,
                self.progress_path,
                self.runlog,
                self.step,
                view=WebStepView(self),
            )
            self._report_outcome(outcome)
        except asyncio.CancelledError:
            self.notice("warning", "Přerušeno. Dosavadní práce je uložena; napište další zprávu, nebo v ní pokračujte.")
        except Exception as exc:
            self.notice("error", f"Neočekávaná chyba: {type(exc).__name__}: {exc}")
        finally:
            save_history_to_disk(self.history, self.history_path)
            auto_update_progress_from_messages(self.history, self.progress_path)
            self.can_continue = outcome is None or outcome.error is not None
            self.step += 1
            self.task = None
            self.live_events = []
            self.emit(self.state_event(), replay=False)

    def _report_outcome(self, outcome: Any) -> None:
        self.runlog.write(
            "step_end",
            step=self.step,
            ok=outcome.error is None,
            error=outcome.error,
            loop=outcome.loop_detected,
            usage=list(outcome.usage),
            seconds=round(outcome.seconds, 1),
        )
        if outcome.error is None:
            output = outcome.output or ""
            if strip_completion_marker(output):
                if outcome.streamed_text.strip() != output.strip():
                    self.emit({"type": "text", "id": self.new_block_id(), "html": render_markdown(output)})
            else:
                self.notice("warning", "Model skončil bez textové odpovědi. Zkuste dotaz zopakovat nebo upřesnit.")
        elif outcome.loop_detected:
            self.hints.append(_loop_hint(outcome.loop_detected))
            self.notice("warning", f"Model se zacyklil ({outcome.loop_detected}), krok byl přerušen. Práce je uložena.")
        elif outcome.tool_failure:
            self.hints.append(_tool_failure_hint(outcome.error or ""))
            self.notice("warning", "Model opakovaně volal nástroj s neplatnými argumenty. Práce je uložena.")
        elif outcome.limit_hit:
            self.notice("warning", "Krok vyčerpal limit požadavků na model. Práce je uložena, můžete pokračovat.")
        else:
            self.notice("error", outcome.error or "Neznámá chyba")

        requests, tokens_in, tokens_out = outcome.usage
        if requests:
            self.emit({
                "type": "usage",
                "requests": requests,
                "input": tokens_in,
                "output": tokens_out,
                "seconds": round(outcome.seconds),
            })

    async def stop_running_step(self) -> None:
        task = self.task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # --- akce z postranního panelu -------------------------------------------------------

    def _diff_text(self) -> str:
        if gitsafe.repo_root(self.workspace) is None:
            return "Workspace není v git repozitáři, změny tu nejde zobrazit."

        def git(*args: str) -> str:
            proc = subprocess.run(
                ["git", *args], cwd=self.workspace, capture_output=True, text=True, errors="replace", timeout=20
            )
            return proc.stdout

        status = git("status", "--short").strip()
        if not status:
            return "Žádné změny."
        return truncate_text(f"{status}\n\n{git('diff')}", MAX_PANEL_CHARS)

    def _latest_checkpoint(self) -> Optional[dict[str, Any]]:
        items = gitsafe.list_checkpoints(self.workspace)
        return items[-1] if items and self.git_enabled else None

    async def _undo(self, commit: Any) -> None:
        checkpoint = self._latest_checkpoint()
        # Potvrzení musí patřit k checkpointu, který uživatel viděl v náhledu
        if checkpoint is None or checkpoint["commit"] != commit:
            raise gitsafe.GitError("Checkpoint se mezitím změnil, otevřete náhled znovu.")
        counts = await asyncio.to_thread(gitsafe.restore_checkpoint, self.workspace, checkpoint)
        gitsafe.drop_checkpoints_from(self.workspace, checkpoint)
        self.history = self.history[: int(checkpoint.get("history_len", 0))]
        save_history_to_disk(self.history, self.history_path)
        rebuild_progress(self.history, self.progress_path)
        self.hints.clear()
        self.can_continue = False
        self.step = int(checkpoint["step"])
        self.runlog.write("undo", to_step=checkpoint["step"], **counts)
        self._broadcast_snapshot()
        self.notice("info", f"Vráceno před krok #{checkpoint['step']}: obnoveno {counts['restored']} souborů, smazáno {counts['deleted']}.")

    def _clear(self) -> None:
        self.history = []
        self.hints.clear()
        self.can_continue = False
        for path in (self.history_path, self.progress_path, self.plan_path):
            if path.exists():
                path.unlink()
        self._broadcast_snapshot()

    # --- zprávy z prohlížeče -------------------------------------------------------------

    async def handle_message(self, message: dict[str, Any], reply: asyncio.Queue) -> None:
        kind = message.get("type")

        if kind == "confirm":
            pending = self.pending_confirms.get(str(message.get("id")))
            if pending and not pending[0].done():
                pending[0].set_result(message.get("ok") is True)
            return
        if kind == "stop":
            if self.task is not None:
                self.task.cancel()
            return
        if kind == "plan":
            text = read_plan(self.plan_path, max_chars=MAX_PANEL_CHARS) or "Plán zatím neexistuje."
            reply.put_nowait({"type": "panel", "title": "Plán", "text": text})
            return
        if kind == "diff":
            text = await asyncio.to_thread(self._diff_text)
            reply.put_nowait({"type": "panel", "title": "Změny", "text": text, "diff": True})
            return

        # Zbytek mění konverzaci nebo soubory, během práce agenta se to nesmí křížit
        if kind not in ("send", "undo_preview", "undo_confirm", "clear"):
            reply.put_nowait({"type": "notice", "level": "error", "text": "Neznámý požadavek."})
            return
        if self.running:
            reply.put_nowait({"type": "notice", "level": "warning", "text": "Agent právě pracuje. Počkejte, nebo ho zastavte."})
            return

        if kind == "send":
            text = str(message.get("text") or "").strip()
            if text or self.can_continue:
                self.start_step(text)
        elif kind == "clear":
            self._clear()
        elif kind == "undo_preview":
            checkpoint = self._latest_checkpoint()
            if checkpoint is None:
                reply.put_nowait({"type": "notice", "level": "info", "text": "Není k dispozici žádný checkpoint."})
                return
            changes = await asyncio.to_thread(gitsafe.describe_changes, self.workspace, checkpoint)
            reply.put_nowait({
                "type": "undo_preview",
                "commit": checkpoint["commit"],
                "step": checkpoint["step"],
                "label": checkpoint.get("label", ""),
                "changes": [list(change) for change in changes[:200]],
            })
        elif kind == "undo_confirm":
            await self._undo(message.get("commit"))


def _origin_allowed(websocket: WebSocket) -> bool:
    """Cizí web v prohlížeči nesmí otevřít spojení k lokálnímu serveru (Origin musí odpovídat Host)."""
    origin = websocket.headers.get("origin")
    return not origin or urlsplit(origin).netloc == websocket.headers.get("host")


def create_app(settings: WebSettings) -> Starlette:
    session = WebSession(settings)

    async def static(request: Request) -> Response:
        name, media_type = STATIC_FILES[request.url.path]
        return Response(
            (STATIC_DIR / name).read_bytes(),
            media_type=media_type,
            headers={
                "Content-Security-Policy": CONTENT_SECURITY_POLICY,
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not _origin_allowed(websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        # Token chodí první zprávou, ne v adrese, aby se nedostal do logů
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT_SECONDS)
            token = auth.get("token") if isinstance(auth, dict) and auth.get("type") == "auth" else None
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect, KeyError):
            token = None
        if not isinstance(token, str) or not secrets.compare_digest(token.encode(), settings.token.encode()):
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=CLOSE_UNAUTHORIZED)
            return

        queue: asyncio.Queue = asyncio.Queue()
        session.clients.add(queue)
        queue.put_nowait(session.snapshot())

        async def sender() -> None:
            while True:
                await websocket.send_json(await queue.get())

        sender_task = asyncio.create_task(sender())
        try:
            while True:
                try:
                    message = await websocket.receive_json()
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                try:
                    await session.handle_message(message, queue)
                except gitsafe.GitError as exc:
                    queue.put_nowait({"type": "notice", "level": "error", "text": str(exc)})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            session.clients.discard(queue)
            sender_task.cancel()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        yield
        await session.stop_running_step()

    routes = [Route(path, static) for path in STATIC_FILES] + [WebSocketRoute("/ws", websocket_endpoint)]
    return Starlette(routes=routes, lifespan=lifespan)
