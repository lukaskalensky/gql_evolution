"""Ochranné vrstvy kolem nástrojů: normalizace argumentů, hlídač shellu a detekce zacyklení."""

import json
import re
import shlex
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, RawToolArgs
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition




# ------------------------------------------------------------------------------
# Tolerantní normalizace argumentů nástrojů (slabší lokální modely schéma nedodržují)
# ------------------------------------------------------------------------------

_LINE_NUMBER_PREFIX = re.compile(r"^ *\d+\t")


def strip_line_number_prefixes(text: str) -> str:
    """
    `read_file` vrací řádky ve tvaru "     3<TAB>obsah". Model je často zkopíruje i s číslem
    řádku do `old_text`, což se v souboru nikdy nenajde. Pokud MAJÍ prefix všechny neprázdné
    řádky, odstraníme ho.
    """
    lines = text.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if non_empty and all(_LINE_NUMBER_PREFIX.match(ln) for ln in non_empty):
        return "\n".join(_LINE_NUMBER_PREFIX.sub("", ln, count=1) for ln in lines)
    return text


def _schema_types(prop: dict[str, Any]) -> set[str]:
    """Všechny JSON typy, které vlastnost schématu připouští (včetně větví anyOf/oneOf)."""
    types: set[str] = set()
    declared = prop.get("type")
    if isinstance(declared, str):
        types.add(declared)
    elif isinstance(declared, list):
        types.update(t for t in declared if isinstance(t, str))
    for key in ("anyOf", "oneOf"):
        for sub in prop.get(key) or []:
            if isinstance(sub, dict):
                types |= _schema_types(sub)
    return types


def normalize_tool_args(tool_name: str, raw: Any, schema: dict[str, Any]) -> Any:
    """
    Opraví typické chyby modelu v argumentech nástroje PŘED validací schématu:
    - neznámé klíče (např. `content` u edit_file) zahodí, pokud schéma zakazuje extra vstupy,
    - seznam/objekt poslaný jako JSON řetězec ("[{...}]") rozbalí,
    - jednotlivý objekt tam, kde se čeká seznam, zabalí do seznamu,
    - u edit_file odstraní číslování řádků zkopírované z výstupu read_file.
    Vstup, kterému nerozumí, vrací beze změny (validace a opakování proběhnou jako dřív).
    """
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            return raw
    if not isinstance(data, dict):
        return raw

    props: dict[str, Any] = schema.get("properties") or {}
    forbid_extra = schema.get("additionalProperties") is False
    result: dict[str, Any] = {}

    for key, value in data.items():
        prop = props.get(key)
        if prop is None:
            if forbid_extra and props:
                continue  # neznámý klíč: zahodit
            result[key] = value
            continue

        types = _schema_types(prop)
        if isinstance(value, str) and types & {"array", "object"} and "string" not in types:
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, RecursionError):
                parsed = None
            if isinstance(parsed, (list, dict)):
                value = parsed
        if isinstance(value, dict) and "array" in types and "object" not in types:
            value = [value]
        result[key] = value

    if tool_name == "edit_file":
        pairs = [result]
        if isinstance(result.get("replacements"), list):
            pairs += [item for item in result["replacements"] if isinstance(item, dict)]
        for pair in pairs:
            old = pair.get("old_text")
            if isinstance(old, str):
                cleaned = strip_line_number_prefixes(old)
                if cleaned != old:
                    pair["old_text"] = cleaned
                    # Když model okopíroval čísla řádků do old_text, udělal to i v new_text
                    if isinstance(pair.get("new_text"), str):
                        pair["new_text"] = strip_line_number_prefixes(pair["new_text"])
    return result


class ToolArgsNormalizer(AbstractCapability):
    """Capability: před validací schématu opraví typické chyby v argumentech nástrojů."""

    async def before_tool_validate(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: RawToolArgs,
    ) -> RawToolArgs:
        try:
            return normalize_tool_args(call.tool_name, args, tool_def.parameters_json_schema or {})
        except Exception:
            return args  # normalizace nikdy nesmí způsobit selhání nástroje


# ------------------------------------------------------------------------------
# Hlídač nebezpečných shell příkazů
# ------------------------------------------------------------------------------

# Regulární výrazy pro příkazy, které se nikdy nespouštějí bez souhlasu (rm řeší zvlášť, viz níže)
_DANGEROUS_REGEXES: list[tuple[str, str]] = [
    (r"\bgit\s+push\b", "git push (odeslání změn mimo počítač)"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard (zahodí neuložené změny)"),
    (r"\bgit\s+clean\b[^;&|]*\s-\w*f", "git clean -f (maže nesledované soubory)"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "zahození všech změn v pracovním stromu"),
    (r"\bgit\s+branch\s+-D\b", "git branch -D (smazání větve)"),
    (r"\bsudo\b", "sudo (zvýšená oprávnění)"),
    (r"(curl|wget)\b[^;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "stažení a rovnou spuštění skriptu"),
    (r"\bmkfs(\.\w+)?\b", "formátování disku"),
    (r"\bdd\s[^;&|]*\bof=/dev/", "zápis přímo na zařízení"),
    (r">\s*/dev/(sd|nvme|hd)", "zápis přímo na zařízení"),
    (r"\bchmod\s+-R\s+0?7[0-7][0-7]\b", "rekurzivní změna oprávnění"),
    (r"\bchown\s+-R\b", "rekurzivní změna vlastníka"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "vypnutí / restart stroje"),
    (r":\(\)\s*\{", "fork bomba"),
    (r"\b(npm\s+publish|twine\s+upload|cargo\s+publish)\b", "publikování balíčku"),
    (r"\bdocker\s+(system\s+prune|rm\s+-f|rmi\s+-f)\b", "mazání docker prostředků"),
]

_RM_UNSAFE_TARGETS = {"/", "~", ".", "..", "*", "./*", "/*", "~/*", ".*"}


def _split_segments(command: str) -> list[str]:
    """Rozdělí složený příkaz (; && || | nový řádek) na jednotlivé části."""
    return [seg.strip() for seg in re.split(r"&&|\|\||;|\||\n", command) if seg.strip()]


def _rm_is_dangerous(segment: str) -> Optional[str]:
    """`rm -r` je nebezpečné jen na absolutní/domovské cesty, nadřazené adresáře a holé wildcardy."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if "rm" not in tokens:
        return None
    rest = tokens[tokens.index("rm") + 1:]
    flags = [t for t in rest if t.startswith("-") and not t.startswith("--")]
    recursive = any("r" in f.lower() for f in flags) or "--recursive" in rest
    targets = [t for t in rest if not t.startswith("-")]
    if not recursive:
        return None
    for target in targets:
        if target in _RM_UNSAFE_TARGETS or target.startswith(("/", "~", "../", "$HOME", "${HOME}")):
            return f"rekurzivní mazání mimo projekt nebo wildcardem ({target})"
    return None


def find_danger(command: str) -> Optional[str]:
    """Vrátí důvod, proč je příkaz nebezpečný, nebo None."""
    if not command:
        return None
    for segment in _split_segments(command):
        reason = _rm_is_dangerous(segment)
        if reason:
            return reason
    for pattern, reason in _DANGEROUS_REGEXES:
        if re.search(pattern, command):
            return reason
    return None


ConfirmFn = Callable[[str, str], Awaitable[bool]]


@dataclass
class ShellGuard(AbstractCapability):
    """
    Capability: nebezpečné shell příkazy se nespustí bez souhlasu. V interaktivním režimu se
    uživatel zeptá (`confirm`), v plně autonomním režimu se příkaz odmítne a model dostane
    vysvětlení (výsledek nástroje), takže může zvolit bezpečnější postup.
    """

    allow_dangerous: bool = False
    confirm: Optional[ConfirmFn] = None
    on_denied: Optional[Callable[[str, str], None]] = None

    async def wrap_tool_execute(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        if call.tool_name == "shell" and not self.allow_dangerous and isinstance(args, dict):
            command = str(args.get("command") or "")
            reason = find_danger(command)
            if reason:
                approved = False
                if self.confirm is not None:
                    try:
                        approved = await self.confirm(command, reason)
                    except Exception:
                        approved = False
                if not approved:
                    if self.on_denied:
                        self.on_denied(command, reason)
                    return (
                        f"DENIED by harness: the command was not run because it is dangerous ({reason}). "
                        "Choose a safer approach (for example delete only specific files inside the project, "
                        "no push/reset --hard). The user can allow such commands with --allow-dangerous."
                    )
        return await handler(args)


# ------------------------------------------------------------------------------
# Detekce zacyklení
# ------------------------------------------------------------------------------

class LoopMonitor:
    """
    Sleduje volání nástrojů v jednom kroku a pozná, že se model zacyklil:
    - totéž volání (nástroj + argumenty) `repeat_threshold`× za sebou, nebo
    - střídání dvou volání A,B,A,B,A,B.
    """

    def __init__(self, repeat_threshold: int = 4, window: int = 6):
        self.repeat_threshold = repeat_threshold
        self.window = window
        self._recent: deque[str] = deque(maxlen=max(window, repeat_threshold))
        self.last_description = ""

    @staticmethod
    def signature(tool_name: str, args: dict[str, Any]) -> str:
        try:
            body = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
        except Exception:
            body = str(args)
        return f"{tool_name}:{body}"

    def observe(self, tool_name: str, args: dict[str, Any]) -> bool:
        """Zaznamená volání; vrací True, pokud se model právě zacyklil."""
        sig = self.signature(tool_name, args)
        self._recent.append(sig)
        recent = list(self._recent)

        tail = recent[-self.repeat_threshold:]
        if len(tail) == self.repeat_threshold and len(set(tail)) == 1:
            self.last_description = f"{tool_name} voláno {self.repeat_threshold}× za sebou se stejnými argumenty"
            return True

        tail = recent[-self.window:]
        if len(tail) == self.window and len(set(tail)) == 2 and all(
            tail[i] != tail[i + 1] for i in range(len(tail) - 1)
        ):
            self.last_description = "model střídá dvě stejná volání dokola"
            return True
        return False
