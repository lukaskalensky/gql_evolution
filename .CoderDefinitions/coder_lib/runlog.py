"""Strukturovaný záznam běhu (.cmd_coder/run.log, JSON na řádek) pro ladění po fakt."""

import json
import time
from pathlib import Path
from typing import Any, Optional

MAX_LOG_BYTES = 5_000_000
MAX_FIELD_CHARS = 800


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"...[+{len(value) - MAX_FIELD_CHARS} znaků]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clip(v) for v in value]
    return value


class RunLog:
    """Připisuje události do souboru; chyba zápisu nikdy neshodí běh. S path=None nedělá nic."""

    def __init__(self, path: Optional[Path]):
        self.path = path
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
                    path.replace(path.with_name(path.name + ".1"))
            except Exception:
                self.path = None

    def write(self, kind: str, **fields: Any) -> None:
        if self.path is None:
            return
        record = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, **_clip(fields)}
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass
