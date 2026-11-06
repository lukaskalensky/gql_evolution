"""Správa historie konverzace: ukládání, bezpečné ořezávání, zkracování starých výsledků."""

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from rich.markup import escape

from .common import _extract_tool_info, _is_tool_call, _tool_target, console


def save_history_to_disk(messages: list[ModelMessage], path: Path) -> None:
    """Bezpečně uloží kompletní historii na disk (přes dočasný soubor, aby pád nezničil starou verzi)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = ModelMessagesTypeAdapter.dump_json(messages, indent=2)
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_bytes(serialized)
        os.replace(tmp_path, path)
    except Exception as exc:
        console.print(f"[bold red]Chyba při ukládání historie:[/bold red] {escape(str(exc))}")


def load_history_from_disk(path: Path) -> list[ModelMessage]:
    """Načte existující historii zpráv z disku."""
    if not path.exists():
        return []
    try:
        content = path.read_bytes()
        if not content.strip():
            return []
        return list(ModelMessagesTypeAdapter.validate_json(content))
    except Exception as exc:
        console.print(f"[yellow]Varování při načítání historie:[/yellow] {escape(str(exc))}")
        return []


def is_user_turn_start(msg: ModelMessage) -> bool:
    """Ověří, zda zpráva představuje začátek nového uživatelského kola (nikoliv tool-return)."""
    if not isinstance(msg, ModelRequest):
        return False
    parts = getattr(msg, "parts", [])
    has_user = any(
        isinstance(p, UserPromptPart) or getattr(p, "part_kind", "") == "user-prompt"
        for p in parts
    )
    has_tool_ret = any(
        isinstance(p, ToolReturnPart) or getattr(p, "part_kind", "") == "tool-return"
        for p in parts
    )
    return has_user and not has_tool_ret


# Kolik posledních zpráv zůstane při zkracování výsledků nástrojů netknutých
DEFAULT_KEEP_RECENT_MESSAGES = 10
# Nad kolik znaků se starý výsledek nástroje / argument zkracuje
DEFAULT_RESULT_CHARS = 1200


def truncate_text(text: str, limit: int, note: str = "zkráceno") -> str:
    """
    Zkrátí text na zhruba `limit` znaků, ale ponechá ZAČÁTEK I KONEC (uprostřed je poznámka, kolik
    znaků chybí). Konec je důležitý: u výstupů příkazů tam bývá chyba, shrnutí testů a návratový kód.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.65)
    tail = limit - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...[{note}: vynecháno {omitted} z {len(text)} znaků]...\n{text[-tail:]}"


def _stringify(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        return str(content)


def compact_old_messages(
    messages: list[ModelMessage],
    keep_recent: int = DEFAULT_KEEP_RECENT_MESSAGES,
    max_chars: int = DEFAULT_RESULT_CHARS,
) -> list[ModelMessage]:
    """
    Vrátí KOPII zpráv, ve které jsou starší výsledky nástrojů a velké argumenty volání (např. celý
    obsah write_file) zkráceny. Posledních `keep_recent` zpráv zůstává beze změny. Originální seznam
    (a tedy historie na disku) se nemění. Struktura zpráv (volání <-> výsledky) zůstává zachována.
    """
    if max_chars <= 0 or len(messages) <= keep_recent:
        return list(messages)

    split = len(messages) - max(keep_recent, 0)
    out: list[ModelMessage] = []
    for index, msg in enumerate(messages):
        if index >= split:
            out.append(msg)
            continue

        new_parts: list[Any] = []
        changed = False
        for part in getattr(msg, "parts", []):
            if isinstance(part, ToolReturnPart):
                text = _stringify(part.content)
                if len(text) > max_chars:
                    part = dataclasses.replace(
                        part, content=truncate_text(text, max_chars, "starší výstup zkrácen, podle potřeby ho zopakuj")
                    )
                    changed = True
            elif _is_tool_call(part):
                args = getattr(part, "args", None)
                parsed = args
                if isinstance(args, str):
                    try:
                        parsed = json.loads(args)
                    except Exception:
                        parsed = None
                if isinstance(parsed, dict):
                    shrunk = {
                        k: (truncate_text(v, max_chars, "starší argument zkrácen") if isinstance(v, str) else v)
                        for k, v in parsed.items()
                    }
                    if shrunk != parsed:
                        part = dataclasses.replace(part, args=shrunk)
                        changed = True
            new_parts.append(part)

        out.append(dataclasses.replace(msg, parts=new_parts) if changed else msg)
    return out


def build_digest(dropped: list[ModelMessage], max_items: int = 12) -> str:
    """
    Deterministické (bez volání modelu) shrnutí vynechané části historie: které soubory se
    zapisovaly, jaké příkazy běžely a co o výsledku řekl asistent.
    """
    writes: dict[str, None] = {}
    commands: list[str] = []
    assistant_notes: list[str] = []

    for msg in dropped:
        for part in getattr(msg, "parts", []):
            if _is_tool_call(part):
                tool_name, args = _extract_tool_info(part)
                if tool_name in ("write_file", "edit_file"):
                    target = _tool_target(args)
                    if target:
                        writes[target] = None
                elif tool_name == "shell" and args.get("command"):
                    first = (str(args["command"]).strip().splitlines() or [""])[0]
                    commands.append(first[:90])
            elif isinstance(part, TextPart) and part.content.strip():
                assistant_notes.append(" ".join(part.content.split())[:300])

    lines = [
        f"[Starší část konverzace ({len(dropped)} zpráv) byla vynechána kvůli omezení kontextového okna. "
        "Aktuální stav ověř v souborech a v plánu. Stručný přehled vynechaného:]"
    ]
    if writes:
        shown = list(writes)[-max_items:]
        lines.append("- Upravené/vytvořené soubory: " + ", ".join(shown))
    if commands:
        lines.append("- Poslední příkazy: " + " | ".join(commands[-5:]))
    for note in assistant_notes[-3:]:
        lines.append(f"- Poznámka asistenta: {note}")
    return "\n".join(lines)


def safe_trim_history(
    messages: list[ModelMessage],
    keep_turns: int = 3,
    preserve_initial: bool = True,
    max_tail: int = 60,
) -> list[ModelMessage]:
    """
    Ořízne historii pro LLM inferenci tak, aby nepřeteklo kontextové okno.
    Zaručuje:
    1. Integritu všech volání a návratů nástrojů (žádné osiřelé tool-return / tool-call).
    2. Zachování původního uživatelského zadání (pokud preserve_initial=True).
    3. Začátek historie vždy validním ModelRequest.
    4. Horní mez délky (max_tail zpráv) i když jediné kolo vygenerovalo stovky tool callů.
    5. Na místě vynechané části je stručný digest (soubory, příkazy, poznámky asistenta).
    """
    if not messages:
        return []

    keep_turns = max(keep_turns, 1)

    # 1. Ořez po celých uživatelských kolech
    turn_indices = [i for i, m in enumerate(messages) if is_user_turn_start(m)]
    cutoff = turn_indices[-keep_turns] if len(turn_indices) > keep_turns else 0

    # 2. Pokud je zbytek stále příliš dlouhý (typicky jedno velké autonomní kolo),
    #    ořízneme uvnitř kola. Bezpečný řez je vždy na ModelResponse: ten nese svá
    #    volání nástrojů a jejich tool-returny následují až za ním, takže nic nezůstane osiřelé.
    if len(messages) - cutoff > max_tail:
        k = max(len(messages) - max_tail, cutoff)
        while k < len(messages) and not isinstance(messages[k], ModelResponse):
            k += 1
        if k < len(messages):
            cutoff = k

    if cutoff == 0:
        return list(messages)

    head: list[ModelMessage] = []
    dropped_from = 0
    if preserve_initial and turn_indices and turn_indices[0] < cutoff:
        head.append(messages[turn_indices[0]])
        dropped_from = turn_indices[0] + 1
    dropped = messages[dropped_from:cutoff]
    if dropped:
        # Následné po sobě jdoucí ModelRequesty PydanticAI před odesláním sloučí.
        head.append(ModelRequest(parts=[UserPromptPart(content=build_digest(dropped))]))

    result = head + list(messages[cutoff:])

    # Pojistka: historie musí začínat požadavkem a nesmí začínat tool-returnem
    while result and (
        not isinstance(result[0], ModelRequest)
        or not any(getattr(p, "part_kind", "") in ("user-prompt", "system-prompt") for p in result[0].parts)
    ):
        result.pop(0)
    return result


def finalize_partial_history(
    messages: list[ModelMessage],
    reason: str = "krok nebyl dokončen",
) -> list[ModelMessage]:
    """
    Připraví zprávy z přerušeného běhu (limit požadavků, chyba serveru, Ctrl+C) tak, aby je
    šlo bezpečně uložit a použít v dalším kroku:
    - zahodí poslední odpověď modelu, pokud volá nástroje, které už nikdo nevykonal (osiřelé tool-cally),
    - pokud historie končí požadavkem, doplní krátkou uzavírací odpověď asistenta, aby další
      uživatelský prompt nebyl sloučen s tool-returny (to by je zduplikovalo).
    Pokud model neodpověděl ani jednou, vrací prázdný seznam (zadání se nemá tvářit jako vyřízené).
    """
    msgs = list(messages)
    if not any(isinstance(m, ModelResponse) for m in msgs):
        return []

    while msgs and isinstance(msgs[-1], ModelResponse) and any(
        _is_tool_call(p) for p in msgs[-1].parts
    ):
        msgs.pop()

    if not msgs:
        return []

    if isinstance(msgs[-1], ModelRequest):
        msgs.append(ModelResponse(parts=[TextPart(
            content=f"[{reason}. Pokračuji podle aktuálního stavu souborů a plánu.]"
        )]))
    return msgs
